"""Phase 4: real SQLite and production tool entry points, synthetic HTTP only."""
from uuid import uuid4

import httpx
import pytest

from agent_runtime.career.discovery import JobDiscovery
from agent_runtime.career.harness import CareerHarness
from agent_runtime.career.repository import TaskRepository
from test_career_flow import career, execute


BLOCKED={'platform':'ashby','company':'synthetic-blocked'}
HEALTHY={'platform':'ashby','company':'synthetic-healthy'}


def discovery(requests):
    def handle(request):
        requests.append(str(request.url))
        if 'synthetic-blocked' in request.url.path:return httpx.Response(403)
        return httpx.Response(200,json={'jobs':[{'jobUrl':'https://jobs.ashbyhq.com/synthetic-healthy/posting-one',
            'title':'Senior Backend Engineer','location':'Remote','isListed':True}]})
    return JobDiscovery(transport=httpx.MockTransport(handle),
        resolver=lambda *a,**k:[(None,None,None,None,('8.8.8.8',443))])


def test_blocked_board_is_not_retried_across_query_or_new_harness(career):
    c=career;requests=[];c.harness.discovery=discovery(requests)
    first=execute(c,'search_jobs',query='senior backend engineer',boards=[BLOCKED,HEALTHY])
    assert first['errors'][0]['blocked'] and first['jobs']
    for query in ('backend','senior engineer'):
        execute(c,'search_jobs',query=query,boards=[BLOCKED])
    fresh=CareerHarness(c.runtime,c.applications,TaskRepository(c.runtime.database.session_factory),
        discovery=discovery(requests))
    result=fresh.execute(c.state['task_id'],'search_jobs',{'query':'engineer','boards':[BLOCKED]},call_id=str(uuid4()))
    assert sum('synthetic-blocked' in u for u in requests)==1
    assert result['skipped_sources']
    execute(c,'search_jobs',query='backend',boards=[HEALTHY])
    assert sum('synthetic-healthy' in u for u in requests)==2
    c.repository.append(c.state['task_id'],role='user',text='Retry the public boards now.')
    c.repository.change(c.state['task_id'],chat_revision=1)
    execute(c,'search_jobs',query='backend',boards=[BLOCKED])
    assert sum('synthetic-blocked' in u for u in requests)==2


def staff_job(c):
    # Real discovery/import/score persistence; no recommendation or discovery stubs.
    class Posting:
        def job(self,url):return {'url':url,'title':'Staff Backend Engineer','company':'Synthetic',
            'location':'Remote','description':'We are hiring a Staff Backend Engineer. Requires Python APIs. Full time position.'}
    c.harness.discovery=Posting()
    execute(c,'read_job',url='https://jobs.lever.co/synthetic/staff-one')
    job=execute(c,'import_job',url='https://jobs.lever.co/synthetic/staff-one')
    execute(c,'score_job',application_id=job['application_id'])
    return job['application_id']


@pytest.mark.parametrize('search_text',[
    'Find Senior only backend engineer jobs.',
    'Find backend engineer jobs, Senior only.',
    'Find backend engineer jobs. Senior only.',
])
def test_senior_only_rejects_staff_at_actual_recommend_entry_with_sqlite(career,search_text):
    c=career
    c.repository.append(c.state['task_id'],role='user',text=search_text)
    identifier=staff_job(c)
    with pytest.raises(ValueError,match='[Ss]eniority|[Ss]enior.only'):
        execute(c,'recommend_job',application_id=identifier,reason='Strong fit',caveats='')
    assert not c.repository.get(c.state['task_id']).get('recommendations')


