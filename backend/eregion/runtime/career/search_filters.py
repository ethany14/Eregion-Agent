"""Provider filter translation and advisory card ordering; no eligibility verdicts."""
from .search_policy import constraints

FILTER_FIELDS = ('experience_level', 'work_type', 'employment_type', 'posted')
FILTER_SCHEMA = {
    'experience_level': {'type':'string','enum':['internship','entry','associate','mid-senior','director','executive']},
    'work_type': {'type':'string','enum':['remote','hybrid','onsite','onsite_or_hybrid'],
                  'description':'Provider work-arrangement filter. A remote-only posting must still show where it may be worked '
                                'to satisfy a requested city; onsite_or_hybrid narrows retrieval to postings tied to a workplace.'},
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

LINKEDIN_WORK_TYPES={'remote':'remote','hybrid':'hybrid','onsite':'on_site','onsite_or_hybrid':'on_site,hybrid'}


def filter_cards(jobs, state):
    from .search_strategy import card_priority
    # Ranking is advisory. Semantic rejection belongs to the model after it
    # has the actual posting, not a growing vocabulary of title exclusions.
    kept=list(jobs)
    from .search_recovery import search_request
    request = search_request(state)
    if request and request['words']:
        kept.sort(key=lambda j:card_priority(j,state))
    return kept, {'excluded_count':0,'excluded':[],
                  'unknowns_retained':True,'qualification':'advisory_order_only; model assessment of the JD still required'}
