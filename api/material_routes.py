"""Materials library: current document of each type across an application's packs."""
import json

from fastapi import APIRouter, Depends, HTTPException

from agent_runtime.application_pack.errors import PackNotFoundError
from agent_runtime.application_pack.rendering import render_cover_letter
from api.session_dependencies import SessionRuntime, get_session_runtime
from job_agent.rendering import render_tailored_resume_text

router = APIRouter(prefix="/api/materials", tags=["application-pack"])

TITLES = {"tailored_resume": "Tailored resume", "cover_letter": "Cover letter", "application_answer": "Application answer"}
PDF = {"tailored_resume": "resume.pdf", "cover_letter": "cover-letter.pdf"}


def _services(runtime: SessionRuntime):
    if getattr(runtime, "packs", None) is None or getattr(runtime, "pack_workflow", None) is None \
            or getattr(runtime, "workspace", None) is None:
        raise HTTPException(503, "The materials runtime is not ready.")
    return runtime.workspace, runtime.packs, runtime.pack_workflow


def render_text(artifact_type: str, content: dict | None) -> str:
    if not content:
        return ""
    if artifact_type == "tailored_resume":
        return render_tailored_resume_text(content)
    if artifact_type == "cover_letter":
        return render_cover_letter(content)
    answer = content.get("answer") or content.get("text")
    return answer if isinstance(answer, str) else json.dumps(content, indent=2, ensure_ascii=False)


def _all_applications(workspace):
    rows, cursor = [], None
    while True:
        page = workspace.list_applications(limit=101, cursor=cursor)
        rows += page[:100]
        if len(page) <= 100:
            return rows
        cursor = page[99].application_id


@router.get("")
def list_materials(runtime: SessionRuntime = Depends(get_session_runtime)):
    workspace, packs, workflow = _services(runtime)
    materials = []
    for application in _all_applications(workspace):
        from agent_runtime.application_pack.selection import current_materials, latest_materials
        selected = current_materials(workspace, packs, workflow, application.application_id)
        latest_ids = {i.pack_item_id for p, i in latest_materials(workspace, packs, workflow, application.application_id)}
        # Stale documents remain visible for review/history, but cannot be applied.
        if not selected:
            selected = [(workflow.refresh_staleness(p.pack_id), i)
                        for p in packs.list_for_application(application.application_id)[:1]
                        for i in packs.items(p.pack_id)]
        job = workspace.application_job(application.application_id)
        for pack, item in selected:
            verification = item.verification
            materials.append({
                "pack_id": pack.pack_id, "pack_item_id": item.pack_item_id,
                "application_id": application.application_id, "application_status": application.status.value,
                "company": job.company, "title": job.title,
                "artifact_type": item.artifact_type, "label": TITLES.get(item.artifact_type, "Document"),
                "source_question": item.source_question,
                "status": item.status.value, "stale": pack.status.value == "stale",
                "version": item.version, "updated_at": item.updated_at.isoformat(),
                "is_latest_attempt": item.pack_item_id in latest_ids,
                "requires_explicit_selection": item.pack_item_id not in latest_ids,
                "verified": None if verification is None else verification.passed,
                "issues": 0 if verification is None else len(verification.issues),
                "pdf": f"/api/packs/{pack.pack_id}/items/{item.pack_item_id}/{PDF[item.artifact_type]}"
                       if item.artifact_type in PDF and item.artifact_id else None,
            })
    materials.sort(key=lambda m: m["updated_at"], reverse=True)
    return {"materials": materials}


@router.get("/{pack_id}/{item_id}")
def material_detail(pack_id: str, item_id: str, runtime: SessionRuntime = Depends(get_session_runtime)):
    _, packs, _ = _services(runtime)
    try:
        item = packs.item(pack_id, item_id)
        versions = packs.versions(pack_id, item_id)
    except (LookupError, PackNotFoundError) as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"pack_item_id": item.pack_item_id, "artifact_type": item.artifact_type, "current_version": item.version,
            "versions": [{"version": v["version"], "status": v["status"], "created_at": v["created_at"],
                          "text": render_text(item.artifact_type, v["content"])} for v in versions]}
