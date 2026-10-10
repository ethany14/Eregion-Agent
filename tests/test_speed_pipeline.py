"""Regression checks for mechanical application steps and shared analysis reuse."""
import json
import os
import time
from contextlib import contextmanager
from threading import Barrier
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

from api.db import create_database
from api.services.fit_analysis_service import FitAnalysisService
from custom_agent.handlers import JobAgentStepHandler
from custom_agent.state import AgentState, Step
from agent_runtime.analysis_cache import AnalysisCache
from agent_runtime.fast_decisions import FastDecisions
from job_agent.schemas import ResumeAnalysis, ResumeEvidence, JobAnalysis, JobRequirement, SkillAssessment, SkillEvidence

class Analyzer:
    def __init__(self): self.calls = []; self.version = 'v1'
    def cache_namespace(self): return self.version
    def __call__(self, schema, system, human):
        self.calls.append(schema)
        if schema is ResumeAnalysis:
            return ResumeAnalysis(summary='Developer', skills=['Python'], education=[],
                evidence=[ResumeEvidence(evidence_id='e', source_section='Skills', exact_text='Python')])
        if schema is JobAnalysis:
            return JobAnalysis(title='Engineer', summary='Role', responsibilities=[], requirements=[
                JobRequirement(requirement_id='r', canonical_name='python', original_text=human,
                    source_text=human, atomic_text=human, level='required')])
        if schema is SkillAssessment:
            job = JobAnalysis.model_validate_json(human.split('\n\nJob analysis:\n')[1])
            return SkillAssessment(matches=[SkillEvidence(requirement_id=r.requirement_id,
                job_skill=r.canonical_name, requirement_level=r.level, match_status='matched',
                resume_evidence=['Python'], confidence=1) for r in job.requirements], explanation='Grounded', recommendations=[])
        raise AssertionError(schema)

def test_fit_cache_survives_restart_and_is_reused_by_workflow(tmp_path):
    db = create_database('sqlite:///' + (tmp_path/'analysis.db').as_posix(), create_schema_for_tests=True)
    analyzer = Analyzer()
    def handler():
        return JobAgentStepHandler(analyzer=analyzer, analysis_cache=AnalysisCache(db.session_factory))
    try:
        fit = FitAnalysisService(handler())._analyze_sync(resume_text='Skills\nPython', job_description='Requires Python')
        assert len(analyzer.calls) == 3
        warm = FitAnalysisService(handler())._analyze_sync(resume_text='Skills\nPython', job_description='Requires Python')
        assert warm.model_calls == 0 and set(warm.cache_hits) == {'resume', 'job', 'match'}
        state = AgentState(run_id='tailor', resume_text='Skills\nPython', job_description='Requires Python')
        h = handler()
        for step in (Step.ANALYZE_RESUME, Step.VALIDATE_EVIDENCE, Step.ANALYZE_JOB, Step.MATCH_SKILLS):
            state = state.model_copy(update=h.execute(step, state).updates)
        assert len(analyzer.calls) == 3
        changed = FitAnalysisService(handler())._analyze_sync(resume_text='Skills\nPython', job_description='Python required.')
        assert changed.cache_hits == ['resume'] and len(analyzer.calls) == 5
        analyzer.version = 'v2'
        FitAnalysisService(handler())._analyze_sync(resume_text='Skills\nPython', job_description='Requires Python')
        assert len(analyzer.calls) == 8
        extra = ResumeEvidence(evidence_id='confirmed-v2', source_section='Confirmed Career Evidence', exact_text='New Python project')
        state = state.model_copy(update={'resume_analysis': state.resume_analysis.model_copy(update={'evidence': [*state.resume_analysis.evidence, extra]})})
        h.execute(Step.MATCH_SKILLS, state)
        assert len(analyzer.calls) == 9
    finally: db.close()

def test_unvalidated_resume_never_enters_cache(tmp_path):
    db = create_database('sqlite:///' + (tmp_path/'invalid.db').as_posix(), create_schema_for_tests=True)
    analyzer = Analyzer(); h = JobAgentStepHandler(analyzer=analyzer, analysis_cache=AnalysisCache(db.session_factory))
    try:
        for _ in range(2):
            with pytest.raises(ValueError):
                h.execute(Step.ANALYZE_RESUME, AgentState(run_id='bad', resume_text='No language listed', job_description=''))
        assert len(analyzer.calls) == 2
    finally: db.close()

