"""Runtime counterexamples for the real search's failure to consume detail evidence."""
import json
import pytest
from threading import RLock
from types import SimpleNamespace
from uuid import uuid4

from langchain_core.messages import HumanMessage

from eregion.runtime.request_context import ContextArchive, prepare_request
from eregion.runtime.core.context import ConversationWindow
from eregion.runtime.tasks.host import TaskHost
from test_career_flow import career


def host_for(c):
    return TaskHost(SimpleNamespace(repository=c.repository,harness=c.harness,lock=RLock(),
        _budget=lambda _:60,_active=lambda s:not s.get('pause_requested'),
        _timing=lambda *a,**k:None,_control=lambda *a:None),c.state['task_id'],None)


def detail_page():
    return {'url':'https://careers.example.com/jobs/7001','title':'Senior Backend Engineer',
        'heading':'Search results / Senior Backend Engineer','text':'Many unrelated results. '*500,
        'observation_id':'new-observation','page_evidence_hash':'same-visible-source',
        'regions':[{'ref':'detail-region','label':'Senior Backend Engineer','tag':'SECTION','text_length':1000}],
        'job_detail':{'body_scope':'bounded_selector','title':'Senior Backend Engineer',
            'read_job_arguments':{'url':'https://careers.example.com/jobs/7001'}},
        'controls':[{'ref':f'control-{i}','label':f'Observed control {i}','tag':'A',
            'href':f'https://careers.example.com/jobs/{i}'} for i in range(40)]}


def test_detail_action_and_region_reach_effective_model_context_not_only_raw_archive(career):
    c=career;page=detail_page()
    c.harness._browsing=SimpleNamespace(inspect=lambda _:page,call=lambda *a,**k:page,close=lambda:None)
    outcome=c.harness.execute(c.state['task_id'],'browser_read',{},call_id=str(uuid4()))
    archive=ContextArchive()
    compact=archive.tool_result(outcome)
    assert compact['job_detail']['read_job_arguments']==page['job_detail']['read_job_arguments']
    assert compact['regions'][0]['ref']=='detail-region'
    host=host_for(c);turn=host.observe()
    messages,metrics=prepare_request(turn.prompt,turn.tools,ConversationWindow(),turn.snapshot,archive,max_chars=48000)
    effective=json.loads(next(m.content for m in reversed(messages) if isinstance(m,HumanMessage)))
    assert effective['browser']['job_detail']['read_job_arguments']==page['job_detail']['read_job_arguments']
    assert effective['browser']['regions'][0]['ref']=='detail-region'
    assert 'read_job' in {t['function']['name'] for t in turn.tools}
    assert not metrics['protected_overflow']


def test_filtered_reads_same_page_evidence_cannot_reset_stall_counter(career):
    c=career;host=host_for(c);turn=host.observe()
    for i,query in enumerate(('Data Analyst','Associate Data Analyst','Full job description')):
        result={**detail_page(),'query':query,'observation_id':f'observation-{i}',
            'text':query,'controls':detail_page()['controls'][i:i+1]}
        host.after_action({'name':'browser_read','args':{'query':query},'id':str(uuid4())},result,turn)
        if i==1:
            assert c.repository.get(c.state['task_id'])['progress_guard']['count']==1
        if i==2:
            assert c.repository.get(c.state['task_id'])['progress_guard']['count']==2
    recovery=host.observe()
    assert recovery.snapshot['must_decide']
    assert 'read_job' in {t['function']['name'] for t in recovery.tools}


def test_stalled_click_cannot_retry_same_ref_by_changing_observation_token(career):
    c=career;host=host_for(c);turn=host.observe()
    calls=[]
    c.harness.execute=lambda *a,**k:calls.append(a) or detail_page()
    c.repository.change(c.state['task_id'],history=[{'tool':'browser_click','chat_revision':0,
        'arguments':{'observation_id':'old','ref':'b-q9g7ab-44'},
        'result':{'no_new_evidence':True},'browser_url':'https://careers.example.com/jobs/7001'}],
        browser={'url':'https://careers.example.com/jobs/7001'})
    result=host.execute({'name':'browser_click','args':{'observation_id':'new','ref':'b-q9g7ab-44'},
        'id':str(uuid4())},turn)
    assert result['error_code']=='repeated_action' and not calls


