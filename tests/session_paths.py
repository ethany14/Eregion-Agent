"""Run a Session test module under both decision paths (unified loop M2 parity).

Import the fixture into a test module to apply it to every test there:
    from session_paths import session_decision_path  # noqa: F401

The fixture also proves which kernel decided: under 'agent_loop' every Session
model decision must happen inside AgentLoop.run with a SessionHost; under
'legacy' none may.
"""
import sys
import threading
from pathlib import Path

import pytest

from agent_runtime.loop_engine import AgentLoop
from agent_runtime.tools.loop import ToolCallingLoop


@pytest.fixture(autouse=True, params=['legacy', 'agent_loop'])
def session_decision_path(request, monkeypatch):
    # Default = shared AgentLoop. 'legacy' stands for a Session registered to
    # drain on the old loop (tests create ids dynamically, so patch the lookup).
    from agent_runtime.sessions import host
    monkeypatch.delenv('JOB_AGENT_SESSION_LEGACY_DRAIN', raising=False)
    if request.param == 'legacy':
        monkeypatch.setattr(host, 'uses_legacy', lambda session_id: True)
    local, decisions = threading.local(), []
    run, decide = AgentLoop.run, ToolCallingLoop.decide

    def tracked_run(self):
        session = type(self.host).__name__ == 'SessionHost'
        previous, local.session = getattr(local, 'session', False), session
        try:
            return run(self)
        finally:
            local.session = previous

    def tracked_decide(self, *args, **kwargs):
        # Tests may call decide() directly to stage a crash window; only
        # decisions made by runtime code count.
        if not Path(sys._getframe(1).f_code.co_filename).name.startswith('test_'):
            decisions.append(getattr(local, 'session', False))
        return decide(self, *args, **kwargs)

    monkeypatch.setattr(AgentLoop, 'run', tracked_run)
    monkeypatch.setattr(ToolCallingLoop, 'decide', tracked_decide)
    yield request.param
    expected = request.param == 'agent_loop'
    assert all(inside == expected for inside in decisions), (request.param, decisions)
    request.node.user_properties.append(('session_decisions', len(decisions)))
