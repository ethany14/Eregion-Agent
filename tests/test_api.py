import asyncio
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.db import create_database
from api.repositories.run_repository import RunRepository
from api.routes.runs import get_run_service
from api.schemas.runs import CreateRunResponse, RunResponse
from api.services.run_service import (
    SAFE_RUN_ERROR,
    InvalidRunStateError,
    RunNotFoundError,
    RunService,
)
from custom_agent.loop import AgentLoop
from custom_agent.repository import StateRepository
from runtime_helpers import CompleteFakeHandler, FailingHandler


FACT = "Built Python APIs."


class FakeRunService:
    def __init__(self) -> None:
        self.review_request = None

    async def create_run(self, request):
        return CreateRunResponse(run_id="test-run-id", status="awaiting_review")

    async def get_run(self, run_id):
        if run_id == "missing":
            raise RunNotFoundError("Run 'missing' was not found.")
        return RunResponse(
            run_id=run_id,
            status="awaiting_review",
            result={"tailored_resume": {"professional_summary": []}},
        )

    async def review_run(self, run_id, request):
        if run_id == "not-reviewable":
            raise InvalidRunStateError("Run is not awaiting review.")
        self.review_request = request
        status = "approved" if request.approved else "awaiting_review"
        return RunResponse(run_id=run_id, status=status, result={"revision_count": 1})


@pytest.fixture
def api_client():
    service = FakeRunService()
    app.dependency_overrides[get_run_service] = lambda: service
    with TestClient(app) as client:
        yield client, service
    app.dependency_overrides.clear()


@contextmanager
def client_for_service(service):
    app.dependency_overrides[get_run_service] = lambda: service
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def run_repository(tmp_path):
    database = create_database(
        f"sqlite:///{(tmp_path / 'runs.sqlite').as_posix()}",
        create_schema_for_tests=True,
    )
    try:
        yield RunRepository(database.session_factory)
    finally:
        database.close()


def test_health(api_client):
    client, _ = api_client
    assert client.get("/health").json() == {
        "status": "ok",
        "mcp": {
            "configured_servers": 0,
            "ready_servers": 0,
            "failed_optional_servers": 0,
            "registered_tools": 0,
            "servers": [],
        },
    }


def test_create_run_uses_fake_service_without_llm(api_client):
    client, _ = api_client
    with patch("job_agent.model.create_model") as model:
        response = client.post(
            "/runs",
            json={"resume_text": FACT, "job_description": "Requires Python"},
        )
    assert response.status_code == 201
    assert response.json() == {
        "run_id": "test-run-id",
        "status": "awaiting_review",
    }
    model.assert_not_called()


@pytest.mark.parametrize(
    ("resume_text", "job_description"),
    [
        ("", "Requires Python"),
        ("Built Python APIs.", ""),
        ("  ", "Requires Python"),
        ("Built Python APIs.", "  "),
    ],
)
def test_create_run_rejects_empty_resume_or_job_description(
    api_client, resume_text, job_description
):
    client, _ = api_client
    response = client.post(
        "/runs",
        json={
            "resume_text": resume_text,
            "job_description": job_description,
        },
    )
    assert response.status_code == 422


def test_get_run_and_not_found(api_client):
    client, _ = api_client
    assert client.get("/runs/test-run-id").json()["status"] == "awaiting_review"
    response = client.get("/runs/missing")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


