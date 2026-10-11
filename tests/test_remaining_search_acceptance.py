from copy import deepcopy

import pytest

from scripts.remaining_search_acceptance import constraints, evaluate_search


def complete():
    jobs = [{'application_id': str(i), 'url': f'https://careers.example.com/jobs/{i}',
        'title': 'Senior Backend Engineer', 'location': 'United States, fully remote',
        'match_score': 60 + i, 'retrieved': True} for i in range(2)]
    return {'status': 'completed', 'calls': 58, 'error': None, 'applications': 0, 'schedules': 0,
        'verified_jobs': jobs, 'recommendations': deepcopy(jobs),
        'final': '\n'.join(f"{j['url']}\nScore: {j['match_score']}" for j in jobs),
        'usage': {'usage_complete': True, 'pending': 0, 'unknown_usage_calls': 0,
            'input_tokens': 1_000_000, 'groups': [{'purpose': 'agent', 'input_tokens': 900_000}]}}


def test_goal_requires_two_real_scored_recommendations_with_original_cost_limits():
    assert evaluate_search(complete(), 'backend')['status'] == 'passed'


@pytest.mark.parametrize('change,expected', [
    (lambda s: s['verified_jobs'][1].update(match_score=None), 'fewer_than_two_verified_scored_qualifying_recommendations'),
    (lambda s: s['verified_jobs'][1].update(location='PK, remote'), 'fewer_than_two_verified_scored_qualifying_recommendations'),
    (lambda s: s['verified_jobs'][1].update(title='Staff Backend Engineer'), 'fewer_than_two_verified_scored_qualifying_recommendations'),
    (lambda s: s['verified_jobs'][1].update(title='Senior Python/DevOps Engineer'), 'fewer_than_two_verified_scored_qualifying_recommendations'),
    (lambda s: s['verified_jobs'][1].update(retrieved=False), 'fewer_than_two_verified_scored_qualifying_recommendations'),
    (lambda s: s['verified_jobs'][1].update(disqualified=True), 'fewer_than_two_verified_scored_qualifying_recommendations'),
    (lambda s: s.update(recommendations=[]), 'fewer_than_two_verified_scored_qualifying_recommendations'),
    (lambda s: s.update(final=s['final'].replace('Score: 61', 'not scored')), 'fewer_than_two_verified_scored_qualifying_recommendations'),
    (lambda s: s['usage'].update(input_tokens=1_000_001), 'total_input_budget'),
    (lambda s: s['usage']['groups'][0].update(input_tokens=1_000_001), 'main_input_budget'),
    (lambda s: s['usage'].update(usage_complete=False,unknown_usage_calls=1), 'incomplete_usage'),
    (lambda s: s.update(applications=1), 'unexpected_application'),
    (lambda s: s.update(schedules=1), 'unexpected_schedule'),
])
def test_completed_partial_or_over_budget_is_not_a_pass(change,expected):
    summary=complete()
    change(summary)
    result=evaluate_search(summary,'backend')
    assert result['status']=='failed'
    assert expected in result['failures']


@pytest.mark.parametrize('applicant,title,location,description',[
    ('analyst','Data Analyst','New York NY','Lead analytics strategy with 8 years experience; mentor junior data analysts'),
    ('designer','UX Designer','Austin TX','Own design strategy; mentor junior designers; 8 years experience required'),
    ('analyst','Junior Data Analyst','New York NY','Minimum 8 years experience required'),
])
def test_junior_colleagues_do_not_establish_the_openings_level(applicant,title,location,description):
    assert not constraints(applicant,dict(title=title,location=location,description=description))['seniority']


def test_an_explicit_entry_level_opening_can_establish_level_without_title_suffix():
    assert constraints('analyst',dict(title='Data Analyst',location='New York NY',
        description='This position is entry-level. Mentor junior volunteers.'))['seniority']


@pytest.mark.parametrize('template', [
    '{score}/100 — Senior Backend Engineer\n{url}',
    '{url}\nScore: {score}',
    '1. **{score}/100** — [Senior Backend Engineer]({url})',
    '- [Senior Backend Engineer]({url}) — **Fit: {score}/100**',
    '- **Score: {score}**\n  Senior Backend Engineer\n  {url}',
    '1. **Senior Backend Engineer**\n   - URL: {url}\n   - Score vs saved resume: **{score}** - limited fit',
    '| Score | Job | Location |\n| {score} | [Senior Backend Engineer]({url}) | United States, remote |',
    '| [Senior Backend Engineer]({url}) | {score}/100 |',
])
def test_reply_scores_belong_to_the_same_entry_in_supported_formats(template):
    summary=complete()
    summary['final']='\n'.join(template.format(score=j['match_score'],url=j['url'])
        .replace('1. ',f'{i+1}. ',1) for i,j in enumerate(summary['verified_jobs']))
    assert evaluate_search(summary,'backend')['status']=='passed'


