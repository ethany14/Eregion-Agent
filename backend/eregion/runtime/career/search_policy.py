"""User-owned search constraints; model plans and tool queries are not authority."""
import re

LEVELS=(('principal',r'principal'),('staff',r'staff'),('senior',r'senior|sr\.?'),
        ('new_grad',r'new[ -]grad(?:uate)?|graduate'),('junior',r'junior|jr\.?|entry[ -]level'),
        ('mid',r'mid[ -]level|intermediate'),('intern',r'intern(?:ship)?'))


def seniority(text):
    return next((name for name,pattern in LEVELS if re.search(r'\b(?:'+pattern+r')\b',text,re.I)),None)


def update_constraints(current,text,message_id):
    value=current
    search_context=False
    for clause in re.split(r'[.;!?\n,]',text):
        clause=clause.strip()
        if not clause:continue
        value=_update_directive(value,clause,message_id,search_context=search_context)
        if re.match(r'^(?:(?:please|can you|could you|I want you to)\s+)?(?:find|search|look for|I am looking for|I want)\b',clause,re.I) and re.search(r'\b(?:jobs?|roles?|positions?)\b',clause,re.I):search_context=True
    if value!=current:value={**value,'request_quote':text[:500]}
    return value


def _update_directive(current,text,message_id,*,search_context=False):
    # Only a direct search instruction or an explicit constraint edit has
    # authority. "only" inside a question about a JD is not a search edit.
    clause=re.split(r'[.;!?\n]',text,maxsplit=1)[0].strip()
    prefix=r'^(?:(?:please|can you|could you|I want you to)\s+)?'
    search=re.match(prefix+r'(?:find|search(?: for)?|look for|I am looking for|I want)\b(.+?\b(?:jobs?|roles?|positions?)\b)',clause,re.I)
    exclusion=re.match(prefix+r'(?:do not include|don\x27t include|exclude|remove|no)\s+(.+)',clause,re.I)
    level_pattern='|'.join(pattern for _,pattern in LEVELS)
    edit=bool((current or search_context) and re.match(prefix+r'(?:(?:also\s+)?include\b|switch\b|change\b|(?:I am |I\x27m )?open to\b|'
        r'(?:'+level_pattern+r')(?:\s+roles?)?\s+(?:is|are)\s+(?:fine|acceptable)\b|(?:'+level_pattern+r')\s+only\b)',clause,re.I))
    if exclusion and current:
        removed={name for name,pattern in LEVELS if re.search(r'\b(?:'+pattern+r')\b',exclusion[1],re.I)}
        allowed=[name for name in current['levels'] if name not in removed]
        # A contradiction removing every allowed level needs clarification;
        # retain the restrictive policy rather than silently permit all levels.
        if allowed and allowed!=current['levels']:
            return {**current,'levels':allowed,'source_message_id':message_id,'request_quote':text[:500]}
        return current
    if not search and not edit:return current
    directive=search[0] if search else clause
    levels=[]
    for name,pattern in LEVELS:
        match=re.search(r'\b(?:'+pattern+r')\b',directive,re.I)
        if match and not re.search(r'\b(?:not|exclude|excluding|no)(?:\s+\w+){0,2}\s+$',directive[:match.start()],re.I):levels.append(name)
    if not levels:return current
    addition=bool(current and re.search(r'\b(?:also|too|include)\b',directive,re.I) and not re.search(r'\b(?:instead|only|switch)\b',directive,re.I))
    allowed=list(dict.fromkeys([*current.get('levels',[]),*levels])) if addition else levels
    return {'levels':allowed,'strict':bool(re.search(r'\b(?:only|exclusively)\b',directive,re.I)) or bool(addition and current.get('strict')),
        'source_message_id':message_id,'request_quote':text[:500]}


def constraints(state):
    if 'search_constraints' in state:return state['search_constraints']
    value=update_constraints({},state.get('goal',''),'initial_goal')
    for message in state.get('messages',[]):
        if message.get('role')=='user':value=update_constraints(value,message.get('text',''),message.get('id'))
    return value


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
    junior=junior or any(0<=int(m[1])<=int(m[2])<=3 for m in re.finditer(
        r'(?:^|\n)\s*(?:[-*•]\s*)?(?:(?:requires?|minimum(?: of)?|at least|must have|candidates? must have)\s+)?'
        r"(\d+)\s*[-–]\s*(\d+)\s+years?['’]?(?:\s+of)?\s+[^\n.;:!?]{0,80}?experience\b",text))
    minimum=re.finditer(r'\b(?:require[ds]?|minimum|at least|must have)\s+(?:(?:at least|of)\s+)?(\d+)'
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


ONLY_LINKEDIN = re.compile(r'\b(?:only|just|exclusively)\s+(?:(?:search|use|look|on|from|in|at)\s+){0,2}linked\s?in\b|'
                           r'\blinked\s?in\s+only\b|(?:只|仅)(?:在|用|从|搜|看)?\s*linked\s?in', re.I)
NOT_ONLY_LINKEDIN = re.compile(r'\bnot\s+(?:only|just)\s+(?:(?:search|use|look|on|from|in|at)\s+){0,2}linked\s?in\b|'
                               r'(?:不只|不仅|不光)(?:在|用|从|搜|看)?\s*linked\s?in', re.I)
NO_LINKEDIN = re.compile(r'\b(?:no|not|exclude|excluding|without|skip|avoid)\s+(?:(?:on|from|use|using)\s+)?linked\s?in\b|'
                         r'(?:不要|别|排除|不用)(?:在|用|从|搜|看)?\s*linked\s?in', re.I)


def source_scope(text):
    """User-owned source restriction from the current request: 'linkedin', 'no_linkedin' or None.

    Negations ("not only LinkedIn", "不只 LinkedIn") are not a restriction. A model plan or
    tool query is never a source of this authority.
    """
    text = text or ''
    if NOT_ONLY_LINKEDIN.search(text):
        return 'no_linkedin' if NO_LINKEDIN.search(NOT_ONLY_LINKEDIN.sub(' ', text)) else None
    if NO_LINKEDIN.search(text):
        return 'no_linkedin'
    if ONLY_LINKEDIN.search(text):
        return 'linkedin'
    return None
