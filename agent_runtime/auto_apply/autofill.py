"""Reusable bulk-fill tool, with field-level failures and bounded verification."""
import time

from .contracts import candidate_answer
from .matching import consent_answer, equivalent, resolve_option
from .decisions import active_decision


def desired_answer(field, state):
    decision = active_decision(field, state)
    if decision: return decision["value"]
    if field['key'] in state['answers']:return state['answers'][field['key']]
    from .education import bound_value
    education=bound_value(field,state)
    if education is not None:return education
    answer = candidate_answer(field, state["profile"], state["answers"])
    return answer if answer is not None else consent_answer(field, state.get("consent_policy", "ask"))


def matches(field, value):
    if field["kind"] in {"radio", "select", "combobox"} or field.get("choice_control"):
        option = resolve_option(field["label"], value, field.get("options", []))
        if option:
            return str(field["value"]).strip().casefold() in {str(option["label"]).strip().casefold(), str(option["value"]).strip().casefold()} and not field.get("invalid")
        if not field.get("options") and equivalent(field["label"], value, {"label": field["value"]}):
            return not field.get("invalid")
        accepted = {str(value).strip().casefold()}
        for option in field.get("options", []):
            if accepted.intersection({str(option["label"]).strip().casefold(), str(option["value"]).strip().casefold()}):
                accepted.update((str(option["label"]).strip().casefold(), str(option["value"]).strip().casefold()))
        return str(field["value"]).strip().casefold() in accepted and not field.get("invalid")
    return field["value"] == value and not field.get("invalid")


def autofill(browser, state, resume, *, edited_keys=frozenset(), active=lambda: True, progress=lambda *args: None):
    attempts, failed, completed = {}, {}, []
    deadline = time.monotonic() + 90
    for _ in range(60):
        if not active():
            return {"cancelled": True, "filled": completed, "failed": failed}
        fields = browser.observe()
        if browser.barrier():
            break
        pending = None
        # Upload first: ATS resume parsers may populate contact fields afterwards.
        for field in sorted(fields, key=lambda item: item["kind"] != "file"):
            key = field["key"]
            if attempts.get(key, 0) >= 2:
                continue
            value = desired_answer(field, state)
            # A website's preselected value must not override the candidate's
            # confirmed answer, especially remembered refusals of consent.
            if value is not None and matches(field, value):
                failed.pop(key, None)
                continue
            if value is not None and field.get("invalid") and matches({**field, "invalid":False}, value):
                failed[key] = "; ".join(field.get("errors",[])) or "website_validation_error"
                continue # Rewriting a rejected value is not a repair strategy.
            if field["kind"] == "file" and "resume" in field["label"].casefold():
                if field["value"]:
                    continue
                value = resume()
            if value is not None:
                if (state.get("automation_mode") == "hybrid" and value == state["profile"].get("phone")
                        and key not in state["answers"] and not active_decision(field,state)):
                    # The model sees the whole contact section and decides whether
                    # this website expects a full number or separate components.
                    continue
                # A custom picker can contain text while still having no selected
                # value. Let the model explore its choices instead of repeatedly
                # typing the same answer into the search input.
                if (field.get("choice_control") and field["kind"] not in {"select", "radio", "combobox"}
                        and not field.get("options") and state.get("automation_mode") == "hybrid"):
                    continue
                pending = field, value
                break
        if pending is None or time.monotonic() > deadline:
            break
        field, value = pending
        key = field["key"]
        attempts[key] = attempts.get(key, 0) + 1
        try:
            browser.fill(field, value)
            # Reading a fresh field is intentional: frameworks replace nodes.
            observed = browser.observe()
            current = next((item for item in observed if item["key"] == key), None)
            verified = (current is None or bool(current["value"])) if field["kind"] == "file" else current is not None and matches(current, value)
            if verified:
                completed.append(key)
                failed.pop(key, None)
            else:
                failed[key] = "value_not_retained"
            progress(observed, "autofill", key, "verified" if verified else "not_retained")
        except Exception as exc:
            failed[key] = type(exc).__name__
            progress(browser.observe(), "autofill", key, "needs_agent")
    return {"filled": list(dict.fromkeys(completed)), "failed": failed}
