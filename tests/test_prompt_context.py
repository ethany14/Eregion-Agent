"""Provider-only context sharing preserves evidence, sources and revision intent."""
import copy
import json
import pytest

from eregion.domain.workflow.state import AgentState
from eregion.domain.prompt_context import encode_context, compact_json_context, context_instruction, resume_context
from eregion.domain.schemas import (ResumeAnalysis, ResumeEvidence, ResumeSourceEntry, JobAnalysis,
    JobRequirement, SkillMatch, SkillEvidence)


def restore(text):
    value = json.loads(text)
    if value.get('encoding') != 'shared-text-v1': return value
    def expand(item):
        if isinstance(item, dict):
            if set(item) == {'$text'}: return value['shared_texts'][item['$text']]
            return {key:expand(child) for key, child in item.items()}
        if isinstance(item, list): return [expand(child) for child in item]
        return item
    return expand(value['content'])


def material_state():
    quote = ('Built Python APIs for an internal synthetic project; documented request validation, '
             'maintained unit tests and investigated errors. No revenue or team-management claims. ')*5
    resume = ResumeAnalysis(summary=quote, skills=['Python'], education=[],
        evidence=[ResumeEvidence(evidence_id='e1', source_section='Experience', source_entry_id='s1', exact_text=quote)],
        source_entries=[ResumeSourceEntry(source_entry_id='s1', entry_type='experience', heading='Developer',
                                         organization='Synthetic', evidence_ids=['e1'])])
    job = JobAnalysis(title='Developer', summary='Synthetic role', responsibilities=[quote], requirements=[
        JobRequirement(requirement_id='r1', canonical_name='Python APIs', original_text=quote, level='required')])
    match = SkillMatch(matches=[SkillEvidence(requirement_id='r1', job_skill='Python APIs', requirement_level='required',
        match_status='matched', resume_evidence=[quote], confidence=1)], explanation='Synthetic', recommendations=[],
        overall_score=100, missing_required_requirements=[], missing_preferred_requirements=[])
    return AgentState(run_id='context', resume_text='Developer\nSynthetic\n'+quote,
        job_description=quote, resume_analysis=resume, job_analysis=job, skill_match=match)


def test_material_input_roundtrips_every_field_without_truncation_or_new_ids():
    state = material_state()
    result = resume_context(state)
    restored = restore(result)
    assert context_instruction(result)
    assert restored == {'original_resume':state.resume_text,
        'resume_analysis':state.resume_analysis.model_dump(mode='json'),
        'job_analysis_not_evidence':state.job_analysis.model_dump(mode='json'),
        'skill_match':state.skill_match.model_dump(mode='json')}
    assert len(result) < len(json.dumps(restored)) * .6
    assert '"evidence_ids":["e1"]' in result  # Public citation identifiers are never replaced.


def test_short_context_and_reference_like_domain_data_remain_plain():
    for value in ({'text':'Python'}, {'text':'fact '*300, 'nested':{'$text':'literal'}, 'quote':'fact '*300}):
        result = encode_context(value)
        assert not context_instruction(result)
        assert json.loads(result) == value


def test_exact_negation_unicode_dates_and_source_ownership_survive_sharing():
    quote = 'No Rust experience. 学位仍在读，预计 2028-05。\n' * 30
    value = {'evidence':[{'evidence_id':'one', 'source_entry_id':'undergrad', 'exact_text':quote},
                         {'evidence_id':'two', 'source_entry_id':'graduate', 'exact_text':quote}],
             'preferences':{'text':'Use concise sentences.'}, 'empty':None}
    original = copy.deepcopy(value)
    assert restore(encode_context(value)) == original and value == original


def test_pack_revision_suffix_and_confirmed_preferences_are_not_lost():
    body = {'evidence':[{'claim_text':'Candidate fact. '*100, 'exact_quote':'Candidate fact. '*100}],
            'preferences':[{'text':'Two summary sentences maximum.'}]}
    suffix = '\nCurrent artifact: {"text":"old draft"}\nVerification feedback: Keep dates unchanged.\n'
    result = compact_json_context(json.dumps(body) + suffix)
    encoded, end = json.JSONDecoder().raw_decode(result)
    assert restore(json.dumps(encoded)) == body and result[end:] == suffix
    assert compact_json_context(result) == result


