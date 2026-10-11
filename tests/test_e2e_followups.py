"""Regressions for defects found while verifying the 2026-10-10 E2E repairs."""
from job_agent.jev_fit.projection import resume_projection


def entries(text, kind):
    analysis = resume_projection(text)
    quotes = {item.evidence_id: item.exact_text for item in analysis.evidence}
    return [(e.heading, e.organization, e.start_date, e.end_date, ' '.join(quotes[i] for i in e.evidence_ids))
            for e in analysis.source_entries if e.entry_type == kind]


def education(body):
    return entries(f'Jane Doe\nEducation\n{body}\nSkills\nPython\n', 'education')


def experience(first, second):
    return entries(f'Jane Doe\nExperience\n{first}\n- Built APIs\n{second}\n- Ran on-call\n'
                   'Education\nB.S. Computer Science, State University, 2017\nSkills\nGo\n', 'experience')


def test_wrapped_in_progress_qualifier_stays_with_its_own_degree():
    rows = education('M.S. in CS, Carnegie Mellon University (Aug 2025 - May 2027\n(expected)) - In progress, GPA 3.8\n'
                     'B.E. in CSE, Anna University (Aug 2019 - May 2023)')
    assert [row[:4] for row in rows] == [('M.S. in CS', 'Carnegie Mellon University', 'Aug 2025', 'May 2027 (expected)'),
                                         ('B.E. in CSE', 'Anna University', 'Aug 2019', 'May 2023')]
    assert 'In progress' in rows[0][4]
    assert 'In progress' not in rows[1][4] and 'expected' not in rows[1][4]


def test_school_names_that_start_with_their_keyword():
    assert education('B.S. in Computer Science, University of Illinois Urbana-Champaign (Aug 2013 - May 2017)')[0][:4] == (
        'B.S. in Computer Science', 'University of Illinois Urbana-Champaign', 'Aug 2013', 'May 2017')
    assert education('B.A. in Economics, University of California, Berkeley (2015 - 2019)')[0][:2] == (
        'B.A. in Economics', 'University of California, Berkeley')
    assert education('University of Michigan\nB.S. in Biology, 2015 - 2019')[0][:2] == ('B.S. in Biology', 'University of Michigan')


def test_additional_experience_header_layouts():
    expected = [('Senior Engineer', 'Acme Corp'), ('Software Engineer', 'Beta Inc')]
    for first, second in [('Acme Corp, Chicago\nSenior Engineer, 2021 - Present', 'Beta Inc\nSoftware Engineer, 2017 - 2021'),
                          ('Senior Engineer\nAcme Corp, 2021 - Present', 'Software Engineer\nBeta Inc, 2017 - 2021'),
                          ('Acme Corp\tMar 2021 – Present\nSenior Engineer', 'Beta Inc\tJul 2017 – Feb 2021\nSoftware Engineer')]:
        assert [row[:2] for row in experience(first, second)] == expected
    assert [row[:2] for row in experience('Senior Engineer at Acme (2021 – Present)', 'Engineer at Beta (2017 – 2021)')] == [
        ('Senior Engineer', 'Acme'), ('Engineer', 'Beta')]


def test_ambiguous_two_line_header_stays_unowned():
    rows = experience('Northwind\nPlatform, 2021 - Present', 'Contoso\nCore, 2017 - 2021')
    assert len(rows) == 1 and rows[0][:4] == (None, None, None, None)


# ---- C4 / D4: requirement splitting ---------------------------------------------------------
from job_agent.jev_fit.core import boilerplate, job_units


def texts(jd):
    return [u['text'] for u in job_units(jd)]


def test_abbreviations_do_not_split_requirements():
    units = texts('Requirements: B.S. Computer Science or equivalent. 3+ years of Python and SQL. '
                  'Preferred: Experience with e.g. Kafka. Familiarity with AWS, i.e. EKS and RDS.')
    assert 'B.S. Computer Science or equivalent.' in units
    assert '3+ years of Python and SQL.' in units
    assert 'Preferred: Experience with e.g. Kafka.' in units
    assert 'Familiarity with AWS, i.e. EKS and RDS.' in units


