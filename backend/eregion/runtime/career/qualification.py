"""Persist model-owned search judgments; validate identity, citations and freshness."""
import hashlib
import json
import re
from .alerts import job_key
from .search_policy import LEVELS
from eregion.domain.search_qualification import POLICY, judge
from eregion.domain.jev_fit.resolve import locate

FIELDS=('role','location','seniority','vacancy')
MAX_BATCH_CHARS=48000
PARALLEL_GROUPS=3


def user_request(state):
    # Preserve the original request and subsequent human corrections, not model plans.
    texts=[state.get('goal','')]
    texts.extend(m['text'] for m in state.get('messages',[]) if m.get('role')=='user')
    return '\n\n'.join(dict.fromkeys(t for t in texts if t))


def request_hash(state):
    from eregion.domain.model import model_settings_fingerprint
    return hashlib.sha256(json.dumps([user_request(state),state.get('chat_revision',0),
        POLICY,model_settings_fingerprint()],sort_keys=True).encode()).hexdigest()


def request_fields(state):
    text=next((m['text'] for m in reversed(state.get('messages',[])) if m.get('role')=='user'),state.get('goal',''))
    match=re.search(r'\bfind\s+(?:(?:one|two|three|four|\d+)\s+)?(?:current\s+)?(.+?)\s+(?:positions|jobs|roles)\b',text,re.I)
    role=match[1] if match else ''
    location=''
    if match:
        before=re.search(r'\s+in\s+(.+)$',role,re.I)
        after=re.match(r'\s+in\s+([^.;!?\n]+?)(?=\s+(?:for|with|using)\b|[.;!?\n]|$)',text[match.end():],re.I)
        if before:location=before[1];role=role[:before.start()]
        elif after:location=after[1]
        for _,pattern in LEVELS:role=re.sub(r'\b(?:'+pattern+r')\b',' ',role,flags=re.I)
        role=re.sub(r'\b(?:current|remote|a|an|the)\b',' ',role,flags=re.I)
    return {'role':' '.join(role.split()),'location':location.strip()}


def body_hash(job):
    return hashlib.sha256(json.dumps({k:job.get(k) for k in ('url','title','location','description')},sort_keys=True).encode()).hexdigest()


def assess(state,job):
    """Read-only view: snapshots and guards never dispatch a model or infer eligibility."""
    saved=state.get('candidate_qualifications',{}).get(job_key(job['url']))
    if (saved and saved.get('request_hash')==request_hash(state)
            and saved.get('body_hash')==body_hash(job)):
        return saved
    return result(state,job,{f:{'status':'unknown','quote':'','reason':'Semantic assessment required.',
                               'evidence':[]} for f in FIELDS},method='not_assessed')


def result(state,job,checks,*,method='model_with_verified_quotes'):
    unresolved=[k for k,v in checks.items() if v['status']=='unknown']
    qualified=all(c['status'] in {'met','not_requested'} for c in checks.values())
    return {'url':job['url'],'revision':state.get('chat_revision',0),'body_hash':body_hash(job),
            'request_hash':request_hash(state),
            **({'application_id':job['application_id']} if job.get('application_id') else {}),
            'requested':request_fields(state),'checks':checks,'qualified':qualified,
            'status':'qualified' if qualified else 'needs_evidence',
            'review':{'method':method,'unresolved':unresolved,
                      'next':'Reuse this assessment for unchanged inputs. New source evidence or user corrections can resolve unknowns.'},
            'interpretation':'Search constraints only; scoring must still check personal eligibility.'}


def record(repository,task_id,job):
    return record_many(repository,task_id,[job])[0]


