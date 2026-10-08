"""Scope checks for model-selected reuse of a confirmed answer."""
import re
from urllib.parse import urlsplit

from .matching import clean, is_consent, question_identity


def compatible(memory, field, state):
    if memory.get('source') != 'user_answer' or field['kind'] in {'password', 'file'}:
        return False
    source, target = memory['question'], field['label']
    first, second = question_identity(source), question_identity(target)
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
    if re.search(employer, source+' '+target, re.I):
        a, b = urlsplit(memory.get('url') or ''), urlsplit(state.get('url') or '')
        if not a.hostname or a.hostname != b.hostname:
            return False
        if re.search(r'greenhouse\.io$|lever\.co$|ashbyhq\.com$', a.hostname):
            if a.path.split('/')[1:2] != b.path.split('/')[1:2]:return False
    if bool(re.search(r'\b(not|never|without)\b', clean(source))) != bool(re.search(r'\b(not|never|without)\b', clean(target))):return False
    return True
