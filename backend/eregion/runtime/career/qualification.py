"""Conservative, source-bound search qualification; unknown is never a quota match."""
import hashlib
import json
import re
from .alerts import job_key
from .search_policy import constraints, recommendation_warning, LEVELS


def request_fields(state):
    text=next((m['text'] for m in reversed(state.get('messages',[])) if m.get('role')=='user'),state.get('goal',''))
    match=re.search(r'\bfind\s+(?:one|two|three|four|\d+)\s+(?:current\s+)?(.+?)\s+(?:positions|jobs|roles)\b',text,re.I)
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
    requested=request_fields(state)
    checks={}
    def add(field,status,quote,reason):
        checks[field]={'status':status,'quote':quote or '', 'reason':reason}
    if requested['role']:
        tokens=set(re.findall(r'[a-z0-9]+',requested['role'].lower()))
        observed=set(re.findall(r'[a-z0-9]+',(job.get('title') or '').lower()))
        add('role','met' if tokens and tokens<=observed else 'unknown',job.get('title'),
            'Literal requested role terms must be present in the verified posting title; related titles are not assumed equivalent.')
    if requested['location']:
        norm=lambda s:' '.join((s or '').casefold().split())
        matched=bool(re.search(r'(?<!\w)'+re.escape(norm(requested['location']))+r'(?!\w)',norm(job.get('location'))))
        add('location','met' if matched else 'unknown',job.get('location'),
            'The requested place must be evidenced by this posting; US-remote does not prove the requested city.')
    policy=constraints(state)
    if policy:
        try:warning=recommendation_warning({**policy,'strict':False},job.get('title',''),job.get('description',''))
        except ValueError:warning={'actual':None}
        from .posting_brief import with_brief
        evidence=with_brief(job)['triage_evidence']
        add('seniority','met' if not warning else 'unmet' if warning.get('actual') else 'unknown',
            job.get('title'),warning.get('message','Requested seniority is not established.') if warning else 'Opening level is supported; explicit higher minimum overrides the title.')
        checks['seniority']['source_excerpts']=evidence
    return {'url':job['url'],'revision':state.get('chat_revision',0),'body_hash':body_hash(job),
            **({'application_id':job['application_id']} if job.get('application_id') else {}),
            'requested':requested,'checks':checks,'qualified':all(c['status']=='met' for c in checks.values()),
            'status':'qualified' if all(c['status']=='met' for c in checks.values()) else 'needs_evidence',
            'interpretation':'Search constraints only; scoring must still check personal eligibility.'}


def record(repository,task_id,job):
    result=assess(repository.get(task_id),job)
    repository.change(task_id,lambda s:{'candidate_qualifications':dict(list({
        **s.get('candidate_qualifications',{}),job_key(job['url']):result}.items())[-100:])})
    return result


def deferred(state):
    bodies={job_key(j['url']):j for j in state.get('retrieved_jobs',{}).values() if j.get('url')}
    return {key for key,row in state.get('candidate_qualifications',{}).items()
            if row.get('revision')==state.get('chat_revision',0) and not row['qualified']
            and (key not in bodies or row['body_hash']==body_hash(bodies[key]))}