def test_seniority_survives_restart_window_and_only_user_can_change_it(career):
    c=career
    c.repository.append(c.state['task_id'],role='user',text='Find Senior only backend engineer jobs.')
    identifier=staff_job(c)
    for _ in range(151):c.repository.append(c.state['task_id'],role='assistant',text='Progress saved.')
    fresh=CareerHarness(c.runtime,c.applications,TaskRepository(c.runtime.database.session_factory),
        fit_service=c.harness.analysis._fit_service)
    with pytest.raises(ValueError,match='Seniority'):
        fresh.execute(c.state['task_id'],'recommend_job',{'application_id':identifier,'reason':'Strong fit','caveats':'Staff role.'},call_id=str(uuid4()))
    assert c.repository.get(c.state['task_id'])['search_constraints']['levels']==['senior']
    c.repository.append(c.state['task_id'],role='user',text='Also include Staff roles.')
    result=fresh.execute(c.state['task_id'],'recommend_job',{'application_id':identifier,'reason':'Strong fit','caveats':''},call_id=str(uuid4()))
    assert result['recommended']
    assert c.repository.get(c.state['task_id'])['recommendations'][0]['title']=='Staff Backend Engineer'


def test_nonexclusive_search_persists_real_mismatch_caveat(career):
    c=career
    c.repository.append(c.state['task_id'],role='user',text='Find Senior backend engineer jobs.')
    identifier=staff_job(c)
    result=execute(c,'recommend_job',application_id=identifier,reason='Strong fit',caveats='Skill gaps disclosed.')
    recommendation=c.repository.get(c.state['task_id'])['recommendations'][0]
    assert result['recommended'] and recommendation['seniority_warning']['actual']=='staff'
    assert 'requested senior' in recommendation['caveats'] and 'posting is staff' in recommendation['caveats']
    assert 'Skill gaps disclosed' in recommendation['caveats']


def test_board_exclusions_apply_by_tenant_not_shared_api_host():
    from agent_runtime.career.discovery import board_source
    requests=[];d=discovery(requests)
    result=d.search('backend',boards=[BLOCKED,HEALTHY],excluded_sources=[board_source(BLOCKED)],
        excluded_hosts=['api.ashbyhq.com'])
    assert len(requests)==1 and 'synthetic-healthy' in requests[0]
    assert result['jobs'] and result['skipped_sources']==[board_source(BLOCKED)]


def test_same_user_turn_survives_revision_change_and_more_than_eight_sources(career):
    c=career;requests=[]
    c.harness.discovery=JobDiscovery(transport=httpx.MockTransport(lambda request:
        (requests.append(str(request.url)) or httpx.Response(403))),
        resolver=lambda *a,**k:[(None,None,None,None,('8.8.8.8',443))])
    for n in range(12):execute(c,'search_jobs',query='backend',boards=[{'platform':'ashby','company':f'synthetic-{n}'}])
    c.repository.change(c.state['task_id'],chat_revision=1)
    for _ in range(151):c.repository.append(c.state['task_id'],role='assistant',text='Saved progress.')
    result=execute(c,'search_jobs',query='engineer',boards=[{'platform':'ashby','company':'synthetic-0'}])
    assert len(requests)==12 and result['skipped_sources']
    from agent_runtime.career.source_health import projection
    view=projection(c.repository.get(c.state['task_id']))
    assert view['source_count']==12 and len(view['sources'])==8


@pytest.mark.parametrize('text',[
    'Do not include Staff roles.',
    'The Staff posting says Python is only preferred. Explain that sentence.',
    'Practice interviewing for the Staff posting; only explain its requirements.',
])
def test_user_negation_and_posting_questions_do_not_relax_senior_only(career,text):
    c=career
    c.repository.append(c.state['task_id'],role='user',text='Find Senior only backend engineer jobs.')
    identifier=staff_job(c)
    c.repository.append(c.state['task_id'],role='user',text=text)
    policy=c.repository.get(c.state['task_id'])['search_constraints']
    assert policy['levels']==['senior'] and policy['strict']
    with pytest.raises(ValueError,match='Seniority'):
        execute(c,'recommend_job',application_id=identifier,reason='Strong fit',caveats='')
    assert not c.repository.get(c.state['task_id']).get('recommendations')


