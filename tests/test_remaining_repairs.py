"""2026-10-11 remaining application and scoring regressions."""
import hashlib
import json

import pytest
from sqlalchemy import select

from agent_runtime.auto_apply.contracts import posting
from agent_runtime.auto_apply.models import AutoApplicationRow
from agent_runtime.auto_apply.repository import ApplyRepository, DuplicateApplication
from agent_runtime.career.alerts import job_key
from test_auto_apply import database, request
from test_career_flow import career, execute


@pytest.mark.parametrize('base',[
    'https://careers.example.com/jobs/4021-data-analyst',
    'https://jobs.ashbyhq.com/acme/abc-123',
    'https://jobs.smartrecruiters.com/acme/123-engineer',
    'https://careers.acme.icims.com/jobs/123/engineer',
    'https://jobs.jobvite.com/acme/job/123',
    'https://boards.greenhouse.io/acme/jobs/123',
    'https://jobs.lever.co/acme/abc-123',
])
def test_apply_alias_is_one_job_but_keeps_navigation_url(base):
    assert posting(base)[1]==posting(base+'/apply')[1]
    assert job_key(base)==job_key(base+'/apply')
    assert posting(base)[1]!=posting(base.replace('123','456') if '123' in base else base+'-other')[1]
    if posting(base)[0] not in {'lever','greenhouse'}:
        assert posting(base+'/apply')[2]==base+'/apply'


def test_legacy_apply_alias_is_not_reopened_after_restart(database):
    repo=ApplyRepository(database.session_factory)
    url='https://careers.example.com/jobs/4021-data-analyst/apply'
    state,_=repo.create(request(url=url))
    # Simulate an attempt saved before the identity normalization upgrade.
    with database.session_factory.begin() as db:
        row=db.scalar(select(AutoApplicationRow).where(AutoApplicationRow.run_id==state['run_id']))
        row.posting_key='generic:'+hashlib.sha256(url.encode()).hexdigest()
    repo.save(state,status='submission_unknown',submission_started=True)
    restarted=ApplyRepository(database.session_factory)
    with pytest.raises(DuplicateApplication) as error:
        restarted.create(request(url=url.removesuffix('/apply'),idempotency_key='restarted-request'))
    assert error.value.run_id==state['run_id']
    assert restarted.get(state['run_id'])['status']=='submission_unknown'


def test_same_conversation_reuses_apply_alias(career):
    first=execute(career,'open_application_url',url='https://careers.example.com/jobs/4021')
    second=execute(career,'open_application_url',url='https://careers.example.com/jobs/4021/apply')
    assert first['run_id']==second['run_id']
    assert len(career.repository.get(career.state['task_id'])['application_runs'])==1


@pytest.mark.parametrize('terminal',['submitted','submission_unknown','submitting'])
def test_legacy_submission_fence_wins_over_indexed_unsubmitted_duplicate(database,terminal):
    repo=ApplyRepository(database.session_factory)
    url='https://careers.example.com/jobs/4021'
    old,_=repo.create(request(url=url+'/apply'))
    with database.session_factory.begin() as db:
        row=db.get(AutoApplicationRow,old['run_id'])
        row.posting_key='legacy:'+old['run_id']
        row.state_json=json.dumps({**json.loads(row.state_json),'url':'https://careers.example.com/jobs/4022'})
    new,_=repo.create(request(url=url,idempotency_key='old-duplicate'))
    with database.session_factory.begin() as db:
        row=db.get(AutoApplicationRow,old['run_id'])
        row.state_json=json.dumps({**json.loads(row.state_json),'url':url+'/apply'})
    repo.save(repo.get(old['run_id']),status=terminal,submission_started=True)
    with pytest.raises(DuplicateApplication) as error:
        ApplyRepository(database.session_factory).create(request(url=url,idempotency_key='after-restart'))
    assert error.value.run_id==old['run_id']
    assert repo.get(new['run_id'])['status']=='queued'


