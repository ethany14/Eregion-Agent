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


def test_two_concurrent_requests_on_one_session_decide_once(runtime, monkeypatch):
    import threading
    from agent_runtime.sessions.errors import SessionClaimConflictError
    monkeypatch.delenv('JOB_AGENT_SESSION_LEGACY_DRAIN', raising=False)
    _, sessions, tool_calls = runtime
    entered, release = threading.Event(), threading.Event()

    class BlockingModel(ScriptedModel):
        def invoke(self, messages, tools):
            entered.set()
            assert release.wait(5)
            return super().invoke(messages, tools)

    model = BlockingModel([response('assistant-1', 'done')])
    service = coordinator(sessions, tool_calls, model, RecordingTool())
    state = service.create_session(session_id='race', allowed_tools=frozenset({'read'}))
    results = {}
    first = threading.Thread(target=lambda: results.setdefault('first', service.submit_user_message(
        'race', user(), expected_version=state.version)))
    first.start()
    assert entered.wait(5)
    with pytest.raises(SessionClaimConflictError):
        service.continue_session('race')
    release.set()
    first.join(5)
    assert results['first'].final_text == 'done'
    assert len(model.calls) == 1


def test_user_message_during_an_in_flight_model_call_is_rejected(runtime, monkeypatch):
    from agent_runtime.sessions.errors import InvalidSessionTransitionError
    monkeypatch.delenv('JOB_AGENT_SESSION_LEGACY_DRAIN', raising=False)
    _, sessions, tool_calls = runtime
    rejected = []

    class SteeredModel(ScriptedModel):
        def invoke(self, messages, tools):
            current = sessions.require('steer')
            try:
                service.submit_user_message('steer', user('user-2', 'change of plan'),
                                            expected_version=current.version)
            except InvalidSessionTransitionError:
                rejected.append(current.status)
            return super().invoke(messages, tools)

    model = SteeredModel([response('assistant-1', 'done')])
    service = coordinator(sessions, tool_calls, model, RecordingTool())
    state = service.create_session(session_id='steer', allowed_tools=frozenset({'read'}))
    outcome = service.submit_user_message('steer', user(), expected_version=state.version)
    assert outcome.final_text == 'done' and rejected == [SessionStatus.RUNNING]
    assert [m.message.message_id for m in sessions.messages('steer')
            if m.message.role == 'user'] == ['user-1']