@pytest.mark.parametrize('operation', ['cover_letter','application_answer','revise_blocks'])
def test_pack_adapters_keep_original_citations_and_revision_data(monkeypatch, operation):
    from eregion.runtime.application_pack.workflow import SharedPackModel
    body = {'evidence':[{'evidence_id':'e1','evidence_version_id':'v1',
                        'claim_text':'Candidate fact. '*120,'exact_quote':'Candidate fact. '*120}],
            'question':'Why this role?', 'preferences':[{'text':'Concise prose.'}]}
    suffix = '\nCurrent artifact: {"text":"Previous draft"}' if operation=='revise_blocks' else ''
    def invoke(model, schema, prompt, content):
        assert context_instruction(content) and 'shared-text-v1' in prompt
        encoded, end = json.JSONDecoder().raw_decode(content)
        assert restore(json.dumps(encoded)) == body and content[end:] == suffix
        return 'checked'
    monkeypatch.setattr('eregion.runtime.application_pack.workflow.shared_model', lambda:object())
    monkeypatch.setattr('eregion.runtime.application_pack.workflow.invoke_structured', invoke)
    adapter = SharedPackModel()
    context = json.dumps(body)+suffix
    result = (adapter.revise_blocks('cover_letter', context) if operation=='revise_blocks'
              else getattr(adapter, operation)(context))
    assert result == 'checked'


def test_low_saving_resume_keeps_the_original_format_and_all_details(monkeypatch):
    from scripts.benchmark_context_sharing import fixture, LegacyAnalyzer
    from eregion.domain.workflow.handlers import SharedModelAnalyzer, JobAgentStepHandler
    from eregion.domain.workflow.state import Step
    from eregion.domain.resume_selection import ResumeSelection
    state, _ = fixture()
    assert SharedModelAnalyzer().resume_context(state) is None
    monkeypatch.setattr('eregion.domain.model.shared_model', lambda **_:object())
    def invoke(model, schema, prompt, content):
        assert content == LegacyAnalyzer().resume_context(state)
        assert not context_instruction(content)
        return ResumeSelection(summary=[], entries=[])
    monkeypatch.setattr('eregion.domain.workflow.handlers.invoke_structured', invoke)
    result = JobAgentStepHandler(analyzer=SharedModelAnalyzer()).execute(Step.WRITE_RESUME, state)
    assert {e.entry_id for s in result.updates['tailored_resume'].sections if s.section_type=='education'
            for e in s.entries} == {'graduate','undergrad'}


def test_real_resume_adapter_receives_shared_context_and_writing_preferences(monkeypatch):
    from eregion.runtime.application_pack.workflow import SharedPackModel
    from eregion.domain.resume_selection import ResumeSelection
    state, calls = material_state(), []
    monkeypatch.setattr('eregion.domain.model.shared_model', lambda **_:object())
    def invoke(model, schema, prompt, content):
        calls.append((prompt,content))
        assert 'shared-text-v1' in prompt
        encoded, end = json.JSONDecoder().raw_decode(content)
        assert restore(json.dumps(encoded))['original_resume'] == state.resume_text
        assert 'Keep Python APIs.' in content[end:]
        return ResumeSelection(summary=[], entries=[{'entry_id':'s1', 'selected_evidence_ids':['e1'],
            'bullets':[{'text':state.resume_analysis.evidence[0].exact_text, 'evidence_ids':['e1']}]}])
    monkeypatch.setattr('eregion.domain.workflow.handlers.invoke_structured', invoke)
    result = SharedPackModel().resume(state, [{'display_text':'Keep Python APIs.'}])
    assert len(calls) == 1
    assert result.claims()[0].source_entry_id == 's1'


def test_semantic_reference_namespace_does_not_mix_claims(monkeypatch):
    from eregion.runtime.semantics import SemanticDecisions, ClaimDecisions
    claims = [{'claim_id':str(i), 'claim':'Paraphrase', 'evidence':[
        {'quote':('Fact for A. ' if i < 4 else 'Fact for B. ')*100}]} for i in range(8)]
    def invoke(model, schema, prompt, content):
        assert context_instruction(content)
        decoded = restore(content)
        for expected, actual in zip(claims, decoded['claims']):
            assert actual['claim_id'] == expected['claim_id'] and actual['evidence'] == expected['evidence']
        return ClaimDecisions(decisions=[{'claim_id':item['claim_id'], 'supported':False} for item in claims])
    monkeypatch.setattr('eregion.runtime.semantics.invoke_structured', invoke)
    assert SemanticDecisions(model=object()).claims(claims) == set()
