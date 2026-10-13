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
    source=LinkedInMcpSource(call,store=store)
    try:
        check()
        if operation=='search':
            filters=effective_filters(state,arguments)
            level=filters.get('experience_level')
            if level=='mid-senior':level='mid_senior'
            result=source.search(arguments['query'],arguments.get('location'),experience_level=level,max_pages=2 if arguments.get('limit',10)>10 else 1)
            result['jobs'],result['local_filter']=filter_cards(result['jobs'],state)
            result['unapplied_filters']+= [k for k in filters if k!='experience_level']
            return result
        return source.details(arguments['job_id'])
    finally:
        harness.repository.change(task_id,linkedin_mcp_state=deepcopy(store))


def search(harness,task_id,state,args):
    key=harness.key(state,'linkedin_mcp_search', {**{k:v for k,v in args.items() if k!='limit'},
        'max_pages':2 if args.get('limit',10)>10 else 1})
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
