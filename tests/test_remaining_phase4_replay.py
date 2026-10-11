"""Frozen paid failure replay; all execution here is offline with real SQLite."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from agent_runtime.career.alerts import job_key
from agent_runtime.career.search_recovery import recovery
from agent_runtime.career.source_health import browser_source, active_sources, record_browser
from agent_runtime.progress import search_evidence
from agent_runtime.request_context import ContextArchive
from agent_runtime.telemetry import outcome_fingerprint
from test_career_flow import career, execute
from test_remaining_search_runtime import host_for


def frozen():
    return json.loads((Path(__file__).parent/'fixtures/remaining_phase4_analyst_failure.json').read_text(encoding='utf-8'))


def test_actual_six_tracking_variants_share_candidate_identity_not_only_search_fingerprint():
    urls=frozen()['joblist_variants']
    assert len(urls)==6
    # Existing search normalization was ALREADY correct before this repair.
    assert len({outcome_fingerprint(search_evidence({'jobs':[{'url':u,'source':'public_search'}]})) for u in urls})==1
    assert len({job_key(u) for u in urls})==1


@pytest.mark.parametrize('parameter',['jk','jobId','q','location','page'])
def test_identity_keeps_real_ids_and_semantic_query_parameters(parameter):
    assert job_key(f'https://careers.example.com/jobs/list?{parameter}=one&msockid=a')!=job_key(
        f'https://careers.example.com/jobs/list?{parameter}=two&msockid=b')
    assert job_key(f'https://careers.example.com/jobs/list?{parameter}=one&msockid=a')==job_key(
        f'https://careers.example.com/jobs/list?{parameter}=one&msockid=b')


def test_actual_blocked_pending_are_excluded_but_search_candidates_are_actionable():
    state=frozen()['state']
    blocked=active_sources(state)
    result=recovery(state)
    assert not any(blocked.get(browser_source(j['url']),{}).get('blocked') for j in result['pending_candidates'])
    state['search_candidates']['https://careers.example.com/jobs/new']={
        'url':'https://careers.example.com/jobs/new','title':'Junior Data Analyst','source':'public_search'}
    result=recovery(state)
    assert any(j['url']=='https://careers.example.com/jobs/new' for j in result['pending_candidates'])
    assert result['read_not_imported']  # real retained JD is available, not silently lost
    assert result['read_not_imported'][0]['title']=='Data Analyst'
    assert 'not' in result['instruction'].lower()  # not automatically qualified/recommended


def test_actual_search_observation_alone_proposes_bounded_verification_never_recommendation():
    state=frozen()['state']
    state.update(observed_job_candidates={},retrieved_jobs={},job_read_attempts={},candidate_rejections={})
    # Real frozen search links, including a subsequently rejected talent network,
    # establish discovery only. Verification is still mandatory.
    result=recovery(state)
    expected=[j for j in state['search_candidates'].values() if 'gainam.com/' in j['url']][0]
    target=next(j for j in result['pending_candidates'] if j['url']==expected['url'])
    assert target['read_job_arguments']=={'url':expected['url']}
    assert not state['recommendations'] and not result['read_not_imported']


def test_recovery_tracks_persisted_control_recovery_and_new_user_turn(career):
    c=career;state=frozen()['state'];tid=c.state['task_id']
    c.repository.change(tid,**{k:state[k] for k in ('user_turn_id','observed_job_candidates','search_source_health','goal','messages')})
    assert not recovery(c.repository.get(tid))['pending_candidates']
    record_browser(c.repository,tid,{'url':'https://www.indeed.com/jobs','blocked':False,
        'page_evidence_hash':'actual-new-positive-observation','observation_id':'after-user-control'})
    assert recovery(c.repository.get(tid))['pending_candidates']
    # A new user turn may retry; the prior source record is not a global ban.
    c.repository.change(tid,search_source_health=state['search_source_health'])
    c.repository.append(tid,role='user',text=state['goal'])
    assert recovery(c.repository.get(tid))['pending_candidates']


def test_actual_search_variants_deduplicate_persisted_candidates_and_blocked_hosts_survive_page_eviction(career):
    c=career;f=frozen();tid=c.state['task_id'];captured=[]
    c.repository.change(tid,user_turn_id=f['state']['user_turn_id'],
        search_source_health=f['state']['search_source_health'],research_pages=[])
    def search(**args):
        captured.append(args)
        return {'jobs':[{'url':u,'title':'Junior Data Analyst','source':'public_search'} for u in f['joblist_variants']]}
    c.harness.discovery=SimpleNamespace(search=search)
    execute(c,'search_jobs',query='junior data analyst')
    assert 'www.linkedin.com' in captured[0]['excluded_hosts']
    assert len(c.repository.get(tid)['search_candidates'])==1
    screened=[]
    c.harness.screen=lambda task,state,jobs,query:screened.extend(jobs) or {'screened':len(jobs)}
    assert execute(c,'screen_jobs',urls=[f['joblist_variants'][0]],query='data analyst')['screened']==1
    assert job_key(screened[0]['url'])==job_key(f['joblist_variants'][0])
    with pytest.raises(ValueError,match='Screen only'):
        execute(c,'screen_jobs',urls=['https://careers.example.com/jobs/not-observed'],query='data analyst')


def test_repeated_action_and_known_blocked_source_do_not_reset_stall_across_tools(career):
    c=career;host=host_for(c);turn=host.observe();tid=c.state['task_id']
    state=frozen()['state']
    c.repository.change(tid,user_turn_id=state['user_turn_id'],search_source_health=state['search_source_health'],
        progress_guard={'revision':0,'count':1})
    call={'name':'read_job','args':{'url':'https://www.indeed.com/viewjob?jk=one'},'id':str(uuid4())}
    try:host.execute(call,turn)
    except ValueError as exc:outcome=host.action_error(exc)
    else:raise AssertionError('Blocked source must not run')
    host.after_action(call,outcome,turn)
    assert c.repository.get(tid)['progress_guard']['count']==2
    # Actual runtime repeated_action errors formerly lacked no_new_evidence.
    host.after_action({'name':'browser_open','args':{'url':'https://example.com'},'id':str(uuid4())},
        {'error':'This exact action already ran','error_code':'repeated_action'},turn)
    assert c.repository.get(tid)['error']['code']=='no_progress'


def test_parent_read_then_child_projection_is_not_new_context_evidence():
    a=ContextArchive();ref=a.reference({'jobs':[{'url':'https://careers.example.com/jobs/1','title':'Junior Data Analyst'}]})['context_ref']
    parent=a.read(ref)
    assert parent['next_offset'] is None
    child=a.read(ref,path=['jobs'])
    assert child.get('no_new_evidence') and child['content']
    # A genuinely unread child/range still supplies evidence.
    b=ContextArchive();ref=b.reference({'text':'x'*7000,'jobs':[{'url':'https://careers.example.com/jobs/2'}]})['context_ref']
    b.read(ref)
    assert not b.read(ref,path=['jobs']).get('no_new_evidence')


def test_context_fingerprint_survives_history_eviction_and_restart(career):
    c=career;host=host_for(c);turn=host.observe()
    call={'name':'read_context','args':{'ref':'immutable','path':['jobs']},'id':str(uuid4())}
    value={'offset':0,'content':'same exact original evidence'}
    host.after_action(call,dict(value),turn)
    c.repository.change(c.state['task_id'],history=[])
    restarted=host_for(c);turn=restarted.observe()
    restarted.after_action({**call,'id':str(uuid4())},dict(value),turn)
    assert c.repository.get(c.state['task_id'])['progress_guard']['count']==1


def test_actual_same_search_limit_churn_does_not_repeat_io_after_restart(career):
    from agent_runtime.career.harness import CareerHarness
    c=career;requests=[]
    actual=next(h['result'] for h in frozen()['history'] if h['tool']=='search_jobs' and h['result'].get('jobs'))
    c.harness.discovery=SimpleNamespace(search=lambda **args:requests.append(args) or copy.deepcopy(actual))
    execute(c,'search_jobs',query='junior data analyst',location='New York, NY',limit=10)
    fresh=CareerHarness(c.runtime,c.applications,c.repository,discovery=c.harness.discovery,
        fit_service=c.harness.analysis._fit_service)
    try:
        for limit in (20,10,20):
            result=fresh.execute(c.state['task_id'],'search_jobs',{
                'query':'junior data analyst','location':'New York, NY','limit':limit},call_id=str(uuid4()))
            assert result['no_new_evidence']
        assert len(requests)==1
        c.repository.append(c.state['task_id'],role='user',text='Retry junior data analyst jobs now.')
        fresh.execute(c.state['task_id'],'search_jobs',{'query':'junior data analyst','location':'New York, NY'},call_id=str(uuid4()))
        assert len(requests)==2
    finally:fresh.close()


def test_larger_limit_can_expand_an_actually_truncated_search(career):
    c=career;requests=[]
    def search(**args):
        requests.append(args)
        return {'jobs':[{'url':f'https://careers.example.com/jobs/{i}','title':'Junior Data Analyst'} for i in range(args['limit'])]}
    c.harness.discovery=SimpleNamespace(search=search)
    execute(c,'search_jobs',query='data analyst',limit=2)
    execute(c,'search_jobs',query='data analyst',limit=4)
    assert len(requests)==2


def test_saved_target_body_import_is_local_even_when_remote_source_later_blocked(career):
    from agent_runtime.career.posting_qualification import PostingRejected
    c=career;tid=c.state['task_id'];state=frozen()['state']
    job=next(iter(state['retrieved_jobs'].values()))
    c.repository.change(tid,user_turn_id=state['user_turn_id'],
        search_source_health=state['search_source_health'],retrieved_jobs=state['retrieved_jobs'])
    calls=[]
    c.harness.discovery=SimpleNamespace(job=lambda url:calls.append(url) or pytest.fail('Cached import must not fetch'))
    saved=execute(c,'import_job',url=job['url'])
    assert saved['description']==job['description'] and saved['title']==job['title'] and not calls
    assert len(c.repository.get(tid)['jobs'])==1
    assert not c.harness.observe(c.repository.get(tid))['search_recovery'] or not c.harness.observe(c.repository.get(tid))['search_recovery']['read_not_imported']
    with pytest.raises(ValueError,match='Source blocked'):
        execute(c,'import_job',url='https://www.indeed.com/viewjob?jk=uncached')
    with pytest.raises(ValueError,match='Source blocked'):
        execute(c,'read_job',url=job['url'])
    # Cached acquisition is not a waiver of posting qualification/rejection.
    invalid={**job,'description':'Register to join our talent network for future opportunities. We place graduates into roles with leading employers.'}
    c.repository.change(tid,retrieved_jobs={job['url']:invalid})
    with pytest.raises(PostingRejected):execute(c,'import_job',url=job['url'])
    assert len(c.repository.get(tid)['jobs'])==1 and not calls
