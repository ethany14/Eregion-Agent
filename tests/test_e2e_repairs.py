"""Regressions from the 2026-10-10 multi-applicant end-to-end failures."""
import json
from datetime import UTC, datetime
from io import BytesIO
from types import SimpleNamespace

import pytest
from pypdf import PdfReader

from agent_runtime.auto_apply.autofill import pending_documents
from agent_runtime.career.alerts import AlertConfig, AlertRepository, next_due, latest_due
from agent_runtime.career.repository import TaskRepository
from agent_runtime.task_loop import TaskLoop
from job_agent.jev_fit.core import job_units
from job_agent.jev_fit.projection import resume_projection
from job_agent.pdf_rendering import render_tailored_resume_pdf
from job_agent.quality import affirmative_skill_clauses, validate_resume_structure
from test_auto_apply import database, field, wait
from test_career_flow import career, execute, prepare, ToolModel, settled
from test_task_loop import Harness


@pytest.mark.parametrize('kind',['resume','cover_letter'])
def test_refresh_requires_observed_upload_but_keeps_prior_step_obligation(kind):
    state={'document_refresh':{kind:True},'document_bindings':{'attachment':kind}}
    assert pending_documents(state,[])==[]
    upload=field('attachment','file')
    assert pending_documents(state,[upload])==[kind]
    state['review_fields']=[upload]
    assert pending_documents(state,[])==[kind]
    state['document_refresh'][kind]=False
    assert pending_documents(state,[])==[]


@pytest.mark.parametrize('role,degree,dates',[
    ('Data Analyst','B.S. in Statistics','Jul 2024 - Present'),
    ('Senior Software Engineer, Payments Platform','B.S. in Computer Science','Mar 2021 - Present'),
    ('Machine Learning Intern','M.S. in Computer Science (expected May 2027)','May 2026 - Aug 2026'),
    ('UX Design Fellow (contract)','B.S. in Nursing','Feb 2026 - Present'),
])
def test_common_pdf_headers_keep_employers_dates_degrees_and_exact_ownership(role,degree,dates):
    source=(f'EXPERIENCE\n{role} - First Company (synthetic), Chicago, IL ({dates})\n'
        '• Built Python APIs.\nSoftware Engineer - Second Company (synthetic), Austin, TX (Jul 2017 - Feb 2021)\n'
        f'• Wrote SQL reports.\nEDUCATION\n{degree}, Fictional University (Aug 2025 - May 2027 (expected)) - In progress\n')
    parsed=resume_projection(source)
    quotes={q.evidence_id:q.exact_text for q in parsed.evidence}
    work=[s for s in parsed.source_entries if s.entry_type=='experience']
    assert len(work)==2
    assert work[0].heading==role and work[0].organization=='First Company (synthetic)'
    assert work[0].start_date==dates.split(' - ')[0]
    assert 'SQL' not in ' '.join(quotes[k] for k in work[0].evidence_ids)
    assert 'Python' not in ' '.join(quotes[k] for k in work[1].evidence_ids)
    education=next(s for s in parsed.source_entries if s.entry_type=='education')
    assert education.heading==degree and education.organization=='Fictional University'
    assert education.end_date=='May 2027 (expected)'
    assert all(q.exact_text in source for q in parsed.evidence)


def test_wrapped_header_does_not_consume_previous_employer_body():
    source=('EXPERIENCE\nEngineer | First Lab | 2022-01 | 2023-02\nBuilt Python tools.\n'
        'Senior Engineer - Second Lab, Chicago, IL\n(Mar 2023 - Present)\n• Built SQL tools.\n')
    parsed=resume_projection(source)
    assert [(s.heading,s.organization) for s in parsed.source_entries]==[
        ('Engineer','First Lab'),('Senior Engineer','Second Lab')]


