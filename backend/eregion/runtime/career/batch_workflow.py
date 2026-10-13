"""Bounded sequential acquisition + existing shared scorer, inside the task owner."""
from eregion.runtime.tasks.loop import function, TEXT
from eregion.runtime.core.engine import LoopStop
from eregion.runtime.provider_usage import usage_scope, TaskProviderBudgetExceeded
from .alerts import job_key
from .qualification import record

TOOL=function('verify_and_score_jobs',
    'Process 1-8 observed posting URLs together: read/reuse, qualify against the user request, import qualified jobs, '
    'then call the existing shared batch scorer once. Unknown/mismatched jobs stay deferred without paid scoring. '
    'Never recommends; decide the returned scored jobs separately. Prefer this for multi-job searches.',
    {'urls':{'type':'array','minItems':1,'maxItems':8,'uniqueItems':True,'items':TEXT}})


def run(harness,task_id,args,call_id):
    repo=harness.repository;initial=repo.get(task_id);revision=initial['chat_revision']
    urls=args['urls'];identities=[job_key(u) for u in urls]
    if not 1<=len(urls)<=8 or len(set(identities))!=len(urls):raise ValueError('Choose 1-8 distinct observed postings.')
    observed={job_key(j['url']) for kind in ('search_candidates','observed_job_candidates','retrieved_jobs')
              for j in initial.get(kind,{}).values() if j.get('url')}
    if any(key not in observed for key in identities):raise ValueError('Use URLs from observed search results or saved retrieved postings.')
    key=harness.key(initial,'verify_and_score_jobs',{'urls':sorted(identities)})
    journal=dict(initial.get('batch_verifications',{}).get(key,{}));items=[];apps=[];changed=False
    def check():
        s=repo.get(task_id)
        if s['chat_revision']!=revision or s.get('pause_requested') or s['status'] in {'cancelled','completed'}:
            raise LoopStop('steered')
    def save(**kwargs):
        check();journal.update(kwargs,items=list(items))
        repo.change(task_id,lambda s:{'batch_verifications':{**s.get('batch_verifications',{}),key:dict(journal)}})
    def invoke(name,arguments):
        check();save(pending=name)
        value=harness.execute(task_id,name,arguments,call_id=f'{call_id}:{name}:{len(items)}')
        check();return value
    try:
        with usage_scope(provider_guard=check):
            for url in urls:
                check();state=repo.get(task_id)
                job=next((j for j in state.get('retrieved_jobs',{}).values() if j.get('url') and job_key(j['url'])==job_key(url)),None)
                try:
                    new_read=job is None
                    job=job or invoke('read_job',{'url':url})
                    if job.get('error'):items.append({'url':url,'status':'read_failed','error':job['error']});continue
                    if new_read:changed=True
                    check();qualification=record(repo,task_id,job)
                    previous=state.get('candidate_qualifications',{}).get(job_key(url),{})
                    if any(previous.get(k)!=qualification.get(k) for k in
                           ('revision','body_hash','requested','checks','qualified')):changed=True
                    item={'url':url,'title':job.get('title'),'qualification':qualification}
                    if not qualification['qualified']:
                        items.append({**item,'status':'needs_evidence'});save(pending=None);continue
                    imported=invoke('import_job',{'url':url})
                    if imported.get('error'):items.append({**item,'status':'import_failed','error':imported['error']});continue
                    apps.append(imported['application_id'])
                    if apps[-1] not in initial.get('jobs',[]):changed=True
                    items.append({**item,'application_id':apps[-1],'status':'imported'})
                    save(pending=None)
                except (ValueError,LookupError) as exc:
                    items.append({'url':url,'status':'source_error','error':str(exc)[:400]});save(pending=None)
            result=invoke('score_jobs',{'application_ids':apps}) if apps else {'jobs':[]}
            if result.get('error'):save(pending=None,failure=result);return {**result,'candidates':items}
            if apps and not result.get('no_new_evidence'):changed=True
            save(pending=None,completed=True,failure=None)
            return {'jobs':result['jobs'],'candidates':items,'qualified_count':len(apps),
                    'no_new_evidence':not changed,
                    'next':'Decide each scored job. Deferred jobs are not quota matches; discover different postings when no qualified pending candidates remain.'}
    except TaskProviderBudgetExceeded:
        save(failure='provider_budget');raise
