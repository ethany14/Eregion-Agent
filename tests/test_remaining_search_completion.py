import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from langchain_core.messages import HumanMessage

from eregion.runtime.career.alerts import job_key
from eregion.runtime.career.search_recovery import recovery
from eregion.runtime.request_context import ContextArchive, prepare_request
from eregion.runtime.core.context import ConversationWindow
from test_career_flow import career, execute
from test_remaining_search_runtime import host_for


GOAL='Find two current junior data analyst in New York positions for my saved resume.'
URL='https://www.indeed.com/viewjob?jk=synthetic-second'


def prepare(c):
    c.repository.append(c.state['task_id'],role='user',text=GOAL)
    c.repository.change(c.state['task_id'],goal=GOAL,model_calls=20,model_budget=60)


def test_actual_browser_controls_survive_filtered_reads_and_reach_model_context(career):
    c=career;prepare(c)
    page={'url':'https://www.indeed.com/jobs?q=data+analyst','title':'Search','controls':[
        {'href':URL,'label':'Junior Data Analyst'},
        {'href':'https://www.indeed.com/help','label':'Data Analyst help'},
        {'href':'https://www.indeed.com/viewjob?jk=wrong','label':'Senior Designer'}]}
    c.harness._browsing=SimpleNamespace(inspect=lambda _:page,call=lambda *a,**k:page,close=lambda:None)
    execute(c,'browser_read')
    page['controls']=[]
    execute(c,'browser_read',query='GoodApple')
    host=host_for(c);turn=host.observe()
    messages,_=prepare_request(turn.prompt,turn.tools,ConversationWindow(),turn.snapshot,ContextArchive(),max_chars=48000)
    snapshot=json.loads(next(m.content for m in reversed(messages) if isinstance(m,HumanMessage)))
    assert [j['url'] for j in snapshot['search_recovery']['pending_candidates']]==[URL]
    with pytest.raises(ValueError,match='40 decisions'):
        c.harness.validate_finish(c.repository.get(c.state['task_id']))
    assert not c.repository.get(c.state['task_id'])['jobs']  # snippets never auto-imported
    names={t['function']['name'] for t in turn.tools}
    assert 'read_job' in names and 'recommend_job' in names and 'browser_open' in names
    assert not names & {'start_interview','open_application_url','draft_materials'}


def test_read_rejection_consumes_candidate_without_forcing_loop_and_new_turn_can_retry(career):
    c=career;prepare(c)
    c.repository.change(c.state['task_id'],observed_job_candidates={job_key(URL):{'url':URL}})
    c.harness.discovery=SimpleNamespace(job=lambda _:(_ for _ in ()).throw(ValueError('ambiguous body')))
    with pytest.raises(ValueError,match='ambiguous body'):execute(c,'read_job',url=URL)
    assert not recovery(c.repository.get(c.state['task_id']))['pending_candidates']
    c.harness.validate_finish(c.repository.get(c.state['task_id']))
    c.repository.change(c.state['task_id'],chat_revision=1)
    assert recovery(c.repository.get(c.state['task_id']))['pending_candidates']


@pytest.mark.parametrize('calls',[57,58,59])
def test_completion_reserve_allows_honest_incomplete_result(career,calls):
    c=career;prepare(c)
    c.repository.change(c.state['task_id'],model_calls=calls,observed_job_candidates={job_key(URL):{'url':URL}})
    c.harness.validate_finish(c.repository.get(c.state['task_id']))


def test_final_omitted_url_is_rejected_without_requiring_links_in_progress_messages(career):
    c=career;prepare(c)
    c.repository.change(c.state['task_id'],recommendations=[{'url':URL,'match_score':43.48}])
    state=c.repository.get(c.state['task_id'])
    c.harness.validate_reply(state,'Found one: Score 43.48/100; insufficient results for the second.')
    with pytest.raises(ValueError,match='Missing URLs'):
        c.harness.validate_completion(state,'Found one: Score 43.48/100; insufficient results for the second.')
    c.harness.validate_completion(state,f'Found one: {URL} Score 43.48/100. Second not found.')


def test_non_search_followup_does_not_force_old_recommendation_or_research(career):
    c=career;prepare(c)
    c.repository.append(c.state['task_id'],role='user',text='Thanks, stop searching.')
    c.repository.change(c.state['task_id'],observed_job_candidates={job_key(URL):{'url':URL}},recommendations=[{'url':URL}])
    state=c.repository.get(c.state['task_id'])
    c.harness.validate_finish(state);c.harness.validate_completion(state,'You are welcome.')


@pytest.mark.parametrize('final',[
    'Found: {a}',
    'Found: {a} Score 99/100',
    '- {a} Score 60/100\n- {b} Score 43.48/100',
    '| Job | Salary (thousands USD) |\n| {a} | 43.48 |\n| {b} | 60 |',
    '| Job | Age |\n| {a} | 43.48 |\n| {b} | 60 |',
    '- {a}\n- {b} Score 43.48/100, Score 60/100',
])
def test_final_completion_rejects_missing_wrong_swapped_and_salary_scores(career,final):
    c=career;prepare(c)
    other='https://careers.example.com/jobs/another'
    c.repository.change(c.state['task_id'],recommendations=[{'url':URL,'match_score':43.48},{'url':other,'match_score':60}])
    with pytest.raises(ValueError,match='score|URL'):
        c.harness.validate_completion(c.repository.get(c.state['task_id']),final.format(a=URL,b=other))


