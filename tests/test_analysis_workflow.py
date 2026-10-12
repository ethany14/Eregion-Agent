"""Unified loop M3: the fixed analysis steps are a deterministic, checkpointed workflow."""
import re
from pathlib import Path

import pytest

import custom_agent.handlers
import custom_agent.loop
import job_agent.workflow.handlers
from job_agent.workflow.analysis import AgentLoop, AnalysisWorkflow
from job_agent.workflow.errors import InvalidTransitionError
from job_agent.workflow.state import Step
from test_custom_agent import FACT, FakeHandler, custom_runtime  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


def test_old_import_paths_are_the_same_modules_not_copies():
    assert custom_agent.handlers is job_agent.workflow.handlers
    assert custom_agent.loop.AgentLoop is AnalysisWorkflow is AgentLoop


def test_each_advance_is_one_persisted_step(custom_runtime):
    handler = FakeHandler()
    workflow = AnalysisWorkflow(repository=custom_runtime.repository, handler=handler)
    state = custom_runtime.repository.create(*_created(workflow))
    steps = []
    while state.step != Step.HUMAN_REVIEW:
        before = state.version
        steps.append(state.step)
        state = workflow.advance(state)
        assert state.version == before + 1  # one checkpoint per step
        assert custom_runtime.repository.require(state.run_id).version == state.version
    assert steps == [Step.VALIDATE_INPUT, Step.ANALYZE_RESUME, Step.VALIDATE_EVIDENCE, Step.ANALYZE_JOB,
                     Step.MATCH_SKILLS, Step.WRITE_RESUME, Step.VERIFY_RESUME]
    with pytest.raises(InvalidTransitionError):
        workflow.advance(state)  # human review is never a computation step


def _created(workflow):
    from job_agent.workflow.events import AgentEventType
    from job_agent.workflow.state import AgentState
    state = AgentState(run_id='wf-1', resume_text=FACT, job_description='Requires Python', max_revisions=1)
    return state, workflow._event(state, AgentEventType.RUN_CREATED, Step.VALIDATE_INPUT)


def test_production_code_does_not_import_the_legacy_package():
    offenders = []
    for folder in ('agent_runtime', 'api', 'job_agent', 'evals', 'scripts'):
        for path in (ROOT / folder).rglob('*.py'):
            for line in path.read_text(encoding='utf-8').splitlines():
                if re.match(r'\s*(from custom_agent[\s.]|import custom_agent\b)', line):
                    offenders.append(f'{path.relative_to(ROOT)}: {line.strip()}')
    main = (ROOT / 'main.py').read_text(encoding='utf-8')
    assert offenders == [] and 'custom_agent' not in main
