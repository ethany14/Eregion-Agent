"""Persist source failures for an actual user turn, independent of read views."""
from urllib.parse import urlsplit
import re

from .discovery import board_source


class SourceBlocked(ValueError):
    """An already observed source failure, not new evidence or missing facts."""
    def __init__(self,source):
        self.source=source
        super().__init__('Source blocked in this user turn. Switch to a different public source; changing query or page does not unblock it. The user can sign in using browser control, or retry in a new turn. Do not bypass verification.')


def blocked_hosts(state):
    # Shared ATS hosts must remain tenant-scoped. Generic browser sources have
    # a host identity; retain it even after their research_page is evicted.
    return sorted(source.removeprefix('browser:') for source,item in active_sources(state).items()
        if source.startswith('browser:') and item.get('blocked'))


def user_turn(state):
    return state.get('user_turn_id') or next((m.get('id') for m in reversed(state.get('messages',[]))
        if m.get('role')=='user' and m.get('id')),None)


def active_sources(state):
    health=state.get('search_source_health') or {}
    return dict(health.get('sources',{})) if health.get('user_turn_id')==user_turn(state) else {}


def browser_source(url):
    parsed=urlsplit(url or '');host=parsed.hostname or '';parts=parsed.path.strip('/').split('/')
    shared={'jobs.ashbyhq.com':'ashby','jobs.lever.co':'lever','jobs.eu.lever.co':'lever',
        'boards.greenhouse.io':'greenhouse','job-boards.greenhouse.io':'greenhouse'}
    if host in shared and parts[0]:return board_source({'platform':shared[host],'company':parts[0]})
    if host.endswith('.myworkdayjobs.com') and parts[0]:
        site=parts[1] if re.fullmatch(r'[a-z]{2}-[A-Z]{2}',parts[0]) and len(parts)>1 else parts[0]
        return board_source({'platform':'workday','company':host.split('.')[0],'host':host,'site':site})
    return 'browser:'+host if host else None


def browser_preflight(state,name,args,observed):
    url=args.get('url') if name in {'browser_open','read_job','import_job'} else (observed or state.get('browser') or {}).get('url')
    source=browser_source(url)
    previous=active_sources(state).get(source,{})
    if not previous.get('blocked'):return
    verified_recovery=bool(observed and not observed.get('blocked')
        and browser_source(observed.get('url'))==source
        and ((observed.get('page_evidence_hash') and observed['page_evidence_hash']!=previous.get('page_evidence_hash'))
            or (observed.get('observation_id') and observed['observation_id']!=previous.get('observation_id'))))
    if verified_recovery:return
    raise SourceBlocked(source)


def record_failure(repository,task_id,url,exc,observed=None):
    import httpx
    blocked=(isinstance(exc,httpx.HTTPStatusError) and exc.response.status_code in {401,403,429}
        or isinstance(exc,ValueError) and 'source blocked' in str(exc).casefold())
    source=browser_source(url)
    if not blocked or not source:return
    observed=observed if observed and browser_source(observed.get('url'))==source else {}
    def mutation(state):
        sources=active_sources(state)
        sources[source]={'blocked':True,'error':type(exc).__name__,
            'page_evidence_hash':observed.get('page_evidence_hash'),'observation_id':observed.get('observation_id')}
        return {'search_source_health':{'revision':state.get('chat_revision'),'user_turn_id':user_turn(state),'sources':sources,'history':(state.get('search_source_health') or {}).get('history',{})}}
    repository.change(task_id,mutation)


def record_browser(repository,task_id,result):
    source=browser_source(result.get('url'))
    if not source:return
    def mutation(state):
        sources=active_sources(state)
        # Keep positive observations only for a formerly blocked source.
        if result.get('blocked') or source in sources:
            sources[source]={'blocked':bool(result.get('blocked')),'error':'browser_blocked' if result.get('blocked') else None,
                'page_evidence_hash':result.get('page_evidence_hash'),'observation_id':result.get('observation_id')}
        return {'search_source_health':{'revision':state.get('chat_revision'),'user_turn_id':user_turn(state),'sources':sources,'history':(state.get('search_source_health') or {}).get('history',{})}}
    repository.change(task_id,mutation)


def searches(state):
    """What each search of this turn covered, as recorded (facts only, no verdict)."""
    cache=state.get('search_request_cache') or {}
    if cache.get('user_turn_id')!=user_turn(state):return []
    rows=[]
    for entry in list((cache.get('requests') or {}).values())[-12:]:
        result=entry.get('result') or {}
        row={'query':entry.get('query'),'location':entry.get('location'),'cards_returned':len(result.get('jobs') or [])}
        if result.get('directory'):
            row['boards']={'searched':len(result.get('directory_searched') or []),'remaining':result.get('directory_remaining'),
                           'matching':result.get('directory_matching')}
        linked=result.get('linkedin_mcp') or {}
        variants=linked.get('query_variants') or ([linked] if linked else [])
        row['linkedin']=[linkedin_row(v) for v in variants]
        rows.append(row)
    return rows


def linkedin_row(result):
    request=result.get('request') or {}
    total,cards=result.get('total'),request.get('cards')
    return {**{k:request.get(k) for k in ('query','location','pages','cards')},'status':result.get('status'),
            'reported_total':total,'cached':bool(result.get('cached')),
            # Arithmetic only: what the provider reports beyond the cards already returned.
            'unseen':max(0,total-cards) if isinstance(total,int) and isinstance(cards,int) else None}


