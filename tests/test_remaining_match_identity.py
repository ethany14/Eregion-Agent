"""Offline assessment identity isolation through production normalization."""
import pytest

from eregion.domain.domain import normalize_job_analysis,normalize_skill_match
from eregion.domain.job_extraction import JobExtraction
from eregion.domain.schemas import ResumeAnalysis,ResumeEvidence,SkillAssessment,SkillEvidence


def inputs(duration=False):
    texts=['Requires two years of Python experience.','Requires five years of Python experience.'] if duration else [
        'Python API development','Python deployment automation']
    statements=[{'source_text':s,'requirements':[{'canonical_name':'python','display_name':'Python',
        'atomic_text':'Python experience' if duration else s,'category':'experience' if duration else 'skill',
        'verification_mode':'years_experience' if duration else 'resume_evidence','minimum_years':(2 if i==0 else 5) if duration else None,
        'level':'required'}]} for i,s in enumerate(texts)]
    job=normalize_job_analysis(JobExtraction(title=None,summary='',statements=statements,responsibilities=[]).expand(),' '.join(texts))
    quote='Built Python APIs for two years.'
    resume=ResumeAnalysis(summary='',skills=[],education=[],evidence=[ResumeEvidence(evidence_id='e',source_section='Experience',exact_text=quote)])
    return job,resume,quote


def assessment(job,quote,ids):
    return SkillAssessment(matches=[SkillEvidence(requirement_id=i or 'temporary',job_skill='python',
        requirement_level='required',match_status='matched',resume_evidence=[quote],confidence=1
        ).model_copy(update={'requirement_id':i}) for i in ids],explanation='',recommendations=[])


@pytest.mark.parametrize('duration',[False,True])
def test_known_id_cannot_be_borrowed_by_another_predicate(duration):
    job,resume,quote=inputs(duration)
    result=normalize_skill_match(resume,job,assessment(job,quote,[job.requirements[0].requirement_id]))
    assert result.matches[0].match_status=='matched'
    assert result.matches[1].match_status=='unknown' and not result.matches[1].resume_evidence
    assert result.overall_score is None


@pytest.mark.parametrize('ids',['wrong','missing','duplicate'])
def test_wrong_missing_and_duplicate_ids_do_not_gain_other_predicate_evidence(ids):
    job,resume,quote=inputs()
    values={'wrong':['unknown-REQ'],'missing':[None],'duplicate':[job.requirements[0].requirement_id]*2}[ids]
    if ids=='duplicate':
        with pytest.raises(ValueError,match='duplicate'):normalize_skill_match(resume,job,assessment(job,quote,values))
    else:
        result=normalize_skill_match(resume,job,assessment(job,quote,values))
        assert all(m.match_status=='unknown' and not m.resume_evidence for m in result.matches)


def test_internal_legacy_no_id_requires_unique_one_to_one_name():
    job,resume,quote=inputs();single=job.model_copy(update={'requirements':job.requirements[:1]})
    assert normalize_skill_match(resume,single,assessment(single,quote,[None])).matches[0].match_status=='matched'
    result=normalize_skill_match(resume,single,assessment(single,quote,[None,None]))
    assert result.matches[0].match_status=='unknown'
    # Public wire schema still requires an ID; no new schema loophole.
    with pytest.raises(ValueError):SkillEvidence.model_validate({'job_skill':'python','requirement_level':'required',
        'match_status':'matched','resume_evidence':[quote],'confidence':1})


@pytest.mark.parametrize('chunked',[False,True])
def test_production_main_and_chunked_matching_refuse_incomplete_identity_coverage(chunked):
    from eregion.domain.workflow.handlers import JobAgentStepHandler
    from eregion.domain.workflow.state import AgentState,Step
    job,resume,quote=inputs()
    class OfflineAnalyzer:
        chunked_matching=chunked
        def __call__(self,*_):return assessment(job,quote,[job.requirements[0].requirement_id])
    handler=JobAgentStepHandler(analyzer=OfflineAnalyzer())
    state=AgentState(run_id='offline-identity',resume_text=quote,job_description=' '.join(r.source_text for r in job.requirements),
        resume_analysis=resume,job_analysis=job)
    if chunked:
        with pytest.raises(ValueError,match='incomplete'):handler.execute(Step.MATCH_SKILLS,state)
    else:
        result=handler.execute(Step.MATCH_SKILLS,state).updates['skill_match']
        assert result.matches[1].match_status=='unknown' and not result.matches[1].resume_evidence
