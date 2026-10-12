"""Build the API runtime using the persisted custom agent loop."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from api.db import create_database, upgrade_database
from api.repositories.run_repository import RunRepository
from api.services.run_service import RunService
from job_agent.workflow.handlers import JobAgentStepHandler
from job_agent.workflow.analysis import AnalysisWorkflow
from job_agent.workflow.repository import StateRepository
from job_agent.results import public_result


def create_run_service(*, database_url: str | None = None,
                       result_serializer: Callable[[dict[str, Any]], dict[str, Any]] = public_result,
                       custom_handler: Any = None) -> RunService:
    """Create the only supported runtime; historical projections remain readable."""
    upgrade_database(database_url)
    database = create_database(database_url)
    try:
        loop = AnalysisWorkflow(repository=StateRepository(database.session_factory),
            handler=custom_handler if custom_handler is not None else JobAgentStepHandler(),
            result_projector=result_serializer)
        return RunService(repository=RunRepository(database.session_factory),
            loop=loop, resources=(database,))
    except BaseException:
        database.close()
        raise
