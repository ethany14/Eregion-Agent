"""E4: preserve literal contact header regions through actual PDF extraction."""
import base64
import json

import pytest

from agent_runtime.auto_apply.resume_profile import ResumeFacts,extract_profile,extract_chat_profile,header_city_region
from job_agent.pdf_rendering import render_letter_pdf


@pytest.mark.parametrize('header,city,expected',[
    ('New York, NY | synthetic@example.com','New York','New York, NY'),
    ('Location: Austin, TX 78701','Austin','Austin, TX'),
    ('San Francisco, CA, United States','San Francisco','San Francisco, CA'),
    ('New York, NY','New York, NY','New York, NY'),
    ('New York','New York','New York'),
    ('New York, ZZ','New York','New York'),
    ('EXPERIENCE\nEmployer | New York, NY','New York','New York'),
    ('EDUCATION\nSchool | Austin, TX','Austin','Austin'),
    ('Worked for a company in New York, NY','New York','New York'),
    ('Toronto, ON','Toronto','Toronto'),
])
def test_header_region_preserves_literal_state_without_inventing_or_reading_employer(header,city,expected):
    assert header_city_region('Synthetic Candidate\n'+header,city)==expected


def test_actual_pdf_extraction_keeps_header_city_state_and_exact_evidence(tmp_path):
    class Model:
        def with_structured_output(self,schema):return self
        def invoke(self,messages):
            return ResumeFacts(facts=[{'field':'city','value':'New York','quote':'New York'},
                {'field':'country','value':'Canada','quote':'Canada'}])
    pdf=render_letter_pdf('Synthetic Candidate\nNew York, NY | synthetic@example.com\nEXPERIENCE\nCompany, Austin, TX\nBuilt Python APIs.')
    result=extract_profile(base64.b64encode(pdf).decode(),model_factory=Model)
    assert result['profile']['city']=='New York, NY'
    assert result['evidence']['city']=='New York, NY'
    assert result['profile']['email']=='synthetic@example.com'
    assert 'country' not in result['profile'] and result['warning'] is None
    (tmp_path/'profile-region.json').write_text(json.dumps({'result':result,
        'scope':'Production PDF text extraction, deterministic extraction provider; not real-model evidence'},indent=2),encoding='utf-8')


@pytest.mark.parametrize('body,value,quote,expected',[
    ('New York, NY','New York, NY','New York, NY','New York, NY'),
    ('CONTACT DETAILS\nNew York, NY, United States','New York','New York, NY','New York, NY'),
    ('CONTACT INFORMATION\nAustin, TX','Austin','Austin, TX','Austin, TX'),
    ('Paris, France','Paris','Paris, France','Paris'),
    ('Toronto, ON','Toronto','Toronto, ON','Toronto'),
    ('EXPERIENCE\nEmployer | New York, NY','New York','New York, NY',None),
    ('EDUCATION\nUniversity | New York, NY','New York','New York, NY',None),
    ('University | New York, NY','New York','New York, NY',None),
    ('Acme Corporation\nNew York, NY','New York','New York, NY',None),
    ('Worked at an office in New York, NY','New York','New York, NY',None),
    ('EXPERIENCE\nBuilt APIs.','New York','New York',None),
])
def test_real_pdf_location_identity_and_absent_region_boundaries(body,value,quote,expected):
    class Model:
        def with_structured_output(self,schema):return self
        def invoke(self,messages):return ResumeFacts(facts=[{'field':'city','value':value,'quote':quote}])
    pdf=render_letter_pdf('Synthetic Candidate\nsynthetic@example.com\n'+body)
    result=extract_profile(base64.b64encode(pdf).decode(),model_factory=Model)
    assert result['profile'].get('city')==expected
    assert ('city' in result['evidence'])==(expected is not None)


@pytest.mark.parametrize('failure',[False,True])
def test_missing_or_failed_model_keeps_email_fallback_without_inventing_city(failure):
    class Model:
        def with_structured_output(self,schema):return self
        def invoke(self,messages):
            if failure:raise RuntimeError('Synthetic provider unavailable')
            return ResumeFacts()
    pdf=render_letter_pdf('Synthetic Candidate\nsynthetic@example.com\nEXPERIENCE\nEmployer | New York, NY')
    result=extract_profile(base64.b64encode(pdf).decode(),model_factory=Model)
    assert result['profile']['email']=='synthetic@example.com'
    assert 'city' not in result['profile'] and 'city' not in result['evidence']
    assert bool(result['warning'])==failure


def test_explicit_chat_correction_uses_new_message_not_old_resume_location():
    class Model:
        def with_structured_output(self,schema):return self
        def invoke(self,messages):return ResumeFacts(facts=[{'field':'city','value':'Austin, TX','quote':'Austin, TX'}])
    result=extract_chat_profile('My current city is Austin, TX.',model_factory=Model,
        current_profile={'city':'New York, NY'})
    assert result['profile']['city']=='Austin, TX'
    direct=extract_chat_profile('Paris',field='city',current_profile={'city':'New York, NY'})
    assert direct['profile']['city']=='Paris'


@pytest.mark.parametrize('heading',['WORK HISTORY','EMPLOYMENT HISTORY','ACADEMIC BACKGROUND',
    'PROFESSIONAL EXPERIENCE','Relevant Work Experience','CAREER BACKGROUND','EDUCATIONAL HISTORY'])
def test_section_heading_families_end_contact_scope_in_helper_and_actual_pdf(heading):
    text=f'Synthetic Candidate\n{heading}\nAcme Corporation\nNew York, NY'
    assert header_city_region(text,'New York')=='New York'
    class Model:
        def with_structured_output(self,schema):return self
        def invoke(self,messages):return ResumeFacts(facts=[{'field':'city','value':'New York','quote':'New York, NY'}])
    result=extract_profile(base64.b64encode(render_letter_pdf(text)).decode(),model_factory=Model)
    assert 'city' not in result['profile'] and 'city' not in result['evidence']


@pytest.mark.parametrize('header',[
    'San Francisco, CA, United States',
    'San Francisco, CA 94105, United States',
    'San Francisco, CA 94105-1234, USA',
    'Address: San Francisco, CA 94105, US',
])
@pytest.mark.parametrize('value',['San Francisco','San Francisco, CA'])
def test_actual_pdf_city_state_zip_country_short_and_full_model_values(header,value):
    class Model:
        def with_structured_output(self,schema):return self
        def invoke(self,messages):return ResumeFacts(facts=[{'field':'city','value':value,'quote':header}])
    text=f'Synthetic Candidate\n{header} | synthetic@example.com\nEXPERIENCE\nBuilt APIs.'
    result=extract_profile(base64.b64encode(render_letter_pdf(text)).decode(),model_factory=Model)
    assert result['profile']['city']=='San Francisco, CA'
    assert result['evidence']['city'] in text
    assert result['warning'] is None
