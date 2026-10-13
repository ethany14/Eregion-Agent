"""Suite-wide isolation for offline tests.

Offline tests must never read the maintainer's real .env, use real model credentials or
open outside connections. An explicit live run (JOB_AGENT_LIVE_*=1 or
JOB_AGENT_B6_REPLAY_LIVE_MODEL=1) is the only exception and turns this isolation off.
"""
import ipaddress
import os
import socket
from pathlib import Path

import pytest

REPO_ENV = (Path(__file__).resolve().parent.parent / '.env').resolve()
LIVE = any(v == '1' for k, v in os.environ.items()
           if k.startswith('JOB_AGENT_LIVE_') or k == 'JOB_AGENT_B6_REPLAY_LIVE_MODEL')
DOTENV_READERS = ('eregion.domain.model', 'eregion.domain.jev_fit.settings', 'eregion.runtime.fast_decisions',
                  'eregion.runtime.application_pack.workflow')
FAKE_MODEL = {'LLM_MODEL_ID': 'offline-test-model', 'LLM_API_KEY': 'offline-test-key',
              'LLM_BASE_URL': 'https://offline.invalid/v1'}


def _loopback(address):
    host = address[0] if isinstance(address, tuple) else address
    if not isinstance(host, str):
        return True  # AF_UNIX / named pipes
    if host in {'localhost', ''}:
        return True
    try:
        return ipaddress.ip_address(host.split('%')[0]).is_loopback
    except ValueError:
        return False


@pytest.fixture(autouse=True)
def _offline_isolation(monkeypatch):
    # Saving a candidate resume starts a background resume analysis with the configured
    # provider (agent_runtime/analysis_cache.warm_resume); it must never run in tests.
    # A test that exercises warmup sets JOB_AGENT_ANALYSIS_WARMUP=1 explicitly.
    monkeypatch.setenv('JOB_AGENT_ANALYSIS_WARMUP', '0')
    if LIVE:
        yield
        return
    import importlib
    import dotenv
    real = dotenv.dotenv_values

    def without_repo_env(path=None, *args, **kwargs):
        if path is not None and Path(path).resolve() == REPO_ENV:
            return {}
        return real(path, *args, **kwargs)

    for name in DOTENV_READERS:
        module = importlib.import_module(name)
        if hasattr(module, 'dotenv_values'):
            monkeypatch.setattr(module, 'dotenv_values', without_repo_env)
    monkeypatch.setattr(dotenv, 'dotenv_values', without_repo_env)  # function-local imports
    for key, value in FAKE_MODEL.items():
        monkeypatch.setenv(key, value)
    attempts = []
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def guarded(method):
        def connect(self, address):
            if self.family in (socket.AF_INET, socket.AF_INET6) and not _loopback(address):
                attempts.append(address)
                raise ConnectionRefusedError(f'offline test attempted an outside connection to {address!r}')
            return method(self, address)
        return connect

    monkeypatch.setattr(socket.socket, 'connect', guarded(original_connect))
    monkeypatch.setattr(socket.socket, 'connect_ex', guarded(original_connect_ex))
    yield
    if attempts:
        pytest.fail(f'Offline test attempted outside connections (caught or not): {attempts[:3]}')
