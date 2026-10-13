"""Main extraction/matching mechanism tests. No paid model or quality gold."""
import json
from collections import Counter
from threading import Lock
from types import SimpleNamespace

import pytest

from eregion.domain.job_extraction import extract_job, numbered_sentences, JobExtraction, ReferencedJobExtraction


@pytest.mark.parametrize('text',['','   ','We are an equal opportunity employer.',
    'Benefits: Health insurance and paid time off.','Requirements:','Senior Backend Engineer'])
def test_only_empty_input_skips_model_all_other_text_is_classified_by_model(monkeypatch,text):
    calls=[]
    monkeypatch.setattr('eregion.domain.model.invoke_structured',lambda *a: calls.append(a) or ReferencedJobExtraction(
        title=None,summary='',statements=[],responsibility_sentence_ids=[]))
    result=extract_job(object(),text)
    assert bool(calls)==bool(text.strip()) and not result.requirements


def test_main_source_map_uses_actual_scoped_units_and_keeps_conditions(monkeypatch):
    text='Requirements: You have communication skills; You are able to execute gap analysis. Benefits: Health insurance. Must be authorized to work in the U.S. Relocation is not offered.'
    calls=[]
    def invoke(model,schema,prompt,payload):
        calls.append(json.loads(payload))
        return ReferencedJobExtraction(title=None,summary='',statements=[],responsibility_sentence_ids=[])
    monkeypatch.setattr('eregion.domain.model.invoke_structured',invoke)
    extract_job(object(),text)
    source=calls[0]['source_sentences']
    assert any(s=='You have communication skills;' for s in source.values())
    assert any('execute gap analysis' in s for s in source.values())
    assert any('Health insurance' in s for s in source.values())
    assert any('authorized to work in the U.S.' in s for s in source.values())
    assert any('Relocation is not offered.' in s for s in source.values())
    assert all(s in text for s in source.values())


def atom(**changes):
    return {'canonical_name':'python_experience','display_name':'Python experience','atomic_text':'Python experience',
        'category':'experience','verification_mode':'years_experience','minimum_years':2,'level':'required',**changes}


@pytest.mark.parametrize('changed',[{'minimum_years':5},{'verification_mode':'resume_evidence'},
    {'category':'skill'},{'level':'preferred'}])
def test_typed_constraints_cannot_silently_collapse(changed):
    data=JobExtraction(title=None,summary='',responsibilities=[],statements=[
        {'source_text':'Requires two years of Python experience.','requirements':[atom()]},
        {'source_text':'Requires five years of Python experience.','requirements':[atom(**changed)]}])
    assert len(data.expand().requirements)==2


def test_production_normalization_keeps_stronger_duration_and_distinct_predicates():
    from eregion.domain.domain import normalize_job_analysis
    source='Requires two years of Python experience. Requires five years of Python experience.'
    extracted=JobExtraction(title=None,summary='',responsibilities=[],statements=[
        {'source_text':'Requires two years of Python experience.','requirements':[atom()]},
        {'source_text':'Requires five years of Python experience.','requirements':[atom(minimum_years=5)]}]).expand()
    normalized=normalize_job_analysis(extracted,source)
    assert [r.minimum_years for r in normalized.requirements]==[2,5]
    assert len({r.requirement_id for r in normalized.requirements})==2
    source='Requires Python for APIs and production deployment.'
    extracted=JobExtraction(title=None,summary='',responsibilities=[],statements=[{
        'source_text':source,'requirements':[atom(atomic_text='Python for APIs',minimum_years=None),
            atom(atomic_text='Python for production deployment',minimum_years=None)]}]).expand()
    assert len(normalize_job_analysis(extracted,source).requirements)==2


def test_formatting_near_duplicate_only_same_source_and_semantics():
    source='Requires Python API development.'
    data=JobExtraction(title=None,summary='',responsibilities=[],statements=[
        {'source_text':source,'requirements':[atom(atomic_text='Python API development'),
            atom(atomic_text='Python API-development.')]},
        {'source_text':'Requires advanced Python API development.','requirements':[atom(atomic_text='Advanced Python API development')]}])
    assert len(data.expand().requirements)==2
    # Negation, tool operators and numbers are not cosmetic differences.
    for texts in [('Python required','Python not required'),('C','C++'),('two years','five years')]:
        data.statements[0].requirements=[type(data.statements[0].requirements[0])(**atom(atomic_text=t)) for t in texts]
        assert len(data.expand().requirements)==3


