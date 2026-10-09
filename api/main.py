"""FastAPI application entry point."""

from contextlib import asynccontextmanager
from collections.abc import Callable
from typing import Any

import anyio
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from urllib.parse import urlencode

from api.error_handlers import install_error_handlers
from api.context_routes import router as context_router
from api.evidence_routes import router as evidence_router
from api.interview_routes import router as interview_router
from api.pack_routes import router as pack_router
from api.agent_task_routes import router as agent_task_router
from api.multi_agent_routes import router as multi_agent_router
from api.mock_interview_routes import router as mock_interview_router
from api.routes.runs import router as runs_router
from api.session_dependencies import SessionRuntime, create_session_runtime
from api.session_routes import router as sessions_router
from api.workspace_routes import router as workspace_router
from api.feedback_routes import router as feedback_router
from api.assistant_routes import router as assistant_router
from api.services.run_service import RunService
from api.resume_routes import router as resume_router
from api.auto_apply_routes import router as auto_apply_router
from api.career_routes import router as career_router, groups_router as career_groups_router
from api.material_routes import router as material_router
from api.job_alert_routes import router as job_alert_router


def chat_redirect(request: Request) -> RedirectResponse:
    # Keep saved-job and browser links useful without carrying old view settings.
    query = urlencode({key: request.query_params[key] for key in ("application", "url")
                       if request.query_params.get(key)})
    return RedirectResponse("/apply" + (f"?{query}" if query else ""),
                            headers={"Cache-Control": "no-store"})


class ChatAssets(StaticFiles):
    async def get_response(self, path, scope):
        # HTML is served only by the chat route, including on case-insensitive Windows.
        if Path(path).suffix.lower() in {".html", ".htm"}:
            return chat_redirect(Request(scope))
        return await super().get_response(path, scope)


def create_app(
    run_service: RunService | None = None,
    *,
    session_runtime: SessionRuntime | None = None,
    session_runtime_factory: Callable[[], SessionRuntime] | None = None,
    fit_analysis_service: Any | None = None,
) -> FastAPI:
    factory = session_runtime_factory
    if factory is None and run_service is None and session_runtime is None:
        factory = create_session_runtime

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        created_runtime = None
        if (
            application.state.session_runtime is None
            and factory is not None
            and not application.dependency_overrides
        ):
            created_runtime = await anyio.to_thread.run_sync(factory)
            application.state.session_runtime = created_runtime
        try:
            from api.auto_apply_routes import restore_applications
            await anyio.to_thread.run_sync(restore_applications, application)
            from api.career_routes import restore_tasks
            await anyio.to_thread.run_sync(restore_tasks, application)
            yield
        finally:
            career = getattr(application.state, 'career_agent', None)
            if career is not None:
                await anyio.to_thread.run_sync(career.close)
                application.state.career_agent = None
            automation = getattr(application.state, "auto_apply", None)
            if automation is not None:
                await anyio.to_thread.run_sync(automation.close)
                application.state.auto_apply = None
            if run_service is None and application.state.run_service is not None:
                await anyio.to_thread.run_sync(application.state.run_service.close)
                application.state.run_service = None
            if created_runtime is not None:
                await anyio.to_thread.run_sync(created_runtime.close)
                application.state.session_runtime = None

    application = FastAPI(
        title="JobHunterAgent API",
        version="0.5.0",
        description=(
            "Evidence-grounded resume tailoring and persistent local agent sessions. "
            "Session access currently assumes a trusted single-user local deployment."
        ),
        lifespan=lifespan,
    )
    application.state.run_service = run_service
    application.state.session_runtime = session_runtime
    application.state.fit_analysis_service = fit_analysis_service
    application.include_router(runs_router)
    application.include_router(sessions_router)
    application.include_router(context_router)
    application.include_router(evidence_router)
    application.include_router(interview_router)
    application.include_router(pack_router)
    application.include_router(agent_task_router)
    application.include_router(multi_agent_router)
    application.include_router(mock_interview_router)
    application.include_router(workspace_router)
    application.include_router(feedback_router)
    application.include_router(assistant_router)
    application.include_router(resume_router)
    application.include_router(auto_apply_router)
    application.include_router(career_router)
    application.include_router(career_groups_router)
    application.include_router(material_router)
    application.include_router(job_alert_router)
    from api.skill_evolution_routes import router as skill_evolution_router
    application.include_router(skill_evolution_router)
    install_error_handlers(application)

    web_root = Path(__file__).resolve().parent.parent / "web_app"
    if web_root.exists():
        application.mount("/web-assets", ChatAssets(directory=web_root), name="web-assets")

        @application.get("/apply", include_in_schema=False)
        async def auto_apply_page() -> FileResponse:
            return FileResponse(web_root / "apply.html", headers={"Cache-Control": "no-store"})

        @application.get("/", include_in_schema=False)
        @application.get("/app", include_in_schema=False)
        @application.get("/app/", include_in_schema=False)
        @application.get("/index.html", include_in_schema=False)
        async def web_app(request: Request) -> RedirectResponse:
            return chat_redirect(request)

    @application.get("/health", tags=["health"])
    async def health() -> dict[str, Any]:
        runtime = application.state.session_runtime
        mcp = (
            runtime.mcp_health().model_dump(mode="json")
            if runtime is not None
            else {
                "configured_servers": 0,
                "ready_servers": 0,
                "failed_optional_servers": 0,
                "registered_tools": 0,
                "servers": [],
            }
        )
        return {
            "status": "degraded" if mcp["failed_optional_servers"] else "ok",
            "mcp": mcp,
        }

    return application


app = create_app()