def test_education_body_and_qualifiers_survive_pdf_export():
    from test_pdf_rendering import sample_resume
    resume=sample_resume();entry=resume['sections'][0]['entries'][0]
    entry.update(heading='Education',subheading=None,bullets=[{'text':
        'M.S. Computer Science, Fictional University. In progress; expected May 2027.',
        'source_entry_id':'school','evidence_ids':['school-evidence']}])
    text='\n'.join(p.extract_text() for p in PdfReader(BytesIO(render_tailored_resume_pdf(resume))).pages)
    assert 'Fictional University' in text and 'In progress' in text and 'expected May 2027' in text


def test_skill_parenthetical_qualifiers_stay_intact():
    assert affirmative_skill_clauses('Go, AWS (EKS, RDS, SQS), Java (prior), SQL')==[
        'Go','AWS (EKS, RDS, SQS)','Java (prior)','SQL']


def test_flat_job_units_keep_headings_and_original_source_coordinates():
    source='Engineer\n\nMinimum requirements\n- Python and SQL.\n- 3 years of experience.\nPreferred qualifications\n- Go.'
    flat=' '.join(source.split())
    for value in (source,flat):
        units=job_units(value)
        assert all(value[u['start']:u['end']]==u['text'] for u in units)
        preferred=next(u for u in units if u['text'].startswith('- Go'))
        assert preferred['section']=='Preferred qualifications'
        assert any('Python and SQL' in u['text'] and '3 years' not in u['text'] for u in units)


def test_repeated_reads_stop_before_budget_without_false_completion(database):
    repo=TaskRepository(database.session_factory);model=ToolModel(lambda _:('lookup',{}))
    loop=TaskLoop(repo,Harness(),model_factory=lambda:model,budget=30)
    try:
        task=loop.start('Inspect the saved observation.','no-progress-regression')
        state=settled(repo,task['task_id'])
        assert state['status']=='needs_input' and state['error']['code']=='no_progress'
        assert model.calls==4 and state['progress_guard']['count']==3
        assert 'not yet complete' in state['messages'][-1]['text']
        loop.chat(task['task_id'],'Try a different approach.','new-user-request')
        state=settled(repo,task['task_id'])
        assert model.calls==8 and state['progress_guard']['revision']==1
    finally:loop.close()


def test_large_interview_keeps_live_id_and_question_without_context_search():
    from agent_runtime.request_context import ContextArchive, prepare_request
    from agent_runtime.loop_context import ConversationWindow
    snapshot={'interviews':[{'mock_interview_id':'interview-id','status':'awaiting_answer',
        'current_question':{'question_id':'q1','question_text':'Your contribution?'},'turns':'x'*16000}]}
    messages,_=prepare_request('system',[],ConversationWindow(),snapshot,ContextArchive(),max_chars=3000)
    value=json.loads(messages[-1].content)
    assert 'context_ref' in value['interviews'][0]
    assert value['live_resources']['interviews'][0]['mock_interview_id']=='interview-id'
    assert value['live_resources']['interviews'][0]['current_question']['question_id']=='q1'


def test_explicit_end_interview_routes_without_reasoning_model(career):
    from agent_runtime.career.service import CareerService
    c=career;job,_=prepare(c)
    interview=execute(c,'start_interview',application_id=job['application_id'],question_count=3)
    class NoModel:
        def __init__(self):raise AssertionError('Ending an interview needs no reasoning model.')
    service=CareerService(c.runtime,c.applications,harness=c.harness,model_factory=NoModel,start_alert_scheduler=False)
    try:
        result=service.chat(c.state['task_id'],'结束面试','end-interview-now')
        assert result['task_status']=='completed'
        ended=c.runtime.mock_interviewer.view(interview['mock_interview_id'])
        assert ended['interview']['status']=='completed' and ended['report_available']
        assert service.repository.get(c.state['task_id'])['model_calls']==0
        service.chat(c.state['task_id'],'结束面试','end-interview-now')  # same message is idempotent
    finally:service.close()


