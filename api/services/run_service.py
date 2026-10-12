"""API adapter for the persisted custom agent loop."""
from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import uuid4

from api.repositories.run_repository import RunRecord, RunRepository
from api.schemas.runs import CreateRunRequest, CreateRunResponse, ReviewRequest, RunResponse
from job_agent.workflow.errors import InvalidTransitionError, StaleStateError, StateNotFoundError
from job_agent.workflow.analysis import AnalysisWorkflow

logger = logging.getLogger(__name__)
SAFE_RUN_ERROR = "The agent could not complete this run."


class RunNotFoundError(LookupError):
    pass


class InvalidRunStateError(RuntimeError):
    pass


class RunService:
    """Run new work on AnalysisWorkflow and expose saved historical results read-only."""

    def __init__(self, *, repository: RunRepository, loop: AnalysisWorkflow,
                 resources: tuple[Any, ...] = ()) -> None:
        self._repository = repository
        self._loop = loop
        self._resources = resources
        self._locks: dict[str, asyncio.Lock] = {}

    async def create_run(self, request: CreateRunRequest) -> CreateRunResponse:
        run_id = str(uuid4())
        try:
            await asyncio.to_thread(self._loop.start, run_id=run_id,
                resume_text=request.resume_text, job_description=request.job_description)
        except Exception as exc:
            logger.error("Agent run %s failed (%s)", run_id, type(exc).__name__)
        record = self._repository.get(run_id)
        if record is None:
            raise RuntimeError("The agent could not create the run.")
        return CreateRunResponse(run_id=run_id, status=record.status)

    async def get_run(self, run_id: str) -> RunResponse:
        return self._response(self._get_record(run_id))

    async def review_run(self, run_id: str, request: ReviewRequest) -> RunResponse:
        lock = self._locks.setdefault(run_id, asyncio.Lock())
        async with lock:
            record = self._get_record(run_id)
            if record.backend != "custom":
                raise InvalidRunStateError(
                    "This historical run is read-only because its execution backend "
                    "is retired or unknown. Create a new run to continue.")
            if record.status != "awaiting_review":
                raise InvalidRunStateError(
                    f"Run '{run_id}' is not awaiting review; current status is '{record.status}'.")
            try:
                await asyncio.to_thread(self._loop.review, run_id,
                    approved=request.approved, feedback=request.feedback)
            except (InvalidTransitionError, StaleStateError, StateNotFoundError, ValueError) as exc:
                raise InvalidRunStateError(str(exc)) from exc
            except Exception as exc:
                logger.error("Agent review %s failed (%s)", run_id, type(exc).__name__)
            return self._response(self._get_record(run_id))

    def _get_record(self, run_id: str) -> RunRecord:
        record = self._repository.get(run_id)
        if record is None:
            raise RunNotFoundError(f"Run '{run_id}' was not found.")
        return record

    @staticmethod
    def _response(record: RunRecord) -> RunResponse:
        return RunResponse(run_id=record.run_id, status=record.status,
            result=record.result, error=record.error_message)

    def close(self) -> None:
        resources, self._resources = self._resources, ()
        for resource in reversed(resources):
            close = getattr(resource, "close", None)
            if callable(close):
                close()