@pytest.mark.parametrize('final', [
    '60/100 — Senior Backend Engineer\n{a}\nSenior Backend Engineer\n{b}',
    '{a}\nSenior Backend Engineer\n61/100 — {b}',
    '- {a}\n- 60/100 — {b}',
    '| {a} | not scored |\n| {b} | 60 |',
    '1. {a}\n2. Score: 60\n   {b}',
    '60/100 — {a}\n60/100 — {b}',
    '{a}\nScore: 61\n{b}\nScore: 60',
])
def test_adjacent_entries_cannot_lend_their_scores_to_another_job(final):
    summary=complete()
    a,b=[j['url'] for j in summary['verified_jobs']]
    summary['final']=final.format(a=a,b=b)
    result=evaluate_search(summary,'backend')
    assert result['status']=='failed'
    assert result['qualified_count']<2


def test_job_id_or_salary_is_not_a_fit_score():
    summary=complete()
    summary['final']='\n'.join(f"{j['url']}\nSalary: {j['match_score']},000; listing 60 days old."
        for j in summary['verified_jobs'])
    assert evaluate_search(summary,'backend')['qualified_count']==0


@pytest.mark.parametrize('description', [
    'Minimum 10 years of experience', 'At least 12 years experience',
    'Requires 20+ years experience', 'Must have 10 years of experience',
    '10 years of experience required', 'Minimum 4–6 years experience',
])
def test_numeric_minimum_years_override_a_junior_title(description):
    assert not constraints('analyst',dict(title='Junior Data Analyst',location='New York NY',
        description=description))['seniority']


@pytest.mark.parametrize('description',['Minimum 0 years of experience','At least 1 year experience',
    'Requires 2 years experience','3 years of experience required'])
def test_genuine_junior_minimum_years_remain_eligible(description):
    assert constraints('analyst',dict(title='Junior Data Analyst',location='New York NY',
        description=description))['seniority']


@pytest.mark.parametrize('final', [
    '- {a}\n- 60/100 — {b}', '| Job | Fit |\n| {a} | not scored |\n| {b} | 60 |',
    '1. {a}\n2. Score: 60\n   {b}', '{a}\n60/100 — {b}',
])
def test_missing_score_does_not_borrow_equal_score_from_adjacent_job(final):
    summary=complete()
    summary['verified_jobs'][1]['match_score']=summary['recommendations'][1]['match_score']=60
    summary['final']=final.format(a=summary['verified_jobs'][0]['url'],b=summary['verified_jobs'][1]['url'])
    result=evaluate_search(summary,'backend')
    assert not result['jobs'][0]['checks']['reply_score']
    assert result['jobs'][1]['checks']['reply_score']
    assert result['qualified_count']==1 and result['status']=='failed'


@pytest.mark.parametrize('heading',['Salary (thousands USD)','Job ID','Age',''])
def test_unlabelled_table_numbers_do_not_establish_fit_scores(heading):
    summary=complete()
    summary['final']=(f'| Job | {heading} |\n| --- | --- |\n' if heading else '')+'\n'.join(
        f"| {j['url']} | {j['match_score']} |" for j in summary['verified_jobs'])
    result=evaluate_search(summary,'backend')
    assert result['qualified_count']==0 and result['status']=='failed'


@pytest.mark.parametrize('heading',['Score','Fit','Fit score','Match score','评分','匹配度','Score (0–100)'])
def test_bare_numbers_in_explicit_scoring_columns_are_valid(heading):
    summary=complete()
    summary['final']=f'| Job | {heading} |\n| --- | --- |\n'+'\n'.join(
        f"| {j['url']} | {j['match_score']} |" for j in summary['verified_jobs'])
    assert evaluate_search(summary,'backend')['status']=='passed'


def test_new_salary_table_cannot_inherit_a_previous_score_column():
    summary=complete()
    a,b=[j['url'] for j in summary['verified_jobs']]
    summary['final']=f'| Job | Score |\n| {a} | 60 |\n\n| Job | Salary |\n| {b} | 61 |'
    result=evaluate_search(summary,'backend')
    assert result['qualified_count']==1 and not result['jobs'][1]['checks']['reply_score']


