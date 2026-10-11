"""E1: production result projection -> final reply, with literal-data exceptions."""
import json
from uuid import uuid4

import pytest

from agent_runtime.career.harness import CareerHarness
from agent_runtime.workspace.types import ArtifactType
from job_agent.schemas import JobAnalysis,ResumeAnalysis,SkillMatch,MissingRequirement
from test_career_flow import career,execute


@pytest.mark.parametrize('text',[
    'Missing autonomous_driving_software_development.',
    'The result is needs_review.',
    'The result is `needs_review`.',
    'The current step is awaiting_review.',
])
def test_final_reply_rejects_internal_skill_and_status_codes_without_search(text):
    with pytest.raises(ValueError,match='ordinary language'):
        CareerHarness.validate_completion(None,{'goal':'Explain my fit.','messages':[]},text)


@pytest.mark.parametrize('goal,text',[
    ('Show the internal codes and IDs.','autonomous_driving_software_development; needs_review'),
    ('请列出内部代码和ID。','needs_review autonomous_driving_software_development'),
    ('Explain my fit.','See https://example.com/autonomous_driving_software_development?state=needs_review'),
    ('Explain my fit.',r'See C:\reports\autonomous_driving_software_development.json'),
    ('Explain my fit.','See /tmp/autonomous_driving_software_development/result.json'),
    ('Explain my fit.','See autonomous_driving_software_development.md'),
    ('Explain my fit.','```python\nresult = needs_review\nautonomous_driving_software_development()\n```'),
    ('Explain my fit.','Use `autonomous_driving_software_development()` in this code example.'),
    ('Explain this Python variable in code.','The variable `python_data_frame` contains the rows.'),
    ('My original tag is autonomous_driving_software_development.','You supplied autonomous_driving_software_development.'),
])
def test_final_reply_preserves_explicit_diagnostics_urls_paths_code_and_user_original(goal,text):
    CareerHarness.validate_completion(None,{'goal':goal,'messages':[{'role':'user','text':goal}]},text)


def test_do_not_show_ids_does_not_disable_language_guard():
    with pytest.raises(ValueError):
        CareerHarness.validate_completion(None,{'goal':'Do not show internal codes or IDs.','messages':[]},'Status: needs_review.')


def test_actual_saved_analysis_and_inspect_tool_use_display_names_and_final_guard(career,tmp_path):
    c=career
    identifier=execute(c,'import_job',url='https://jobs.lever.co/example/language')['application_id']
    execute(c,'score_job',application_id=identifier)
    workspace=c.runtime.workspace
    artifacts={a.artifact_type:a for a in workspace.list_artifacts(identifier)}
    job=JobAnalysis.model_validate(artifacts[ArtifactType.JOB_ANALYSIS].content)
    report=SkillMatch.model_validate(artifacts[ArtifactType.MATCH_REPORT].content)
    code='autonomous_driving_software_development';label='Autonomous driving software development'
    req=job.requirements[0].model_copy(update={'canonical_name':code,'display_name':label})
    job=job.model_copy(update={'requirements':[req]})
    row=report.matches[0].model_copy(update={'requirement_id':req.requirement_id,'job_skill':code,'match_status':'unknown','resume_evidence':[]})
    report=report.model_copy(update={'matches':[row],'analysis_status':'needs_review',
        'missing_required_requirements':[MissingRequirement(canonical_name=code,original_text=label)]})
    # Revalidate the synthetic report before the real repository projection.
    report=SkillMatch.model_validate(report.model_dump(mode='json'))
    app=workspace.get_application(identifier)
    workspace.project_fit_analysis(identifier,snapshot_id=app.current_snapshot_id,analysis_id=str(uuid4()),
        resume=ResumeAnalysis.model_validate(artifacts[ArtifactType.RESUME_ANALYSIS].content),job=job,match=report,
        expected_version=app.version,resume_text=c.harness.candidate()[1])
    result=execute(c,'inspect_job',application_id=identifier)
    assert result['analysis_status']=='needs_review'  # exact machine/source contract retained
    assert result['analysis_status_label']=='Needs review'
    assert result['match_overview']['unknown'][0]['requirement']==label
    assert result['match_overview']['unknown'][0]['display_name']==label
    assert result['gaps']==[label]
    assert result['match_report']['matches'][0]['job_skill']==code  # immutable original remains exact
    state={**c.repository.get(c.state['task_id']),'goal':'Explain this saved result.','messages':[]}
    with pytest.raises(ValueError):c.harness.validate_completion(state,f'{code}: needs_review')
    final=f'{label}: unresolved evidence. This result needs review.'
    c.harness.validate_completion(state,final)
    c.harness.validate_completion({**state,'goal':'Show internal IDs and codes.'},f'{code}: needs_review')
    (tmp_path/'tool-to-final-language.json').write_text(json.dumps({'scope':'Production SQLite projection/inspect_job/completion guard, synthetic scoring',
        'tool_result':result,'accepted_final':final,'rejected_final':f'{code}: needs_review'},indent=2),encoding='utf-8')
