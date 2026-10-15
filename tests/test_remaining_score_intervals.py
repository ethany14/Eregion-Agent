"""Bounded uncertainty must survive persistence and the final-result fence."""
import json
from uuid import uuid4

import pytest

from eregion.runtime.career.harness import CareerHarness
from eregion.runtime.workspace.types import ArtifactType
from eregion.domain.schemas import JobAnalysis, ResumeAnalysis, SkillMatch
from test_career_flow import career, execute
from test_remaining_search_completion import GOAL, URL, prepare


def interval_state():
    return {'goal': GOAL, 'scored_job_evidence': {'job': {
        'url': URL, 'match_score': None, 'score_range': [20, 60]}}, 'recommendations': []}


@pytest.mark.parametrize('format',[
    '{url} Score range 20-60/100; unresolved qualifications remain.',
    '**Analyst**\n- URL: {url}\n- Fit interval: 20–60/100\n- Unresolved qualifications remain.',
    '| Job | Score range |\n| --- | --- |\n| {url} | 20–60 |\nUnresolved qualifications remain.',
    '| Job | Fit |\n| --- | --- |\n| {url} | 20 to 60 |\nUnresolved qualifications remain.',
    '20—60/100 — Analyst\n{url}\nUnresolved qualifications remain.',
])
def test_completion_accepts_exact_bounded_uncertainty(format):
    final=format.format(url=URL)+'\nRead and scored, not recommended; unresolved qualifications remain.'
    CareerHarness.validate_completion(None, interval_state(), final)
    from eregion.runtime.career.reply_evidence import reply_job_scores
    assert not reply_job_scores(final).get(URL)  # Neither bound is a point score.


@pytest.mark.parametrize('score',[
    '', 'Score range 20-61/100', 'Score range 60-20/100', 'Score 40/100',
    'Salary range 20-60 thousand USD', 'Age range 20-60',
    'Score range 20-60/100; Score 40/100',
    'Score range 20-60/100; Score range 0-100/100',
    '| Job | Salary |\n| --- | --- |\n| '+URL+' | 20-60 |',
])
def test_completion_rejects_missing_wrong_or_fabricated_interval_evidence(score):
    with pytest.raises(ValueError, match='score|interval'):
        CareerHarness.validate_completion(None, interval_state(), URL+' '+score)


def test_interval_and_point_scores_cannot_be_swapped_between_jobs():
    state=interval_state()
    other='https://careers.example.com/jobs/point'
    state['scored_job_evidence']['other']={'url':other,'match_score':43.48,'score_range':[43.48,43.48]}
    CareerHarness.validate_completion(None,state,
        f'- {URL} Score range 20-60/100; unresolved.\n- {other} Score 43.48/100.')
    for final in [
        f'- {URL} Score 43.48/100\n- {other} Score range 20-60/100',
        f'- {URL}\n- {other} Score range 20-60/100; Score 43.48/100',
        f'- {URL} Score range 20-60/100\n- {other} Score range 20-60/100',
        f'- {URL} Score range 20-60/100\n- {other} Score 43.48/100; Score 99/100',
    ]:
        with pytest.raises(ValueError, match='score|interval'):
            CareerHarness.validate_completion(None,state,final)


def test_different_job_intervals_are_not_interchangeable():
    state=interval_state()
    other='https://careers.example.com/jobs/other-interval'
    state['scored_job_evidence']['other']={'url':other,'match_score':None,'score_range':[30,70]}
    CareerHarness.validate_completion(None,state,f'- {URL} Fit range 20-60\n- {other} Fit range 30-70\nBoth unresolved.')
    with pytest.raises(ValueError,match='interval'):
        CareerHarness.validate_completion(None,state,f'- {URL} Fit range 30-70\n- {other} Fit range 20-60')


@pytest.mark.parametrize('interval',[None,[None,None],[20,101],[60,20],[True,60],[20,60,80]])
def test_completion_does_not_invent_an_interval_for_invalid_saved_evidence(interval):
    state=interval_state();state['scored_job_evidence']['job']['score_range']=interval
    with pytest.raises(ValueError, match='score|interval'):
        CareerHarness.validate_completion(None,state,URL+' Score range 20-60/100; unresolved.')


def test_production_job_summary_and_recommendation_keep_the_persisted_interval(career,tmp_path):
    c=career;prepare(c)
    execute(c,'read_job',url=URL)
    job=execute(c,'import_job',url=URL)
    identifier=job['application_id']
    execute(c,'score_job',application_id=identifier)
    # Publish a real needs-review report through the production repository,
    # without stubbing job_summary or replacing the final validator.
    workspace=c.runtime.workspace
    artifacts={a.artifact_type:a for a in workspace.list_artifacts(identifier)}
    report=SkillMatch.model_validate(artifacts[ArtifactType.MATCH_REPORT].content)
    report=report.model_copy(update={'overall_score':None,'score_range':[20,60],
        'analysis_status':'needs_review','score_breakdown':report.score_breakdown.model_copy(update={'overall_score':None})})
    app=workspace.get_application(identifier)
    workspace.project_fit_analysis(identifier,snapshot_id=app.current_snapshot_id,
        analysis_id=str(uuid4()),resume=ResumeAnalysis.model_validate(artifacts[ArtifactType.RESUME_ANALYSIS].content),
        job=JobAnalysis.model_validate(artifacts[ArtifactType.JOB_ANALYSIS].content),match=report,
        expected_version=app.version,resume_text=c.harness.candidate()[1])
    c.harness.save_scored_evidence(c.state['task_id'],[identifier])
    summary=c.harness.job_summary(identifier)
    assert summary['match_score'] is None and summary['score_range']==[20,60]
    assert summary['match_overview']['score_range']==[20,60]
    assert summary['analysis_status']=='needs_review'
    final=f'Read and scored, not recommended: {URL} Score range 20-60/100; unresolved qualifications remain.'
    c.harness.validate_completion(c.repository.get(c.state['task_id']),final)
    result=execute(c,'recommend_job',application_id=identifier,tier='to_confirm',reason='Potential fit pending review.',
                   evidence=[summary['title']],gaps=[],to_confirm=['Unresolved qualifications in the posting.'],
                   next_steps=['Review the unresolved requirements.'],caveats='Qualifications remain unresolved.')
    saved=result['recommendation']
    assert saved['match_score'] is None and saved['score_range']==[20,60]
    # The interval is explained by the tier contract's score meaning, not appended caveat text.
    assert 'interval' in saved['score_meaning'] and saved['to_confirm']
    c.harness.validate_completion(c.repository.get(c.state['task_id']),
        f'Needs your confirmation (1)\n- {URL} Score range 20-60/100; unresolved qualifications remain to confirm.')
    for score in ['Score 40/100','Score range 20-61/100','Salary: 20-60 thousand USD']:
        with pytest.raises(ValueError,match='score|interval'):
            c.harness.validate_completion(c.repository.get(c.state['task_id']),URL+' '+score)
    (tmp_path/'persisted-interval-evidence.json').write_text(json.dumps({
        'scope':'Synthetic offline providers, production workspace projection/job_summary/recommend_job/completion validation',
        'provider_calls':0,'application_id':identifier,'job_summary':summary,
        'scored_job_evidence':c.repository.get(c.state['task_id'])['scored_job_evidence'],
        'recommendation':saved,'accepted_final_before_recommendation':final,
        'rejected_formats':['fabricated point','wrong interval','salary range']},ensure_ascii=False,indent=2),encoding='utf-8')
