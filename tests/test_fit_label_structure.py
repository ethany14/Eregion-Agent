"""Real r2 source segmentation regressions; not extracted-requirement/score evidence."""
import json
from pathlib import Path
import pytest
from eregion.domain.jev_fit.core import job_units


def source(identifier):
    data=json.loads(Path('tools/evals/fit_labels_v1.json').read_text(encoding='utf-8'))
    return next(j for j in data['jobs'] if j['job_id']==identifier)


def test_real_backbase_flat_independent_semicolon_clauses_do_not_merge():
    text=source('workatbackbase-7721248')['flat'];units=job_units(text)
    starts=['You have excellent communication','You are able to showcase','Organizational and cultural sensitivity',
        'You are able to execute product gap analysis','You know your way around requirements management']
    selected=[next(u for u in units if s in u['text']) for s in starts]
    assert len({u['id'] for u in selected})==5
    assert all(len(u['text'])<=220 for u in selected)
    assert all(text[u['start']:u['end']]==u['text'] for u in units)


def test_real_caseguard_flat_certification_does_not_inherit_benefits_or_company_body():
    text=source('caseguard-5387488008')['flat'];units=job_units(text)
    cert=next(u for u in units if 'Relevant AWS certifications' in u['text'])
    assert len(cert['text'])<=220
    assert 'Benefits' not in cert['text'] and 'About CaseGuard' not in cert['text']
    benefit=next(u for u in units if 'Competitive Salary' in u['text'])
    company=next(u for u in units if 'CaseGuard is a software company' in u['text'])
    assert benefit['section'] != cert['section'] and company['section'] != cert['section']
    assert all(text[u['start']:u['end']]==u['text'] for u in units)


@pytest.mark.parametrize('text',[
    'Requirements: Python and SQL experience.',
    'Requirements: Familiarity with Python; SQL; and Docker.',
    'Requirements: Knowledge of tools (Python; SQL) is required.',
    'Requirements: Relevant AWS certifications (e.g., AWS Certified Solutions Architect, AWS Certified Developer).',
])
def test_technology_conjunctions_lists_and_abbreviations_are_not_arbitrarily_split(text):
    units=[u for u in job_units(text) if u['text'].rstrip(':')!='Requirements']
    assert len(units)==1
    assert text[units[0]['start']:units[0]['end']]==units[0]['text']


def test_semicolon_independent_clauses_split_without_truncating_or_inventing_text():
    text='Requirements: You know Python and SQL; You can design APIs; Experience with tools (Python; SQL) is useful.'
    units=[u for u in job_units(text) if u['text'].rstrip(':')!='Requirements']
    assert len(units)==3
    assert any('Python and SQL' in u['text'] for u in units)
    assert any('(Python; SQL)' in u['text'] for u in units)
    assert all(text[u['start']:u['end']]==u['text'] for u in units)


def test_all_24_captured_texts_keep_original_offsets():
    data=json.loads(Path('tools/evals/fit_labels_v1.json').read_text(encoding='utf-8'))
    for job in data['jobs']:
        for form in ('flat','structured'):
            text=job[form]
            assert all(text[u['start']:u['end']]==u['text'] for u in job_units(text))