def test_lists_and_in_phrase_dashes():
    assert texts('Qualifications:\n1. Python - expert level\n2. SQL') == ['Qualifications:', '1. Python - expert level', '2. SQL']
    assert texts('Salary range: $170,000 - $210,000') == ['Salary range:', '$170,000 - $210,000']


def test_benefits_salary_and_eeo_are_context_not_requirements():
    units = job_units('Requirements: Strong SQL. Benefits: 401(k) match. '
                      'We are an equal opportunity employer regardless of race or religion.')
    flags = {u['text']: boilerplate(u) for u in units}
    assert flags['Strong SQL.'] is False
    assert flags['401(k) match.'] is True
    assert flags['We are an equal opportunity employer regardless of race or religion.'] is True


# ---- C4: main-model resolution of requirements Jev leaves unknown -----------------------------
import pytest
from job_agent.jev_fit.resolve import UnknownDecision, UnknownResolution, resolve_unknowns

EVIDENCE = 'Built Python tools for analytics.\nRan Kubernetes clusters in production for 3 years.\n'


def raw_with_unknowns(*texts_):
    matches = [{'requirement_id': f'j{i}', 'text': t, 'level': 'required', 'weight': 2, 'status': 'unknown',
                'reason': '', 'citations': [], 'initial_decisions': {}, 'focused_decisions': {}} for i, t in enumerate(texts_)]
    extraction = [{'id': f'j{i}', 'classification': 'required'} for i in range(len(texts_))]
    return {'matches': matches, 'extraction': extraction, 'provider_errors': [], 'score': None, 'score_range': [0, 100]}


def decide(*decisions):
    return lambda model, schema, system, human: UnknownResolution(decisions=[UnknownDecision(**d) for d in decisions])


def test_resolver_requires_a_verbatim_quote_for_support():
    raw = raw_with_unknowns('Kubernetes in production', 'Go')
    result = resolve_unknowns(raw, EVIDENCE, model=None, invoke=decide(
        dict(requirement_id='j0', is_candidate_requirement=True, level='required', personal_condition=False, status='matched',
             evidence_quote='Ran Kubernetes clusters in production for 3 years.', reason='explicit'),
        dict(requirement_id='j1', is_candidate_requirement=True, level='required', personal_condition=False, status='missing', reason='absent')))
    by_id = {m['requirement_id']: m for m in result['matches']}
    assert by_id['j0']['status'] == 'matched' and by_id['j0']['resolved_by'] == 'main_model'
    assert by_id['j0']['citations'][0]['exact_text'] == 'Ran Kubernetes clusters in production for 3 years.'
    assert by_id['j1']['status'] == 'missing'
    assert result['score'] == 50.0 and result['status'] == 'completed' and result['main_model_calls'] == 1


def test_resolver_rejects_fabricated_quotes_and_drops_non_requirements():
    raw = raw_with_unknowns('Go', 'We offer great benefits', 'Authorized to work in the US')
    result = resolve_unknowns(raw, EVIDENCE, model=None, invoke=decide(
        dict(requirement_id='j0', is_candidate_requirement=True, level='required', personal_condition=False, status='matched',
             evidence_quote='Wrote Go services at Google.', reason='invented'),
        dict(requirement_id='j1', is_candidate_requirement=False, level='required', personal_condition=False, status='missing', reason='benefit'),
        dict(requirement_id='j2', is_candidate_requirement=True, level='required', personal_condition=True, status='missing', reason='condition')))
    by_id = {m['requirement_id']: m for m in result['matches']}
    assert by_id['j0']['status'] == 'unknown'  # unverifiable support is never adopted
    assert 'j1' not in by_id
    assert by_id['j2']['status'] == 'needs_confirmation'
    assert result['score'] is None


def test_resolver_failure_keeps_the_honest_interval():
    raw = raw_with_unknowns('Go')
    def boom(*_):
        raise TimeoutError('provider')
    result = resolve_unknowns(raw, EVIDENCE, model=None, invoke=boom)
    assert result['matches'][0]['status'] == 'unknown' and result['resolver']['status'] == 'failed'


