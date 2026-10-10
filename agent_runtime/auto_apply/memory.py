"""Scope checks for reusing answers the user approved, and the approval queue."""
import re
from urllib.parse import parse_qs, unquote, urlsplit

from .matching import clean, is_consent, question_identity, salary_compatible

SCOPES = ("global", "employer")
# Preferences that commonly differ between roles or employers. They are reused
# everywhere only when the user explicitly approves a global scope.
SENSITIVE = re.compile(r"\b(salary|compensation|pay|wages?|hourly rate|start date|earliest start|availability|"
                       r"notice period|relocat\w*|commute|on.?site|hybrid|remote)\b|薪资|到岗", re.I)


def sensitive(label):
    return bool(SENSITIVE.search(label or ""))


def default_scope(label):
    return "employer" if sensitive(label) else "global"


def approved(memory):
    # Records saved before approval tracking were explicit user answers.
    return memory.get("status", "approved") == "approved"


def employer_key(url):
    """An employer namespace, not just the shared ATS hostname."""
    parsed = urlsplit(url or "")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        return None
    if any(host == domain or host.endswith("." + domain)
           for domain in ("linkedin.com", "indeed.com", "glassdoor.com")):
        return None  # Aggregator URLs alone do not identify the hiring employer.
    for domain in ("greenhouse.io", "lever.co", "ashbyhq.com", "smartrecruiters.com"):
        if host == domain or host.endswith("." + domain):
            board = unquote(parsed.path).strip("/").split("/")[0].casefold()
            if domain == "greenhouse.io" and board == "embed":
                board = parse_qs(parsed.query).get("for", [""])[0].casefold()
            if not board or board in {"embed", "jobs", "job", "apply", "application"}:
                return None  # A shared landing page does not identify an employer.
            return f"{domain}:{board}"
    return host


def same_employer(first_url, second_url):
    first, second = employer_key(first_url), employer_key(second_url)
    return first is not None and first == second


def record_scope(record):
    # Match memories(): legacy explicit answers were globally approved.
    return record.get("scope", "global" if "status" not in record else default_scope(record["question"]))


def compatible(memory, field, state):
    if memory.get('source') != 'user_answer' or not approved(memory) or field['kind'] in {'password', 'file'}:
        return False
    if memory.get('scope', 'global') == 'employer' and not same_employer(memory.get('url'), state.get('url')):
        return False
    source, target = memory['question'], field['label']
    first, second = question_identity(source), question_identity(target)
    if not salary_compatible(source, memory.get("value", ""), target):
        return False
    # A repeated education row must be grounded in its own record.
    if state['profile'].get('education') and re.search(r'\b(school|university|college|degree|major|field of study)\b', target, re.I):
        return False
    consent = is_consent({'kind': 'checkbox', 'label': source}) or is_consent(field)
    material_scope = r'\b(sponsor\w*|immigration|visa|authori[sz]ed|eligible|citizen\w*)\b'
    if consent or re.search(material_scope, source+' '+target, re.I):
        return first == second
    # Employer-specific facts (employment, referrals, relationships) do not
    # transfer between employers just because the question has the same wording.
    employer = r'\b(previously|former|formerly|employee|employed|worked|relative|referr\w*|relationship)\b'
    if re.search(employer, source+' '+target, re.I) and not same_employer(memory.get('url'), state.get('url')):
        return False
    if bool(re.search(r'\b(not|never|without)\b', clean(source))) != bool(re.search(r'\b(not|never|without)\b', clean(target))):return False
    return True


def review_fields(state, fields):
    known = {f["key"]: f for f in state.get("review_fields", [])}
    known.update({f["key"]: f for f in fields})
    return known


def pending_approvals(state, fields):
    """Answers used in this run that the user has not yet approved for reuse."""
    known = review_fields(state, fields)
    items = []
    for key, source in state.get("answer_sources", {}).items():
        if not source.get("pending_approval") or key not in state["answers"] or key not in known:
            continue
        field = known[key]
        if field["kind"] in {"file", "password"}:
            continue
        items.append({"key": key, "label": field["label"], "value": state["answers"][key],
            "origin": source.get("interpretation", "chat"), "sensitive": sensitive(field["label"]),
            "scope": default_scope(field["label"])})
    return items


def review_required(state, fields):
    """Auto-submit only answers the user supplied or already approved."""
    known = review_fields(state, fields)
    defaults = any(decision.get("mode") == "default" for key, decision in state.get("field_decisions", {}).items()
                   if key in known)
    return defaults or bool(pending_approvals(state, fields))
