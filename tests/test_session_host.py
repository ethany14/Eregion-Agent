"""Session turns are decided by the shared AgentLoop; there is no legacy decision path (M7)."""
import pytest

from eregion.runtime.core import host_protocol
from eregion.runtime.core.engine import AgentLoop
from eregion.runtime.sessions import host as session_host
from eregion.runtime.sessions.host import SessionHost
from eregion.runtime.sessions.state import SessionStatus
from test_session_coordinator import (call, coordinator, response, runtime, user,  # noqa: F401
                                      ApprovalTool, RecordingTool, ScriptedModel)


def test_session_host_satisfies_the_contract():
    assert host_protocol.missing_methods(SessionHost) == []


def _turn(runtime, monkeypatch, session_id='s-1'):
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


def test_every_session_turn_uses_the_shared_agent_loop(runtime, monkeypatch):
    assert _turn(runtime, monkeypatch) == ['SessionHost']


def test_the_removed_legacy_drain_switch_has_no_effect(runtime, monkeypatch):
    # M7 removed the legacy decision loop; the old drain variable selects nothing.
    monkeypatch.setenv('JOB_AGENT_SESSION_LEGACY_DRAIN', 's-1')
    assert _turn(runtime, monkeypatch) == ['SessionHost']
    assert not hasattr(session_host, 'uses_legacy')


def test_shared_loop_error_propagates_with_no_fallback(runtime, monkeypatch):
    monkeypatch.setattr(AgentLoop, 'run', lambda self: (_ for _ in ()).throw(RuntimeError('kernel bug')))
    _, sessions, tool_calls = runtime
    model = ScriptedModel([response('assistant-1', 'unused')])
    service = coordinator(sessions, tool_calls, model, RecordingTool())
    state = service.create_session(allowed_tools=frozenset({'read'}))
    with pytest.raises(RuntimeError, match='kernel bug'):
        service.submit_user_message(state.session_id, user(), expected_version=state.version)
    assert model.calls == []


def test_in_flight_sessions_are_listed(runtime, monkeypatch):
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
    from eregion.runtime.sessions.errors import SessionClaimConflictError
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
    from eregion.runtime.sessions.errors import InvalidSessionTransitionError
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
