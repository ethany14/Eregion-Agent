"""Career and application Hosts satisfy the single AgentLoop contract."""
import re
from pathlib import Path

import pytest

from agent_runtime import host_protocol
from agent_runtime.auto_apply.runner import ApplicationHost
from agent_runtime.task_host import TaskHost

ENGINE = Path(host_protocol.__file__).with_name('loop_engine.py')


@pytest.mark.parametrize('host', [TaskHost, ApplicationHost])
def test_existing_hosts_provide_every_required_method(host):
    assert host_protocol.missing_methods(host) == []


def test_missing_methods_names_what_an_incomplete_host_lacks():
    class Partial:
        def active(self): return True
        revision = 3  # not callable
    missing = host_protocol.missing_methods(Partial())
    assert 'revision' in missing and 'observe' in missing and 'active' not in missing


def test_the_engine_uses_only_contract_members():
    used = set(re.findall(r'self\.host\.([a-z_]+)', ENGINE.read_text(encoding='utf-8')))
    declared = set(host_protocol.REQUIRED) | set(host_protocol.OPTIONAL) | set(host_protocol.ATTRIBUTES)
    assert used <= declared, used - declared
    # Optional members are always guarded by hasattr in the engine.
    for name in host_protocol.OPTIONAL + host_protocol.ATTRIBUTES:
        assert f"hasattr(self.host, '{name}')" in ENGINE.read_text(encoding='utf-8'), name