@pytest.mark.parametrize('platform',['ashby','workday'])
def test_public_ats_search_read_import_score_chain(career,platform):
    c=career;requests=[]
    description='We are hiring a Senior Backend Engineer. This full-time position requires Python APIs and SQL. Work on our production services.'
    if platform=='ashby':
        board=HEALTHY;url='https://jobs.ashbyhq.com/synthetic-healthy/posting-one'
    else:
        board={'platform':'workday','company':'synthetic','host':'synthetic.wd5.myworkdayjobs.com','site':'External'}
        url='https://synthetic.wd5.myworkdayjobs.com/External/job/Remote/Senior-Backend_R1'
    def handle(request):
        requests.append((request.method,str(request.url)))
        if platform=='ashby':
            assert request.url.path=='/posting-api/job-board/synthetic-healthy'
            return httpx.Response(200,json={'jobs':[{'jobUrl':url,'title':'Senior Backend Engineer','location':'Remote',
                'isListed':True,'descriptionHtml':'<p>'+description+'</p>'},
                {'jobUrl':url+'-other','title':'Other Company Role','descriptionHtml':'UNRELATED BODY'}]})
        if request.method=='POST':return httpx.Response(200,json={'jobPostings':[
            {'title':'Senior Backend Engineer','externalPath':'/job/Remote/Senior-Backend_R1','locationsText':'Remote'}]})
        assert request.url.path=='/wday/cxs/synthetic/External/job/Remote/Senior-Backend_R1'
        return httpx.Response(200,json={'jobPostingInfo':{'title':'Senior Backend Engineer','location':'Remote',
            'externalPath':'/job/Remote/Senior-Backend_R1','jobDescription':'<p>'+description+'</p>'}})
    c.harness.discovery=JobDiscovery(transport=httpx.MockTransport(handle),
        resolver=lambda *a,**k:[(None,None,None,None,('8.8.8.8',443))])
    result=execute(c,'search_jobs',query='senior backend engineer',boards=[board])
    assert result['jobs'][0]['url']==url
    read=execute(c,'read_job',url=url)
    assert read['description']==description and read['title']=='Senior Backend Engineer'
    assert 'UNRELATED' not in read['description']
    imported=execute(c,'import_job',url=url)
    scored=execute(c,'score_job',application_id=imported['application_id'])
    assert scored['match_score'] is not None
    assert c.runtime.workspace.current_snapshot(imported['application_id']).cleaned_job_description==description
    assert len(requests)==2


def test_blocked_browser_does_not_repeat_open_read_or_query_after_restart(career):
    c=career
    class Browser:
        def __init__(self):self.calls=[];self.page=None
        def inspect(self,task_id):return self.page
        def call(self,task_id,name,args,**kwargs):
            self.calls.append((name,args))
            self.page={'url':args.get('url','https://www.indeed.com/jobs?q=backend'),
                'blocked':True,'title':'Access denied','text':'Verify you are human',
                'controls':[],'page_evidence_hash':'blocked-page','observation_id':'blocked-observation'}
            return self.page
    browser=Browser();c.harness._browsing=browser
    execute(c,'browser_open',url='https://www.indeed.com/jobs?q=backend')
    for name,args in [('browser_open',{'url':'https://www.indeed.com/jobs?q=engineer&start=10'}),('browser_read',{})]:
        with pytest.raises(ValueError,match='[Bb]locked|[Ss]ource'):execute(c,name,**args)
    c.repository.change(c.state['task_id'],chat_revision=1)
    fresh=CareerHarness(c.runtime,c.applications,TaskRepository(c.runtime.database.session_factory))
    fresh._browsing=browser
    with pytest.raises(ValueError,match='[Bb]locked|[Ss]ource'):
        fresh.execute(c.state['task_id'],'browser_open',{'url':'https://www.indeed.com/jobs?q=python'},call_id=str(uuid4()))
    assert len(browser.calls)==1
    # A verified current observation after the USER completes login/challenge
    # can recover the source. The agent never solves or bypasses a challenge.
    browser.page={**browser.page,'blocked':False,'page_evidence_hash':'human-unblocked','observation_id':'new-observation'}
    execute(c,'browser_read')
    assert len(browser.calls)==2
    c.repository.append(c.state['task_id'],role='user',text='Retry Indeed now.')
    execute(c,'browser_open',url='https://www.indeed.com/jobs?q=backend')
    assert len(browser.calls)==3