def test_cross_conversation_alias_rejects_live_owner_then_adopts_cancelled_owner(career):
    from test_auto_apply import wait
    c=career
    first=execute(c,'open_application_url',url='https://careers.example.com/jobs/4021/apply')
    wait(c.applications,first['run_id'])
    other,_=c.repository.create('Reopen this job.','second-conversation')
    def reopen():return c.harness.execute(other['task_id'],'open_application_url',
        {'url':'https://careers.example.com/jobs/4021'},call_id='alias-in-another-conversation')
    with pytest.raises(ValueError,match='another conversation'):reopen()
    assert c.applications.repository.get(first['run_id'])['origin_task_id']==c.state['task_id']
    assert len(c.browsers)==1
    c.repository.change(c.state['task_id'],status='cancelled')
    adopted=reopen()
    assert adopted['run_id']==first['run_id']
    assert c.applications.repository.get(first['run_id'])['origin_task_id']==other['task_id']
    assert len(c.browsers)==1


@pytest.mark.parametrize('terminal',['submitted','submission_unknown'])
def test_application_loop_restart_alias_does_not_open_browser(database,terminal):
    from agent_runtime.auto_apply.loop import ApplicationLoop
    repo=ApplyRepository(database.session_factory)
    state,_=repo.create(request(url='https://careers.example.com/jobs/4021/apply'))
    repo.save(state,status=terminal,submission_started=True)
    loop=ApplicationLoop(ApplyRepository(database.session_factory),
        browser_factory=lambda _:pytest.fail('Terminal application must not open a browser'))
    try:
        with pytest.raises(DuplicateApplication):
            loop.start(request(url='https://careers.example.com/jobs/4021',idempotency_key='restart-request'))
        assert repo.get(state['run_id'])['status']==terminal
    finally:loop.close()


def test_running_parent_restart_reuses_legacy_child(career):
    from agent_runtime.task_loop import TaskLoop
    from test_career_flow import ToolModel, settled
    from test_auto_apply import wait
    c=career
    first=execute(c,'open_application_url',url='https://careers.example.com/jobs/4021/apply')
    wait(c.applications,first['run_id'])
    with c.runtime.database.session_factory.begin() as db:
        db.get(AutoApplicationRow,first['run_id']).posting_key='legacy:'+first['run_id']
    c.repository.change(c.state['task_id'],status='running')
    model=ToolModel(lambda snap:('open_application_url',{'url':'https://careers.example.com/jobs/4021'})
        if not any(h['tool']=='open_application_url' for h in snap['history']) else
        ('finish_task',{'text':'The existing application is ready for review. Nothing has been submitted.'}))
    loop=TaskLoop(c.repository,c.harness,model_factory=lambda:model)
    try:
        result=settled(c.repository,c.state['task_id'],statuses=('completed',))
        assert result['application_runs']==[first['run_id']]
        assert len(c.browsers)==1 and c.browsers[0].submissions==0
    finally:loop.close()


def test_literal_country_saved_without_substring_or_legal_inference(database):
    from test_auto_apply import field
    repo=ApplyRepository(database.session_factory)
    repo.save_candidate(request().profile.model_dump())
    state,_=repo.create(request())
    state=repo.save(state,fields=[field('country',label='Country'),field('sponsorship',label='Sponsorship')])
    assert repo.save_literal_profile_facts(state,{'country':'US'},'Russia')=={}
    assert repo.save_literal_profile_facts(state,{'country':'United States','sponsorship':'No'},'United States; No')=={'country':'United States'}
    assert repo.saved_candidate()['profile']['country']=='United States'
    assert 'sponsorship' not in repo.saved_candidate()['profile']


