"""Durable source-backed exclusions shared across research/import tools."""
import hashlib
import json

from .alerts import job_key
from .posting_qualification import PostingRejected, validate_posting


def active_rejections(state):
    return [r for r in state.get('candidate_rejections',{}).values()
        if r['revision']==state.get('chat_revision',0)]


def preflight(state,name,args,observed):
    if name not in {'browser_open','browser_read','read_job','import_job'}:return
    url=args.get('url')
    if name=='browser_read':url=url or (observed or {}).get('url')
    if not url:return
    identity=job_key(url)
    records=state.get('candidate_rejections',{})
    record=records.get(identity) or next((r for r in records.values() if r.get('url')
        and job_key(r['url'])==identity and r['revision']==state.get('chat_revision',0)),None)
    if not record or record['revision']!=state.get('chat_revision',0):return
    # Query/offset/ref filtering never changes the unfiltered source hash.
    # A genuinely changed, already observed page may be read and revalidated.
    if (observed and job_key(observed['url'])==identity and observed.get('page_evidence_hash')
            and observed['page_evidence_hash']!=record.get('page_evidence_hash')):return
    exc=PostingRejected(record['reason'],code=record['rejection_code'])
    exc.evidence={'candidate_identity':identity,'body_hash':record['body_hash'],'url':record['url']}
    exc.repeated=True
    raise exc


def validate_and_record(repository,task_id,job,observed=None):
    identity=job_key(job['url']) if job.get('url') else None
    try:
        validate_posting(job)
    except PostingRejected as exc:
        if identity:
            body_hash=hashlib.sha256(json.dumps({k:job.get(k) for k in
                ('title','company','location','description')},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            def save(state):
                old=state.get('candidate_rejections',{}).get(identity)
                exc.repeated=bool(old and old['revision']==state.get('chat_revision',0) and old['body_hash']==body_hash)
                exc.evidence={'candidate_identity':identity,'body_hash':body_hash,'url':job['url']}
                record={'revision':state.get('chat_revision',0),'url':job['url'],'title':job.get('title'),
                    'body_hash':body_hash,'reason':str(exc),'rejection_code':exc.code,
                    'page_evidence_hash':observed.get('page_evidence_hash') if observed and job_key(observed['url'])==identity else None}
                return {'candidate_rejections':dict(list({**state.get('candidate_rejections',{}),identity:record}.items())[-100:])}
            repository.change(task_id,save)
        raise
    if identity:
        repository.change(task_id,lambda s:{'candidate_rejections':{
            k:v for k,v in s.get('candidate_rejections',{}).items() if k!=identity}})
    return job
