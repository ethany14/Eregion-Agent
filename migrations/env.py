"""Alembic migration environment."""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from api.db import Base
import agent_runtime.analysis_cache  # noqa: F401
import agent_runtime.provider_usage  # noqa: F401
import api.models  # noqa: F401
import agent_runtime.models  # noqa: F401
import agent_runtime.sessions.models  # noqa: F401
import agent_runtime.memory.models  # noqa: F401
import agent_runtime.skills.models  # noqa: F401
import agent_runtime.skills.evolution_models  # noqa: F401
import agent_runtime.context.models  # noqa: F401
import agent_runtime.evidence.models  # noqa: F401
import agent_runtime.interviewer.models  # noqa: F401
import agent_runtime.mock_interview.models  # noqa: F401
import agent_runtime.feedback.models  # noqa: F401
import agent_runtime.learning.models  # noqa: F401
import agent_runtime.application_pack.models  # noqa: F401
import agent_runtime.multi_agent.models  # noqa: F401
import agent_runtime.assistant.models  # noqa: F401
import agent_runtime.workspace.models  # noqa: F401
import agent_runtime.resumes.models  # noqa: F401
import job_agent.workflow.models  # noqa: F401
import agent_runtime.auto_apply.models  # noqa: F401
import agent_runtime.career.repository  # noqa: F401
import agent_runtime.career.alerts  # noqa: F401

config = context.config
if config.config_file_name is not None:
    # Migrations run inside the server at startup; keep the application's
    # already-created loggers (agent failures, task loop) enabled.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

database_url = os.getenv("JOB_AGENT_DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