def test_stale_account_banner_follows_child_wait_token(career):
    from agent_runtime.career.service import CareerService
    from test_auto_apply import wait
    c=career
    first=execute(c,'open_application_url',url='https://careers.example.com/jobs/4021')
    child=wait(c.applications,first['run_id'])
    child=c.applications.repository.save(child,status='needs_input',account_request={'origin':'https://careers.example.com','mode':'register','stage':'account'},message='Sign in or register.')
    c.repository.change(c.state['task_id'],status='needs_input',input_request={'id':'account-question',
        'text':'Sign in or register.','application_run_id':child['run_id'],
        'application_wait_token':c.harness.wait_token({'id':child['run_id']})})
    service=CareerService.__new__(CareerService)
    service.repository,service.harness,service.applications=c.repository,c.harness,c.applications
    assert service.view(c.state['task_id'])['message']=='Sign in or register.'
    child=c.applications.repository.save(child,account_request={**child['account_request'],'stage':'verification'},message='Enter verification code.')
    assert service.view(c.state['task_id'])['message']=='Enter verification code.'
    assert c.repository.get(c.state['task_id'])['input_request'] is None
    question={'id':'country-question','text':'Country?','field_keys':['country'],'fields':[]}
    c.applications.repository.save(child,account_request=None,input_request=question,message='Country?')
    view=service.view(c.state['task_id'])
    assert view['message']=='Country?' and view['input_request']['id']=='country-question'


def test_two_stalled_reads_require_decision_without_another_read(career):
    from agent_runtime.task_host import TaskHost
    from types import SimpleNamespace
    from threading import RLock
    c=career
    c.repository.change(c.state['task_id'],progress_guard={'revision':0,'count':2})
    loop=SimpleNamespace(repository=c.repository,harness=c.harness,_budget=lambda _:60,
        _timing=lambda *a,**k:None)
    host=TaskHost(loop,c.state['task_id'],None)
    turn=host.observe()
    names={t['function']['name'] for t in turn.tools}
    assert turn.snapshot['must_decide']
    assert {'finish_task','ask_user'}<=names
    assert 'search_jobs' in names  # A changed source/query can recover, identical args are rejected.
    assert {'read_job','browser_open'}<=names  # Capturing detail or switching source must remain possible.
    assert not {'browser_read','say','read_context'} & names
    assert turn.snapshot['known_results']['jobs']==[]


def test_open_both_one_call_and_truthful_completion(career):
    from test_auto_apply import wait
    c=career
    urls=['https://careers.example.com/jobs/5001','https://careers.example.com/jobs/5002']
    c.repository.append(c.state['task_id'],role='user',text='Apply to both '+ ' '.join(urls))
    result=execute(c,'open_application_url',urls=urls)
    assert result['started_count']==result['opened_or_reused_count']==2
    assert len(c.repository.get(c.state['task_id'])['application_runs'])==2
    for item in result['results']:wait(c.applications,item['application']['run_id'])
    state=c.repository.get(c.state['task_id'])
    c.harness.validate_reply(state,'Both applications are ready for review.')
    with pytest.raises(ValueError,match='submitted'):c.harness.validate_reply(state,'Both applications have been submitted.')
    repeat=execute(c,'open_application_url',urls=[urls[0],urls[0]+'/apply'])
    assert repeat['requested_count']==1 and repeat['started_count']==0
    assert len(c.browsers)==2


def test_plural_claim_rejected_when_only_one_started(career):
    from test_auto_apply import wait
    c=career
    urls=['https://careers.example.com/jobs/5001','https://careers.example.com/jobs/5002']
    c.repository.append(c.state['task_id'],role='user',text='Apply to both '+ ' '.join(urls))
    first=execute(c,'open_application_url',url=urls[0])
    wait(c.applications,first['run_id'])
    with pytest.raises(ValueError,match='Only 1 of 2'):c.harness.validate_reply(c.repository.get(c.state['task_id']),'I opened both applications.')
    c.harness.validate_reply(c.repository.get(c.state['task_id']),'Only one application started. The second did not start.')