def test_fit_service_sends_only_jev_unknowns_to_the_main_model(tmp_path, monkeypatch):
    from dataclasses import replace
    import httpx
    from api.services.fit_analysis_service import FitAnalysisService
    from job_agent.jev_fit.settings import Settings
    from test_jev_fit_production import JevEndpoint, NoMainModel
    endpoint = JevEndpoint(); endpoint.unknown = True
    sent = []
    def fake_invoke(model, schema, system, human):
        sent.append(human)
        ids = [line.split()[1] for line in human.splitlines() if line.startswith('- j')]
        return UnknownResolution(decisions=[UnknownDecision(requirement_id=i, is_candidate_requirement=True, level='required',
            personal_condition=False, status='matched', evidence_quote='Built Python tools.', reason='quoted') for i in ids])
    monkeypatch.setattr('job_agent.model.invoke_structured', fake_invoke)
    monkeypatch.setattr('job_agent.model.shared_model', lambda **_: object())
    config = replace(Settings(key='test-only', cache_path=tmp_path / 'd.sqlite3'), resolve_unknowns=True)
    service = FitAnalysisService(NoMainModel(), jev_enabled=True, jev_config=config, jev_transport=httpx.MockTransport(endpoint))
    result = service._analyze_sync(resume_text='Candidate Example\nEXPERIENCE\nEngineer | Example Lab | 2023-01 | 2026-01\n'
                                   'Built Python tools.\nSKILLS\nPython, SQL\n', job_description='Engineer\nRequired: Python\n')
    requested = [line for line in sent[0].splitlines() if line.startswith('- j')]
    assert len(sent) == 1 and len(requested) == 1 and requested[0].endswith(': Python')
    assert result.main_model_calls == 1 and result.skill_match.overall_score == 100.0
    assert any(r['purpose'] == 'jev_fit_resolver' for r in result.decision_routing)


# ---- D5: an application whose owner conversation is gone can be reopened -----------------------
class _Repo:
    def __init__(self, tasks):self.tasks=tasks
    def get(self, task_id):
        if task_id not in self.tasks:raise LookupError('Conversation not found.')
        return self.tasks[task_id]
    def metadata(self, task_id):
        if task_id not in self.tasks:raise LookupError('Conversation not found.')
        return {'trashed_at': self.tasks[task_id].get('trashed_at')}
    def list(self):return list(self.tasks.values())


class _Runs:
    def __init__(self):self.saved=[]
    def save(self, run, **changes):
        self.saved.append(changes);return {**run, **changes}


def _harness(tasks):
    from types import SimpleNamespace
    from agent_runtime.career.harness import CareerHarness
    harness=CareerHarness.__new__(CareerHarness)
    harness.repository=_Repo(tasks)
    harness.applications=SimpleNamespace(repository=_Runs())
    return harness


def test_live_owner_still_blocks_other_conversations():
    harness=_harness({'a':{'task_id':'a','status':'needs_input','application_runs':['r1']},'b':{'task_id':'b','status':'running'}})
    with pytest.raises(ValueError, match='owned by another conversation'):
        harness.require_application_owner({'task_id':'b'},{'run_id':'r1','origin_task_id':'a','status':'needs_input'},adopt=True)


def test_deleted_or_cancelled_owner_can_be_adopted_when_reopened():
    for tasks in ({'b':{'task_id':'b','status':'running'}},
                  {'a':{'task_id':'a','status':'cancelled'},'b':{'task_id':'b','status':'running'}},
                  {'a':{'task_id':'a','status':'completed','trashed_at':'now'},'b':{'task_id':'b','status':'running'}}):
        harness=_harness(tasks)
        run=harness.require_application_owner({'task_id':'b'},{'run_id':'r1','origin_task_id':'a','status':'cancelled'},adopt=True)
        assert run['origin_task_id']=='b'
        with pytest.raises(ValueError, match='Reopen the job'):
            harness.require_application_owner({'task_id':'b'},{'run_id':'r1','origin_task_id':'a','status':'cancelled'})