def test_another_conversation_cannot_replace_or_cancel_application(career):
    c=career;run=execute(c,'open_application_url',url='https://jobs.lever.co/example/abc123')
    child=wait(c.applications,run['run_id'])
    other,_=c.repository.create('Open same posting.','different-conversation')
    with pytest.raises(ValueError,match='another conversation'):
        c.harness.open_application_url(other,{'url':child['url']},'second-open')
    assert c.applications.repository.get(run['run_id'])['version']==child['version']
    c.repository.link(other['task_id'],'application_runs',run['run_id'])  # legacy shared link
    c.harness.control(c.repository.get(other['task_id']),'pause')
    assert not c.applications.repository.get(run['run_id']).get('pause_requested')


def test_weekday_schedule_skips_weekends_and_preserves_local_dst_time():
    config=AlertConfig(name='Weekdays',preferences='Remote work',timezone='America/New_York',weekdays=[0,1,2,3,4]).model_dump()
    assert next_due(config,datetime(2026,10,9,15,tzinfo=UTC))==datetime(2026,10,12,13,tzinfo=UTC)
    assert latest_due(config,datetime(2026,10,11,15,tzinfo=UTC))==datetime(2026,10,9,13,tzinfo=UTC)
    assert next_due(config,datetime(2026,10,30,15,tzinfo=UTC))==datetime(2026,11,2,14,tzinfo=UTC)
    for days in ([],[7],[True],['1']):
        with pytest.raises(ValueError):AlertConfig(**{**config,'weekdays':days})


def test_digest_threshold_uses_lower_bound_without_fabricating_point_score(database):
    repo=AlertRepository(database.session_factory)
    config=AlertConfig(name='Matches',preferences='Python work',timezone='UTC',min_score=70).model_dump()
    alert=repo.save(config,request_key='interval-test');run=repo.claim(alert['alert_id'],request_key='now')
    payload={'url':'https://jobs.lever.co/example/abc','match_score':None,'score_range':[75,95]}
    result=repo.add(run['run_id'],payload)['recommendation']
    assert result['match_score'] is None and result['score_range']==[75,95]
    with pytest.raises(ValueError,match='lower bound'):
        repo.add(run['run_id'],{**payload,'url':'https://jobs.lever.co/example/def','score_range':[60,95]})


def test_manual_browser_control_never_auto_resumes_when_verification_clears(database):
    from agent_runtime.auto_apply.loop import ApplicationLoop, AUTO_RESUME
    from agent_runtime.auto_apply.repository import ApplyRepository
    from test_auto_apply import request, FakeBrowser
    repo=ApplyRepository(database.session_factory)
    child,_=repo.create(request())
    repo.save(child,status='needs_input',pause_requested=True,paused_for_control=True,
        handoff_kind=next(iter(AUTO_RESUME)))
    loop=ApplicationLoop(repo,browser_factory=FakeBrowser)
    try:
        before=repo.get(child['run_id'])
        loop._resume_after_handoff(child['run_id'],FakeBrowser(''))
        after=repo.get(child['run_id'])
        assert after['status']=='needs_input' and after['pause_requested'] and after['paused_for_control']
        assert after['chat_revision']==before['chat_revision'] and after['version']==before['version']
    finally:loop.close()


def test_unknown_dated_source_structure_cannot_pass_material_verification():
    from job_agent.schemas import ResumeSourceEntry, TailoredResume
    source=ResumeSourceEntry(source_entry_id='degraded',entry_type='experience',heading='Experience',evidence_ids=['e'])
    resume=TailoredResume.model_validate({'header':{},'sections':[{'section_type':'experience','title':'Experience',
        'entries':[{'entry_id':'degraded','heading':'Experience','bullets':[{'text':'Built Python APIs.',
            'source_entry_id':'degraded','evidence_ids':['e']}]}]}]})
    issues=validate_resume_structure(resume,[source],source_resume_text='EXPERIENCE\nEngineer - Company (Mar 2021 - Present)\nBuilt Python APIs.')
    assert 'unresolved_source_structure' in {i.code for i in issues}


def test_snapshot_does_not_turn_resume_summary_into_employment():
    from agent_runtime.application_pack.workflow import resume_analysis_from_snapshot
    items=[SimpleNamespace(category='experience',source_section=section,source_type='resume',employer_or_project=None,
        role=None,start_date=None,end_date=None,claim_text=text,evidence_version_id=str(index))
        for index,(section,text) in enumerate([('Summary','Engineer with Python experience.'),('Resume','Anonymous header')])]
    result=resume_analysis_from_snapshot(SimpleNamespace(items=items))
    assert [s.entry_type for s in result.source_entries]==['summary','other']


