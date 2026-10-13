"""Task-owned MCP budget/cache; no second execution loop or implicit login."""
from copy import deepcopy
from .linkedin_source import LinkedInMcpSource, LinkedInSourceStopped
from .source_health import user_turn
from .search_filters import effective_filters, filter_cards
from .alerts import job_key


def available(harness):
    manager=getattr(harness.runtime,'mcp_manager',None)
    return bool(manager and 'mcp__linkedin__search_jobs' in manager.public_tool_names
                and 'mcp__linkedin__get_job_details' in manager.public_tool_names)


def invoke(harness,task_id,state,operation,arguments):
    store=deepcopy(state.get('linkedin_mcp_state') or {})
    if any(row.get('outcome')=='pending' for row in store.get('log',[])):
        store['stopped']='pending_call_requires_recovery'
    revision=state.get('chat_revision')
    def check():
        current=harness.repository.get(task_id)
        if current.get('pause_requested') or current.get('status') in {'cancelled','completed'} or current.get('chat_revision')!=revision:
            raise LinkedInSourceStopped('task_changed_or_cancelled')
    def call(server,tool,args,**kwargs):
        check()
        # Reserve/count before network; restart must not erase an in-flight attempt.
        harness.repository.change(task_id,linkedin_mcp_state=deepcopy(store))
        result=harness.runtime.mcp_manager.call_tool(server,tool,args,**kwargs)
        check()
        return result
    from .search_strategy import source_limits
    limits=source_limits(state,arguments)
    source=LinkedInMcpSource(call,store=store,call_budget=limits['calls'],max_pages=4)
    try:
        check()
        if operation=='search':
            filters=effective_filters(state,arguments)
            level=filters.get('experience_level')
            if level=='mid-senior':level='mid_senior'
            result=source.search(arguments['query'],arguments.get('location'),experience_level=level,max_pages=limits['pages'])
            result['jobs'],result['local_filter']=filter_cards(result['jobs'],state)
            result['unapplied_filters']+= [k for k in filters if k!='experience_level']
            return result
        return source.details(arguments['job_id'])
    finally:
        harness.repository.change(task_id,linkedin_mcp_state=deepcopy(store))


def _search_one(harness,task_id,state,args):
    # Only upstream-effective parameters identify a remote query. Directory mode,
    # explicit default filters and presentation limits cannot mint duplicate calls.
    filters=effective_filters(state,args)
    from .search_strategy import source_limits
    key=harness.key(state,'linkedin_mcp_search', {
        'query':' '.join(args['query'].casefold().split()),
        'location':' '.join(args.get('location','').casefold().split()),
        'experience_level':filters.get('experience_level'),
        'max_pages':source_limits(state,args)['pages']})
    cached=state.get('linkedin_mcp_search_cache',{}).get(key)
    if cached is not None:return {**cached,'cached':True,'no_new_evidence':True}
    stopped=(state.get('linkedin_mcp_state') or {}).get('stopped')
    if stopped:return {'jobs':[],'status':'blocked','error_code':stopped,'no_new_evidence':True}
    if not available(harness):return {'jobs':[],'status':'unavailable','error_code':'linkedin_mcp_unavailable','no_new_evidence':True}
    try:result=invoke(harness,task_id,state,'search',args)
    except LinkedInSourceStopped as exc:
        result={'jobs':[],'status':'blocked','error_code':exc.reason,'no_new_evidence':True}
    except Exception as exc:
        result={'jobs':[],'status':'unavailable','error_code':type(exc).__name__,'no_new_evidence':True}
    if result.get('error_code')=='task_changed_or_cancelled':raise LinkedInSourceStopped(result['error_code'])
    def save(s):
        candidates={job_key(j['url']):j for j in s.get('search_candidates',{}).values() if j.get('url')}
        candidates.update({job_key(j['url']):j for j in result.get('jobs',[])})
        return {'search_candidates':dict(list(candidates.items())[-100:]),
            'linkedin_mcp_search_cache':dict(list({**s.get('linkedin_mcp_search_cache',{}),key:result}.items())[-16:])}
    harness.repository.change(task_id,save)
    return result


def search(harness,task_id,state,args):
    from .search_strategy import variants, card_priority
    queries=variants(state,args)
    if len(queries)==1:return _search_one(harness,task_id,state,args)
    results=[];jobs={}
    for query in queries:
        current=harness.repository.get(task_id)
        result=_search_one(harness,task_id,current,{**args,'query':query})
        results.append({'query':query,**{k:v for k,v in result.items() if k!='jobs'}})
        jobs.update({job_key(j['url']):j for j in result.get('jobs',[])})
        if result.get('status') in {'blocked','unavailable'}:break
    ordered=sorted(jobs.values(),key=lambda j:card_priority(j,state))
    final_status=results[-1].get('status','no_match')
    return {'jobs':ordered,'status':final_status if final_status in {'blocked','unavailable'} else 'ok' if ordered else final_status,
            'query_variants':results,'queries_attempted':len(results),
            'no_new_evidence':all(r.get('no_new_evidence',False) for r in results),
            'error_code':results[-1].get('error_code'),
            'qualification':'Discovery expansion only: original role, location and seniority checks remain mandatory.'}