def test_invalid_archive_child_path_reports_real_available_paths_and_no_progress():
    archive=ContextArchive();ref=archive.reference({'controls':[{'ref':'actual'}]})['context_ref']
    result=archive.read(ref,path=['controls','10'])
    assert result['error'] and result['no_new_evidence']
    assert ['controls','0'] in [p['path'] for p in result['available_paths']]


def test_actual_stalled_click_remains_blocked_after_large_result_archiving(career):
    c=career;host=host_for(c);host.context_archive=ContextArchive();turn=host.observe()
    page=detail_page()
    c.repository.change(c.state['task_id'],browser=page)
    call={'name':'browser_click','args':{'observation_id':'first','ref':'b-q9g7ab-44'},'id':str(uuid4())}
    host.after_action(call,dict(page),turn)
    host.after_action({**call,'id':str(uuid4())},dict(page),turn)
    last=c.repository.get(c.state['task_id'])['history'][-1]
    assert last['result']['no_new_evidence'] and last['result']['page_evidence_hash']==page['page_evidence_hash']
    calls=[];c.harness.execute=lambda *a,**k:calls.append(a) or detail_page()
    blocked=host.execute({**call,'args':{**call['args'],'observation_id':'fresh'},'id':str(uuid4())},turn)
    assert blocked['error_code']=='repeated_action' and not calls
    # A new actual source state permits technical recovery. The domain browser
    # still validates the target purpose/token; this host never bypasses it.
    c.repository.change(c.state['task_id'],browser={**page,'page_evidence_hash':'changed-source'})
    result=host.execute({**call,'args':{**call['args'],'observation_id':'fresh'},'id':str(uuid4())},turn)
    assert result.get('url')==page['url'] and len(calls)==1


@pytest.mark.parametrize('known_ineligible',[False,True])
def test_production_recommendation_allows_disclosed_low_fit_but_blocks_known_ineligibility(career,known_ineligible):
    from test_career_flow import execute
    from eregion.runtime.workspace.types import ArtifactType
    from eregion.domain.schemas import SkillEvidence
    c=career;url='https://jobs.lever.co/example/abc123'
    execute(c,'read_job',url=url)
    job=execute(c,'import_job',url=url);identifier=job['application_id']
    execute(c,'score_job',application_id=identifier)
    report=c.harness.job_summary(identifier,detail=True)['match_report']
    report['overall_score']=43.45
    if known_ineligible:
        report['matches'].append(SkillEvidence(requirement_id='authorization',job_skill='US authorization required',
            requirement_level='required',match_status='confirmed_condition',condition_satisfied=False,
            resume_evidence=[],confidence=1).model_dump(mode='json'))
    c.runtime.workspace.create_artifact(identifier,artifact_type=ArtifactType.MATCH_REPORT,
        content=report,evidence_ids=[],created_by='synthetic-score-provider',
        expected_version=c.runtime.workspace.get_application(identifier).version)
    args=dict(application_id=identifier,reason='Verified opening, limited skill fit.',
        caveats='Score 43.45; SQL and pipeline experience unresolved. Confirm work authorization.')
    if known_ineligible:
        with pytest.raises(ValueError,match='condition is not satisfied'):execute(c,'recommend_job',**args)
        assert not c.repository.get(c.state['task_id']).get('recommendations')
    else:
        result=execute(c,'recommend_job',**args)
        assert result['recommendation']['match_score']==43.45
        assert c.repository.get(c.state['task_id'])['recommendations'][0]['caveats']==args['caveats']


