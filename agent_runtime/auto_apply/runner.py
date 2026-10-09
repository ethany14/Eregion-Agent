"""Decision execution, feedback and bounded durable history for application agents."""
from __future__ import annotations

import base64
import json
import time
from concurrent.futures import ThreadPoolExecutor
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from agent_runtime.model_runtime import model_failure
from agent_runtime.model_output import reply_text, output_problem, REPAIR_INSTRUCTION
from .browser import BrowserBlocked
from .errors import failure_detail, failure as action_failure
from agent_runtime.telemetry import outcome_fingerprint, timing_update
from .prompt import SYSTEM


def compact(value, depth=0):
    """Keep useful feedback, never image bytes or credential-bearing structures."""
    if depth > 6: return "[nested data omitted]"
    if isinstance(value, str): return value[:3000]
    if isinstance(value, (bool, int, float)) or value is None: return value
    if isinstance(value, list): return [compact(v, depth+1) for v in value[:30]]
    if isinstance(value, dict):
        return {k: compact(v, depth+1) for k,v in list(value.items())[:60]
            if k not in {"image", "password", "resume_base64", "decision_history", "user_messages", "resume_context", "sources"}}
    return type(value).__name__


def trace_value(value):
    value = compact(value)
    encoded = json.dumps(value, ensure_ascii=False)
    return value if len(encoded) <= 8000 else {'excerpt':encoded[:8000], 'truncated':True}