@pytest.mark.parametrize('final',[
    '- 43.48/100 — Analyst\n  {a}\n- 60/100 — Analyst\n  {b}',
    '**Analyst A**\n- URL: {a}\n- Score vs saved resume: **43.48**\n**Analyst B**\n- URL: {b}\n- Fit: 60',
    '| Job | Score |\n| {a} | 43.48 |\n| {b} | 60 |',
])
def test_final_completion_accepts_score_semantics_in_the_correct_job_block(career,final):
    c=career;prepare(c)
    other='https://careers.example.com/jobs/another'
    c.repository.change(c.state['task_id'],recommendations=[{'url':URL,'match_score':43.48},{'url':other,'match_score':60}])
    c.harness.validate_completion(c.repository.get(c.state['task_id']),final.format(a=URL,b=other))


@pytest.mark.parametrize('suffix',['',' Score 99/100',' Salary: 43.48 thousand USD'])
def test_single_recommendation_also_requires_its_actual_score(career,suffix):
    c=career;prepare(c)
    c.repository.change(c.state['task_id'],recommendations=[{'url':URL,'match_score':43.48}])
    with pytest.raises(ValueError,match='score'):
        c.harness.validate_completion(c.repository.get(c.state['task_id']),'Found: '+URL+suffix)


@pytest.mark.parametrize('extra',['and apply to them','and draft cover letters','and prepare materials','and start interview practice'])
def test_search_schema_does_not_remove_other_explicit_requested_capabilities(career,extra):
    c=career
    c.repository.append(c.state['task_id'],role='user',text=GOAL+' '+extra)
    assert 'open_application_url' in {t['function']['name'] for t in c.harness.available_tools(c.repository.get(c.state['task_id']))}


def test_real_qualification_final_cannot_vacuously_pass_without_saved_recommendations():
    from pathlib import Path
    from eregion.runtime.career.harness import CareerHarness
    case=json.loads((Path(__file__).parent/'fixtures/remaining_qualification_analyst.json').read_text(encoding='utf-8'))
    state={'goal':case['goal'],'analyses':case['analyses'],'recommendations':[]}
    with pytest.raises(ValueError,match='URL'):
        CareerHarness.validate_completion(None,state,case['final'])
    job=case['verified_jobs'][0]
    state['scored_job_evidence']={job['application_id']:job}
    with pytest.raises(ValueError,match='URL'):
        CareerHarness.validate_completion(None,state,case['final'])
    for suffix in ['', ' Score 99/100',f' Salary: {job["match_score"]} thousand USD']:
        with pytest.raises(ValueError,match='score'):
            CareerHarness.validate_completion(None,state,job['url']+suffix)
    CareerHarness.validate_completion(None,state,f'Read and scored, not recommended: {job["url"]} Score {job["match_score"]}/100. Second qualifying result not found.')
    # This guard does not manufacture recommendations or satisfy the two-job goal.
    assert state['recommendations']==[]


def test_scored_qualification_quote_and_unresolved_recommendation_decision_reach_real_context(career):
    c=career;prepare(c)
    c.harness.discovery=SimpleNamespace(job=lambda url:{'url':url,'title':'Data Analyst',
        'company':'Synthetic','location':'New York, NY',
        'description':'Requires Python APIs.\nRequirements: 0-2 years of marketing or analytics experience.'})
    execute(c,'read_job',url=URL)
    job=execute(c,'import_job',url=URL)
    execute(c,'score_job',application_id=job['application_id'])
    state=c.repository.get(c.state['task_id'])
    evidence=state['scored_job_evidence'][job['application_id']]['qualification_evidence']
    assert any(e['field']=='seniority' and '0-2 years' in e['quote'] for e in evidence)
    host=host_for(c);turn=host.observe()
    messages,_=prepare_request(turn.prompt,turn.tools,ConversationWindow(),turn.snapshot,ContextArchive(),max_chars=48000)
    snapshot=json.loads(next(m.content for m in reversed(messages) if isinstance(m,HumanMessage)))
    known=snapshot['known_results']['scored_not_recommended'][0]
    assert known['url']==URL and known['match_score'] is not None
    assert '0-2 years' in str(known['qualification_evidence'])
    assert 'recommend_job' in snapshot['known_results']['instruction']


def test_provider_attempt_reserve_also_allows_honest_incomplete_result(career,monkeypatch):
    from eregion.runtime.provider_usage import UsageLedger
    c=career;prepare(c)
    c.repository.change(c.state['task_id'],model_calls=10,observed_job_candidates={job_key(URL):{'url':URL}})
    monkeypatch.setenv('JOB_AGENT_TASK_MAX_PROVIDER_ATTEMPTS','12')
    ledger=UsageLedger(c.repository.sessions)
    for i in range(8):ledger.start(f'c{i}',{'task_id':c.state['task_id']},{'purpose':'jev:fit:support_yes_no'})
    with pytest.raises(ValueError,match='decisions available'):   # 4 attempts left: keep working
        c.harness.validate_finish(c.repository.get(c.state['task_id']))
    for i in range(8,10):ledger.start(f'c{i}',{'task_id':c.state['task_id']},{'purpose':'agent'})
    c.harness.validate_finish(c.repository.get(c.state['task_id']))   # only the reply reserve remains
