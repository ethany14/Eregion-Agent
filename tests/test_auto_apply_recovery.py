"""Retry schedule per failure kind, Retry-After, and internal errors kept apart from AI failures."""
import logging
from types import SimpleNamespace

from agent_runtime.auto_apply.agent import HybridApplicationAgent
from agent_runtime.auto_apply.loop import MAX_RETRY_DELAY, RETRY_POLICY, ApplicationLoop
from agent_runtime.model_runtime import model_failure
from test_auto_apply import database
from agent_runtime.auto_apply.repository import ApplyRepository


def test_rate_limits_back_off_longer_than_other_failures(database):
    loop = ApplicationLoop(ApplyRepository(database.session_factory))
    try:
        limited = [loop._retry_delay("model_rate_limited", attempt) for attempt in range(5)]
        assert limited[-1] is None and len(RETRY_POLICY["model_rate_limited"]) == 4
        assert all(.8 * base <= delay <= 1.2 * base for delay, base in zip(limited, RETRY_POLICY["model_rate_limited"]))
        assert loop._retry_delay("browser_error", 2) is None  # Default: two quick retries.
        # A provider's Retry-After wins over a shorter schedule, within a cap.
        assert loop._retry_delay("model_rate_limited", 0, retry_after=60) == 60
        assert loop._retry_delay("model_rate_limited", 0, retry_after=3000) == MAX_RETRY_DELAY
    finally:
        loop.close()


def test_explicit_schedule_applies_to_every_reason(database):
    loop = ApplicationLoop(ApplyRepository(database.session_factory), retry_delays=(0,))
    try:
        assert loop._retry_delay("model_rate_limited", 0) == 0
        assert loop._retry_delay("model_rate_limited", 1) is None
    finally:
        loop.close()


def test_retry_after_header_is_read_from_rate_limit_errors():
    class RateLimitError(Exception):
        status_code = 429
        response = SimpleNamespace(headers={"retry-after": "12"})
    failure = model_failure(RateLimitError("body"))
    assert failure.code == "model_rate_limited" and failure.retry_after == 12
    class NoHeader(Exception):
        status_code = 429
    assert model_failure(NoHeader()).retry_after is None


def test_harness_defect_is_internal_error_and_logs_no_message(caplog):
    class BrokenBrowser:
        def observe(self):
            raise RuntimeError("typed answer: secret-value")
    class Model:
        def invoke(self, *args):
            raise AssertionError("The model should not be called.")
    state = {"profile": {"first_name": "A", "last_name": "B", "email": "a@example.com"}, "answers": {}}
    with caplog.at_level(logging.ERROR):
        result = HybridApplicationAgent(model_factory=Model).run(BrokenBrowser(), state,
            autofill=lambda: {}, active=lambda: True, reserve=lambda kind: True, report=lambda *args: None)
    assert result == {"reason": "internal_error", "field_keys": []}
    assert "RuntimeError" in caplog.text and "observe" in caplog.text
    assert "secret-value" not in caplog.text
