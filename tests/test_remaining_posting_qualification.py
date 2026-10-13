import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_career_flow import career, execute
from test_remaining_search_completion import prepare


FIXTURE=json.loads((Path(__file__).parent/'fixtures/remaining_candidate_recovery.json').read_text())


def test_actual_talent_network_is_read_then_model_dismissal_blocks_import(career):
    c=career;job=FIXTURE['jobs'][0]
    c.harness.discovery=SimpleNamespace(job=lambda _:job)
    assert execute(c,'read_job',url=job['url'])['description']==job['description']
    execute(c,'dismiss_candidate',url=job['url'],quote=job['description'][:300],
            reason='Model identified a talent network rather than a specific vacancy.')
    with pytest.raises(ValueError,match='talent|network|vacancy'):
        execute(c,'import_job',url=job['url'],title='Junior Data Analyst')
    assert not c.repository.get(c.state['task_id'])['jobs']


@pytest.mark.parametrize('description',[
    'Apply to join our talent community for future opportunities. We support graduates with leading employers.',
    'Register your interest in our talent pool. This is not a current vacancy; recruiters may contact you later.',
    'Our program places graduates into roles with leading employers. Join the early careers talent network.',
])
def test_network_and_program_words_do_not_trigger_a_read_time_regex_verdict(career,description):
    c=career;url='https://careers.example.com/jobs/100'
    c.harness.discovery=SimpleNamespace(job=lambda _:dict(url=url,title='Junior Data Analyst',description=description))
    assert execute(c,'read_job',url=url)['description']==description
    assert not c.repository.get(c.state['task_id']).get('candidate_rejections')


def test_missing_heading_cannot_be_overridden_by_model_import_metadata(career):
    c=career;url='https://careers.example.com/jobs/100'
    c.harness.discovery=SimpleNamespace(job=lambda _:dict(url=url,title='',description='Requires Python and SQL. '*12))
    with pytest.raises(ValueError,match='title|identity'):
        execute(c,'import_job',url=url,title='Junior Data Analyst')
    assert not c.repository.get(c.state['task_id'])['jobs']


def test_specific_vacancy_with_incidental_network_link_remains_readable(career):
    c=career;url='https://careers.example.com/jobs/100'
    description='We are hiring a Junior Data Analyst. This position requires SQL and Python. Apply for this role. You can also join our talent network for other opportunities.'
    c.harness.discovery=SimpleNamespace(job=lambda _:dict(url=url,title='Junior Data Analyst',description=description))
    assert execute(c,'read_job',url=url)['description']==description


def test_specific_vacancy_with_actual_register_network_cta_remains_readable(career):
    c=career;url='https://careers.example.com/jobs/100'
    description='We are hiring a Junior Data Analyst for our New York office. This full-time position requires SQL and Python, 0-2 years of experience. Apply for this role using requisition DA-123. Not ready to apply? Register to join our talent network for other future opportunities.'
    c.harness.discovery=SimpleNamespace(job=lambda _:dict(url=url,title='Junior Data Analyst',description=description))
    assert execute(c,'read_job',url=url)['description']==description


def test_actual_final_cannot_claim_verified_match_without_persisted_recommendation(career):
    c=career;prepare(c)
    with pytest.raises(ValueError,match='recommendation|verified match'):
        c.harness.validate_completion(c.repository.get(c.state['task_id']),FIXTURE['final'])
