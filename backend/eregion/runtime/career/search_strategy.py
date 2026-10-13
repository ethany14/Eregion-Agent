"""Bounded discovery variants and card triage; never changes qualification criteria."""
import re
from .qualification import request_fields
from .search_policy import constraints


def normalized(text):
    return ' '.join(re.findall(r'[a-z0-9]+',(text or '').casefold()))


def variants(state,args):
    from .search_recovery import search_request
    request=search_request(state)
    role=request_fields(state)['role']
    levels=set(constraints(state).get('levels',[]))
    if not request or request['count']<10 or not role or not levels or not levels<={'junior','new_grad'}:
        return [args['query']]
    queries=[f'junior {role}',f'entry level {role}',f'graduate {role}',f'"{role}"']
    if normalized(args['query']) not in {normalized(q) for q in queries}:
        return [args['query']]
    return queries  # Source entry filter and user's location remain identical for all four.


def card_mismatch(job,state):
    """Only explicit competing titles are excluded; blank/truncated/ambiguous cards stay."""
    role=normalized(request_fields(state)['role']);title=job.get('title') or ''
    if not role or not title or re.search(r'\.\.\.|…',title):return None
    actual=normalized(title)
    if re.search(r'\b'+re.escape(role)+r'\b',actual):return None
    # A broad 'Analyst' heading or differently worded data role is not a proven mismatch.
    # Match complete occupational names, not employer names or isolated keywords.
    others={
        'data analyst':r'\b(?:financial|investment|equity|credit|business|yield|pricing|marketing|commercial|operations|systems|intelligence|business insights) analyst\b|'
                       r'\b(?:software engineer|data scientist|data engineer|accountant|recruiter|quantitative researcher|analytics consultant|product operations)\b',
    }
    if role in others and re.search(others[role],actual):
        return {'reason':'explicit_role_mismatch','quote':title,'requested_role':role}
    return None


def card_priority(job,state):
    fields=request_fields(state);role=normalized(fields['role']);title=normalized(job.get('title'))
    exact=bool(role and re.search(r'\b'+re.escape(role)+r'\b',title))
    words=len(set(role.split()) & set(title.split()))
    place=normalized(fields['location']);location=normalized(job.get('location'))
    return (-int(exact),-int(bool(place) and place in location),-words)
