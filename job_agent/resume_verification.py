"""Source ownership, citations and writing structure checks requiring no model."""
from job_agent.quality import quality_result, validate_resume_structure
from job_agent.schemas import UnsupportedClaim, VerificationResult


def verify_resume_structure(state):
    if state.tailored_resume is None or state.resume_analysis is None:
        raise ValueError('A tailored resume and resume analysis are required.')
    known_ids = {item.evidence_id for item in state.resume_analysis.evidence}
    unsupported, feedback = [], []
    for claim in state.tailored_resume.claims():
        unknown = [identifier for identifier in claim.evidence_ids if identifier not in known_ids]
        if not claim.evidence_ids or unknown:
            reason = (f"References unknown evidence IDs: {', '.join(unknown)}." if unknown
                      else 'The claim does not reference any resume evidence.')
            unsupported.append(UnsupportedClaim(claim=claim.text, reason=reason))
            feedback.append(f"Remove or rewrite '{claim.text}' using valid evidence IDs.")
    quality = quality_result(validate_resume_structure(
        state.tailored_resume, state.resume_analysis.source_entries,
        known_evidence_ids=known_ids, allow_legacy_source_ids=False,
        source_resume_text=state.resume_text))
    return VerificationResult(passed=not unsupported and quality.passed,
        unsupported_claims=unsupported, quality=quality,
        revision_feedback=list(dict.fromkeys([*feedback, *quality.revision_feedback])))