def verified_checks(decision,request,job):
    checks={}
    for field in FIELDS:
        item=getattr(decision,field)
        citations=[]
        valid=not item.request_quote if item.status=='not_requested' else locate(item.request_quote,request) is not None
        if field=='vacancy' and item.status=='not_requested':valid=False
        for quote in item.evidence:
            original=job.get(quote.source) or ''
            span=locate(quote.quote,original)
            if span is None:valid=False;continue
            citations.append({'source':quote.source,'quote':original[span[0]:span[1]],
                              'start':span[0],'end':span[1]})
        if item.status in {'met','unmet'} and not citations:valid=False
        checks[field]={'status':item.status if valid else 'unknown','quote':'\n'.join(c['quote'] for c in citations),
            'request_quote':item.request_quote,'reason':item.reason if valid else 'Model citation was missing or not found in this posting/request.',
            'evidence':citations,'citation_valid':valid}
    return checks


def record_many(repository,task_id,jobs):
    """Batched semantic IO under the caller's owner, budget and cancellation guard."""
    from eregion.runtime.core.engine import LoopStop
    from eregion.runtime.provider_usage import usage_scope, TaskProviderBudgetExceeded
    state=repository.get(task_id);fingerprint=request_hash(state);request=user_request(state)
    def check():
        current=repository.get(task_id)
        if (request_hash(current)!=fingerprint or current.get('pause_requested')
                or current.get('status') in {'cancelled','completed'}):raise LoopStop('steered')
    pending=[j for j in jobs if assess(state,j)['review']['method']=='not_assessed']
    groups=[];part=[];size=len(request)
    for job in pending:
        n=len(json.dumps({k:job.get(k) for k in ('title','location','description')},ensure_ascii=False))
        if part and (len(part)>=4 or size+n>MAX_BATCH_CHARS):groups.append(part);part=[];size=len(request)
        part.append(job);size+=n
    if part:groups.append(part)
    def ask(group):
        """Model IO only; runs in a worker. Persistence stays on the calling thread."""
        check()
        postings=[{'posting_id':str(i),**{k:j.get(k) or '' for k in ('title','location','description')}} for i,j in enumerate(group)]
        try:
            if len(json.dumps(postings,ensure_ascii=False))+len(request)>MAX_BATCH_CHARS:
                raise ValueError('Qualification input too large; complete text was not truncated.')
            with usage_scope(provider_guard=check):response=judge(request,postings)
            ids=[d.posting_id for d in response.decisions]
            if len(ids)!=len(group) or set(ids)!={str(i) for i in range(len(group))}:
                raise ValueError('Qualification response identities do not match the supplied batch.')
            return {d.posting_id:d for d in response.decisions},None
        except (TaskProviderBudgetExceeded,LoopStop):raise
        except Exception as exc:return {},type(exc).__name__
    def save(group,decisions,error):
        check()
        outputs={}
        for i,job in enumerate(group):
            checks=verified_checks(decisions[str(i)],request,job) if error is None else {
                f:{'status':'unknown','quote':'','reason':'Semantic assessment unavailable: '+error,'evidence':[]} for f in FIELDS}
            outputs[job_key(job['url'])]=result(state,job,checks,method='model_unavailable' if error else 'model_with_verified_quotes')
        repository.change(task_id,lambda s:{'candidate_qualifications':dict(list({
            **s.get('candidate_qualifications',{}),**outputs}.items())[-100:])})
    # Independent groups are judged concurrently (bounded) to keep a large batch
    # inside the task deadline; every call still meters against the same owner.
    from concurrent.futures import ThreadPoolExecutor
    from contextvars import copy_context
    with ThreadPoolExecutor(max_workers=max(1,min(len(groups),PARALLEL_GROUPS)),thread_name_prefix='qualify') as pool:
        futures=[(group,pool.submit(copy_context().run,ask,group)) for group in groups]
        try:
            for group,future in futures:
                save(group,*future.result())
        except BaseException:
            for _,future in futures:future.cancel()
            raise
    current=repository.get(task_id)
    return [assess(current,j) for j in jobs]


def deferred(state):
    bodies={job_key(j['url']):j for j in state.get('retrieved_jobs',{}).values() if j.get('url')}
    return {key for key,row in state.get('candidate_qualifications',{}).items()
            if row.get('request_hash')==request_hash(state) and not row['qualified']
            and (key not in bodies or row['body_hash']==body_hash(bodies[key]))}
