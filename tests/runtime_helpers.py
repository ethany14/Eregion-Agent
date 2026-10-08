"""Deterministic step handler for custom-loop integration tests; no model calls."""
from custom_agent.state import Step
from custom_agent.steps import StepOutcome
from job_agent.domain import make_evidence_id
from job_agent.schemas import (JobAnalysis, JobRequirement, ResumeAnalysis,
    ResumeEvidence, ScoreBreakdown, SkillEvidence, SkillMatch, SupportedClaim,
    TailoredResume, VerificationResult)

FACT = "Built Python APIs."
FACT_ID = make_evidence_id(FACT)


class CompleteFakeHandler:
    def execute(self, step, state):
        resume = ResumeAnalysis(summary="Developer", skills=["Python"], evidence=[
            ResumeEvidence(evidence_id=FACT_ID, source_section="Experience", exact_text=FACT)], education=[])
        requirement = JobRequirement(requirement_id="REQ-1", canonical_name="python",
            original_text="Python", level="required")
        job = JobAnalysis(title="Backend Engineer", summary="Build APIs",
            requirements=[requirement], responsibilities=[])
        match = SkillMatch(matches=[SkillEvidence(requirement_id="REQ-1",
            job_skill="python", requirement_level="required", match_status="matched",
            resume_evidence=[FACT], confidence=1)], explanation="Supported",
            recommendations=[], missing_required_requirements=[],
            missing_preferred_requirements=[], overall_score=100,
            score_breakdown=ScoreBreakdown(overall_score=100))
        claim = SupportedClaim(text=FACT, evidence_ids=[FACT_ID], source_entry_id="legacy:unattributed")
        updates = {
            Step.VALIDATE_INPUT: {}, Step.ANALYZE_RESUME: {"resume_analysis": resume},
            Step.VALIDATE_EVIDENCE: {}, Step.ANALYZE_JOB: {"job_analysis": job},
            Step.MATCH_SKILLS: {"skill_match": match},
            Step.WRITE_RESUME: {"tailored_resume": TailoredResume(
                professional_summary=[claim], experience_bullets=[claim],
                highlighted_skills=[SupportedClaim(text="Python", evidence_ids=[FACT_ID], source_entry_id="legacy:skills")])},
            Step.VERIFY_RESUME: {"verification": VerificationResult(
                passed=True, unsupported_claims=[], revision_feedback=[]),
                "revision_feedback": []},
            Step.REVISE_RESUME: {"tailored_resume": state.tailored_resume},
        }
        return StepOutcome(updates=updates[step])


def sqlite_url(path): return f"sqlite:///{path.as_posix()}"



class FailingHandler:
    def execute(self, step, state):
        raise RuntimeError("secret provider details and api key")