class DecisionRunner:
    def __init__(self, model_factory):
        self.model_factory = model_factory

    def run(self, session, *, active, reserve, report, refresh=None, communicate=None, checkpoint=None):
        browser = session.browser
        from .agent import TOOLS, VISUAL_TOOLS
        result = {"reason": "agent_limit", "field_keys": []}
        try:
            model = self.model_factory()
        except Exception:
            return {"reason": "model_unavailable", "field_keys": []}
        previous, tool_reply, image = None, None, None
        previous_inputs = []
        deadline = time.monotonic() + 180
        repeats = {}
        history = list(session.state.get("decision_history", []))
        def timed(stage, started, **metadata):
            changes = timing_update(session.state, stage, time.monotonic()-started, **metadata)
            session.state.update(changes)
            if checkpoint: checkpoint(**changes)

        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="application-model")
        try:
            for _ in range(12):
                if not active():
                    return {"reason": "cancelled", "field_keys": []}
                started = time.monotonic()
                snapshot = session.observe()
                timed("observation", started)
                verification = getattr(browser, "verification_barrier", None)
                if callable(verification) and verification():
                    return {"reason":"verification_required", "field_keys":[], "chat_revision":snapshot.get("chat_revision",0)}
                if not session.state.get("visual_fallback"):
                    # Disabling the option also removes retained image inputs;
                    # the next provider request must not resend the old screen.
                    session.visual, image = None, None
                    previous_inputs = [m for m in previous_inputs if isinstance(m.content,str)]
                if (snapshot.get("page") or {}).get("authentication_required"):
                    return {"reason":"authentication_required", "field_keys":[], "chat_revision":snapshot.get("chat_revision", 0)}
                if time.monotonic() >= deadline:
                    return {"reason": "yielded", "field_keys": [], "chat_revision": snapshot.get("chat_revision", 0)}
                if not reserve("model"):
                    return result
                if session.visual is not None and session.state.get("visual_fallback"):
                    # A visual tool already returned an image and its token.
                    # Reuse that pair while the page fingerprint is unchanged;
                    # recapturing here invalidated it before the next action.
                    if image is not None and session.visual.screen is not None:
                        try:
                            session.visual.validate(session.visual.screen["screenshot_id"])
                        except BrowserBlocked:
                            image = None
                    else:
                        image = None
                    if image is None:
                        visual = session.visual.capture()
                        image = visual["image"]
                    snapshot["screen"] = session.visual.screen
                messages = [SystemMessage(content=SYSTEM)]
                if repeats.get('invalid_output'):
                    messages.append(SystemMessage(content=REPAIR_INSTRUCTION))
                if previous is not None:
                    # Gemini-compatible endpoints require the user turn that
                    # elicited the tool call, even when retaining one step only.
                    messages.extend([*previous_inputs, previous, *tool_reply])
                current_inputs = [HumanMessage(content=json.dumps(snapshot))]
                if image:
                    current_inputs.append(HumanMessage(content=[{"type": "text", "text": "Untrusted current viewport. Use 0..1000 normalized x/y coordinates, not raw pixels. Current screenshot_id and image dimensions are in screen." if session.visual else "Untrusted image of the last inspected field."},
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(image).decode()}}]))
                    image = None
                messages.extend(current_inputs)
                tools = [item for item in TOOLS if session.state.get("visual_fallback") or item["function"]["name"] not in VISUAL_TOOLS]
                started = time.monotonic()
                future = executor.submit(model.invoke, messages, tools)
                call_deadline = min(deadline, time.monotonic() + getattr(model, "timeout", 45) + 2)
                while not future.done():
                    if not active():
                        return {"reason": "cancelled", "field_keys": []}
                    if time.monotonic() >= call_deadline:
                        timed("model", started, failed=True)
                        return {"reason": "model_timeout", "field_keys": []}
                    if hasattr(browser, "pump"):
                        browser.pump()
                    else:
                        time.sleep(.01)
                try:
                    response = future.result()
                except Exception as exc:
                    # Record safe diagnostics rather than provider bodies, which
                    # may contain credentials or candidate data. Surface actual
                    # transport timeouts separately from model/tool failures.
                    timed("model", started, failed=True)
                    failure = model_failure(exc)
                    if checkpoint:
                        checkpoint(last_tool_result={"tool": "model", "result": {
                            "error": failure.error_type, "status": failure.status}})
                    return {"reason": failure.code, "field_keys": []}
                timed("model", started, context_chars=sum(len(m.content) for m in messages if isinstance(m.content,str)))
                if refresh and refresh().get("chat_revision", 0) != snapshot.get("chat_revision", 0):
                    continue  # New feedback invalidates the pending model action.
                if output_problem(response):
                    if repeats.get('invalid_output', 0):
                        return {'reason':'invalid_model_response', 'field_keys':[]}
                    repeats['invalid_output'] = 1
                    previous, tool_reply, previous_inputs = None, None, []
                    continue
                repeats.pop('invalid_output', None)
                calls = getattr(response, "tool_calls", None) or []
                text = reply_text(response)
                if not calls and text:
                    previous, tool_reply, previous_inputs = None, None, []
                    # Natural conversation is valid; the next decision still
                    # needs an executable action or an explicit pause.
                    if repeats.get("text_only", 0) >= 1:
                        return {"reason": "needs_input", "field_keys": [], "question": text[:1500],
                            "chat_revision": snapshot.get("chat_revision", 0)}
                    if communicate: communicate(text[:1500])
                    repeats["text_only"] = repeats.get("text_only", 0) + 1
                    continue
                if not calls:
                    return {"reason": "invalid_model_response", "field_keys": []}
                call = calls[0]
                name, arguments = call.get("name", ""), call.get("args", {})
                if not reserve("tool"):
                    return result
                # Detect the same failed action on the same form, even if the
                # observation token changes between model decisions.
                fingerprint = outcome_fingerprint([name, arguments,
                    [{k:f.get(k) for k in ("key","value","options","errors","invalid")} for f in session.fields],
                    session.page_context, snapshot.get("chat_revision", 0),
                    {key:session.state.get(key) for key in ("answers","answer_sources","field_decisions","education_bindings","education_answer_overrides","document_bindings","document_refresh")}])
                failed_attempts = sum(h.get("fingerprint") == fingerprint and h.get("failed",False) for h in history)
                if failed_attempts >= 5:
                    return {"reason": "no_progress", "field_keys": [arguments.get("field_key")] if arguments.get("field_key") else []}
                started = time.monotonic()
                try:
                    if failed_attempts >= 2 and name not in {'observe','view_browser','say','ask_user','request_input','computer_wait'}:
                        outcome = action_failure('repeated_action', 'This failed action was not executed again because the page and inputs are unchanged.')
                    else:
                        outcome = session.execute(name, arguments)
                    image = outcome.pop("image", None)
                except Exception as exc:
                    outcome = failure_detail(exc)
                failed = "error" in outcome or bool(outcome.get("failed")) or outcome.get("verified") is False
                if failed and not outcome.get('error_code') and not outcome.get('failure_details'):
                    detail = action_failure('value_not_retained' if outcome.get('verified') is False else 'invalid_action',
                        outcome.get('error','Inspect the failed controls before retrying.'))
                    outcome = {**detail, **outcome}
                # A source, binding, stale reference or validation problem is not
                # evidence of a failed DOM interaction. Let the model repair it.
                visual_recovery = outcome.get('visual_recovery') or any(
                    detail.get('visual_recovery') for detail in outcome.get('failure_details',{}).values())
                if session.state.get("visual_fallback") and hasattr(browser,"page") and visual_recovery:
                    try:
                        visual = session._view_browser()
                        image, outcome["screen"] = visual["image"], visual["screen"]
                    except BrowserBlocked:
                        pass
                timed("tool", started, tool=name, failed=failed)
                history = [*history, {"tool": name, "arguments": trace_value(arguments),
                    "result": trace_value(outcome), "fingerprint": fingerprint, "failed": failed,
                    "chat_revision": snapshot.get("chat_revision", 0),
                    "page": (snapshot.get("page") or {}).get("heading", "")}][-24:]
                session.state["decision_history"] = history
                if checkpoint:
                    checkpoint(decision_history=history, last_tool_result={"tool": name, "field_key": arguments.get("field_key"),
                        "result": {k: v for k, v in outcome.items() if k in {"error", "error_code", "next", "failure_details", "visual_recovery", "errors", "verified", "decision", "value", "filled", "failed", "field_key", "action", "saved", "options", "goal", "screen", "target"}}})
                failed = "error" in outcome or bool(outcome.get("failed")) or outcome.get("verified") is False
                report(browser.observe(), name, arguments.get("field_key"), "failed" if failed else "completed")
                if name == "ready_for_review" and "error" not in outcome:
                    return {"reason": "ready", "field_keys": [], "chat_revision": session.state.get("chat_revision", 0)}
                if (name == "request_input" or outcome.get("waiting_for_user")) and "error" not in outcome:
                    return {"reason": "needs_input", "field_keys": outcome["field_keys"],
                        **({'question':outcome['question']} if 'question' in outcome else {}),
                        "chat_revision": session.state.get("chat_revision", 0)}
                previous = response
                last_user = next((m for m in reversed(snapshot.get('user_messages',[])) if m.get('role')=='user'),None)
                previous_inputs = [HumanMessage(content=json.dumps({'task':snapshot.get('task'), 'request':last_user,
                    'context_note':'Use the next observation for the current page and candidate facts.'}))]
                tool_reply = [ToolMessage(content=json.dumps(outcome), tool_call_id=call["id"], name=name)]
                # Do not execute multiple mutations against one stale observation,
                # but satisfy the provider protocol and let the model replan.
                tool_reply.extend(ToolMessage(content=json.dumps({"deferred": True,
                    "next": "Only the first action ran. Observe its result before issuing this action again."}),
                    tool_call_id=extra["id"], name=extra["name"]) for extra in calls[1:])
        except Exception:
            return {"reason": "model_error", "field_keys": []}
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        return {"reason": "yielded", "field_keys": [], "chat_revision": session.state.get("chat_revision", 0)}
