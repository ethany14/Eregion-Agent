"""Reusable bulk-fill tool, with field-level failures and bounded verification."""
import time
import re

from .errors import failure_detail, failure
from .contracts import candidate_answer
from .matching import city_equivalent, consent_answer, equivalent, resolve_option, field_category
from .decisions import active_decision


def desired_answer(field, state):
    decision = active_decision(field, state)
    if decision: return decision["value"]
    if field['key'] in state['answers']:return state['answers'][field['key']]
    if field['kind'] != 'file' and 'cover letter' in field['label'].casefold() and state.get('cover_letter'):
        return state['cover_letter']
    from .education import bound_value
    education=bound_value(field,state)
    if education is not None:return education
    answer = candidate_answer(field, state["profile"], state["answers"])
    return answer if answer is not None else consent_answer(field, state.get("consent_policy", "ask"))


def matches(field, value):
    if field['kind'] == 'location':
        # The browser exposes a value only after this picker commits a place.
        return bool(field['value']) and city_equivalent(value, field['value']) and not field.get('invalid')
    if field["kind"] in {"radio", "select", "combobox"} or field.get("choice_control"):
        option = resolve_option(field["label"], value, field.get("options", []))
        if option:
            selected = str(field["value"]).strip().casefold()
            exact = selected in {str(option["label"]).strip().casefold(), str(option["value"]).strip().casefold()}
            country_match = (field.get('value_committed') and field_category(field['label']) == 'country'
                and equivalent(field['label'], field['value'], option))
            return bool(exact or country_match) and not field.get("invalid")
        if not field.get("options") and equivalent(field["label"], value, {"label": field["value"]}):
            return not field.get("invalid")
        accepted = {str(value).strip().casefold()}
        for option in field.get("options", []):
            if accepted.intersection({str(option["label"]).strip().casefold(), str(option["value"]).strip().casefold()}):
                accepted.update((str(option["label"]).strip().casefold(), str(option["value"]).strip().casefold()))
        return str(field["value"]).strip().casefold() in accepted and not field.get("invalid")
    if field['kind'] == 'tel' or (field['kind'] == 'text' and re.search(r'\b(phone|telephone|mobile)\b', field['label'], re.I)):
        observed, expected = str(field['value']), str(value)
        if all(re.fullmatch(r'[\d\s()+.\-]+', text) for text in (observed, expected)):
            # Browser input masks may insert punctuation. Never drop a country
            # prefix here: the agent must explicitly bind that format decision.
            digits = re.sub(r'\D', '', expected)
            return bool(digits) and re.sub(r'\D', '', observed) == digits and not field.get('invalid')
    if field['kind'] in {'text', 'textarea', 'search'} and isinstance(value, str):
        # Single-line controls can flatten line breaks in prose. Verify all words
        # and punctuation while tolerating this presentation-only whitespace.
        normalize = lambda text: re.sub(r'\s+', ' ', str(text)).strip()
        return normalize(field['value']) == normalize(value) and not field.get('invalid')
    return field["value"] == value and not field.get("invalid")


def document_kind(field,state):
    if field['kind']!='file':return None
    bound = state.get('document_bindings',{}).get(field['key'])
    if bound:return bound
    label=field['label'].casefold()
    if 'cover letter' in label:return 'cover_letter'
    if re.search(r'resume|résumé|curriculum|\bcv\b',label):return 'resume'
    return None


def pending_documents(state,fields):
    refresh=state.get('document_refresh',{})
    pending=['resume'] if refresh.get('resume') else []
    if refresh.get('cover_letter') and any(document_kind(f,state)=='cover_letter' for f in [*fields,*state.get('review_fields',[])]):
        pending.append('cover_letter')
    return pending


def autofill(browser, state, resume, *, edited_keys=frozenset(), active=lambda: True, progress=lambda *args: None):
    attempts, failed, completed, details = {}, {}, [], {}
    deadline = time.monotonic() + 90
    for _ in range(60):
        if not active():
            return {"cancelled": True, "filled": completed, "failed": failed, "failure_details": details}
        fields = browser.observe()
        if browser.barrier():
            break
        pending = []
        # Upload first: ATS resume parsers may populate contact fields afterwards.
        for field in sorted(fields, key=lambda item: item["kind"] != "file"):
            key = field["key"]
            if attempts.get(key, 0) >= (1 if state.get("automation_mode") == "hybrid" else 2):
                continue
            value = desired_answer(field, state)
            # A website's preselected value must not override the candidate's
            # confirmed answer, especially remembered refusals of consent.
            if value is not None and matches(field, value):
                failed.pop(key, None); details.pop(key, None)
                continue
            if value is not None and field.get("invalid") and matches({**field, "invalid":False}, value):
                failed[key] = "; ".join(field.get("errors",[])) or "website_validation_error"
                details[key] = failure("validation_error", failed[key])
                continue # Rewriting a rejected value is not a repair strategy.
            kind=document_kind(field,state)
            if kind=='resume':
                if field["value"] and not state.get('document_refresh',{}).get(kind):
                    continue
                value = resume()
            elif kind=='cover_letter' and state.get('cover_letter'):
                if field['value'] and not state.get('document_refresh',{}).get(kind):continue
                from job_agent.pdf_rendering import render_letter_pdf
                value = render_letter_pdf(state['cover_letter'])
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
                plain = field['kind'] in {'text', 'email', 'tel', 'url', 'textarea', 'number', 'search'} and not field.get('choice_control')
                if not plain and pending:
                    break
                pending.append((field, value, plain))
                if not plain:
                    break
        if not pending or time.monotonic() > deadline:
            break
        attempted = []
        for field, value, plain in pending:
            if not active():
                break
            key = field['key']
            attempts[key] = attempts.get(key, 0) + 1
            try:
                upload = document_kind(field, state)
                target = {**field, 'upload_filename': 'cover-letter.pdf' if upload == 'cover_letter' else 'resume.pdf'} if upload else field
                if plain and hasattr(browser, 'fill_plain'):
                    browser.fill_plain(target, value)
                else:
                    browser.fill(target, value)
                attempted.append((field, value))
            except Exception as exc:
                details[key] = failure_detail(exc)
                failed[key] = details[key]['error_code']
        observed = browser.observe()
        current_fields = {f['key']: f for f in observed}
        for field, value in attempted:
            key = field['key']
            current = current_fields.get(key)
            verified = (current is None or bool(current['value'])) if field['kind'] == 'file' else current is not None and matches(current, value)
            if verified:
                completed.append(key)
                failed.pop(key, None); details.pop(key, None)
                if document_kind(field, state) and state.get('document_refresh'):
                    state['document_refresh'][document_kind(field, state)] = False
            else:
                failed[key] = 'value_not_retained'
                details[key] = failure('value_not_retained', 'The control did not retain the supplied value.')
        progress(observed, 'autofill', None, 'needs_agent' if failed else 'verified')
    return {"filled": list(dict.fromkeys(completed)), "failed": failed, "failure_details": details}