def test_eighteen_pending_requirements_run_three_parallel_chunks():
    from job_agent.fast_match import assess_skills
    resume = ResumeAnalysis(summary='', skills=[], education=[], evidence=[])
    job = JobAnalysis(title='Role', summary='', responsibilities=[], requirements=[JobRequirement(
        requirement_id=str(i), canonical_name=f'duty{i}', original_text=f'Duty {i}', level='required', category='responsibility') for i in range(18)])
    meeting = Barrier(3, timeout=3); sizes = []
    def analyze(schema, prompt, content):
        subset = JobAnalysis.model_validate_json(content.split('\n\nJob analysis:\n')[1])
        sizes.append(len(subset.requirements)); meeting.wait()
        return SkillAssessment(matches=[SkillEvidence(requirement_id=r.requirement_id,
            job_skill=r.canonical_name, requirement_level='required', match_status='missing',
            resume_evidence=[], confidence=1) for r in subset.requirements], explanation='', recommendations=[])
    result = assess_skills(resume, job, analyze, FastDecisions())
    assert sizes == [6, 6, 6] and len(result.matches) == 18

def test_exact_skill_keeps_negation_expertise_and_tool_identity():
    from job_agent.fast_match import exact_skill_quote
    r = JobRequirement(requirement_id='r', canonical_name='tableau', original_text='Tableau', level='required')
    def evidence(text): return [ResumeEvidence(evidence_id='e', source_section='Skills', exact_text=text)]
    assert exact_skill_quote(r, evidence('Used Tableau.')) == 'Used Tableau.'
    for text in ('Used Power BI.', 'No Tableau experience.', 'Learning Tableau.'):
        assert exact_skill_quote(r, evidence(text)) is None
    assert exact_skill_quote(r.model_copy(update={'atomic_text':'Advanced Tableau administration'}), evidence('Used Tableau.')) is None

def test_sentence_references_round_trip_exactly():
    from job_agent.job_extraction import numbered_sentences, ReferencedJobExtraction
    text = 'Engineer.\nMust know Python; SQL is preferred.\nBuild APIs.'
    sentences = numbered_sentences(text)
    extraction = ReferencedJobExtraction(title='Engineer', summary='', statements=[{'sentence_id':'s1', 'requirements':[
        {'canonical_name':'python','display_name':'Python','atomic_text':'Must know Python','category':'skill','verification_mode':'resume_evidence','level':'required'}]}], responsibility_sentence_ids=['s2'])
    result = extraction.expand(sentences)
    assert result.requirements[0].source_text == 'Must know Python; SQL is preferred.'
    assert result.responsibilities == ['Build APIs.']
    with pytest.raises(ValueError): extraction.expand({})

