"""Scripted semantic responses for IO-free workflow tests, never production logic."""
from eregion.domain.search_qualification import SearchQualification


def judge(request, postings):
    from eregion.runtime.career.qualification import request_fields
    from eregion.runtime.career.search_policy import constraints
    fields=request_fields({'goal':request});policy=constraints({'goal':request})
    def item(status,job,source):
        text=job.get(source) or ''
        return {'status':status,'request_quote':request if status!='not_requested' else '',
                'reason':'Scripted test-model response.',
                'evidence':[{'source':source,'quote':text[:1000]}] if text and status!='not_requested' else []}
    results=[]
    for job in postings:
        role='not_requested' if not fields['role'] else 'met' if fields['role'].removeprefix('and score ').casefold() in job['title'].casefold() else 'unknown'
        location='not_requested' if not fields['location'] else 'met' if fields['location'].casefold() in job['location'].casefold() else 'unknown'
        warning=recommendation_warning({**policy,'strict':False},job['title'],job['description'].replace('Requirements:', '\n')) if policy else None
        level='not_requested' if not policy else 'met' if warning is None else 'unmet' if warning.get('actual') else 'unknown'
        results.append({'posting_id':job['posting_id'],'role':item(role,job,'title'),
            'location':item(location,job,'location'),'seniority':item(level,job,'description' if job['description'] else 'title'),
            'vacancy':item('met',job,'description')})
    return SearchQualification.model_validate({'decisions':results})


# Frozen responses for historical test fixtures; never imported by runtime.
import re
from eregion.runtime.career.search_policy import seniority
ENTRY_LEVELS={'junior','new_grad','intern'}


def opening_level(description):
    """Level stated for this opening itself, never colleagues it mentors.

    An explicit entry-level/junior statement or a bounded low range (max 3 years)
    is junior evidence; any stated minimum of 4+ years overrides it. A preferred
    "minimum 1 year" or an "Associate" title alone does not establish a level.
    """
    text=(description or '').casefold()
    junior=bool(re.search(r'\b(?:entry[- ]level|junior)[ -]+(?:role|position|opportunity)\b|'
        r'\bthis (?:role|position) is (?:an? )?(?:entry[- ]level|junior)\b',text))
    for m in re.finditer(r'\b(?:seeking|hiring|recruiting|looking for)\s+(?:an?\s+)?(?:entry[- ]level|junior)\s+(?:professional|candidate|analyst|engineer|designer)\b',text):
        clause=re.split(r'[.!?\n]',text[:m.start()])[-1][-80:]
        if not re.search(r"\b(?:not|never|isn't|aren't|don't)\b",clause):junior=True
    junior=junior or any(0<=int(m[1])<=int(m[2])<=3 for m in re.finditer(
        r'(?:^|\n)\s*(?:[-*•]\s*)?(?:(?:requires?|minimum(?: of)?|at least|must have|candidates? must have|'
        r'you (?:have|bring)|(?:the )?(?:ideal|successful) candidate (?:has|will have)|experience\s*:)\s+)?'
        r"(\d+)\s*[-–]\s*(\d+)\s+years?['’]?(?:\s+of)?\s+[^\n.;:!?]{0,80}?experience\b",text))
    minimum=re.finditer(r'\b(?:require[ds]?|minimum|at least|must have|you (?:have|bring))\s+(?:(?:at least|of)\s+)?(\d+)'
        r'(?:\s*[-–]\s*\d+)?\+?\s+years?\b|\b(\d+)(?:\s*[-–]\s*\d+)?\+?\s+years? (?:of )?experience\s+(?:is )?required\b',text)
    if any(int(next(g for g in m.groups() if g is not None))>=4 for m in minimum):return 'senior'
    return 'junior' if junior else None


def recommendation_warning(policy,title,description=''):
    if not policy:return None
    actual=seniority(title)
    if set(policy['levels']) & ENTRY_LEVELS and opening_level(description) == 'senior':
        actual='senior'  # An explicit 4+ minimum overrides even a Junior/New Grad title.
    if actual is None and set(policy['levels'])&ENTRY_LEVELS:
        # A level-free title is not junior evidence; read the opening itself.
        actual=opening_level(description)
    # Junior and new-grad are both entry level: a "Graduate Data Analyst" satisfies a
    # junior request (paid P1b raised a false mismatch). Internships stay separate.
    if actual in policy['levels'] or (actual in {'junior','new_grad'} and set(policy['levels'])&{'junior','new_grad'}):return None
    requested=', '.join(policy['levels'])
    if policy.get('strict'):
        raise ValueError(f'Seniority constraint: {requested} only was requested; this posting is {actual or "unverified level"}. Do not recommend it unless the user changes that condition.')
    if actual:
        return {'requested':policy['levels'],'actual':actual,
            'message':f'Seniority mismatch: requested {requested}; this posting is {actual}.'}
    return {'requested':policy['levels'],'actual':None,
        'message':f'Level unverified: requested {requested}, but neither the title nor the description states '
            f'the opening level. Do not describe it as a {requested} match; it does not count toward the requested level.'}
