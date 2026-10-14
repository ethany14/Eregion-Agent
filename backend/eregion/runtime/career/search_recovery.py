"""Observed candidate recovery, without treating search snippets as verified jobs."""
import re
from urllib.parse import parse_qs, urlsplit

from .alerts import job_key


def search_request(state):
    latest=next((m['text'] for m in reversed(state.get('messages',[])) if m.get('role')=='user'),state.get('goal',''))
    # The number is optional: an open request ('find current X positions') is still a
    # search; count is None and nothing waits for a quota.
    match=re.search(r'\bfind\s+(?:(one|two|three|four|\d+)\s+)?(?:current\s+)?(.{1,80}?)\s+(?:positions|jobs|roles)\b',latest,re.I)
    if not match:return None
    count=None if match[1] is None else {'one':1,'two':2,'three':3,'four':4}.get(match[1].lower())
    if count is None and match[1] is not None:count=int(match[1])
    words=set(re.findall(r'[a-z]+',match[2].lower()))-{
        'senior','junior','entry','level','remote','in','new','york','us','current','the','and','or'}
    return {'count':count,'words':words}


def posting_link(url):
    parsed=urlsplit(url)
    return parsed.scheme=='https' and bool(parsed.hostname) and bool(
        re.search(r'/(?:jobs?/(?:view/)?[^/?]+|viewjob|rc/clk|pagead/clk|postings/[^/?]+)',parsed.path,re.I)
        or {'jk','vjk'} & parse_qs(parsed.query).keys()
        or parsed.hostname in {'jobs.lever.co','jobs.eu.lever.co','jobs.ashbyhq.com'} and len(parsed.path.strip('/').split('/'))>=2)


def candidates_from_page(result,request):
    if not request or result.get('blocked'):return {}
    candidates={}
    for control in result.get('controls',[]):
        url=control.get('href','');label=control.get('label','')
        words=set(re.findall(r'[a-z]+',label.lower()))
        if posting_link(url) and request['words'] and len(words & request['words'])>=min(2,len(request['words'])):
            candidates[job_key(url)]={'url':url,'title':label[:240],'source_page':result.get('url')}
    return candidates


def recovery(state,*,saved_urls=()):
    request=search_request(state)
    if not request:return None
    revision=state.get('chat_revision',0)
    # Search snippets and observed browser links have the same discovery role.
    # Neither is a verified vacancy. Normalize legacy URL-keyed maps on read.
    candidates={job_key(j['url']):j for j in [*state.get('search_candidates',{}).values(),
        *state.get('observed_job_candidates',{}).values()] if j.get('url')}
    tried=state.get('job_read_attempts',{})
    legacy_tried={job_key(j['url']) for mapping in ('search_candidates','observed_job_candidates')
        for key,j in state.get(mapping,{}).items() if j.get('url') and tried.get(key)==revision}
    from .candidate_health import active_rejections
    excluded={job_key(j['url']) for j in active_rejections(state)}
    from .qualification import deferred
    excluded |= deferred(state)
    retrieved={job_key(j['url']) for j in state.get('retrieved_jobs',{}).values() if j.get('url')}
    from .source_health import active_sources, browser_source
    sources=active_sources(state)
    linkedin=state.get('linkedin_mcp_state') or {}
    # A stopped or exhausted LinkedIn MCP source cannot read its cards in this turn.
    linkedin_closed=bool(linkedin.get('stopped')) or (bool(linkedin.get('call_limit'))
                                                   and linkedin.get('calls_used',0)>=linkedin['call_limit'])
    pending=[j for key,j in candidates.items() if key not in retrieved and key not in excluded
        and key not in legacy_tried and tried.get(key)!=revision
        and not sources.get(browser_source(j['url']),{}).get('blocked')
        and not (linkedin_closed and j.get('source')=='linkedin_mcp')]
    from .search_filters import filter_cards
    from .candidate_queue import enabled
    if enabled():pending,_=filter_cards(pending,state)
    saved={job_key(url) for url in saved_urls if url}|{job_key(j['url']) for j in state.get('recommendations',[]) if j.get('url')}
    read_not_imported={job_key(j['url']):{k:j[k] for k in ('url','title','company','location') if k in j}
        for j in state.get('retrieved_jobs',{}).values() if j.get('url') and job_key(j['url']) not in excluded|saved}
    return {'requested_count':request['count'],'recommended_count':len(state.get('recommendations',[])),
        'pending_candidates':[{**{k:j[k] for k in ('url','title','source','source_page') if k in j},
            'read_job_arguments':{'url':j['url']}} for j in pending[:20]],
        'read_not_imported':[{**j,'import_job_arguments':{'url':j['url']}} for j in list(read_not_imported.values())[:3]],
        'instruction':'Pending links are discovery only, not verified jobs. Use the bounded read_job arguments to verify the target posting, identity, location, seniority and eligibility. Saved retrieved bodies can be imported without another remote read, but are not automatically qualifying or recommended. Do not repeat blocked sources or already-read details. If no eligible candidate remains, change public source or query to discover genuinely different postings; do not repeat identical result lists.'}