def test_summary_counts_survive_bounded_trace():
    from agent_runtime.telemetry import timing_update, application_perf_summary
    state = {'created_at':'2026-10-09T00:00:00+00:00'}
    for i in range(100):
        state['page_history'] = [{'heading':str(i//50)}]
        state.update(timing_update(state, 'model', 2, context_chars=1000, input_tokens=200, output_tokens=20))
    summary = application_perf_summary(state)
    assert summary['model_calls'] == 100 and summary['model_seconds'] == 200
    assert summary['average_context_chars'] == 1000 and len(summary['model_calls_per_page']) == 2
    assert len(state['timings']) == 80

def test_thirty_field_snapshot_filters_memory_and_completed_fields(monkeypatch):
    from agent_runtime.auto_apply.agent import AgentTools, HIDDEN_TOOLS
    from test_auto_apply import FakeBrowser, field
    browser = FakeBrowser(''); browser.fields = [field(f'f{i}') for i in range(30)]
    for f in browser.fields:
        f.update(value='done', help='long help '*100, options=[{'label':str(i), 'value':str(i)} for i in range(100)])
    state={'profile':{},'answers':{f['key']:'done' for f in browser.fields},
        'remembered_answers':[{'memory_id':str(i), 'source':'user_answer', 'question':'Unrelated', 'value':'x'} for i in range(50)]}
    session=AgentTools(browser,state,autofill=lambda:{},active=lambda:True)
    snapshot=session.observe()
    assert len(json.dumps(snapshot))<25000
    assert not snapshot['remembered_answers'] and all(f['done'] for f in snapshot['fields'])
    assert 'observe' in HIDDEN_TOOLS
    old=session.observation_id
    assert session.execute('observe',{}) == {'refreshed':True,'next':'Use the observation in this turn.'}
    assert session.observation_id == old

FORM = '''<main><h1 id="heading">Application contact</h1><form onsubmit="event.preventDefault();window.submits++">
<section id="p1"><label>First name<input id="first" required></label><button type="button" onclick="p1.hidden=true;p2.hidden=false;heading.textContent='Application name'">Next</button></section>
<section id="p2" hidden><label>Last name<input id="last" required></label><button type="button" onclick="p2.hidden=true;p3.hidden=false;heading.textContent='Application review'">Continue</button></section>
<section id="p3" hidden><label>Email<input type="email" id="email" required></label><button type="submit">Submit application</button></section></form></main><script>window.submits=0</script>'''

@pytest.mark.skipif(os.getenv('JOB_AGENT_BROWSER_TESTS') != '1', reason='Opt-in real Chrome')
@pytest.mark.parametrize('url', ['https://job-boards.greenhouse.io/example/jobs/123',
    'https://jobs.lever.co/example/speed-test', 'https://example.wd5.myworkdayjobs.com/en-US/Careers/job/Speed-Test_R123'])
def test_known_three_page_application_needs_zero_model_calls(url, monkeypatch):
    from agent_runtime.auto_apply.browser import ApplicationBrowser
    from agent_runtime.auto_apply.agent import HybridApplicationAgent
    from agent_runtime.auto_apply.autofill import autofill
    monkeypatch.setenv('TYPESAFE_ENABLED','false'); monkeypatch.setenv('JOB_AGENT_HIDDEN_BROWSER','headless')
    class Browser(ApplicationBrowser):
        def _guard_request(self, route): route.fulfill(content_type='text/html', body=FORM)
    class Model:
        def invoke(self,*args): raise AssertionError('Mechanical flow called a model')
    browser=Browser(url,headless=True)
    state={'profile':{'first_name':'Test','last_name':'Candidate','email':'test@example.invalid'},'answers':{},'url':url}
    calls=[]
    try:
        result=HybridApplicationAgent(model_factory=Model).run(browser,state,
            autofill=lambda:autofill(browser,state,lambda:b''), active=lambda:True,
            reserve=lambda kind:calls.append(kind) or True, report=lambda *args:None,
            checkpoint=lambda **updates:state.update(updates))
        assert result['reason']=='ready',result
        assert 'model' not in calls and browser.page.evaluate('window.submits')==0
        assert len(state['page_history'])==2
    finally: browser.close()

def test_duplicate_batch_rejected_before_any_mutation(monkeypatch):
    from test_auto_apply import FakeBrowser, field
    from agent_runtime.auto_apply.agent import AgentTools
    from agent_runtime.auto_apply.runner import ApplicationHost
    from agent_runtime.loop_engine import Turn, ToolArgumentsError
    monkeypatch.setenv('TYPESAFE_ENABLED','false')
    browser=FakeBrowser('');browser.fields=[field('name')]
    session=AgentTools(browser,{'profile':{'first_name':'Test','last_name':'Candidate'},'answers':{}},autofill=lambda:{},active=lambda:True)
    session.observe()
    host=ApplicationHost(session,object(),active=lambda:True,reserve=lambda _:True,report=lambda *args:None)
    calls=[{'name':'type_from_source','args':{'field_key':'name'}}]*2
    with pytest.raises(ToolArgumentsError):host.validate_batch(calls,Turn('',{},[]))
    assert not browser.fields[0]['value']

@pytest.mark.skipif(os.getenv('JOB_AGENT_BROWSER_TESTS') != '1', reason='Opt-in real Chrome')
def test_worker_chrome_is_shared_but_contexts_are_isolated(monkeypatch):
    from agent_runtime.auto_apply.browser import ApplicationBrowser
    from agent_runtime.auto_apply.worker import BrowserWorker
    monkeypatch.setenv('JOB_AGENT_HIDDEN_BROWSER','headless')
    class Browser(ApplicationBrowser):
        def _guard_request(self,route):route.fulfill(content_type='text/html',body=FORM)
    def work():
        a=Browser('https://jobs.lever.co/example/one',headless=True)
        b=Browser('https://jobs.lever.co/example/two',headless=True)
        process=a.browser
        try:
            assert a.browser is b.browser and a.context is not b.context
            a.context.add_cookies([{'name':'isolated','value':'one','domain':'jobs.lever.co','path':'/'}])
            assert not b.context.cookies()
            a.close();assert b.is_open()
            field=next(f for f in b.observe() if f['kind']=='text')
            start=time.perf_counter();b.type_field(field['key'],'x'*2000)
            assert time.perf_counter()-start<1
        finally:a.close();b.close()
        return process
    worker=BrowserWorker(lambda:None)
    try:worker.submit(work).result(timeout=35)
    finally:worker.shutdown()

def test_one_turn_can_fill_four_independent_fields(monkeypatch):
    from test_auto_apply import FakeBrowser, field
    from agent_runtime.auto_apply.agent import HybridApplicationAgent
    monkeypatch.setenv('TYPESAFE_ENABLED','false')
    browser=FakeBrowser('');browser.fields=[field(f'answer{i}') for i in range(4)]
    browser.page_state=lambda: {'can_submit':True,'controls':[],'url':'https://example.invalid/apply','heading':'Application'}
    def type_field(key,value):next(f for f in browser.fields if f['key']==key).update(value=value)
    browser.type_field=type_field
    state={'profile':{},'answers':{f['key']:'value' for f in browser.fields},'chat_revision':0}
    class Model:
        calls=0
        def invoke(self,messages,tools):
            self.calls+=1
            snapshot=json.loads(messages[-1].content)
            return AIMessage(content='',tool_calls=[{'id':str(i),'name':'type_from_source','args':{
                'observation_id':snapshot['observation_id'],'field_key':f'answer{i}','source_ref':f'answer:answer{i}'}} for i in range(4)])
    model=Model()
    result=HybridApplicationAgent(model_factory=lambda:model).run(browser,state,autofill=lambda:{},
        active=lambda:True,reserve=lambda _:True,report=lambda *args:None)
    assert result['reason']=='ready' and model.calls==1
    assert all(f['value']=='value' for f in browser.fields)

def test_unknown_required_field_gets_one_model_question(monkeypatch):
    from test_auto_apply import FakeBrowser, field
    from agent_runtime.auto_apply.agent import HybridApplicationAgent
    monkeypatch.setenv('TYPESAFE_ENABLED','false')
    browser=FakeBrowser('');browser.fields=[field('editor',label='Preferred editor')]
    calls=[]
    class Model:
        def invoke(self,messages,tools):
            calls.append(1)
            return AIMessage(content='',tool_calls=[{'id':'ask','name':'request_input','args':{'field_keys':['editor']}}])
    result=HybridApplicationAgent(model_factory=Model).run(browser,{'profile':{},'answers':{}},
        autofill=lambda:{},active=lambda:True,reserve=lambda _:True,report=lambda *args:None)
    assert result['reason']=='needs_input' and calls==[1] and not browser.submissions

def test_observation_schema_stays_stable_and_does_not_poll_repository(monkeypatch):
    from test_auto_apply import FakeBrowser, field
    from agent_runtime.auto_apply.agent import AgentTools
    from agent_runtime.auto_apply.runner import ApplicationHost
    monkeypatch.setenv('TYPESAFE_ENABLED','false')
    browser=FakeBrowser('');browser.fields=[field('editor',label='Preferred editor')]
    state={'profile':{},'answers':{},'chat_revision':3};reads=[]
    def refresh():reads.append(1);return state
    refresh.revision=lambda:3
    session=AgentTools(browser,state,autofill=lambda:{},active=lambda:True,refresh=refresh)
    host=ApplicationHost(session,object(),active=lambda:True,reserve=lambda _:True,report=lambda *args:None,refresh=refresh)
    first=host.observe();second=host.observe()
    assert json.dumps(first.tools)==json.dumps(second.tools)
    count=len(reads)
    for _ in range(100):assert host.revision()==3
    assert len(reads)==count

def test_factual_only_revision_removes_claim_without_a_model():
    from job_agent.schemas import ResumeSourceEntry, ResumeEntry, ResumeSection, SupportedClaim, TailoredResume, VerificationResult, UnsupportedClaim
    from job_agent.resume_selection import remove_unsupported
    source=ResumeSourceEntry(source_entry_id='s',entry_type='experience',heading='Developer',evidence_ids=['e'])
    resume=ResumeAnalysis(summary='',skills=[],education=[],source_entries=[source],evidence=[
        ResumeEvidence(evidence_id='e',source_section='Experience',source_entry_id='s',exact_text='Built Python APIs.')])
    draft=TailoredResume(sections=[ResumeSection(section_type='experience',title='Experience',entries=[
        ResumeEntry(entry_id='s',heading='Developer',bullets=[SupportedClaim(text='Led a team of 100.',evidence_ids=['e'],source_entry_id='s')])])])
    state=AgentState(run_id='repair',resume_text='Experience\nDeveloper\nBuilt Python APIs.',job_description='Python',
        resume_analysis=resume,tailored_resume=draft,verification=VerificationResult(passed=False,
        unsupported_claims=[UnsupportedClaim(claim='Led a team of 100.',reason='Unsupported claim')],revision_feedback=['Remove unsupported claim.']))
    revised=remove_unsupported(state)
    assert revised is not None
    assert [c.text for c in revised.claims()]==['Built Python APIs.']

def test_code_and_model_verification_overlap_and_keep_rejection():
    from agent_runtime.application_pack.parallel_checks import parallel_checks
    from agent_runtime.application_pack.types import ArtifactVerification, ClaimIssue
    meeting=Barrier(2,timeout=2)
    def code():meeting.wait();return ArtifactVerification(passed=True)
    def model():meeting.wait();return 'model verdict'
    assert parallel_checks(code,model)[1]=='model verdict'
    reject=ArtifactVerification(passed=False,issues=[ClaimIssue(block_id='x',unsupported_text='x',reason='unsupported',cited_evidence_ids=[],revision_instruction='remove')])
    def failure():raise RuntimeError('Ignored because code rejected the draft')
    result,other=parallel_checks(lambda:reject,failure)
    assert result is reject and other is None

def test_cached_fast_options_are_not_counted_as_provider_calls():
    from agent_runtime.telemetry import timing_update, application_perf_summary
    state = {}
    state.update(timing_update(state, 'model', 1, input_tokens=100, context_chars=200))
    state.update(timing_update(state, 'fast_options', .001, requests=0, input_tokens=0))
    state.update(timing_update(state, 'fast_options', .1, requests=1, input_tokens=50))
    summary = application_perf_summary(state)
    assert summary['model_calls'] == 2
    assert sum(summary['model_calls_per_page'].values()) == 2
    assert summary['average_input_tokens'] == 75
    assert summary['average_context_chars'] == 200

def test_optional_browser_model_tiers_keep_recovery_on_main(monkeypatch):
    from agent_runtime.auto_apply.agent import ConfiguredToolModel
    used = []
    class Model:
        request_timeout = 10
        def __init__(self, tier): self.tier = tier
        def bind_tools(self, tools): return self
        def invoke(self, messages, **kwargs): used.append(self.tier); return AIMessage(content='Ready')
    monkeypatch.setattr('job_agent.model.shared_model', lambda **kwargs: Model(kwargs['purpose']))
    model = ConfiguredToolModel()
    for snapshot in ({'fields':[]}, {'fields':[{'kind':'textarea'}]}, {'runtime_feedback':{'repeated_action':True}}, {'recovery':'previous action failed'}):
        model.invoke_turn([], [], snapshot)
    assert used == ['fast', 'agent', 'agent', 'agent']

def test_batch_rejects_new_conditional_fields_before_any_action(monkeypatch):
    from agent_runtime.auto_apply.agent import AgentTools
    from agent_runtime.auto_apply.runner import ApplicationHost
    from agent_runtime.loop_engine import ToolArgumentsError
    from test_auto_apply import FakeBrowser, field
    monkeypatch.setenv('TYPESAFE_ENABLED','false')
    browser = FakeBrowser(''); browser.fields = [field('first')]
    state = {'profile':{},'answers':{}}
    session = AgentTools(browser,state,autofill=lambda:{},active=lambda:True)
    host = ApplicationHost(session,object(),active=lambda:True,reserve=lambda _:True,report=lambda *args:None)
    turn = host.observe()
    with pytest.raises(ToolArgumentsError, match='newly revealed'):
        host.validate_batch([{'args':{'field_key':'first'}},{'args':{'field_key':'revealed-after-first'}}],turn)
    assert not browser.fields[0]['value']

def test_document_replacement_invalidates_memory_revision_and_close_unsubscribes(tmp_path):
    from agent_runtime.auto_apply.repository import ApplyRepository
    from agent_runtime.auto_apply.loop import ApplicationLoop
    from test_auto_apply import request, FakeBrowser
    db = create_database('sqlite:///' + (tmp_path/'revision.db').as_posix(),create_schema_for_tests=True)
    repo = ApplyRepository(db.session_factory)
    saved, _ = repo.create(request())
    saved = repo.save(saved,status='needs_input',pause_requested=True)
    loop = ApplicationLoop(repo,browser_factory=FakeBrowser)
    try:
        saved = repo.get(saved['run_id'])
        refresh = loop._refresh_hook(saved['run_id'])
        assert refresh.revision() == 0
        repo.replace_documents(saved,b'%PDF synthetic replacement',None)
        assert refresh.revision() == 1 and not loop._can_act(saved['run_id'])
        loop._track_control(saved)  # A delayed older notification cannot undo steering.
        assert refresh.revision() == 1
    finally:
        loop.close(); db.close()
    assert not repo.state_listeners
