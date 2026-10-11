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


def recommendation_warning(policy,title):
    if not policy:return None
    actual=seniority(title)
    if actual in policy['levels']:return None
    requested=', '.join(policy['levels'])
    if policy.get('strict'):
        raise ValueError(f'Seniority constraint: {requested} only was requested; this posting is {actual or "unverified level"}. Do not recommend it unless the user changes that condition.')
    if actual:
        return {'requested':policy['levels'],'actual':actual,
            'message':f'Seniority mismatch: requested {requested}; this posting is {actual}.'}
