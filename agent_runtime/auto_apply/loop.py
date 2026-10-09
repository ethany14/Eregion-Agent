"""A bounded observe/act/verify loop with durable pauses and submission fencing."""
from threading import RLock
import hashlib
import json
from pathlib import Path
import time
from uuid import uuid4

from agent_runtime.model_runtime import MODEL_PAYMENT_MESSAGE

from .agent import HybridApplicationAgent
from .autofill import autofill, desired_answer, matches, pending_documents
from .browser import ApplicationBrowser, BrowserBlocked, form_digest
from .contracts import PAUSED, TERMINAL
from .repository import ApplyConflict, now
from .worker import BrowserWorker
from .matching import boolean_answer, is_consent
from .conversation import ordered_answers, input_prompt
from .browser_sessions import BrowserSessionStore
from . import authentication
from .decisions import unresolved_paths
from .drafting import visible_drafts


class ApplicationLoop:
    def __init__(self, repository, *, browser_factory=ApplicationBrowser, agent_factory=HybridApplicationAgent, retry_delays=(1, 3), max_model_calls=120, max_tool_calls=360):
        self.repository = repository
        self.browser_factory = browser_factory
        self.agent_factory = agent_factory
        self.lock = RLock()
        self.browsers = {}
        self.previews = {}
        self.preview_times = {}
        self.closed = False
        self.retry_delays = retry_delays
        self.max_model_calls,self.max_tool_calls=max_model_calls,max_tool_calls
        self.scheduled = {}
        self.session_store = BrowserSessionStore(Path(__file__).resolve().parents[2] / ".browser-sessions")
        restored = self.repository.recover()
        self.executor = BrowserWorker(self._pump_browsers)
        for run_id in restored or []:
            self.executor.submit(self._drive, run_id, None)

    def _pump_browsers(self):
        with self.lock:
            for run_id, (deadline, revision) in list(self.scheduled.items()):
                if time.monotonic() >= deadline:
                    del self.scheduled[run_id]
                    state = self._active(run_id)
                    if state and state["status"] == "queued" and not state.get("pause_requested") and state.get("chat_revision", 0) == revision:
                        self.executor.submit(self._drive, run_id, None)
        for run_id, browser in list(self.browsers.items()):
            pump = getattr(browser, "pump", None)
            if callable(pump):
                try:
                    pump()
                except Exception:
                    pass
            self._capture_preview(run_id, browser)
            if hasattr(browser, "save_login_state"):
                browser.save_login_state()

    def _capture_preview(self, run_id, browser):
        if not hasattr(browser, "preview") or time.monotonic() - self.preview_times.get(run_id, 0) < 2:
            return
        self.preview_times[run_id] = time.monotonic()
        try:
            content = browser.preview()
            with self.lock:
                self.previews[run_id] = content
        except Exception:
            pass

    def preview(self, run_id):
        self.repository.get(run_id)
        with self.lock:
            return self.previews.get(run_id)

    def set_browser_visible(self,run_id,visible,version):
        """Only the user's window button invokes this; model tools cannot show Chrome."""
        with self.lock:
            state=self.repository.get(run_id)
            if self.closed or state['version']!=version or state['status'] in TERMINAL|{'submitting'}:
                raise ApplyConflict('The application changed or is submitting. Refresh before taking control.')
            if run_id not in self.browsers:raise ApplyConflict('No application browser is open. Resume the task first.')
            state=self.repository.save(state,status='needs_input',pause_requested=True,
                chat_revision=state.get('chat_revision',0)+1,review_digest=None,retry_at=None,
                message='Paused for browser control. Switching modes reloads the page; saved answers remain. Resume when ready.')
            self.scheduled.pop(run_id,None)
        def change():
            latest=self.repository.get(run_id)
            if not latest.get('pause_requested') or latest.get('chat_revision')!=state['chat_revision']:
                raise ApplyConflict('The task changed. Pause before switching browser mode.')
            browser=self.browsers.get(run_id)
            if not browser or not hasattr(browser,'set_visible'):raise ApplyConflict('This browser does not support manual window control.')
            browser.set_visible(visible)
            self._capture_preview(run_id,browser)
            return self.repository.get(run_id)
        try:return self.executor.submit(change).result()
        except BrowserBlocked as exc:raise ApplyConflict(str(exc)) from None

    def browser_control(self, run_id, request, *, parent_scope=''):
        from agent_runtime.browser.handoff import control_browser
        with self.lock:
            state = self.repository.get(run_id)
            if self.closed or state['status'] in TERMINAL | {'submitting'}:
                raise ApplyConflict('This application is closed or submitting.')
            if run_id not in self.browsers:
                raise ApplyConflict('No application browser is open. Resume the task first.')
            if request.action == 'start':
                if state['version'] != request.expected_version:
                    raise ApplyConflict('The application changed. Refresh before taking control.')
                state = self.repository.save(state, status='needs_input', pause_requested=True,
                    chat_revision=state.get('chat_revision', 0)+1, review_digest=None, retry_at=None,
                    message='Paused for browser control. Your current page is preserved. Resume when ready.')
                self.scheduled.pop(run_id, None)
            if not state.get('pause_requested'):
                raise ApplyConflict('Pause the agent before controlling its browser.')
            revision = state.get('chat_revision', 0)
        def control():
            latest = self.repository.get(run_id)
            if (self.closed or not latest.get('pause_requested')
                    or latest.get('chat_revision', 0) != revision
                    or latest['status'] in TERMINAL | {'submitting'}):
                raise ApplyConflict('The task resumed or changed. Take control again.')
            browser = self.browsers.get(run_id)
            if not browser:
                raise ApplyConflict('The browser is no longer open.')
            result = control_browser(browser, request, f'{parent_scope}:application:{run_id}:{revision}')
            self.preview_times.pop(run_id, None)
            self._capture_preview(run_id, browser)
            return result
        try:
            return self.executor.submit(control).result()
        except BrowserBlocked as exc:
            raise ApplyConflict(str(exc)) from None
        except ApplyConflict:
            raise
        except Exception:
            # Playwright exceptions can contain typed input. Never return them.
            raise ApplyConflict('Browser control could not complete. Refresh the view before trying again.') from None

    def account(self, run_id, request, *, switch=False):
        with self.lock:
            state = self.repository.get(run_id)
            if (self.closed or state["status"] != "needs_input" or state["version"] != request.expected_version
                    or not state.get("account_request") or run_id not in self.browsers):
                raise ApplyConflict("The account request changed. Refresh and review the current page.")
            if request.origin != state["account_request"]["origin"]:
                raise ApplyConflict("Credentials must be sent to the site shown in the account request.")
            updated = self.repository.save(state, status="queued", pause_requested=False, review_digest=None,
                account_request=None, message="Opening the account form." if switch else "Completing the account step.")
            # This request is held only by the worker job; it is never persisted,
            # appended to messages, or passed to the model.
            self.executor.submit(self._account, run_id, request, switch, state["account_request"])
            return updated

    def _account(self, run_id, request, switch, expected):
        try:
            state = self._active(run_id)
            if state is None or state.get("pause_requested"): return
            browser = self.browsers[run_id]
            options = {'model_factory':getattr(self.agent_factory(), 'model_factory', None),
                'active':lambda:self._can_act(run_id), 'reserve':lambda kind:self._reserve(run_id,kind)}
            if switch:
                authentication.switch_mode(browser, request.mode, request.origin, **options)
            else:
                authentication.authenticate(browser, request, expected=expected, **options)
            self._drive(run_id, None)
        except Exception as exc:
            browser = self.browsers.get(run_id)
            message = str(exc) if isinstance(exc, BrowserBlocked) else "The account step needs attention in Chrome. Continue after checking it."
            try:
                fields = browser.observe() if browser else []
            except Exception:
                fields = []
            self._browser_handoff(run_id, message, fields)

    def chat(self, run_id, request):
        with self.lock:
            state = self.repository.get(run_id)
            if any(m["id"] == request.message_id for m in state.get("messages", [])):
                return state
            if self.closed or state["status"] in TERMINAL | {"submitting"}:
                raise ApplyConflict("This attempt no longer accepts changes.")
            if state.get("reopening"):
                raise ApplyConflict("The application is reopening. Wait for the browser to be ready.")
            fields = {f["key"]: f for f in state["fields"]}
            if request.field_key and request.field_key not in fields:
                raise ApplyConflict("Choose a question from the current application.")
            from agent_runtime.task_control import requests_resume, requests_pause, resume_command_only
            pause = requests_pause(request.text)
            resume = requests_resume(request.text)
            control_only = pause or (resume and resume_command_only(request.text))
            if not pause and not resume and not request.field_key and state.get("automation_mode", "autofill") != "hybrid":
                raise ApplyConflict("General feedback requires Agent + autofill. In autofill-only mode, choose the question you are answering.")
            answers = {}
            if request.field_key and not pause:
                answer = request.text
                if fields[request.field_key]["kind"] == "checkbox":
                    answer = boolean_answer(answer)
                    if answer is None:
                        raise ApplyConflict("Answer this checkbox with yes or no.")
                answers[request.field_key] = answer
            message = {"id": request.message_id, "role": "user", "text": request.text,
                "field_key": request.field_key, "control": control_only, "at": now()}
            input_request=state.get('input_request')
            if input_request and not control_only:
                message['in_reply_to']=input_request['id']
            if answers:
                message["bound_answers"] = answers
                message["binding_method"] = "explicit_field"
            was_paused = state["status"] in PAUSED or run_id in self.scheduled
            self.scheduled.pop(run_id, None)
            updated = self.repository.save(state,
                status="needs_input" if pause else "queued" if was_paused else state["status"],
                messages=[*state.get("messages", []), message][-100:], chat_revision=state.get("chat_revision", 0) + 1,
                input_request=input_request if control_only else None,
                answers={**state["answers"], **answers}, review_digest=None, pause_requested=pause,
                retry_at=None, recovery_attempts=0, continuations=0,
                visual_fallback=request.visual_fallback if request.visual_fallback is not None else state.get("visual_fallback", False),
                budget_model_base=state.get("agent_calls", 0), budget_tool_base=state.get("agent_tools", 0),
                answer_sources={**state.get("answer_sources", {}), **{key: {"type": "chat", "message_id": request.message_id} for key in answers}},
                message="Paused at your request. Continue when ready." if pause else "Your feedback will be read before the next agent action.")
            self.repository.remember(updated, answers)
            if was_paused and not pause:
                self.executor.submit(self._drive, run_id, None, frozenset(answers))
            return updated

    def _say(self, run_id, text):
        with self.lock:
            state = self._active(run_id)
            if state is not None:
                for old in reversed(state.get('messages', [])):
                    if old.get('role') == 'user':break
                    if old.get('role') == 'assistant' and old.get('text','').strip() == text.strip():return
                message = {"id": str(uuid4()), "role": "assistant", "text": text, "at": now()}
                self.repository.save(state, messages=[*state.get("messages", []), message][-100:])

    def _checkpoint(self, run_id, **changes):
        with self.lock:
            state = self._active(run_id)
            if state is not None and not state.get("pause_requested"):
                self.repository.save(state, **changes)

    def _schedule_recovery(self, run_id, reason, *, progressed=False):
        with self.lock:
            state = self._active(run_id)
            if state is None or state.get("pause_requested") or state["status"] == "submitting": return False
            if state.get("automation_mode") != "hybrid": return False
            if state.get("agent_calls", 0) - state.get("budget_model_base", 0) >= self.max_model_calls: return False
            if state.get('agent_tools',0)-state.get('budget_tool_base',0)>=self.max_tool_calls:return False
            attempts = state.get("recovery_attempts", 0)
            if reason == "yielded":
                delay = 0
                attempts=0
                message = "Continuing from the saved decisions and current page."
            elif reason in {"validation_error", "model_error", "model_timeout", "model_rate_limited", "model_unavailable", "invalid_model_response", "browser_error", "no_progress"} and attempts < len(self.retry_delays):
                delay = self.retry_delays[attempts]
                attempts += 1
                message = "Recovering this step automatically. Your completed answers are saved."
            else:
                return False
            self.repository.save(state, status="queued", retry_at=time.time() + delay,
                recovery_attempts=attempts, continuations=state.get("continuations", 0) + 1,
                recovery_note=f"Previous step ended with {reason}. Observed progress: {progressed}. Inspect the latest state and change unsuccessful strategies.",
                review_digest=None, message=message)
            self.scheduled[run_id] = (time.monotonic() + delay, state.get("chat_revision", 0))
            return True

    def _accept_chat_answer(self, run_id, key, value, message_id):
        with self.lock:
            state = self._active(run_id)
            if state is None or state.get("pause_requested"):
                raise BrowserBlocked("The attempt is paused or cancelled.")
            updated = self.repository.save(state, answers={**state["answers"], key: value},
                answer_sources={**state.get("answer_sources", {}), key: {"type": "chat", "message_id": message_id}})
            self.repository.remember(updated, {key: value})

    def _bind_answers(self, run_id, items, chat_revision):
        with self.lock:
            state = self._active(run_id)
            if state is None or state.get("pause_requested") or state.get("chat_revision", 0) != chat_revision:
                raise BrowserBlocked("New feedback arrived; interpret the latest conversation again.")
            values = {item["field_key"]: item["value"] for item in items}
            messages = [dict(message) for message in state.get("messages", [])]
            for message in messages:
                bound = {item["field_key"]: item["value"] for item in items if item["message_id"] == message["id"]}
                if bound:
                    message["bound_answers"] = {**message.get("bound_answers", {}), **bound}
                    message["binding_method"] = "model"
            sources = {item["field_key"]: {"type": "chat", "message_id": item["message_id"],
                "quote": item["quote"], "interpretation": "model"} for item in items}
            updated = self.repository.save(state, answers={**state["answers"], **values},
                answer_sources={**state.get("answer_sources", {}), **sources}, messages=messages)
            self.repository.remember(updated, values)

    def _recover_chat_answers(self, state):
        # A previously failed model call may have left a compact reply unused.
        # Replay later corrections over earlier chat answers, but never overwrite
        # newer chat replies or explicit edits without a known chronological order.
        messages, recovered, sources = [], {}, {}
        order = {m["id"]: index for index, m in enumerate(state.get("messages", []))}
        for index, original in enumerate(state.get("messages", [])):
            message = dict(original)
            if message["role"] == "user" and not message.get("field_key") and not message.get("control") and "bound_answers" not in message:
                bound = ordered_answers(message["text"], messages, state["fields"])
                if bound:
                    message["bound_answers"] = bound
                    message["binding_method"] = "fallback"
                    for key, value in bound.items():
                        source = sources.get(key, state.get("answer_sources", {}).get(key, {}))
                        earlier_chat = source.get("type") == "chat" and source.get("message_id") in order and order[source["message_id"]] < index
                        if key not in state["answers"] or earlier_chat:
                            recovered[key] = value
                            sources[key] = {"type": "chat", "message_id": message["id"]}
            messages.append(message)
        if messages != state.get("messages", []):
            state = self.repository.save(state, messages=messages,
                answers={**state["answers"], **recovered}, answer_sources={**state.get("answer_sources", {}), **sources})
            self.repository.remember(state, recovered)
        return state

    def start(self, request, *, material_refs=None):
        from .contracts import Candidate
        from .education import normalize_records
        import base64
        with self.lock:
            if self.closed:
                raise ApplyConflict("The application service is stopping.")
            profile=request.profile.model_dump()
            profile['education']=normalize_records(profile.get('education',[]))
            request=request.model_copy(update={'profile':Candidate.model_validate(profile)})
            state, created = self.repository.create(request,material_refs=material_refs)
            if created:
                if request.save_as_default:
                    self.repository.save_candidate(profile,resume=base64.b64decode(request.resume_base64),name=request.resume_name)
                self.executor.submit(self._drive, state["run_id"], None)
            return state

    def continue_run(self, run_id, request):
        with self.lock:
            state = self.repository.get(run_id)
            if self.closed or state["version"] != request.expected_version or state["status"] not in PAUSED:
                raise ApplyConflict("Refresh the attempt; it is no longer waiting at this step.")
            state=self.repository.refresh_education(state)
            if request.confirm_submit and state["status"] != "awaiting_review":
                raise ApplyConflict("The filled form must be ready for review before confirming submission.")
            allowed_keys = {field["key"] for field in state["fields"]}
            if not set(request.answers).issubset(allowed_keys):
                raise ApplyConflict("The form changed. Only answer questions from the latest observation.")
            approval = state["review_digest"] if request.confirm_submit and not request.answers else None
            messages=state.get('messages',[])
            if request.answers:
                fields={f['key']:f for f in state['fields']}
                messages=[*messages,{'id':str(uuid4()),'role':'user','at':now(),
                    'text':'\n'.join(f"{fields[k]['label']}: {('Yes' if v else 'No') if isinstance(v,bool) else v}" for k,v in request.answers.items()),
                    'bound_answers':request.answers,'binding_method':'explicit_batch',
                    'in_reply_to':(state.get('input_request') or {}).get('id')}][-100:]
            updated = self.repository.save(state, status="queued", answers={**state["answers"], **request.answers},
                messages=messages,chat_revision=state.get('chat_revision',0)+bool(request.answers),
                input_request=None,
                review_digest=None if request.answers else state.get('review_digest'),
                pause_requested=False,
                recovery_attempts=0, continuations=0, retry_at=None,
                budget_model_base=state.get("agent_calls", 0), budget_tool_base=state.get("agent_tools", 0),
                answer_sources={**state.get("answer_sources", {}), **{key: {"type": "user"} for key in request.answers}},
                consent_policy=request.consent_policy or state.get("consent_policy", "ask"),
                automation_mode=request.automation_mode or state.get("automation_mode", "autofill"),
                visual_fallback=request.visual_fallback if request.visual_fallback is not None else state.get("visual_fallback", False),
                message="Continuing the application.")
            self.repository.remember(updated, request.answers)
            self.executor.submit(self._drive, run_id, approval, frozenset(request.answers))
            return updated

    def cancel(self, run_id, version):
        with self.lock:
            state = self.repository.get(run_id)
            if state["version"] != version or state["status"] in TERMINAL | {"submitting"}:
                raise ApplyConflict("This attempt cannot be cancelled at its current step.")
            state = self.repository.save(state, status="cancelled", pause_requested=False, reopening=False,
                review_digest=None, retry_at=None, message="Application cancelled before submission. Your saved progress can be resumed.")
            self.scheduled.pop(run_id, None)
            self.executor.submit(self._close_browser, run_id)
            return state

    def resume(self, run_id, version):
        with self.lock:
            state = self.repository.get(run_id)
            if self.closed or state["version"] != version:
                raise ApplyConflict("The attempt changed. Refresh before resuming.")
            updated = self.repository.reopen(state)
            self.executor.submit(self._finish_reopen, run_id, updated["chat_revision"])
            return updated

    def replace_materials(self, run_id, resume, cover_letter, *, profile=None, material_refs=None):
        """Browser work remains serialized; no previous submission approval survives."""
        with self.lock:
            if self.closed:raise ApplyConflict('The application service is stopping.')
            state = self.repository.get(run_id)
            updated = self.repository.replace_documents(state,resume,cover_letter,profile=profile,material_refs=material_refs)
            self.scheduled.pop(run_id,None)
            self.executor.submit(self._finish_reopen,run_id,updated['chat_revision'])
            return updated

    def _finish_reopen(self, run_id, revision):
        with self.lock:
            state = self._active(run_id)
            if (state is None or not state.get("reopening") or state["status"] != "queued"
                    or state.get("chat_revision") != revision):
                return
            self.repository.save(state, reopening=False, pause_requested=False,
                message="Restoring saved answers in a new browser session.")
        self._close_browser(run_id)
        self._drive(run_id, None)

    def _close_browser(self, run_id):
        browser = self.browsers.pop(run_id, None)
        self.previews.pop(run_id, None)
        self.preview_times.pop(run_id, None)
        if browser:
            try:
                browser.close()
            except Exception:
                pass

    def _active(self, run_id):
        state = self.repository.get(run_id)
        return state if not self.closed and state["status"] not in TERMINAL else None

    def _can_act(self, run_id):
        state = self._active(run_id)
        return state is not None and not state.get("pause_requested")

    def _progress(self, run_id, fields, tool, key, outcome):
        with self.lock:
            state = self._active(run_id)
            if state is not None:
                field = next((f for f in fields if f["key"] == key), None)
                action = {"tool": tool, "field_key": key, "label": field["label"] if field else "Application form",
                    "outcome": outcome, "source": state.get("answer_sources", {}).get(key), "at": now()}
                last = state.get("last_tool_result") or {}
                if last.get("tool") == tool and last.get("field_key") == key:
                    action["detail"] = {k:v for k,v in last.get("result",{}).items()
                        if k in {"error","errors","verified","decision","target"}}
                self.repository.save(state, fields=fields, last_action=action,
                    actions=[*state.get("actions", []), action][-100:],
                    message=f"{tool}: {action['label']} — {outcome}.")
        browser = self.browsers.get(run_id)
        if browser: self._capture_preview(run_id, browser)

    def _reserve(self, run_id, kind):
        with self.lock:
            state = self._active(run_id)
            if state is None or state.get("pause_requested"):
                return False
            key, limit = ("agent_calls", self.max_model_calls) if kind == "model" else ("agent_tools", self.max_tool_calls)
            used = state.get(key, 0)
            base = state.get("budget_model_base" if kind == "model" else "budget_tool_base", 0)
            if used - base >= limit:
                return False
            self.repository.save(state, **{key: used + 1})
            return True

    def _agent_context(self,run_id):
        state=self.repository.agent_context(run_id)
        return {**state,'budget_remaining':{
            'model_calls':max(0,self.max_model_calls-state.get('agent_calls',0)+state.get('budget_model_base',0)),
            'tool_calls':max(0,self.max_tool_calls-state.get('agent_tools',0)+state.get('budget_tool_base',0))}}

    @staticmethod
    def _progress_digest(fields,page,state):
        # Navigating, discovering a menu and binding an answer are progress even
        # before an input's value changes. Operational counters are not progress.
        payload=[form_digest(fields),page,state.get('answers'),state.get('field_decisions'),state.get('education_bindings')]
        return hashlib.sha256(json.dumps(payload,sort_keys=True,default=str).encode()).hexdigest()

    def _publish_question(self, run_id, text, keys, fields, revision):
        with self.lock:
            state = self._active(run_id)
            if state is None or state.get('pause_requested'):
                raise BrowserBlocked('Application paused or cancelled.')
            if state.get('chat_revision', 0) != revision:
                raise BrowserBlocked('New feedback arrived. Read it before asking another question.')
            pending = state.get('input_request')
            if pending:
                return pending  # One batch, one reply; never overwrite or repeat it.
            keys = list(dict.fromkeys(keys))
            question = {'id':str(uuid4()), 'role':'assistant', 'text':text,
                'question_keys':keys, 'at':now(), 'kind':'question'}
            messages = list(state.get('messages',[]))
            if messages and messages[-1].get('role') == 'assistant' and messages[-1].get('text') == text:
                question['id'] = messages[-1]['id']
                messages[-1] = question
            else:
                messages.append(question)
            request = {'id':question['id'], 'text':text, 'field_keys':keys,
                'fields':[f for f in fields if f['key'] in keys]}
            self.repository.save(state, fields=fields, pending_fields=keys, input_request=request,
                messages=messages[-100:], review_digest=None,
                message='Your question is ready. I am continuing the independent steps.')
            return request

    def _pause_for_question(self, run_id, text, keys, fields, revision):
        with self.lock:
            state = self._active(run_id)
            if state is None or state.get('pause_requested'):return
            if state.get('chat_revision', 0) != revision:
                self.executor.submit(self._drive, run_id, None)
                return
            self._publish_question(run_id, text, keys, fields, revision)
            state = self.repository.get(run_id)
            self.repository.save(state, status='needs_input', agent_reason='user_question', retry_at=None,
                message='Waiting for your reply. Your completed work is saved.')

    def reply_question(self, run_id, request):
        """Answer a question while the worker runs, independent of polling versions."""
        with self.lock:
            state = self.repository.get(run_id)
            previous = next((m for m in state.get('messages',[]) if m.get('in_reply_to') == request.request_id
                and m.get('binding_method') == 'explicit_batch'), None)
            if previous and previous.get('bound_answers') == request.answers:return state
            pending = state.get('input_request')
            if (self.closed or state['status'] in TERMINAL | {'submitting'} or state.get('reopening')
                    or not pending or pending['id'] != request.request_id):
                raise ApplyConflict('That question has already been answered or changed. Read the latest conversation.')
            fields = {f['key']:f for f in pending.get('fields',[])}
            if not request.answers or not set(request.answers).issubset(fields):
                raise ApplyConflict('Answer fields from this question, or reply in chat.')
            message = {'id':str(uuid4()), 'role':'user', 'at':now(), 'in_reply_to':pending['id'],
                'bound_answers':request.answers, 'binding_method':'explicit_batch',
                'text':'\n'.join(f"{fields[k]['label']}: {('Yes' if v else 'No') if isinstance(v,bool) else v}"
                    for k,v in request.answers.items())}
            paused = state.get('pause_requested',False)
            needs_worker = state['status'] in PAUSED or run_id in self.scheduled
            self.scheduled.pop(run_id, None)
            updated = self.repository.save(state, status='needs_input' if paused else 'queued' if needs_worker else state['status'],
                messages=[*state.get('messages',[]),message][-100:], chat_revision=state.get('chat_revision',0)+1,
                answers={**state['answers'],**request.answers}, input_request=None, pending_fields=[], review_digest=None,
                answer_sources={**state.get('answer_sources',{}),**{k:{'type':'chat','message_id':message['id']} for k in request.answers}},
                retry_at=None, recovery_attempts=0, budget_model_base=state.get('agent_calls',0),
                budget_tool_base=state.get('agent_tools',0), message='Your answers are saved. I will read them before the next action.')
            # A pending question can refer to the previous page. Its frozen field
            # labels preserve memory scope even after independent navigation.
            self.repository.remember({**updated,'fields':list(fields.values())},request.answers)
            if needs_worker and not paused:
                self.executor.submit(self._drive,run_id,None,frozenset(request.answers))
            return updated

    def _drive(self, run_id, approval, edited_keys=frozenset()):
        fields = None
        try:
            with self.lock:
                state = self._active(run_id)
                if state is None or state.get("pause_requested"):
                    return
                state = self.repository.refresh_education(state)
                state = self.repository.save(state, status="running", retry_at=None, account_request=None, message="Inspecting the application and choosing the next step.")
            browser = self.browsers.get(run_id)
            if browser is not None and not browser.is_open():
                self._close_browser(run_id)
                browser = None
            if browser is None:
                # A finished browser may remain open briefly for inspection, but
                # never accumulate an unbounded number of browser processes.
                for old_id in list(self.browsers):
                    if self.repository.get(old_id)["status"] in TERMINAL:
                        self._close_browser(old_id)
                if self.browser_factory is ApplicationBrowser:
                    browser = self.browser_factory(state["url"], session_store=self.session_store,
                        owner_key=self.repository.owner_key(state["profile"]))
                else:
                    browser = self.browser_factory(state["url"])
                self.browsers[run_id] = browser
                # Repeated controls can reuse their DOM IDs for another record.
                # Preserve confirmed education answers by record/component and
                # let the agent map the fresh page before filling them again.
                from .education import new_browser_bindings
                with self.lock:
                    current = self._active(run_id)
                    if current is None:return
                    state = self.repository.save(current, **new_browser_bindings(current))
                approval = None  # An approval never survives a new browser session.
            proof = browser.confirmation()
            if proof:
                self.repository.save(self.repository.get(run_id), status="submitted", confirmation=proof,
                    message="The employer displayed an application confirmation.")
                self._close_browser(run_id)
                return
            fields = browser.observe()
            barrier = browser.barrier()
            if barrier:
                self._browser_handoff(run_id, barrier, fields)
                return
            page = browser.page_state() if hasattr(browser, "page_state") else None
            before_digest=self._progress_digest(fields,page,state)
            if not fields and not (page and (page.get('controls') or page.get('text'))) and state.get('automation_mode')!='hybrid':
                raise BrowserBlocked("No supported application form is visible. Open the form in the browser, then continue.")
            with self.lock:
                state = self._active(run_id)
                if state is None or state.get("pause_requested"): return
                recalled, sources = self.repository.recalled_answers(state, fields)
                state = self.repository.save(state, fields=fields, answers={**state["answers"], **recalled},
                    answer_sources={**state.get("answer_sources", {}), **sources})
            initial_chat_revision = state.get("chat_revision", 0)
            outcome = {"reason": "ready", "field_keys": []}
            fill_report = {}
            if approval is None:
                def bulk_fill():
                    with self.lock:
                        current = self.repository.get(run_id)
                        recalled, sources = self.repository.recalled_answers(current, browser.observe())
                        if recalled:
                            current = self.repository.save(current, answers={**current["answers"], **recalled},
                                answer_sources={**current.get("answer_sources", {}), **sources})
                    chat_keys = {key for key, source in current.get("answer_sources", {}).items() if source["type"] == "chat"}
                    result = autofill(browser, current, lambda: self.repository.resume(run_id), edited_keys=edited_keys | chat_keys,
                        active=lambda: self._can_act(run_id) and self.repository.get(run_id).get("chat_revision", 0) == current.get("chat_revision", 0),
                        progress=lambda *args: self._progress(run_id, *args))
                    with self.lock:
                        latest=self.repository.get(run_id)
                        if self._can_act(run_id) and latest.get('chat_revision',0)==current.get('chat_revision',0):
                            self._checkpoint(run_id,document_refresh=current.get('document_refresh',{}))
                    fill_report.update(result)
                    return result
                if state.get("automation_mode", "autofill") == "hybrid":
                    # Explicit chat answers must survive an unavailable model.
                    if edited_keys:
                        bulk_fill()
                    outcome = self.agent_factory().run(browser, state, autofill=bulk_fill,
                        active=lambda: self._can_act(run_id),
                        reserve=lambda kind: self._reserve(run_id, kind),
                        report=lambda *args: self._progress(run_id, *args),
                        refresh=lambda: self._agent_context(run_id), communicate=lambda text: self._say(run_id, text),
                        publish_question=lambda text,keys,fields,revision: self._publish_question(run_id,text,keys,fields,revision),
                        accept_answer=lambda key, value, message_id: self._accept_chat_answer(run_id, key, value, message_id),
                        checkpoint=lambda **changes: self._checkpoint(run_id, **changes),
                        bind_answers=lambda items, revision: self._bind_answers(run_id, items, revision))
                    if outcome["reason"] in {"model_payment_required", "model_error", "model_timeout", "model_unavailable", "model_rate_limited", "invalid_model_response"}:
                        with self.lock:
                            current = self._active(run_id)
                            if current and current.get("chat_revision", 0) == initial_chat_revision:
                                self._recover_chat_answers(current)
                        bulk_fill()
                else:
                    # Autofill-only mode deliberately has no model interpreter.
                    # Preserve its deterministic chat fallback.
                    with self.lock:
                        current = self._active(run_id)
                        if current and current.get("chat_revision", 0) == initial_chat_revision:
                            self._recover_chat_answers(current)
                    bulk_fill()
            state = self._active(run_id)
            if state is None:
                self._close_browser(run_id)
                return
            if state.get("pause_requested"): return
            barrier = browser.barrier()
            if barrier or outcome["reason"] == "authentication_required":
                self._browser_handoff(run_id, barrier or "Sign in or create your account in the open Chrome window, then send continue here.", browser.observe())
                return
            if state.get("chat_revision", 0) != outcome.get("chat_revision", initial_chat_revision):
                self.executor.submit(self._drive, run_id, None)
                return
            fields = browser.observe()
            if outcome.get('question'):
                self._pause_for_question(run_id,outcome['question'],outcome.get('field_keys',[]),fields,
                    outcome.get('chat_revision',initial_chat_revision))
                return
            missing = [field for field in fields if (field["required"] and not field["value"]) or field.get("invalid") or
                (state.get("consent_policy", "ask") == "ask" and is_consent(field) and field["key"] not in state["answers"])]
            for field in fields:
                if (field["key"] in fill_report.get("failed", {}) or field["key"] in state["answers"]) and field not in missing:
                    desired = desired_answer(field, state)
                    if desired is not None and not matches(field, desired):
                        missing.append(field)
            reason = outcome["reason"]
            # The agent can ask about optional fields too (for example voluntary
            # self-identification). They must reach the same question/option UI
            # as required fields, rather than only the pending_fields list.
            requested = set(outcome.get("field_keys", []))
            for field in fields:
                if field["key"] not in requested or field in missing:
                    continue
                desired = desired_answer(field, state)
                if ((desired is None and (not field["value"] or field.get("invalid")))
                        or (desired is not None and not matches(field, desired))):
                    missing.append(field)
            drafts = visible_drafts(state, fields)
            missing.extend(f for f in fields if f['key'] in drafts and f not in missing)
            paths = unresolved_paths(fields,state)
            missing.extend(f for f in fields if f['key'] in paths and f not in missing)
            if reason == "ready" and any(desired_answer(f,state) is not None for f in missing):
                # A model 'done' response is not proof that a known answer passed
                # the site's validation. Return its latest error to the agent.
                reason = "validation_error"
            page = browser.page_state() if hasattr(browser, "page_state") else None
            from .education import gaps as education_gaps
            if reason == 'ready' and education_gaps(state,fields,page,final=True):
                reason='validation_error'
            if reason=='ready' and pending_documents(state,fields):reason='document_upload_required'
            if reason == "ready" and page is not None and not page["can_submit"]:
                reason = "navigation_required"
            if reason != "ready" and self._schedule_recovery(run_id, reason, progressed=self._progress_digest(fields,page,state) != before_digest):
                return
            if reason == 'yielded':
                reason = 'agent_limit'
            if state.get('input_request') and reason != 'ready':
                pending = state['input_request']
                self._pause_for_question(run_id,pending['text'],pending['field_keys'],fields,
                    outcome.get('chat_revision',initial_chat_revision))
                return
            if missing or reason != "ready":
                if reason != "model_payment_required" and hasattr(browser, "enrich_options"):
                    fields = browser.enrich_options(fields, active=lambda: self._can_act(run_id))
                    latest = {f["key"]: f for f in fields}
                    missing = [latest.get(f["key"], f) for f in missing]
                pending = list(dict.fromkeys([f["key"] for f in missing] + outcome.get("field_keys", [])))
                messages = {"model_payment_required": MODEL_PAYMENT_MESSAGE,
                    "model_unavailable": "The configured AI model is unavailable. Check the model settings, or switch to autofill only.",
                    "model_rate_limited": "The AI service is busy. Your answers are saved; continue to retry.",
                    "model_error": "The AI tool call failed. You can retry or use autofill only.",
                    "invalid_model_response": "The configured model did not return a valid tool call. Use a model supporting tool calls.",
                    "model_timeout": "The model response timed out. Completed fields are saved; continue to retry.",
                    "agent_limit": "The agent reached its bounded call limit. Completed fields are saved.",
                    "no_progress": "The agent stopped repeating an unsuccessful action. Check the highlighted control."}
                messages["navigation_required"] = "This application has another step. Enable Agent + autofill, or continue in the browser and then send continue here."
                messages['document_upload_required']='The selected resume or cover letter still needs uploading. Inspect the attachment control before reviewing this application.'
                messages["validation_error"] = "The website still rejects a known answer or needs its final sub-option. Your facts are saved; check the current control or continue to retry."
                with self.lock:
                    state = self._active(run_id)
                    if state is None or state.get("pause_requested"): return
                    if state.get("chat_revision", 0) != outcome.get("chat_revision", initial_chat_revision):
                        self.executor.submit(self._drive, run_id, None)
                        return
                    chat_messages = state.get("messages", [])
                    if missing and reason not in {'no_progress','agent_limit','model_payment_required'}:
                        unknown = [f for f in missing if desired_answer(f, state) is None]
                        failed = [f for f in missing if desired_answer(f, state) is not None]
                        text, question_keys = input_prompt(unknown, failed, {f["key"]: desired_answer(f, state) for f in failed})
                        if any(key in drafts for key in question_keys):
                            text = "I drafted answers from your resume and supplied details below. Edit the drafts and add any missing details, then send your answers.\n\n" + text
                        if reason in {"model_error", "model_timeout", "model_unavailable", "model_rate_limited", "invalid_model_response"}:
                            text = messages[reason] + " Your chat messages are saved.\n\n" + text
                    else:
                        text = messages.get(reason, "The remaining step needs attention. Your completed answers are saved.")
                        question_keys = []
                    if not chat_messages or chat_messages[-1].get("text") != text:
                        chat_messages = [*chat_messages, {"id": str(uuid4()), "role": "assistant", "at": now(),
                            "text": text, "question_keys": question_keys}][-100:]
                    self.repository.save(state, status="needs_input", fields=fields, pending_fields=pending,
                        review_digest=None, agent_reason=reason, messages=chat_messages,
                        input_request=None,
                        message=messages.get(reason, "Completed fields are kept. Answer only the highlighted questions, then continue."))
                return
            digest = self._review_digest(fields, page)
            if (not state["auto_submit"] or state.get("recovery_review_required")) and approval != digest:
                with self.lock:
                    state = self._active(run_id)
                    if state is None or state.get("pause_requested"): return
                    if state.get("chat_revision", 0) != outcome.get("chat_revision", initial_chat_revision):
                        self.executor.submit(self._drive, run_id, None)
                        return
                    review = {f["key"]:f for f in state.get("review_fields", [])}
                    review.update({f["key"]:f for f in fields})
                    self.repository.save(state, status="awaiting_review", fields=fields, review_fields=list(review.values()),
                        pending_fields=[], review_digest=digest,
                        task_plan=[],
                        message="The form is filled. Check the browser and the answers below before submitting.")
                return
            # Submission remains a host-only transition, never a model tool.
            with self.lock:
                current = self._active(run_id)
                if current is None or current.get("pause_requested"):
                    return
                if current.get("chat_revision", 0) != outcome.get("chat_revision", initial_chat_revision):
                    self.executor.submit(self._drive, run_id, None)
                    return
                self.repository.save(current, status="submitting", fields=fields, recovery_review_required=False,
                    message="Submitting once and waiting for the employer confirmation.")
            browser.submit()
            proof = browser.wait_confirmation()
            self.repository.save(self.repository.get(run_id),
                status="submitted" if proof else "submission_unknown", confirmation=proof,
                message="Application confirmed by the employer." if proof else
                "Submission was attempted but confirmation is unavailable. Check the browser or employer email; automatic retry is disabled.")
            if proof:
                self._close_browser(run_id)
        except Exception as exc:
            state = self.repository.get(run_id)
            if state["status"] in TERMINAL or state.get("pause_requested"):
                return
            submitting = state["status"] == "submitting"
            if not submitting and not isinstance(exc, BrowserBlocked) and self._schedule_recovery(run_id, "browser_error"):
                return
            message = ("Submission may have reached the employer. Check the browser or confirmation email; automatic retry is disabled."
                if submitting else str(exc) if isinstance(exc, BrowserBlocked) else
                "The browser could not finish this step. Check that Chrome is installed and the form is open, then continue.")
            try:
                self.repository.save(state, status="submission_unknown" if submitting else "needs_input",
                    message=message, error_type=type(exc).__name__,
                    **({"fields": fields} if fields is not None else {}))
            except ApplyConflict:
                pass

    @staticmethod
    def _review_digest(fields, page):
        if page is None: return form_digest(fields)
        return hashlib.sha256(json.dumps({"fields":form_digest(fields), "url":page["url"],
            "heading":page["heading"], "text":page["text"], "can_submit":page["can_submit"]},
            sort_keys=True).encode()).hexdigest()

    def _browser_handoff(self, run_id, message, fields):
        browser = self.browsers.get(run_id)
        try:
            account = authentication.context(browser) if isinstance(browser, ApplicationBrowser) else None
        except Exception:
            account = None
        with self.lock:
            state = self._active(run_id)
            if state is None or state.get("pause_requested"): return
            history = state.get("messages", [])
            if not history or history[-1].get("text") != message:
                history = [*history, {"id":str(uuid4()), "role":"assistant", "text":message,
                    "at":now(), "question_keys":[]}][-100:]
            self.repository.save(state, status="needs_input", fields=fields, pending_fields=[],
                input_request=None, review_digest=None, agent_reason="browser_handoff", account_request=account, messages=history, message=message)

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            self.scheduled.clear()
        self.executor.submit(lambda: [self._close_browser(key) for key in list(self.browsers)])
        self.executor.shutdown(wait=True)