def test_empty_search_query_variants_do_not_create_progress_without_new_source_evidence(career):
    host=host_for(career);turn=host.observe()
    outcome={'jobs':[],'errors':[{'source':'https://html.duckduckgo.com/html/','blocked':True}],
        'sources_checked':['https://html.duckduckgo.com/html/']}
    for query in ('junior data analyst','data analyst entry level','data analyst'):
        host.after_action({'name':'search_jobs','args':{'query':query},'id':str(uuid4())},dict(outcome),turn)
    assert career.repository.get(career.state['task_id'])['progress_guard']['count']==2
    host.after_action({'name':'search_jobs','args':{'query':'data analyst'},'id':str(uuid4())},
        {'jobs':[{'url':'https://careers.example.com/jobs/new','title':'Junior Data Analyst'}],
            'errors':[],'sources_checked':['public-company-board']},turn)
    assert career.repository.get(career.state['task_id'])['progress_guard']['count']==0


def test_search_tracking_label_and_order_churn_is_not_new_evidence_after_other_work(career):
    host=host_for(career);turn=host.observe()
    def result(token,label,reverse=False):
        jobs=[{'url':'https://www.joblist.com/j/data-analyst-jobs/new-york?msockid='+token,
            'title':label,'source':'public_search'},
            {'url':'https://careers.example.com/jobs/100','title':'Junior Data Analyst','source':'public_search'}]
        return {'jobs':list(reversed(jobs)) if reverse else jobs,'errors':[],'sources_checked':['https://www.bing.com/search']}
    host.after_action({'name':'search_jobs','args':{'query':'data analyst'},'id':str(uuid4())},result('a','Read more'),turn)
    # A durable fingerprint must survive the last-12 action window and restart.
    career.repository.change(career.state['task_id'],history=[])
    restarted=host_for(career);turn=restarted.observe()
    restarted.after_action({'name':'search_jobs','args':{'query':'junior analyst'},'id':str(uuid4())},
        result('b','Junior Data Analyst Jobs (Hiring Now!)',True),turn)
    assert career.repository.get(career.state['task_id'])['progress_guard']['count']==1
    restarted.after_action({'name':'search_jobs','args':{'query':'data analyst'},'id':str(uuid4())},
        {'jobs':[{'url':'https://careers.example.com/jobs/101','title':'Junior Data Analyst','source':'public_search'}],
            'errors':[],'sources_checked':['https://www.bing.com/search']},turn)
    assert career.repository.get(career.state['task_id'])['progress_guard']['count']==0


def test_narrower_or_truncated_repeat_of_observed_search_links_is_not_progress(career):
    # B6 live r2: the same public query ran six times; each time blocked-host
    # exclusions or the limit changed the list slightly, so it counted as progress.
    host=host_for(career);turn=host.observe()
    def links(*names):
        return {'jobs':[{'url':f'https://www.{n}.com/junior-data-analyst-new-york-ny','title':'Junior Data Analyst Jobs',
            'source':'public_search'} for n in names],'errors':[],'sources_checked':['https://www.bing.com/search']}
    host.after_action({'name':'search_jobs','args':{'query':'junior data analyst','limit':20},'id':str(uuid4())},
        links('zippia','hiringcafe','jooble'),turn)
    assert career.repository.get(career.state['task_id'])['progress_guard']['count']==0
    outcome=links('zippia','jooble')
    host.after_action({'name':'search_jobs','args':{'query':'junior data analyst','limit':10},'id':str(uuid4())},outcome,turn)
    assert career.repository.get(career.state['task_id'])['progress_guard']['count']==1
    assert outcome['no_new_evidence'] and 'boards' in outcome['progress_feedback']
    # One genuinely new candidate is still discovery progress.
    host.after_action({'name':'search_jobs','args':{'query':'junior data analyst'},'id':str(uuid4())},
        links('zippia','jobtoday'),turn)
    assert career.repository.get(career.state['task_id'])['progress_guard']['count']==0