def test_only_failed_extraction_batch_retries_once_and_does_not_hide_terminal_failure(monkeypatch):
    attempts=Counter();lock=Lock()
    def invoke(model,schema,prompt,payload):
        targets=tuple(json.loads(payload)['extract_sentence_ids'])
        with lock:attempts[targets]+=1;n=attempts[targets]
        if targets[0]=='s8' and n==1:raise TimeoutError('synthetic timeout')
        return ReferencedJobExtraction(title=None,summary='',statements=[],responsibility_sentence_ids=[])
    monkeypatch.setattr('eregion.domain.model.invoke_structured',invoke)
    text='\n'.join(f'- Candidate must demonstrate qualification {i}.' for i in range(25))
    extract_job(object(),text)
    assert sorted(attempts.values())==[1,1,1,2]
    assert sum(len(k) for k in attempts)==25


def test_only_failed_matching_chunk_retries_instead_of_whole_analysis():
    from eregion.domain.fast_match import assess_skills
    from eregion.domain.schemas import JobAnalysis,ResumeAnalysis,SkillAssessment,SkillEvidence
    requirements=[{'requirement_id':f'r{i}','requirement_group_id':f'g{i}',
        'original_text':f'Deliver project {i}', 'source_text':f'Deliver project {i}.', **atom(
        atomic_text=f'Deliver project {i}',canonical_name=f'project_{i}',category='responsibility',
        verification_mode='resume_evidence',minimum_years=None)} for i in range(50)]
    job=JobAnalysis(title=None,summary='',requirements=requirements,responsibilities=[])
    resume=ResumeAnalysis(summary='',skills=[],evidence=[],education=[])
    calls=Counter();lock=Lock()
    def analyze(schema,prompt,payload):
        part=JobAnalysis.model_validate_json(payload.split('\n\nJob analysis:\n',1)[1])
        key=tuple(r.requirement_id for r in part.requirements)
        with lock:calls[key]+=1;n=calls[key]
        if key[0]=='r24' and n==1:raise TimeoutError('synthetic timeout')
        return SkillAssessment(matches=[SkillEvidence(requirement_id=r.requirement_id,job_skill=r.canonical_name,
            requirement_level=r.level,match_status='missing',resume_evidence=[],confidence=1) for r in part.requirements],explanation='',recommendations=[])
    result=assess_skills(resume,job,analyze,SimpleNamespace(enabled=False))
    assert len(result.matches)==50 and sorted(calls.values())==[1,1,2]


def test_wrapped_timeout_retries_exact_batch_and_validation_errors_do_not(monkeypatch):
    calls=[]
    def invoke(*args):
        calls.append(args)
        if len(calls)==1:
            try:raise TimeoutError('synthetic')
            except TimeoutError as exc:raise RuntimeError('adapter') from exc
        return ReferencedJobExtraction(title=None,summary='',statements=[],responsibility_sentence_ids=[])
    monkeypatch.setattr('eregion.domain.model.invoke_structured',invoke)
    extract_job(object(),'Must know Python.')
    assert len(calls)==2 and calls[0][3]==calls[1][3]
    calls.clear()
    def invalid(*args):calls.append(args);raise ValueError('invalid schema')
    monkeypatch.setattr('eregion.domain.model.invoke_structured',invalid)
    with pytest.raises(ValueError):extract_job(object(),'Must know Python.')
    assert len(calls)==1


def test_terminal_transport_failure_and_retry_attribution_remain_visible(monkeypatch):
    from eregion.runtime.provider_usage import current_scope
    attempts=[]
    def fail(*_):
        attempts.append(current_scope().get('attempt'))
        raise TimeoutError('synthetic persistent timeout')
    monkeypatch.setattr('eregion.domain.model.invoke_structured',fail)
    with pytest.raises(TimeoutError):extract_job(object(),'Must know Python.')
    assert attempts==[1,2]


def test_all_real_structured_flat_units_preserve_source_and_no_requirement_cap(monkeypatch):
    from pathlib import Path
    from eregion.domain.jev_fit.core import job_units
    data=json.loads(Path('tools/evals/fit_labels_v1.json').read_text(encoding='utf-8'))
    for job in data['jobs']:
        for form in ('structured','flat'):
            text=job[form]; source=numbered_sentences(text)
            assert list(source.values())==[u['text'] for u in job_units(text)]
            assert all(text[u['start']:u['end']]==u['text'] for u in job_units(text))
    def invoke(model,schema,prompt,payload):
        p=json.loads(payload)
        return ReferencedJobExtraction(title=None,summary='',statements=[
            {'sentence_id':i,'requirements':[atom(atomic_text=p['source_sentences'][i])]} for i in p['extract_sentence_ids']],responsibility_sentence_ids=[])
    monkeypatch.setattr('eregion.domain.model.invoke_structured',invoke)
    text='\n'.join(f'- Candidate must have qualification {i}.' for i in range(35))
    assert len(extract_job(object(),text).requirements)==35
