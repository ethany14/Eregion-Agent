"""Unified loop M3: the fixed analysis steps are a deterministic, checkpointed workflow."""
import re
from pathlib import Path

import pytest

from eregion.domain.workflow import analysis
from eregion.domain.workflow.analysis import AnalysisWorkflow
from eregion.domain.workflow.errors import InvalidTransitionError
from eregion.domain.workflow.state import Step
from test_analysis_workflow_state import FACT, FakeHandler, custom_runtime  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


def test_analysis_workflow_is_not_another_agent_loop():
    assert not hasattr(analysis, 'AgentLoop')
    assert not (ROOT / 'backend' / 'custom_agent').exists()
    assert not (ROOT / 'backend' / 'eregion' / 'compat').exists()


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
    from eregion.domain.workflow.events import AgentEventType
    from eregion.domain.workflow.state import AgentState
    state = AgentState(run_id='wf-1', resume_text=FACT, job_description='Requires Python', max_revisions=1)
    return state, workflow._event(state, AgentEventType.RUN_CREATED, Step.VALIDATE_INPUT)


def test_production_code_does_not_import_the_legacy_package():
    offenders = []
    for folder in ('backend/eregion', 'tools/evals', 'tools/scripts'):
        for path in (ROOT / folder).rglob('*.py'):
            for line in path.read_text(encoding='utf-8').splitlines():
                if re.match(r'\s*(from custom_agent[\s.]|import custom_agent\b)', line):
                    offenders.append(f'{path.relative_to(ROOT)}: {line.strip()}')
    main = (ROOT / 'main.py').read_text(encoding='utf-8')
    assert offenders == [] and 'custom_agent' not in main