def linkedin_queries(state):
    """Every recorded LinkedIn query, including earlier turns, so a follow-up such as
    'search more' can continue the same query deeper instead of starting over."""
    return [linkedin_row(r) for r in list((state.get('linkedin_mcp_search_cache') or {}).values())[-8:]
            if r.get('request')]


def yields(state):
    """Per source: postings carded, read, qualified and recommended so far this turn (facts)."""
    from .alerts import job_key
    def source(url):
        try:return 'linkedin' if job_key(url).startswith('linkedin:') else 'company_boards'
        except ValueError:return None
    rows={}
    def add(url,field):
        name=source(url or '')
        if name:rows.setdefault(name,{'cards':0,'read':0,'qualified':0,'recommended':0})[field]+=1
    for j in (state.get('search_candidates') or {}).values():add(j.get('url'),'cards')
    for j in (state.get('retrieved_jobs') or {}).values():add(j.get('url'),'read')
    for q in (state.get('candidate_qualifications') or {}).values():
        if q.get('qualified'):add(q.get('url'),'qualified')
    for r in state.get('recommendations') or []:add(r.get('url'),'recommended')
    return rows


def coverage(state):
    sources=active_sources(state)
    blocked=[source for source,item in sources.items() if item.get('blocked')]
    return {'blocked_sources':blocked[-8:],'blocked_count':len(blocked),'exhausted_sources':[source for source,item in sources.items() if item.get('empty_count',0)>=2][-8:],
        'searches':searches(state),'yield_by_source':yields(state),'linkedin_queries':linkedin_queries(state),
        'instruction':'Disclose source access limitations once to the user. These failures do not establish absence of vacancies. Public detail reading and switching sources are already authorized.'}


def projection(state):
    sources=active_sources(state)
    return {'user_turn_id':user_turn(state),'source_count':len(sources),'sources':dict(list(sources.items())[-8:]),
        'note':'Bounded display only; the complete persistent exclusion table still guards every source.'}


def validate_coverage(state,text):
    import re
    blocked=coverage(state)['blocked_sources']
    if not blocked:return
    messages=state.get('messages',[])
    start=next((i+1 for i in range(len(messages)-1,-1,-1) if messages[i].get('role')=='user'),0)
    disclosures=[m.get('text','') for m in messages[start:] if m.get('role')=='assistant']+[text]
    # Reject an absence claim, not the disclaimer that denies one
    # ("a coverage gap, not proof no vacancies exist").
    for claim in re.finditer(r'\bno (?:current )?(?:jobs|vacancies|openings) (?:exist|are available)\b',text,re.I):
        before=text[max(0,claim.start()-60):claim.start()]
        if not re.search(r'\b(?:not|never|no|isn.t|aren.t|do not|does not|don.t|doesn.t|cannot|can.t)\s+(?:\w+\s+){0,3}?'
                         r'(?:proof|prove|proves|evidence|mean|means|show|shows|establish|establishes|imply|implies)'
                         r'(?:\s+that)?\s*$',before,re.I):
            raise ValueError('Blocked source coverage cannot prove absence of vacancies; report only observed results and access limits.')
    labels=[]
    for source in blocked:
        if source.startswith('ats:'):labels.append(source.split(':')[1]);continue
        value=source.removeprefix('browser:')
        host=urlsplit(value).hostname if '://' in value else value
        if host:
            parts=host.split('.')
            brand=parts[-2] if len(parts)>1 else host
            if brand in {'co','com','net','org'} and len(parts)>2:brand=parts[-3]
            labels.extend([host,brand])
    if not any(any(label.casefold() in reply.casefold() for label in labels)
        and re.search(r'block|login|log.in|sign.in|challenge|unavailable|access|could not|couldn.t|limited|403|受阻|阻止|登录|访问|验证码',reply,re.I) for reply in disclosures):
        raise ValueError('Disclose the observed blocked source/access limitation to the user; do not present restricted source coverage as a complete search or proof of no vacancies.')


def record_board_outcomes(sources, history, result, turn):
    """Persist tenant outcomes across turns; only current-turn failures exclude."""
    from datetime import UTC, datetime
    sources, history = dict(sources), dict(history)
    stamp = datetime.now(UTC).isoformat()
    outcomes = list(result.get('board_outcomes', [])) + [
        {**e, 'status':'http_error' if e.get('http_status') else 'error'}
        for e in result.get('errors', []) if str(e.get('source','')).startswith('ats:')]
    for item in outcomes:
        source = item['source']
        old = sources.get(source, {})
        past = history.get(source, {})
        failed = item['status'] in {'http_error', 'error'}
        errors = old.get('error_count', 0) + 1 if failed else 0
        consecutive = past.get('consecutive_errors', 0) + 1 if failed else 0
        sources[source] = {**old, 'status':item['status'], 'timestamp':stamp,
            'blocked':bool(item.get('blocked')), 'http_status':item.get('http_status'),
            'error_count':errors, 'empty_count':old.get('empty_count', 0)+1 if item['status']=='empty' else 0}
        history[source] = {'status':item['status'], 'timestamp':stamp, 'user_turn_id':turn,
            'consecutive_errors':consecutive, 'observations':past.get('observations', 0)+1,
            'refresh_required':item.get('http_status')==404 or consecutive>=2,
            'http_status':item.get('http_status')}
    return sources, history
