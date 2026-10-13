"""Bounded discovery variants and card triage; never changes qualification criteria."""
import re
from .qualification import request_fields
from .search_policy import constraints


def normalized(text):
    return ' '.join(re.findall(r'[a-z0-9]+',(text or '').casefold()))


def source_limits(state,args=None):
    from .search_recovery import search_request
    request=search_request(state)
    large=bool(request and request['count']>=10)
    fields=request_fields(state);query=normalized((args or {}).get('query'))
    broad=query in {normalized(fields['role']),normalized(f"{fields['role']} in {fields['location']}")}
    # One broad LinkedIn call can page deep (one source call, ~9 s/page); 8 pages keeps
    # it inside the 120 s per-call deadline instead of repeating near-duplicate queries.
    # The LinkedIn source budget is an explicit task/experiment setting, never raised implicitly.
    import os
    configured=os.getenv('JOB_AGENT_LINKEDIN_MAX_CALLS','').strip()
    calls=int(configured) if configured.isdigit() and int(configured)>0 else 50 if large else 26
    return {'calls':calls,
            'pages':8 if large and broad else 4 if large else 2 if (args or {}).get('limit',10)>10 else 1}


def variants(state,args):
    from .search_recovery import search_request
    request=search_request(state)
    role=request_fields(state)['role']
    levels=set(constraints(state).get('levels',[]))
    if not request or request['count']<10 or not role or not levels or not levels<={'junior','new_grad'}:
        return [args['query']]
    place=request_fields(state)['location']
    # The provider level filter already scopes the broad query; '"role" in place' only
    # repeated it with extra keywords. Explicit early-career wording is ranked first.
    # The unquoted form also reaches equivalent titles that split the words
    # ('Analyst, Data Operations'); the model still judges the occupation from the JD.
    # The occupation head ('analyst') with explicit early-career words reaches equivalent
    # titles whose posting states the level ('Junior Analyst, Data & Reporting').
    head=role.split()[-1]
    queries=[f'"{role}" AND (junior OR "entry level" OR graduate OR "new grad")',f'"{role}"',role,
             f'"{head}" AND (junior OR "entry level" OR graduate OR "new grad" OR "early career")']
    aliases=[f'junior {role}',f'entry level {role}',f'graduate {role}',role,f'{role} in {place}',f'junior {role} in {place}',*queries]
    if normalized(args['query']) not in {normalized(q) for q in aliases}:
        return [args['query']]
    return list(dict.fromkeys(queries))  # Original source filters and final gates remain mandatory.


def card_priority(job,state):
    from .search_policy import seniority
    fields=request_fields(state);role=normalized(fields['role']);title=normalized(job.get('title'))
    exact=bool(role and re.search(r'\b'+re.escape(role)+r'\b',title))
    words=len(set(role.split()) & set(title.split()))
    place=normalized(fields['location']);location=normalized(job.get('location'))
    entry=seniority(job.get('title') or '') in {'junior','new_grad'}
    place_priority=0 if place and place in location else 1 if not location else 2
    return (-int(exact),place_priority,-int(entry),-words)