def test_approve_run(api_client):
    client, service = api_client
    response = client.post(
        "/runs/test-run-id/review",
        json={"approved": True, "feedback": None},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    assert service.review_request.approved is True


def test_rejection_requires_feedback(api_client):
    client, _ = api_client
    response = client.post(
        "/runs/test-run-id/review",
        json={"approved": False, "feedback": " "},
    )
    assert response.status_code == 422
    assert "feedback is required" in str(response.json())


def test_rejection_with_feedback_returns_to_review(api_client):
    client, service = api_client
    response = client.post(
        "/runs/test-run-id/review",
        json={"approved": False, "feedback": "Emphasize Python."},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "awaiting_review"
    assert service.review_request.feedback == "Emphasize Python."


def test_review_conflict_returns_409(api_client):
    client, _ = api_client
    response = client.post(
        "/runs/not-reviewable/review", json={"approved": True}
    )
    assert response.status_code == 409


def make_service(repository, handler):
    return RunService(repository=repository,
        loop=AgentLoop(repository=StateRepository(repository._session_factory), handler=handler))


def test_run_service_uses_run_id_as_thread_id_and_resumes_approval(run_repository):
    handler = CompleteFakeHandler()
    service = make_service(run_repository, handler=handler)
    created = asyncio.run(
        service.create_run(
            SimpleNamespace(resume_text=FACT, job_description="Requires Python")
        )
    )
    assert created.status == "awaiting_review"
    assert run_repository.get(created.run_id).backend == "custom"
    assert run_repository.get(created.run_id).thread_id == created.run_id
    reviewed = asyncio.run(
        service.review_run(
            created.run_id,
            SimpleNamespace(approved=True, feedback=None),
        )
    )
    assert reviewed.status == "approved"
    assert run_repository.get(created.run_id).status == "approved"


def test_run_service_rejection_revises_and_pauses_again(run_repository):
    service = make_service(run_repository, handler=CompleteFakeHandler())
    created = asyncio.run(
        service.create_run(
            SimpleNamespace(resume_text=FACT, job_description="Requires Python")
        )
    )
    reviewed = asyncio.run(
        service.review_run(
            created.run_id,
            SimpleNamespace(approved=False, feedback="Shorten summary."),
        )
    )
    assert reviewed.status == "awaiting_review"
    assert reviewed.result["revision_count"] == 1


def test_run_service_rejects_review_after_approval(run_repository):
    service = make_service(run_repository, handler=CompleteFakeHandler())
    created = asyncio.run(
        service.create_run(
            SimpleNamespace(resume_text=FACT, job_description="Requires Python")
        )
    )
    asyncio.run(
        service.review_run(
            created.run_id,
            SimpleNamespace(approved=True, feedback=None),
        )
    )
    with pytest.raises(InvalidRunStateError, match="not awaiting review"):
        asyncio.run(
            service.review_run(
                created.run_id,
                SimpleNamespace(approved=True, feedback=None),
            )
        )


def test_run_service_preserves_failed_status_and_error(run_repository):
    service = make_service(run_repository, handler=FailingHandler())
    created = asyncio.run(
        service.create_run(
            SimpleNamespace(resume_text=FACT, job_description="Requires Python")
        )
    )
    assert created.status == "failed"
    stored = asyncio.run(service.get_run(created.run_id))
    assert stored.status == "failed"
    assert stored.result is None
    assert stored.error == SAFE_RUN_ERROR


def test_api_rejects_second_review_after_run_is_approved(run_repository):
    service = make_service(run_repository, handler=CompleteFakeHandler())
    with client_for_service(service) as client:
        created = client.post(
            "/runs",
            json={"resume_text": FACT, "job_description": "Requires Python"},
        )
        run_id = created.json()["run_id"]
        approved = client.post(
            f"/runs/{run_id}/review", json={"approved": True}
        )
        repeated = client.post(
            f"/runs/{run_id}/review", json={"approved": True}
        )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert repeated.status_code == 409
    assert "not awaiting review" in repeated.json()["detail"]


def test_api_exposes_understandable_failed_run_status(run_repository):
    service = make_service(run_repository, handler=FailingHandler())
    with client_for_service(service) as client:
        created = client.post(
            "/runs",
            json={"resume_text": FACT, "job_description": "Requires Python"},
        )
        run_id = created.json()["run_id"]
        stored = client.get(f"/runs/{run_id}")
    assert created.status_code == 201
    assert created.json()["status"] == "failed"
    assert stored.status_code == 200
    assert stored.json() == {
        "run_id": run_id,
        "status": "failed",
        "result": None,
        "error": SAFE_RUN_ERROR,
    }
