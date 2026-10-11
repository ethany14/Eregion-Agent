import pytest

from job_agent.jev_fit.core import job_units


@pytest.mark.parametrize('country', ['U.S.', 'U.K.'])
def test_country_abbreviation_can_end_an_independent_sentence(country):
    text=f'Requirements: Must be authorized to work in the {country} Sponsorship is not available.'
    units=job_units(text)
    assert [u['text'] for u in units][1:]==[
        f'Must be authorized to work in the {country}', 'Sponsorship is not available.']
    assert all(text[u['start']:u['end']]==u['text'] for u in units)


@pytest.mark.parametrize('sentence', [
    'Must work with U.S. clients and U.K. teams.',
    'Experience with U.S. Python teams is required.',
    'A B.S. Degree in Engineering is required.',
    'Use tools, e.g. Python and SQL.',
    'Worked at Acme Inc. Engineering team.',
    'Fluency in U.S. English is required.',
    'Fluency in U.K. English is required.',
    'Proficiency in U.S. Spanish is required.',
])
def test_abbreviation_inside_a_sentence_keeps_original_offsets(sentence):
    text='Requirements: '+sentence
    units=job_units(text)
    assert [u['text'] for u in units][1:]==[sentence]
    assert all(text[u['start']:u['end']]==u['text'] for u in units)


@pytest.mark.parametrize('following',[
    'Relocation is not offered.', 'Travel may be required.', 'Insurance is provided.',
    'We do not offer relocation.', 'The successful applicant must pass a background check.',
    'This position requires weekend availability.',
])
@pytest.mark.parametrize('country',['U.S.','U.K.'])
def test_unseen_independent_subject_and_predicate_after_country(country,following):
    first=f'Must be authorized to work in the {country}'
    text=f'Requirements: {first} {following}'
    units=job_units(text)
    assert [u['text'] for u in units][1:]==[first,following]
    assert all(text[u['start']:u['end']]==u['text'] for u in units)


@pytest.mark.parametrize('leading',['Python is required.','You must use Python.','Applicants may work remotely.'])
@pytest.mark.parametrize('country',['U.S.','U.K.'])
def test_prior_sentence_predicate_does_not_leak_into_language_fragment(leading,country):
    sentence=f'Fluency in {country} English is required.'
    text=f'Requirements: {leading} {sentence}'
    units=job_units(text)
    assert [u['text'] for u in units][1:]==[leading,sentence]
    assert all(text[u['start']:u['end']]==u['text'] for u in units)


@pytest.mark.parametrize('country',['U.S.','U.K.'])
@pytest.mark.parametrize('following',['Sponsorship is not available.','Relocation is not offered.'])
def test_actual_pdf_to_sentence_units_keeps_independent_conditions_and_original_offsets(tmp_path,country,following):
    import json
    from api.resume_routes import extract_pdf_text
    from job_agent.pdf_rendering import render_letter_pdf
    source=f'Requirements: Must be authorized to work in the {country} {following}'
    pdf=render_letter_pdf(source)
    text,pages=extract_pdf_text(pdf)
    units=job_units(text)
    assert [u['text'] for u in units][1:]==[f'Must be authorized to work in the {country}',following]
    assert all(text[u['start']:u['end']]==u['text'] for u in units)
    (tmp_path/'sentence-pdf-evidence.json').write_text(json.dumps({'pages':pages,'extracted_text':text,
        'units':units,'scope':'Production PDF render/extract/job_units; no model/provider calls'},indent=2),encoding='utf-8')


@pytest.mark.parametrize('sentence',[
    'Fluency in U.S. English is required.',
    'Fluency in U.K. English is required.',
    'Python is required. Fluency in U.S. English is required.',
    'You must use Python. Fluency in U.K. English is required.',
    'Experience with U.S. Python teams is required.',
])
def test_actual_pdf_abbreviations_do_not_create_false_conditions(sentence):
    from api.resume_routes import extract_pdf_text
    from job_agent.pdf_rendering import render_letter_pdf
    text,_=extract_pdf_text(render_letter_pdf('Requirements: '+sentence))
    units=job_units(text)
    expected=sentence.split('. Fluency')
    expected=[expected[0]+'.','Fluency'+expected[1]] if len(expected)==2 else [sentence]
    assert [u['text'] for u in units][1:]==expected
    assert all(text[u['start']:u['end']]==u['text'] for u in units)
