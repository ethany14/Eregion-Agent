"""JOB_AGENT_JOB_API_FIRST drives prompt, snapshot and tool descriptions together."""
from types import SimpleNamespace

import pytest

from agent_runtime.career import source_mode
from agent_runtime.career.prompt import SYSTEM, TRIMMED_SYSTEM
from agent_runtime.loop_engine import describe_tools
from agent_runtime.request_options import slim_tools
from agent_runtime.task_host import TaskHost
from test_career_flow import career  # noqa: F401


@pytest.mark.parametrize('prompt,edits', [(SYSTEM, source_mode.FULL_PROMPT_EDITS),
                                           (TRIMMED_SYSTEM, source_mode.TRIMMED_PROMPT_EDITS)])
def test_every_edit_matches_the_shipped_prompt_exactly_once(prompt, edits):
    # Guards against prompt drift silently leaving browser-first wording behind.
    for old, new in edits:
        assert prompt.count(old) == 1, old[:60]
        assert new not in prompt
    changed = source_mode.prompt_for(prompt, True)
    assert 'browser-first' not in changed
    assert 'search_jobs is the primary discovery path' in changed


def test_off_is_byte_for_byte_unchanged():
    assert source_mode.prompt_for(SYSTEM, False) is SYSTEM
    assert source_mode.prompt_for(TRIMMED_SYSTEM, False) is TRIMMED_SYSTEM
    assert source_mode.tool_descriptions(False) == {}
    assert source_mode.snapshot_policy(False, 'linkedin') == {}


def test_unknown_prompt_is_never_rewritten():
    assert source_mode.prompt_for('custom prompt', True) == 'custom prompt'


def test_host_descriptions_survive_slimming_without_mutating_tools():
    from agent_runtime.career.harness import TOOLS
    original = [t for t in TOOLS if t['function']['name'] in {'search_jobs', 'read_job', 'score_job'}]
    before = [t['function']['description'] for t in original]
    tools = describe_tools(slim_tools(original), source_mode.tool_descriptions(True))
    named = {t['function']['name']: t['function']['description'] for t in tools}
    assert named['search_jobs'].startswith('Primary discovery')
    assert named['read_job'] == source_mode.TOOL_DESCRIPTIONS['read_job']
    assert 'Persist the actual' in named['score_job']  # untouched slim text
    assert [t['function']['description'] for t in original] == before


def host(c):
    loop = SimpleNamespace(repository=c.repository, harness=c.harness, _budget=lambda state: 50,
                           _active=lambda state: True, _timing=lambda *args: None)
    return TaskHost(loop, c.state['task_id'], model=None)


def _turn(c):
    c.repository.append(c.state['task_id'], role='user', text='Find junior data analyst jobs in New York')
    return host(c).observe()


def test_task_turn_is_browser_first_when_off(career, monkeypatch):
    monkeypatch.setenv('JOB_AGENT_JOB_API_FIRST', '0')
    turn = _turn(career)
    assert turn.prompt == SYSTEM
    assert turn.tool_descriptions == {}
    assert 'source_policy' not in turn.snapshot


@pytest.mark.parametrize('trim', ['0', '1'])
def test_task_turn_agrees_everywhere_when_on(career, monkeypatch, trim):
    monkeypatch.setenv('JOB_AGENT_JOB_API_FIRST', '1')
    monkeypatch.setenv('JOB_AGENT_OPT_PROMPT_TRIM', trim)
    turn = _turn(career)
    assert 'browser-first' not in turn.prompt
    assert 'Prefer browser search' not in turn.prompt
    assert 'search_jobs is the primary discovery path' in turn.prompt
    assert turn.snapshot['source_policy']['api_first'] is True
    assert turn.tool_descriptions['search_jobs'].startswith('Primary discovery')