def test_interview_is_not_superseded_by_parent_job_state():
    from agent_runtime.request_context import ContextArchive
    archive=ContextArchive()
    archive.record_resource({'application_id':'job','status':'applied','version':8})
    interview={'mock_interview_id':'practice','application_id':'job','status':'awaiting_answer','version':3}
    assert archive.clean_history(interview)==interview
    assert ContextArchive.resource_identity(interview)=='mock_interview_id:practice'


@pytest.mark.parametrize('applicant',['analyst','backend','student','designer'])
def test_four_applicants_keep_source_ownership_through_vault_snapshot_and_pdf(database,applicant):
    from agent_runtime.application_pack.workflow import resume_analysis_from_snapshot
    from agent_runtime.application_pack.types import EvidenceSnapshotItem
    from agent_runtime.evidence.repository import CareerEvidenceRepository
    from scripts.e2e_repair_evaluation import APPLICANTS
    source=APPLICANTS[applicant]
    projected=resume_projection(source)
    imported=CareerEvidenceRepository(database.session_factory).import_resume_evidence(projected,source)
    items=[]
    for evidence in imported:
        v=evidence.current
        items.append(EvidenceSnapshotItem(evidence_id=evidence.evidence_id,evidence_version_id=v.evidence_version_id,
            content_hash=v.content_hash,source_type=v.source_type.value,selection_reason='regression',associated_requirement_ids=[],
            claim_text=v.claim_text,exact_quote=v.exact_quote,source_section=v.source_section,
            category=v.category.value,employer_or_project=v.employer_or_project,role=v.role,
            start_date=v.start_date,end_date=v.end_date))
    restored=resume_analysis_from_snapshot(SimpleNamespace(items=items))
    def owners(analysis):
        return {(s.entry_type,s.heading,s.organization,s.start_date,s.end_date) for s in analysis.source_entries
                if s.entry_type in {'experience','education'}}
    assert owners(restored)==owners(projected)
    quotes={e.evidence_id:e.exact_text for e in restored.evidence}
    sections=[]
    for s in restored.source_entries:
        if s.entry_type not in {'experience','education','skills'}:continue
        sections.append({'section_type':s.entry_type,'title':s.entry_type.title(),'entries':[{
            'entry_id':s.source_entry_id,'heading':s.heading,'subheading':s.organization,
            'start_date':s.start_date,'end_date':s.end_date,'bullets':[{
                'text':quotes[eid],'source_entry_id':s.source_entry_id,'evidence_ids':[eid]} for eid in s.evidence_ids]}]})
    pdf='\n'.join(p.extract_text() for p in PdfReader(BytesIO(render_tailored_resume_pdf({'header':{},'sections':sections}))).pages)
    for s in restored.source_entries:
        if s.entry_type not in {'experience','education'}:continue
        assert s.heading in pdf and s.organization in pdf
        assert s.start_date in pdf and s.end_date in pdf
    if applicant=='student':assert 'not graduated' in pdf and 'expected' in pdf
    if applicant=='backend':assert 'AWS (EKS, RDS)' in pdf


def test_direct_control_failure_leaves_retryable_user_state_instead_of_queued_task(database):
    class BrokenControl(Harness):
        def route_user_control(self,state,message):raise ValueError('private tool detail')
    repo=TaskRepository(database.session_factory)
    state,_=repo.create('Saved task.','broken-control')
    repo.change(state['task_id'],status='needs_input')
    loop=TaskLoop(repo,BrokenControl(),model_factory=lambda:None)
    try:
        result=loop.chat(state['task_id'],'End interview.','end-now')
        assert result['status']=='needs_input' and result['error']['stage']=='decision'
        assert 'private tool detail' not in json.dumps(result)
        assert result['model_calls']==0
    finally:loop.close()