def test_workday_browser_and_api_source_identity_respects_hyphenated_sites():
    from agent_runtime.career.discovery import board_source
    from agent_runtime.career.source_health import browser_source
    base='https://synthetic.wd5.myworkdayjobs.com'
    a=browser_source(base+'/External-Careers/job/Remote/Engineer_R1')
    b=browser_source(base+'/Other-Careers/job/Remote/Engineer_R1')
    assert a!=b
    assert a==browser_source(base+'/en-US/External-Careers/job/Remote/Engineer_R1')
    assert a==board_source({'platform':'workday','company':'synthetic','host':'synthetic.wd5.myworkdayjobs.com','site':'External-Careers'})


def test_blocked_browser_switches_source_and_completion_discloses_actual_coverage(career):
    c=career
    class Browser:
        page=None
        def inspect(self,task_id):return self.page
        def call(self,task_id,name,args,**kwargs):
            blocked='indeed.com' in args['url']
            self.page={'url':args['url'],'blocked':blocked,'text':'Access denied' if blocked else 'Senior Backend Engineer',
                'controls':[],'observation_id':str(uuid4()),'page_evidence_hash':str(blocked)}
            return self.page
    c.harness._browsing=Browser()
    execute(c,'browser_open',url='https://www.indeed.com/jobs?q=backend')
    healthy=execute(c,'browser_open',url='https://careers.synthetic.example.com/jobs/1')
    assert not healthy['blocked']
    state=c.repository.get(c.state['task_id'])
    with pytest.raises(ValueError,match='Disclose'):c.harness.validate_completion(state,'The search is complete.')
    with pytest.raises(ValueError,match='absence'):c.harness.validate_completion(state,'Indeed was blocked. No vacancies exist.')
    c.harness.validate_completion(state,'Indeed was blocked. I switched to a public employer page; this is limited source coverage, not proof of no vacancies.')
    c.repository.append(c.state['task_id'],role='assistant',text='Indeed was blocked; I switched source.')
    c.harness.validate_completion(c.repository.get(c.state['task_id']),'Here are the observed results.')


def test_actual_duckduckgo_engine_identity_requires_the_correct_readable_source(career):
    c=career
    c.harness.discovery=JobDiscovery(transport=httpx.MockTransport(lambda request:httpx.Response(200,text=
        '<form id="challenge-form">Blocked</form>' if request.url.host=='html.duckduckgo.com' else
        '<a href="https://careers.synthetic.example/jobs/one">Senior Backend Engineer</a>')),
        resolver=lambda *a,**k:[(None,None,None,None,('8.8.8.8',443))])
    result=execute(c,'search_jobs',query='senior backend engineer')
    assert result['errors'][0]['source']=='https://html.duckduckgo.com/html/' and result['errors'][0]['blocked']
    state=c.repository.get(c.state['task_id'])
    c.harness.validate_completion(state,'DuckDuckGo was blocked; I used another public source.')
    for reply in ('Bing was blocked; I used another public source.','HTML was blocked; I used another public source.'):
        with pytest.raises(ValueError,match='Disclose'):c.harness.validate_completion(state,reply)


def test_blocked_ats_cannot_be_retried_through_read_import_or_new_harness(career):
    c=career;requests=[];c.harness.discovery=discovery(requests)
    execute(c,'search_jobs',query='backend',boards=[BLOCKED])
    url='https://jobs.ashbyhq.com/synthetic-blocked/target'
    for name in ('read_job','import_job'):
        with pytest.raises(ValueError,match='Source blocked'):execute(c,name,url=url)
    fresh=CareerHarness(c.runtime,c.applications,TaskRepository(c.runtime.database.session_factory),discovery=discovery(requests))
    with pytest.raises(ValueError,match='Source blocked'):
        fresh.execute(c.state['task_id'],'read_job',{'url':url},call_id=str(uuid4()))
    assert len(requests)==1


