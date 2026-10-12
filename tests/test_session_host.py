"""Session turns are decided by the shared AgentLoop; legacy only drains registered Sessions."""
import pytest

from agent_runtime import host_protocol
from agent_runtime.loop_engine import AgentLoop
from agent_runtime.sessions import host as session_host
from agent_runtime.sessions.host import SessionHost
from agent_runtime.sessions.state import SessionStatus
from test_session_coordinator import (call, coordinator, response, runtime, user,  # noqa: F401
                                      ApprovalTool, RecordingTool, ScriptedModel)


def test_session_host_satisfies_the_contract():
    assert host_protocol.missing_methods(SessionHost) == []


def _turn(runtime, monkeypatch, drain=None, session_id='s-1'):
    if drain is None:
        monkeypatch.delenv('JOB_AGENT_SESSION_LEGACY_DRAIN', raising=False)
    else:
        monkeypatch.setenv('JOB_AGENT_SESSION_LEGACY_DRAIN', drain)
    runs = []
    original = AgentLoop.run
    monkeypatch.setattr(AgentLoop, 'run', lambda self: runs.append(type(self.host).__name__) or original(self))
    _, sessions, tool_calls = runtime
    model = ScriptedModel([response('assistant-1', calls=[call('c1')]), response('assistant-2', 'done')])
    service = coordinator(sessions, tool_calls, model, RecordingTool())
    state = service.create_session(session_id=session_id, allowed_tools=frozenset({'read'}))
    outcome = service.submit_user_message(state.session_id, user(), expected_version=state.version)
    assert outcome.final_text == 'done'
    return runs


def test_default_is_the_shared_agent_loop(runtime, monkeypatch):
    assert _turn(runtime, monkeypatch) == ['SessionHost']


def test_only_explicitly_registered_sessions_drain_on_the_legacy_loop(runtime, monkeypatch):
    assert _turn(runtime, monkeypatch, drain='other, s-1') == []


@pytest.mark.parametrize('drain', ['*', 'all', 's-', ' , '])
def test_drain_registry_has_no_wildcard(runtime, monkeypatch, drain):
    assert _turn(runtime, monkeypatch, drain=drain) == ['SessionHost']


def test_shared_loop_error_is_not_retried_on_the_legacy_loop(runtime, monkeypatch):
    monkeypatch.delenv('JOB_AGENT_SESSION_LEGACY_DRAIN', raising=False)
    monkeypatch.setattr(AgentLoop, 'run', lambda self: (_ for _ in ()).throw(RuntimeError('kernel bug')))
    _, sessions, tool_calls = runtime
    model = ScriptedModel([response('assistant-1', 'unused')])
    service = coordinator(sessions, tool_calls, model, RecordingTool())
    state = service.create_session(allowed_tools=frozenset({'read'}))
    with pytest.raises(RuntimeError, match='kernel bug'):
        service.submit_user_message(state.session_id, user(), expected_version=state.version)
    assert model.calls == []  # the legacy loop did not take over


def test_in_flight_sessions_are_listed_for_registration(runtime, monkeypatch):
    monkeypatch.delenv('JOB_AGENT_SESSION_LEGACY_DRAIN', raising=False)
    _, sessions, tool_calls = runtime
    model = ScriptedModel([response('assistant-1', calls=[call('w1', tool='write')])])
    service = coordinator(sessions, tool_calls, model, ApprovalTool('write'))
    waiting = service.create_session(session_id='waiting', allowed_tools=frozenset({'write'}))
    outcome = service.submit_user_message('waiting', user(), expected_version=waiting.version)
    assert outcome.state.status == SessionStatus.AWAITING_TOOL_APPROVAL
    service.create_session(session_id='idle')
    assert session_host.in_flight_session_ids(sessions) == ['waiting']
