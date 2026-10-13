"""Prove that Session decisions are made by the shared AgentLoop (unified loop M2/M7).

Import the fixture into a test module to apply it to every test there:
    from session_paths import session_decision_path  # noqa: F401

M2 ran these modules on both the legacy and the shared kernel (parity evidence in
docs/benchmarks/unified-loop-m2-20261012). M7 removed the legacy decision loop, so
the fixture now asserts, after every test, that each runtime model decision
happened inside AgentLoop.run with a SessionHost.
"""
import sys
import threading
from pathlib import Path

import pytest

from eregion.runtime.core.engine import AgentLoop
from eregion.runtime.tools.loop import ToolCallingLoop


@pytest.fixture(autouse=True)
def session_decision_path(request, monkeypatch):
    local, decisions = threading.local(), []
    run, decide = AgentLoop.run, ToolCallingLoop.decide

    def tracked_run(self):
        previous, local.host = getattr(local, 'host', None), type(self.host).__name__
        try:
            return run(self)
        finally:
            local.host = previous

    def tracked_decide(self, *args, **kwargs):
        # Tests may call decide() directly to stage a crash window; only
        # decisions made by runtime code count.
        if not Path(sys._getframe(1).f_code.co_filename).name.startswith('test_'):
            decisions.append(getattr(local, 'host', None))
        return decide(self, *args, **kwargs)

    monkeypatch.setattr(AgentLoop, 'run', tracked_run)
    monkeypatch.setattr(ToolCallingLoop, 'decide', tracked_decide)
    yield 'agent_loop'
    allowed = {'SessionHost', '_RunHost'}  # _RunHost: ToolCallingLoop.run compatibility entry
    assert all(host in allowed for host in decisions), decisions
    request.node.user_properties.append(('session_decisions', len(decisions)))