def test_abandoned_run_is_not_adopted_while_still_executing():
    harness=_harness({'b':{'task_id':'b','status':'running'}})
    with pytest.raises(ValueError, match='still finishing'):
        harness.require_application_owner({'task_id':'b'},{'run_id':'r1','origin_task_id':'a','status':'running'},adopt=True)


# ---- D6: runtime feedback never changes an archived source reference ---------------------------
def test_progress_feedback_does_not_change_archive_ref():
    from agent_runtime.request_context import ContextArchive
    archive=ContextArchive()
    big={'application_id':'job-1','status':'needs_evidence','report':'x'*8000}
    first=archive.tool_result(dict(big))
    second=archive.tool_result({**big,'progress_feedback':'No new evidence from this action.'})
    assert first['context_ref']==second['context_ref']
    assert second['progress_feedback']=='No new evidence from this action.'


# ---- D7: browser contexts pin a locale instead of inheriting the OS ----------------------------
def test_browser_context_locale_is_pinned(monkeypatch):
    from agent_runtime.auto_apply.browser import context_options
    monkeypatch.delenv('JOB_AGENT_BROWSER_LOCALE', raising=False)
    assert context_options()['locale']=='en-US'
    assert context_options()['extra_http_headers']['Accept-Language'].startswith('en-US')
    monkeypatch.setenv('JOB_AGENT_BROWSER_LOCALE','en-GB')
    assert context_options()['locale']=='en-GB'


# ---- C3 / D8: upload obligations follow the actual controls ------------------------------------
def test_required_generic_upload_field_counts_as_the_resume_slot():
    from agent_runtime.auto_apply.autofill import pending_documents
    refresh={'document_refresh':{'resume':True}}
    assert pending_documents(refresh,[{'key':'f','kind':'file','label':'Attachments','required':True}])==['resume']
    assert pending_documents(refresh,[{'key':'f','kind':'file','label':'Additional documents','required':False}])==[]
    assert pending_documents(refresh,[{'key':'n','kind':'text','label':'First name','required':True}])==[]


def test_resolver_decisions_persist_so_scores_do_not_drift(tmp_path):
    from job_agent.jev_fit.resolve import DecisionStore
    store = DecisionStore(tmp_path / 'd.sqlite3')
    calls = []
    def once(model, schema, system, human):
        calls.append(human)
        return UnknownResolution(decisions=[UnknownDecision(requirement_id='j0', is_candidate_requirement=True, level='required',
            personal_condition=False, status='matched', evidence_quote='Ran Kubernetes clusters in production for 3 years.', reason='q')])
    first = resolve_unknowns(raw_with_unknowns('Kubernetes in production'), EVIDENCE, model=None, invoke=once, store=store)
    second = resolve_unknowns(raw_with_unknowns('Kubernetes in production'), EVIDENCE, model=None, invoke=once, store=store)
    assert len(calls) == 1 and first['score'] == second['score'] == 100.0
    assert second['main_model_calls'] == 0 and second['resolver']['cached'] == 1
    # Different evidence is a different decision.
    resolve_unknowns(raw_with_unknowns('Kubernetes in production'), EVIDENCE + 'More.\n', model=None, invoke=once, store=store)
    assert len(calls) == 2


def test_quote_verification_tolerates_only_presentation_differences():
    from job_agent.jev_fit.resolve import locate
    source = 'Built 14 dashboards.\n\x7f Wrote SQL pipelines; cut time\nfrom 3 days to 4 hours.\nLed the team’s data–quality work.'
    span = locate('Built 14 dashboards.\n\x07 Wrote SQL pipelines; cut time from 3 days to 4 hours.', source)
    assert span and source[span[0]:span[1]].startswith('Built 14') and source[span[0]:span[1]].endswith('4 hours.')
    assert locate("Led the team's data-quality work.", source)
    assert locate('Built 15 dashboards.', source) is None          # changed facts never verify
    assert locate('Wrote SQL pipelines to cut time', source) is None  # paraphrase never verifies
