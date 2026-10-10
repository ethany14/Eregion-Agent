"""Compose material validation without two overlapping factual model requests."""
from agent_runtime.multi_agent.model_usage import invoke_model
from .types import ArtifactVerification, ClaimIssue

MATERIAL_VERIFICATION_VERSION = 'all-claims-structure-v2'


def as_artifact_verification(result):
    issues = [ClaimIssue(block_id=f'resume-fact-{i}', unsupported_text=claim.claim,
                        reason=claim.reason, cited_evidence_ids=[],
                        revision_instruction='Remove or correct the unsupported claim.')
              for i, claim in enumerate(result.unsupported_claims)]
    if result.quality:
        issues.extend(ClaimIssue(block_id=f'resume-quality-{i}', unsupported_text='',
                                reason=issue.message, cited_evidence_ids=[],
                                revision_instruction=issue.message)
                      for i, issue in enumerate(result.quality.issues) if issue.severity == 'error')
    if not result.passed and not issues:
        issues.append(ClaimIssue(block_id='resume-verification', unsupported_text='',
            reason='The resume verifier did not approve this draft.', cited_evidence_ids=[],
            revision_instruction='; '.join(result.revision_feedback) or 'Revise the unverified draft.'))
    return ArtifactVerification(passed=result.passed, issues=issues)


def verify_material_resume(state, model, artifact_check):
    # This explicit capability promises deterministic source/structure checks;
    # artifact_check supplies the complete semantic pass over ALL resume claims.
    # Other injected models retain their existing additional verifier contract.
    structure_check = getattr(model, 'verify_resume_structure', None)
    if callable(structure_check):
        # This is local code; reserving a model call here would inflate task
        # budgets even though the provider ledger correctly records no request.
        structure = as_artifact_verification(structure_check(state))
        if not structure.passed:
            return structure
        return artifact_check()
    verdict = artifact_check()
    if not verdict.passed:
        return verdict
    return as_artifact_verification(invoke_model(model.verify_resume, state))
