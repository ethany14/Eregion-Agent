"""PDF resume storage and a small analysis surface shared by both frontends."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from threading import Lock
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from agent_runtime.resumes.repository import (
    ResumeConflictError,
    ResumeDocument,
    ResumeDocumentRepository,
    ResumeNotFoundError,
)
from agent_runtime.resumes.pdf_text import MAX_RESUME_TEXT, extract_pdf_text  # noqa: F401 (re-export)
from api.resume_schemas import (
    PublicResume,
    AnalyzeSavedApplicationRequest,
    QuickAnalysisRequest,
    QuickAnalysisResponse,
    ResumeListResponse,
)
from api.session_dependencies import SessionRuntime, get_session_runtime
from api.services.workspace_service import WorkspaceAnalysisService
from api.services.fit_analysis_service import FitAnalysisService
from api.workspace_schemas import AnalyzeApplicationResponse, PublicApplication, PublicApplicationArtifact

router = APIRouter(prefix="/api", tags=["resumes"])
MAX_PDF_BYTES = 10 * 1024 * 1024
_fit_service_lock = Lock()


def get_fit_analysis_service(request: Request) -> FitAnalysisService:
    service = getattr(request.app.state, "fit_analysis_service", None)
    if service is None:
        with _fit_service_lock:
            service = getattr(request.app.state, "fit_analysis_service", None)
            if service is None:
                from agent_runtime.analysis_cache import AnalysisCache
                runtime = getattr(request.app.state, 'session_runtime', None)
                from agent_runtime.memory.policy import LocalOwnerResolver
                cache = AnalysisCache(runtime.database.session_factory,
                    owner=(getattr(runtime, 'owner_resolver', None) or LocalOwnerResolver()).resolve().owner_id
                ) if getattr(runtime, 'database', None) else None
                service = FitAnalysisService(analysis_cache=cache)
                request.app.state.fit_analysis_service = service
    return service


def _resources(runtime: SessionRuntime) -> tuple[ResumeDocumentRepository, str]:
    if runtime.resumes is None or runtime.owner_resolver is None:
        raise RuntimeError("The resume runtime is not initialized.")
    return runtime.resumes, runtime.owner_resolver.resolve().owner_id


def _public(value: ResumeDocument) -> PublicResume:
    return PublicResume.model_validate({
        "resume_id": value.resume_id,
        "filename": value.filename,
        "display_name": value.display_name,
        "page_count": value.page_count,
        "is_default": value.is_default,
        "created_at": value.created_at,
        "updated_at": value.updated_at,
    })


def _analysis_resume(runtime: SessionRuntime, resume_id: str | None) -> ResumeDocument:
    repository, owner_id = _resources(runtime)
    if resume_id:
        return repository.require(owner_id, resume_id)
    # The chat is now the resume upload surface. Reuse its original document for
    # extension analysis too, including resumes saved before the UI migration.
    if getattr(runtime, "database", None) is not None:
        import base64
        from agent_runtime.auto_apply.repository import ApplyRepository

        saved = ApplyRepository(runtime.database.session_factory).saved_candidate()
        if saved.get("resume_base64"):
            content = base64.b64decode(saved["resume_base64"])
            digest = sha256(content).hexdigest()
            existing = next((item for item in repository.list(owner_id)
                             if item.content_sha256 == digest), None)
            if existing:
                return existing if existing.is_default else repository.set_default(owner_id, existing.resume_id)
            try:
                text, page_count = extract_pdf_text(content)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            filename = saved.get("resume_name") or "resume.pdf"
            try:
                return repository.create(owner_id=owner_id, filename=filename,
                    display_name=Path(filename).stem, content_sha256=digest,
                    extracted_text=text, page_count=page_count, make_default=True)
            except ResumeConflictError:
                # A concurrent analysis may have indexed the same original PDF.
                for item in repository.list(owner_id):
                    if item.content_sha256 == digest:return item
                raise
    return repository.default(owner_id)


@router.post("/resumes", response_model=PublicResume, status_code=status.HTTP_201_CREATED)
async def upload_resume(
    request: Request,
    filename: str = Header(alias="X-Resume-Filename"),
    display_name: str | None = Header(default=None, alias="X-Resume-Name"),
    runtime: SessionRuntime = Depends(get_session_runtime),
) -> PublicResume:
    if request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/pdf":
        raise HTTPException(status_code=415, detail="Upload a PDF file.")
    content = await request.body()
    if not content or len(content) > MAX_PDF_BYTES:
        raise HTTPException(status_code=422, detail="PDF size must be between 1 byte and 10 MB.")
    safe_filename = Path(unquote(filename)).name.strip()
    if not safe_filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=422, detail="The resume filename must end in .pdf.")
    try:
        text, page_count = extract_pdf_text(content)
        repository, owner_id = _resources(runtime)
        value = repository.create(
            owner_id=owner_id,
            filename=safe_filename,
            display_name=(unquote(display_name).strip() if display_name else Path(safe_filename).stem),
            content_sha256=sha256(content).hexdigest(),
            extracted_text=text,
            page_count=page_count,
            make_default=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ResumeConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    from agent_runtime.analysis_cache import warm_resume
    if getattr(runtime, 'database', None):
        warm_resume(runtime.database.session_factory, text, owner=owner_id)
    return _public(value)


@router.get("/resumes", response_model=ResumeListResponse)
def list_resumes(runtime: SessionRuntime = Depends(get_session_runtime)) -> ResumeListResponse:
    repository, owner_id = _resources(runtime)
    return ResumeListResponse(resumes=[_public(item) for item in repository.list(owner_id)])


@router.post("/resumes/{resume_id}/default", response_model=PublicResume)
def set_default_resume(
    resume_id: str,
    runtime: SessionRuntime = Depends(get_session_runtime),
) -> PublicResume:
    repository, owner_id = _resources(runtime)
    try:
        return _public(repository.set_default(owner_id, resume_id))
    except ResumeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/resumes/{resume_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_resume(resume_id: str, runtime: SessionRuntime = Depends(get_session_runtime)) -> None:
    repository, owner_id = _resources(runtime)
    try:
        repository.delete(owner_id, resume_id)
    except ResumeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _requirement_label(item: dict) -> str:
    return str(item.get("display_name") or item.get("canonical_name") or item.get("job_skill") or "requirement")


@router.post("/quick-analysis", response_model=QuickAnalysisResponse)
async def quick_analysis(
    payload: QuickAnalysisRequest,
    runtime: SessionRuntime = Depends(get_session_runtime),
    fit_service: FitAnalysisService = Depends(get_fit_analysis_service),
) -> QuickAnalysisResponse:
    try:
        resume = _analysis_resume(runtime, payload.resume_id)
    except ResumeNotFoundError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    try:
        result = await fit_service.analyze(
            resume_text=resume.extracted_text,
            job_description=payload.job_description,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="The agent could not analyze this job.",
        ) from exc
    skill_match = result.skill_match.model_dump(mode="json")
    if not skill_match:
        raise HTTPException(status_code=502, detail="The agent could not analyze this job.")
    matches = skill_match.get("matches") or []
    grouped = {name: [item for item in matches if item.get("match_status") == name]
               for name in ("matched", "partial", "missing", "needs_confirmation", "unknown", "confirmed_condition")}
    missing = [*(skill_match.get("missing_required_requirements") or []),
               *(skill_match.get("missing_preferred_requirements") or [])]
    confirmations = skill_match.get("confirmation_requirements") or []
    suggestions = [
        f"Add concrete resume evidence for {_requirement_label(item)} if you have it; otherwise leave it as a gap."
        for item in missing[:3]
    ]
    suggestions.extend(
        f"Strengthen the evidence for {_requirement_label(item)} with a specific example or outcome."
        for item in grouped["partial"][:2]
    )
    suggestions.extend(
        f"Confirm {_requirement_label(item)} before applying."
        for item in confirmations[:2]
    )
    suggestions.extend(
        f"Review the unresolved evidence for {_requirement_label(item)}; it is not a confirmed match or gap."
        for item in grouped['unknown'][:2]
    )
    if not suggestions:
        suggestions.append("Keep the strongest matched requirements prominent and preserve factual evidence links.")
    return QuickAnalysisResponse(
        analysis_id=result.analysis_id, status=result.status, resume_id=resume.resume_id,
        model_calls=result.model_calls, latency_seconds=result.latency_seconds,
        main_model_calls=result.main_model_calls, fast_model_calls=result.fast_model_calls,
        match_score=skill_match.get("overall_score"), score_range=skill_match.get('score_range'),
        unknown_requirements=grouped['unknown'],confirmed_conditions=grouped['confirmed_condition'],
        matched_requirements=grouped["matched"], partial_requirements=grouped["partial"],
        missing_requirements=missing, confirmation_requirements=confirmations,
        suggestions=suggestions,
    )


@router.post(
    "/applications/{application_id}/analyze-with-resume",
    response_model=AnalyzeApplicationResponse,
)
async def analyze_saved_application(
    application_id: str,
    payload: AnalyzeSavedApplicationRequest,
    runtime: SessionRuntime = Depends(get_session_runtime),
    fit_service: FitAnalysisService = Depends(get_fit_analysis_service),
) -> AnalyzeApplicationResponse:
    if runtime.workspace is None:
        raise RuntimeError("The Job Workspace runtime is not initialized.")
    try:
        resume = _analysis_resume(runtime, payload.resume_id)
    except ResumeNotFoundError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    application = runtime.workspace.get_application(application_id)
    current, run_id, run_status, artifacts = await WorkspaceAnalysisService(
        runtime.workspace, fit_service, runtime.evidence
    ).analyze(
        application_id,
        snapshot_id=application.current_snapshot_id,
        resume_text=resume.extracted_text,
        expected_version=payload.expected_version,
        resume_id=resume.resume_id,
    )
    return AnalyzeApplicationResponse(
        application=PublicApplication.model_validate(current.model_dump()),
        run_id=run_id,
        run_status=run_status,
        artifacts=[PublicApplicationArtifact.model_validate(
            item.model_dump(exclude={"application_id"})
        ) for item in artifacts],
    )
