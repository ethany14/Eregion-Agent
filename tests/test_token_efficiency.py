"""Second-round efficiency regressions: grounding, complete batches and fail-closed checks."""
from types import SimpleNamespace

import pytest

from agent_runtime.application_pack.types import EvidenceSnapshotItem
from agent_runtime.application_pack.verifier import ArtifactVerifier
from agent_runtime.application_pack.verification import verify_material_resume
from agent_runtime.application_pack.workflow import SharedPackModel
from custom_agent.handlers import JobAgentStepHandler
from custom_agent.state import AgentState, Step
from job_agent.compact_match import match_payload
from job_agent.fast_match import matching_batches
from job_agent.schemas import (JobRequirement, ResumeAnalysis, ResumeEvidence, ResumeSourceEntry,
    ResumeEntry, ResumeSection, SupportedClaim, TailoredResume, VerificationResult, UnsupportedClaim)


def resume_case(text='Developed APIs using Python.', *, section='experience'):
    quote = 'Built Python APIs.' if section == 'experience' else 'Master of Engineering in progress.'
    source = ResumeSourceEntry(source_entry_id='s', entry_type=section, heading='Source', evidence_ids=['e'])
    resume = ResumeAnalysis(summary='', skills=[], education=[], source_entries=[source], evidence=[
        ResumeEvidence(evidence_id='e', source_section=section, source_entry_id='s', exact_text=quote)])
    draft = TailoredResume(sections=[ResumeSection(section_type=section, title=section, entries=[
        ResumeEntry(entry_id='s', heading='Source', bullets=[
            SupportedClaim(text=text, evidence_ids=['e'], source_entry_id='s')])])])
    state = AgentState(run_id='efficiency', resume_text='Source\n'+quote, job_description='Engineer',
                       resume_analysis=resume, tailored_resume=draft)
    evidence = [EvidenceSnapshotItem(evidence_id='e', evidence_version_id='e', content_hash='fixture',
        source_type='resume', selection_reason='fixture', associated_requirement_ids=[],
        claim_text=quote, exact_quote=quote)]
    return state, evidence


def test_batch_size_accounts_for_actual_payload_without_dropping_evidence():
    state, _ = resume_case()
    requirements = [JobRequirement(requirement_id=f'r{i}', canonical_name='duty',
        original_text='Detailed requirements. '*80, category='responsibility', level='required') for i in range(18)]
    batches = matching_batches(state.resume_analysis, requirements, target_chars=10_000)
    assert len(batches) > 1
    assert [r for batch in batches for r in batch] == requirements
    assert all(len(match_payload(state.resume_analysis, batch)) <= 10_000 for batch in batches)
    assert all('Built Python APIs.' in match_payload(state.resume_analysis, batch) for batch in batches)
    huge = state.resume_analysis.model_copy(update={'evidence': [state.resume_analysis.evidence[0].model_copy(
        update={'exact_text': 'Evidence sentence. '*6000})]})
    short = [r.model_copy(update={'original_text':'Duty', 'atomic_text':'Duty', 'source_text':'Duty'}) for r in requirements]
    assert len(matching_batches(huge, short)) < len(short)


@pytest.mark.parametrize('section,text,supported', [
    ('experience', 'Developed APIs using Python.', True),
    ('experience', 'Led 100 engineers to grow revenue 50%.', False),
    ('education', 'Completed Master of Engineering.', False),
])
def test_consolidated_verifier_checks_every_section_once(section, text, supported):
    state, evidence = resume_case(text, section=section)
    calls = []
    def judge(claims):
        calls.append(claims)
        return {c['claim_id'] for c in claims} if supported else set()
    verifier = ArtifactVerifier(judge)
    model = SharedPackModel()
    model.verify_resume = lambda _: pytest.fail('Do not start a duplicate factual model request')
    result = verify_material_resume(state, model,
        lambda: verifier.verify(state.tailored_resume.model_dump(), 'tailored_resume', evidence))
    assert result.passed is supported
    assert len(calls) == 1 and calls[0][0]['claim'] == text


def test_invalid_resume_structure_is_rejected_before_any_model_request():
    state, _ = resume_case()
    state.tailored_resume.sections[0].entries[0].heading = 'Invented title'
    def unexpected(*args): pytest.fail('Structural failure should not spend model tokens')
    result = verify_material_resume(state, SharedPackModel(), unexpected)
    assert not result.passed and 'metadata' in result.issues[0].reason
    handler_result = JobAgentStepHandler(analyzer=unexpected).execute(Step.VERIFY_RESUME, state)
    assert not handler_result.updates['verification'].passed


def test_invalid_citation_skips_semantics_and_revised_content_is_rechecked():
    state, evidence = resume_case()
    calls = []
    def judge(claims): calls.append(claims); return set()
    verifier = ArtifactVerifier(judge)
    claim = state.tailored_resume.claims()[0]
    state.tailored_resume.sections[0].entries[0].bullets.append(claim.model_copy(update={'evidence_ids':['unknown']}))
    assert not verifier.verify(state.tailored_resume.model_dump(), 'tailored_resume', evidence).passed
    assert not calls
    state.tailored_resume.sections[0].entries[0].bullets.pop()
    assert not verifier.verify(state.tailored_resume.model_dump(), 'tailored_resume', evidence).passed
    assert len(calls) == 1


def test_custom_model_keeps_its_additional_rejection():
    from agent_runtime.application_pack.types import ArtifactVerification
    custom = SimpleNamespace(verify_resume=lambda _: VerificationResult(passed=False,
        unsupported_claims=[UnsupportedClaim(claim='Claim', reason='Unverified')], revision_feedback=['Remove claim.']))
    assert not verify_material_resume(None, custom, lambda: ArtifactVerification(passed=True)).passed


@pytest.mark.parametrize('quote,claim', [
    ('Learning Python.', 'Python'),
    ('Planning to manage a team of 100.', 'manage a team of 100'),
    ('Master of Engineering in progress.', 'Master of Engineering'),
])
def test_omitting_source_qualifiers_cannot_skip_semantic_validation(quote, claim):
    state, evidence = resume_case(claim)
    evidence = [evidence[0].model_copy(update={'claim_text':quote, 'exact_quote':quote})]
    calls = []
    def reject(items): calls.append(items); return set()
    result = ArtifactVerifier(reject).verify(state.tailored_resume.model_dump(), 'tailored_resume', evidence)
    assert not result.passed and len(calls) == 1


def test_unchanged_complete_quote_needs_no_semantic_request():
    state, evidence = resume_case('Built Python APIs.')
    result = ArtifactVerifier(lambda _: pytest.fail('Full exact quote is already supported')).verify(
        state.tailored_resume.model_dump(), 'tailored_resume', evidence)
    assert result.passed
