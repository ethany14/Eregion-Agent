"""Suite-wide isolation for offline tests."""
import pytest


@pytest.fixture(autouse=True)
def _no_background_resume_warmup(monkeypatch):
    # Saving a candidate resume starts a best-effort background resume analysis with
    # the configured provider (agent_runtime/analysis_cache.warm_resume). In tests that
    # thread made real model calls and outlived its test, tripping later network guards.
    # A test that exercises warmup sets JOB_AGENT_ANALYSIS_WARMUP=1 explicitly.
    monkeypatch.setenv('JOB_AGENT_ANALYSIS_WARMUP', '0')