def test_first_detail_403_persists_health_and_blocks_other_acquisition_tools(career):
    c=career;requests=[];c.harness.discovery=discovery(requests)
    url='https://jobs.ashbyhq.com/synthetic-blocked/target'
    with pytest.raises(httpx.HTTPStatusError):execute(c,'read_job',url=url)
    with pytest.raises(ValueError,match='Source blocked'):execute(c,'import_job',url=url)
    assert len(requests)==1
    healthy=execute(c,'search_jobs',query='backend',boards=[HEALTHY])
    assert healthy['jobs'] and len(requests)==2
    c.repository.append(c.state['task_id'],role='user',text='Retry this detail now.')
    with pytest.raises(httpx.HTTPStatusError):execute(c,'read_job',url=url)
    assert len(requests)==3


def test_blocked_remote_source_does_not_prevent_literal_authorized_jd_import(career,monkeypatch):
    from agent_runtime.semantics import SemanticDecisions
    monkeypatch.setattr(SemanticDecisions,'pasted_job_text',lambda self,message,quote:quote in message)
    c=career;requests=[];c.harness.discovery=discovery(requests)
    text='We are hiring a Backend Engineer. This full-time position requires Python APIs and SQL. Build production services for our software team.'
    message=c.repository.append(c.state['task_id'],role='user',text='Here is the pasted job description: '+text)['messages'][-1]
    execute(c,'search_jobs',query='backend',boards=[BLOCKED])
    result=execute(c,'import_job',url='https://jobs.ashbyhq.com/synthetic-blocked/target',
        message_id=message['id'],job_text=text,title='Backend Engineer',company='Synthetic',location='Remote')
    assert result['application_id'] and len(requests)==1
    assert c.runtime.workspace.current_snapshot(result['application_id']).cleaned_job_description==text
    with pytest.raises(ValueError,match='literal'):
        execute(c,'import_job',url='https://jobs.ashbyhq.com/synthetic-blocked/target',
            message_id=message['id'],job_text=text+' Invented qualification.',title='Backend Engineer')
    with pytest.raises(ValueError):
        execute(c,'import_job',url='https://jobs.ashbyhq.com/synthetic-blocked/target',
            message_id='not-a-user-message',job_text=text,title='Backend Engineer')
    assert len(requests)==1 and len(c.repository.get(c.state['task_id'])['jobs'])==1


def test_internal_rendered_read_records_first_block_and_prevents_repeat(career):
    c=career;url='https://synthetic.example.com/jobs/1'
    class Browser:
        calls=0
        def inspect(self,task_id):return {'url':url,'blocked':False,'page_evidence_hash':'initial','observation_id':'initial'}
        def call(self,*a,**k):
            self.calls+=1
            return {'url':url,'blocked':'credentials','page_evidence_hash':'login-wall','observation_id':'login'}
    browser=Browser();c.harness._browsing=browser
    with pytest.raises(ValueError,match='account'):execute(c,'read_job',url=url)
    # This cache mimics the actual blocked observation recorded by the manager.
    browser.inspect=lambda task_id:{'url':url,'blocked':'credentials','page_evidence_hash':'login-wall','observation_id':'login'}
    with pytest.raises(ValueError,match='Source blocked'):execute(c,'read_job',url=url)
    assert browser.calls==1


def test_internal_rendered_pagination_block_is_persisted_without_partial_import(career):
    c=career;url='https://synthetic.example.com/jobs/2'
    class Browser:
        calls=0
        page={'url':url,'blocked':False,'page_evidence_hash':'public','observation_id':'public'}
        def inspect(self,task_id):return self.page
        def call(self,*a,**k):
            self.calls+=1
            self.page=({'url':url,'body_scope':'job_detail','primary_heading':'Senior Backend Engineer',
                'text':'Requires Python. '*500,'text_length':8000,'controls':[],
                'observation_id':'first-slice','page_evidence_hash':'public'} if self.calls==1 else
                {'url':url,'blocked':'credentials','observation_id':'blocked-slice','page_evidence_hash':'login-wall'})
            return self.page
    browser=Browser();c.harness._browsing=browser
    with pytest.raises(ValueError,match='page changed'):execute(c,'read_job',url=url)
    with pytest.raises(ValueError,match='Source blocked'):execute(c,'read_job',url=url)
    assert browser.calls==2 and not c.repository.get(c.state['task_id']).get('retrieved_jobs')