def runtime_analyst():
    import json
    from pathlib import Path
    return json.loads((Path(__file__).parent/'fixtures/remaining_runtime_analyst.json').read_text(encoding='utf-8'))


def test_actual_goodapple_bounded_low_experience_is_opening_level_evidence():
    job=runtime_analyst()['verified_jobs'][0]
    assert '0-2 years of marketing or analytics experience' in job['description']
    assert constraints('analyst',job)['seniority']


@pytest.mark.parametrize('description',[
    '0-2 years of marketing or analytics experience',
    'Requires 1–3 years of data analytics experience.',
])
def test_bounded_low_experience_establishes_level_without_junior_title(description):
    assert constraints('analyst',dict(title='Data Analyst',location='New York NY',description=description))['seniority']


@pytest.mark.parametrize('description',[
    'Mentor junior data analysts with 0-2 years of marketing or analytics experience.',
    'Our junior colleagues have 0-2 years of marketing or analytics experience.',
    '0-2 years of marketing or analytics experience\nMinimum 4 years of experience',
    '0-2 years of marketing or analytics experience\nAt least 12 years experience',
    'A minimum of 1 year data management experience is preferred.',
])
def test_low_years_do_not_override_senior_minimum_or_describe_colleagues(description):
    assert not constraints('analyst',dict(title='Associate Data Analyst',location='New York NY',description=description))['seniority']


def test_actual_title_blocks_with_peer_bullets_associate_their_own_scores():
    from scripts.remaining_search_acceptance import reply_job_scores
    summary=runtime_analyst()
    scores=reply_job_scores(summary['final'])
    for job in summary['verified_jobs']:
        assert scores.get(job['url'])==[job['match_score']]


@pytest.mark.parametrize('mutation',['missing','swapped','salary'])
def test_actual_title_blocks_cannot_borrow_or_invent_scores(mutation):
    from scripts.remaining_search_acceptance import reply_job_scores
    summary=runtime_analyst()
    final=summary['final']
    if mutation=='missing': final=final.replace('- Score: 43.45 / completed','- Analysis pending')
    if mutation=='salary': final=final.replace('- Score:', '- Salary (thousands USD):')
    if mutation=='swapped': final=summary['final'].replace('Score: 43.45','Score: TEMP').replace('Score: 47.05','Score: 43.45').replace('Score: TEMP','Score: 47.05')
    scores=reply_job_scores(final)
    a,b=summary['verified_jobs']
    assert a['match_score'] not in scores.get(a['url'],[])
    if mutation=='missing': assert scores.get(b['url'])==[b['match_score']]
    else: assert b['match_score'] not in scores.get(b['url'],[])


def test_actual_analyst_missing_recommend_job_stays_failed_after_parser_fixes():
    summary=runtime_analyst()
    assert summary['recommendations']==[]
    result=evaluate_search(summary,'analyst')
    assert result['status']=='failed' and result['qualified_count']==0
    assert all(not job['checks']['recommended'] for job in result['jobs'])


@pytest.mark.parametrize('location,expected',[
    ('San Francisco, CA 94104; Remote',True),('San Francisco, CA 94104',False),
    ('Remote; CA',False),('Remote; Toronto, ON',False),('Remote; Lahore, PK 54000',False),
])
def test_remote_and_us_evidence_belong_to_the_saved_target_location(location,expected):
    assert constraints('backend',dict(title='Senior Backend Engineer',location=location,
        description='An unrelated office in the United States. Remote jobs elsewhere.'))['location']==expected


def test_actual_score_vs_saved_resume_still_fails_with_only_one_recommendation():
    import json
    from pathlib import Path
    summary=json.loads((Path(__file__).parent/'fixtures/remaining_outcome_analyst.json').read_text(encoding='utf-8'))
    result=evaluate_search(summary,'analyst')
    assert result['jobs'][0]['checks']['reply_score']
    assert result['qualified_count']==1 and result['status']=='failed'
    assert 'fewer_than_two_verified_scored_qualifying_recommendations' in result['failures']


@pytest.mark.parametrize('label,value',[('Salary vs saved resume',60),('Score vs saved resume',61)])
def test_qualified_score_label_does_not_accept_salary_or_mismatched_value(label,value):
    summary=complete();a,b=summary['verified_jobs']
    summary['final']=f"1. **First role**\n- URL: {a['url']}\n- {label}: **{value}**\n2. **Second role**\n- URL: {b['url']}\n- Score: 61"
    result=evaluate_search(summary,'backend')
    assert not result['jobs'][0]['checks']['reply_score']
    assert result['jobs'][1]['checks']['reply_score']
    assert result['status']=='failed'