def test_public_board_sources_and_blocked_fallback():
    import httpx
    from agent_runtime.career.discovery import JobDiscovery
    calls=[]
    def serve(req):
        calls.append((str(req.url),req.method,req.content))
        if 'blocked' in str(req.url):return httpx.Response(200,text='<title>Just a moment...</title>')
        if 'ashbyhq' in str(req.url):return httpx.Response(200,json={'jobs':[
            {'jobUrl':'https://jobs.ashbyhq.com/acme/1','title':'Staff Backend Engineer','location':'Remote','isListed':True},
            {'jobUrl':'https://jobs.ashbyhq.com/acme/2','title':'Senior Backend Engineer','location':'Remote','isListed':False}]})
        assert req.method=='POST' and json.loads(req.content)['searchText']=='senior backend engineer'
        return httpx.Response(200,json={'jobPostings':[{'externalPath':'/job/Remote/Senior-Backend_R1','title':'Senior Backend Engineer','locationsText':'Remote'}]})
    discovery=JobDiscovery(transport=httpx.MockTransport(serve),resolver=lambda *a,**k:[(None,None,None,None,('8.8.8.8',443))])
    result=discovery.search('senior backend engineer',boards=[{'platform':'ashby','company':'blocked'},
        {'platform':'ashby','company':'acme'},{'platform':'workday','company':'acme','host':'acme.wd5.myworkdayjobs.com','site':'External'}])
    assert result['errors'][0]['blocked']
    assert len(result['jobs'])==2 and result['jobs'][0]['seniority_warning']['actual']=='staff'
    assert 'seniority_warning' not in result['jobs'][1]
    assert result['jobs'][1]['url']=='https://acme.wd5.myworkdayjobs.com/External/job/Remote/Senior-Backend_R1'
    before=len(calls)
    bad=discovery.search('engineer',boards=[{'platform':'workday','company':'acme','host':'evil.example.com','site':'External'}])
    assert not bad['jobs'] and len(calls)==before


def test_budget_reserves_final_decisions_without_extending_limit(career):
    from agent_runtime.task_host import TaskHost
    from types import SimpleNamespace
    c=career
    c.repository.change(c.state['task_id'],model_calls=57)
    loop=SimpleNamespace(repository=c.repository,harness=c.harness,_budget=lambda _:60,_timing=lambda *a,**k:None)
    turn=TaskHost(loop,c.state['task_id'],None).observe()
    assert turn.snapshot['budget_remaining']==3 and turn.snapshot['completion_required']
    assert {t['function']['name'] for t in turn.tools}=={'finish_task','ask_user'}


@pytest.mark.parametrize('text',[
    'Both applications are ready for review.',
    'Both applications have been submitted, but PDF generation failed.',
    'Both applications have been submitted; only one PDF was generated.',
    'I opened both applications.',
    'Both applications have started, but the PDF failed.',
])
def test_plural_status_claim_cannot_be_excused_by_unrelated_failure(text):
    from agent_runtime.career.harness import CareerHarness
    from types import SimpleNamespace
    urls=['https://careers.example.com/jobs/5001','https://careers.example.com/jobs/5002']
    runs={'one':{'url':urls[0],'status':'awaiting_review'},'two':{'url':urls[1],'status':'failed'}}
    harness=CareerHarness.__new__(CareerHarness)
    harness.applications=SimpleNamespace(repository=SimpleNamespace(get=lambda rid:runs[rid]))
    state={'application_runs':list(runs),'messages':[{'role':'user','text':'Apply to both '+' '.join(urls)}]}
    with pytest.raises(ValueError):harness.validate_reply(state,text)
    for honest in ['One is ready for review; the other failed.','Both applications are not ready for review.',
                   'Neither application has been submitted.','Not both applications have been submitted.',
                   'Only one application started; the other failed.']:
        harness.validate_reply(state,honest)
