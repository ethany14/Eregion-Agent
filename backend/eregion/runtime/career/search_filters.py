"""Conservative card filtering; unknown evidence is never an exclusion."""
from .search_policy import constraints, seniority

FILTER_FIELDS = ('experience_level', 'work_type', 'employment_type', 'posted')
FILTER_SCHEMA = {
    'experience_level': {'type':'string','enum':['internship','entry','associate','mid-senior','director','executive']},
    'work_type': {'type':'string','enum':['remote','hybrid','onsite']},
    'employment_type': {'type':'string','enum':['full-time','part-time','contract','internship','temporary']},
    'posted': {'type':'string','enum':['24h','week','month']},
}

def effective_filters(state, args):
    result={k:args[k] for k in FILTER_FIELDS if args.get(k)}
    for k,v in result.items():
        if v not in FILTER_SCHEMA[k]['enum']: raise ValueError('Unsupported search filter: '+k)
    levels=set(constraints(state).get('levels',[]))
    # Only map unambiguous user-owned constraints, never a guessed model query level.
    mapped={'junior':'entry','new_grad':'entry','intern':'internship'}
    values={mapped.get(v) for v in levels}
    if values and None not in values and len(values)==1:
        result['experience_level']=next(iter(values))
    return result

def filter_cards(jobs, state):
    levels=set(constraints(state).get('levels',[]))
    if levels & {'junior','new_grad'}: levels |= {'junior','new_grad'}
    kept,excluded=[],[]
    for job in jobs:
        actual=seniority(job.get('title') or '')
        if levels and actual and actual not in levels:
            excluded.append({'url':job.get('url'),'title':job.get('title'),
                             'reason':'explicit_seniority_mismatch','actual':actual})
        else: kept.append(job)
    from .search_recovery import search_request
    import re
    request = search_request(state)
    if request and request['words']:
        kept.sort(key=lambda j: -len(request['words'] & set(re.findall(r'[a-z]+', (j.get('title') or '').lower()))))
    return kept, {'excluded_count':len(excluded),'excluded':excluded,
                  'unknowns_retained':True,'qualification':'cards_only; JD verification still required'}
