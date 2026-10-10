"""Fit-analysis integration boundary for saved Job Workspace applications."""

from __future__ import annotations

import logging
import hashlib
import json

from agent_runtime.workspace.repository import JobWorkspaceRepository
from agent_runtime.workspace.types import ApplicationStatus
from agent_runtime.evidence.repository import CareerEvidenceRepository
from agent_runtime.evidence.types import EvidenceLinkType
from api.services.fit_analysis_service import FitAnalysisService


logger = logging.getLogger(__name__)


class WorkspaceAnalysisService:
    """Persist analysis artifacts without running resume generation or review."""

    def __init__(
        self,
        workspace: JobWorkspaceRepository,
        fit_service: FitAnalysisService | None = None,
        evidence: CareerEvidenceRepository | None = None,
    ) -> None:
        self._workspace = workspace
        self._fit_service = fit_service or FitAnalysisService()
        self._evidence = evidence

    def cache_signature(self):
        signature = getattr(self._fit_service,'cache_signature',None)
        return signature() if callable(signature) else 'custom-fit-service'

    async def analyze(
        self,
        application_id: str,
        *,
        snapshot_id: str,
        resume_text: str,
        expected_version: int,
        resume_id: str | None = None,
    ):
        current = self._workspace.require_snapshot_for_application(
            application_id, snapshot_id
        )
        if current.version != expected_version:
            from agent_runtime.workspace.errors import StaleApplicationError

            raise StaleApplicationError("The application version is stale.")

        # The persisted result belongs to exact inputs and model/prompt/schema
        # configuration, so a new chat or server process need not score it again.
        cache_key = (hashlib.sha256(json.dumps([snapshot_id, resume_text,
            self.cache_signature()], ensure_ascii=False).encode()).hexdigest()
            if callable(getattr(self._fit_service, 'cache_signature', None)) else None)
        cache_lookup = getattr(self._workspace, 'cached_fit_analysis', None)
        cached = cache_lookup(application_id, cache_key) if cache_key and callable(cache_lookup) else None
        if cached and current.status not in {ApplicationStatus.SAVED, ApplicationStatus.ANALYZING, ApplicationStatus.ANALYSIS_FAILED}:
            logger.info('Reused saved fit analysis: application=%s model_calls=0', application_id)
            return current, None, 'completed', cached

        analyzing = self._workspace.transition_status(
            application_id,
            target_status=ApplicationStatus.ANALYZING,
            expected_version=expected_version,
        )
        try:
            snapshot = self._workspace.current_snapshot(application_id)
            result = await self._fit_service.analyze(
                resume_text=resume_text,
                job_description=snapshot.cleaned_job_description,
            )
            if self._evidence is not None:
                imported = self._evidence.import_resume_evidence(
                    result.resume_analysis,
                    resume_text,
                    created_by="fit_analysis",
                )
                linked = {
                    item.evidence_id
                    for item in self._evidence.list_for_application(application_id)
                }
                for item in imported:
                    if item.evidence_id in linked:
                        continue
                    self._evidence.link_to_application(
                        item.evidence_id,
                        application_id,
                        expected_version=item.version,
                        link_type=EvidenceLinkType.RELATED,
                        created_by="fit_analysis",
                    )
            state, artifacts = self._workspace.project_fit_analysis(
                application_id,
                snapshot_id=snapshot_id,
                analysis_id=result.analysis_id,
                resume=result.resume_analysis,
                job=result.job_analysis,
                match=result.skill_match,
                expected_version=analyzing.version,
                resume_text=resume_text, resume_id=resume_id,
                analysis_cache_key=cache_key,
                analysis_timing={"model_calls":result.model_calls, "latency_seconds":result.latency_seconds,
                    "stage_seconds":result.stage_seconds, "cache_hits":result.cache_hits,
                    "main_model_calls":result.main_model_calls, "fast_model_calls":result.fast_model_calls,
                    "decision_routing":result.decision_routing},
            )
            has_gaps = bool(
                result.skill_match.missing_required_requirements
                or result.skill_match.missing_preferred_requirements
                or result.skill_match.confirmation_requirements
            )
            ready = self._workspace.transition_status(
                application_id,
                target_status=(
                    ApplicationStatus.NEEDS_EVIDENCE
                    if has_gaps
                    else ApplicationStatus.MATERIALS_READY
                ),
                expected_version=state.version,
            )
            # Analysis-only executions are not persisted Run workflows.
            return ready, None, "completed", artifacts
        except Exception as exc:
            logger.exception("Workspace fit analysis failed: %s", type(exc).__name__)
            latest = self._workspace.get_application(application_id)
            if latest.status == ApplicationStatus.ANALYZING and latest.version == analyzing.version:
                self._workspace.transition_status(
                    application_id,
                    target_status=ApplicationStatus.ANALYSIS_FAILED,
                    expected_version=latest.version,
                    error_code="fit_analysis_failed",
                )
            raise
