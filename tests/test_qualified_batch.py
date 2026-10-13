import asyncio
from copy import deepcopy
import pytest
from test_career_flow import career,execute
from eregion.runtime.career.qualification import assess,deferred
from eregion.runtime.core.engine import LoopStop
from eregion.runtime.provider_usage import provider_call,usage_scope,TaskProviderBudgetExceeded

GOAL='Find 15 current junior data analyst positions in New York for my saved resume.'
def posting(i,**kw):
    return {'url':f'https://jobs.lever.co/example/{i}','title':'Junior Data Analyst','location':'New York, NY',
            'company':'Synthetic','description':'Requires Python.\n0-2 years of analytical experience.',**kw}

def prepare(c,monkeypatch,jobs):
    monkeypatch.setenv('JOB_AGENT_JOB_API_FIRST','1')
    c.repository.change(c.state['task_id'],goal=GOAL,messages=[],search_constraints={'levels':['junior'],'strict':True},
                        search_candidates={j['url']:j for j in jobs})
    calls=[]
    def read(url):calls.append(url);return deepcopy(next(j for j in jobs if j['url']==url))
    monkeypatch.setattr(c.harness.discovery,'job',read)
    return calls

@pytest.mark.parametrize('change,field,status',[
    ({'location':'United States (Remote)'},'location','unknown'),
    ({'title':'Yield Analyst'},'role','unknown'),
    ({'description':'Requires 5 years of professional experience.'},'seniority','unmet'),
    ({'title':'Data Analyst','description':'Enjoy our company benefits.'},'seniority','unknown'),
])
def test_unknown_or_mismatch_never_qualifies(change,field,status):
    result=assess({'goal':GOAL},posting(1,**change))
    assert not result['qualified'] and result['checks'][field]['status']==status

def test_batch_only_scores_qualified_and_reuses_persisted_results(career,monkeypatch):
    c=career;jobs=[posting(1),posting(2),posting(3,location='US Remote')]
    reads=prepare(c,monkeypatch,jobs)
    service=c.harness.analysis._fit_service;original=service.analyze_many;groups=[]
    async def batch(**kwargs):groups.append([j['id'] for j in kwargs['jobs']]);return await original(**kwargs)
    monkeypatch.setattr(service,'analyze_many',batch)
    args={'urls':[j['url'] for j in jobs]}
    result=execute(c,'verify_and_score_jobs',**args)
    assert result['qualified_count']==2 and len(result['jobs'])==2
    assert [len(g) for g in groups]==[2]
    state=c.repository.get(c.state['task_id'])
    assert len(deferred(state))==1 and len(state['jobs'])==2
    repeated=execute(c,'verify_and_score_jobs',**args)
    assert repeated['no_new_evidence'] and len(groups)==1 and len(reads)==3
    extra=posting(4);jobs.append(extra)
    c.repository.change(c.state['task_id'],lambda s:{'search_candidates':{**s['search_candidates'],extra['url']:extra}})
    execute(c,'verify_and_score_jobs',urls=[jobs[0]['url'],extra['url']])
    assert [len(g) for g in groups]==[2,1]  # warm item removed before paid dispatch
    changed=deepcopy(state);changed['chat_revision']+=1
    assert not deferred(changed)


def test_recommendation_rechecks_current_request(career,monkeypatch):
    c=career;jobs=[posting(1)];prepare(c,monkeypatch,jobs)
    result=execute(c,'verify_and_score_jobs',urls=[jobs[0]['url']])
    identifier=result['jobs'][0]['application_id']
    c.repository.change(c.state['task_id'],goal=GOAL.replace('New York','Boston'))
    result=execute(c,'recommend_job',application_id=identifier,reason='Good Python fit',caveats='')
    assert result['error_code']=='qualification_needed'
    assert not c.repository.get(c.state['task_id']).get('recommendations')

def test_batch_preflights_all_urls_before_io(career,monkeypatch):
    jobs=[posting(1)];reads=prepare(career,monkeypatch,jobs)
    with pytest.raises(ValueError,match='observed'):
        execute(career,'verify_and_score_jobs',urls=[jobs[0]['url'],posting(99)['url']])
    assert reads==[]

def test_cancel_mid_read_stops_before_import_or_next_source(career,monkeypatch):
    c=career;jobs=[posting(1),posting(2)];prepare(c,monkeypatch,jobs)
    calls=[]
    def read(url):
        calls.append(url);c.repository.change(c.state['task_id'],status='cancelled',pause_requested=True);return jobs[0]
    monkeypatch.setattr(c.harness.discovery,'job',read)
    with pytest.raises(LoopStop):execute(c,'verify_and_score_jobs',urls=[j['url'] for j in jobs])
    assert len(calls)==1 and c.repository.get(c.state['task_id'])['jobs']==[]

def test_nested_provider_guard_blocks_dispatch_before_reservation():
    def stop():raise LoopStop('steered')
    with usage_scope(provider_guard=stop):
        with pytest.raises(LoopStop):
            with provider_call('fake'):pytest.fail('provider body must not run')

def test_budget_stop_keeps_imports_and_resume_uses_same_jobs(career,monkeypatch):
    c=career;jobs=[posting(1),posting(2)];reads=prepare(c,monkeypatch,jobs)
    original=c.harness.analysis.analyze_many
    async def stop(*args,**kw):raise TaskProviderBudgetExceeded('test')
    monkeypatch.setattr(c.harness.analysis,'analyze_many',stop)
    with pytest.raises(TaskProviderBudgetExceeded):execute(c,'verify_and_score_jobs',urls=[j['url'] for j in jobs])
    before=c.repository.get(c.state['task_id'])
    assert len(before['jobs'])==2 and not before.get('analyses')
    monkeypatch.setattr(c.harness.analysis,'analyze_many',original)
    execute(c,'verify_and_score_jobs',urls=[j['url'] for j in jobs])
    after=c.repository.get(c.state['task_id'])
    assert after['jobs']==before['jobs'] and len(reads)==2 and len(after['analyses'])==2

def test_granular_scoring_cannot_bypass_location_guard(career,monkeypatch):
    c=career;jobs=[posting(1,location='US Remote')];prepare(c,monkeypatch,jobs)
    execute(c,'read_job',url=jobs[0]['url']);saved=execute(c,'import_job',url=jobs[0]['url'])
    assert execute(c,'score_job',application_id=saved['application_id'])['error_code']=='qualification_needed'
    assert execute(c,'score_jobs',application_ids=[saved['application_id']])['error_code']=='qualification_needed'
