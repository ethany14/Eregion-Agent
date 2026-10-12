"""Isolated evaluation execution using the production custom loop and handlers."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from api.db import create_database
from job_agent.workflow.handlers import JobAgentStepHandler
from job_agent.workflow.analysis import AnalysisWorkflow
from job_agent.workflow.repository import StateRepository
from job_agent.workflow.state import AgentState, AgentStatus, Step
from job_agent.model import create_model, invoke_structured


def evaluation_handler(callbacks=None):
    def analyze(schema, system_message, human_message):
        return invoke_structured(create_model(), schema, system_message, human_message,
                                 {"callbacks": callbacks} if callbacks else None)
    return JobAgentStepHandler(analyzer=analyze)


class EvaluationWorkflow:
    """Run each case in an isolated database, retaining only its evaluation output.

    writer_only is an explicit ablation of the computation handlers. It produces
    an unverified draft, never a reviewable or approved production run.
    """
    def __init__(self, *, writer_only=False, handler=None):
        self.writer_only = writer_only
        self.handler = handler
        self.results = {}

    def run(self, inputs, *, run_id=None, callbacks=None):
        run_id = run_id or str(uuid4())
        handler = self.handler if self.handler is not None else evaluation_handler(callbacks)
        if self.writer_only:
            state = AgentState(run_id=run_id, **inputs)
            for step in (Step.VALIDATE_INPUT, Step.ANALYZE_RESUME,
                         Step.VALIDATE_EVIDENCE, Step.ANALYZE_JOB,
                         Step.MATCH_SKILLS, Step.WRITE_RESUME):
                state = AgentState.model_validate({**state.model_dump(), "step": step})
                outcome = handler.execute(step, state)
                state = AgentState.model_validate({**state.model_dump(), **outcome.updates})
            result = {**state.job_state(), "completed": True, "reached_human_review": False}
        else:
            with TemporaryDirectory(prefix="jobagent-eval-") as directory:
                database = create_database(
                    f"sqlite:///{(Path(directory) / 'runs.sqlite').as_posix()}",
                    create_schema_for_tests=True)
                try:
                    loop = AnalysisWorkflow(repository=StateRepository(database.session_factory),
                                     handler=handler)
                    state = loop.start(run_id=run_id, **inputs)
                    reached = state.status == AgentStatus.AWAITING_REVIEW
                    result = {**state.job_state(), "completed": reached,
                              "reached_human_review": reached}
                finally:
                    database.close()
        self.results[run_id] = result
        return result

    def get_result(self, run_id):
        return self.results[run_id]


def execute_reflection_step(step, values, callbacks=None):
    fields = {key: value for key, value in values.items() if key in AgentState.model_fields}
    fields.update(run_id="reflection", step=step,
                  status=AgentStatus.REVISING if step == Step.REVISE_RESUME else AgentStatus.RUNNING)
    state = AgentState.model_validate(fields)
    updates = evaluation_handler(callbacks).execute(step, state).updates
    if step == Step.REVISE_RESUME:
        updates = {**updates, "revision_count": state.revision_count + 1,
                   "verification": None}
    return updates
