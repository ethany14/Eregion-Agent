"""One paid request is settled once; unknown usage is never reported as zero."""
import json

from sqlalchemy import select

from eregion.runtime.provider_usage import (ProviderUsageRow, UsageLedger, adapter_attempt,
                                          capture_provider_attempts, provider_call, summarize,
                                          usage_scope)
from eregion.api.db import create_database


def ledger(tmp_path):
    db = create_database('sqlite:///' + (tmp_path / 'usage.db').as_posix(), create_schema_for_tests=True)
    return db, UsageLedger(db.session_factory)


def test_adapter_wrapping_a_metered_call_is_settled_once(tmp_path):
    # A structured/analysis adapter delegating to a metered client is one request.
    db, usage = ledger(tmp_path)
    with usage_scope(ledger=usage, run_id='run-1'), capture_provider_attempts() as events:
        with adapter_attempt('structured:Example'):
            with provider_call('inner-model') as inner:
                inner.update(input_tokens=120, output_tokens=7)
    with db.session_factory() as session:
        rows = [json.loads(r.details_json) for r in session.scalars(select(ProviderUsageRow))]
    assert len(rows) == 1 and rows[0]['model'] == 'inner-model'
    assert [e['source'] for e in events] == ['provider']
    assert usage.summary(run_ids=['run-1'])['calls'] == 1
    db.close()


def test_unmetered_adapter_is_one_attempt_with_unknown_usage():
    with capture_provider_attempts() as events:
        with adapter_attempt('structured:Example'):
            pass
    assert len(events) == 1 and events[0]['source'] == 'adapter'
    assert 'input_tokens' not in events[0]
    assert summarize([{**events[0], 'adopted': True}])['unknown_usage_calls'] == 1


def test_overlapping_provider_calls_are_separate_budgeted_attempts(tmp_path, monkeypatch):
    # Overlap is a second request (e.g. a concurrent worker), never a free child.
    from eregion.runtime.provider_usage import TaskProviderBudgetExceeded
    import pytest
    monkeypatch.setenv('JOB_AGENT_TASK_MAX_PROVIDER_ATTEMPTS', '1')
    db, usage = ledger(tmp_path)
    with usage_scope(ledger=usage, task_id='t'):
        with provider_call('first') as row:
            with pytest.raises(TaskProviderBudgetExceeded), provider_call('second'):
                pass
            row.update(input_tokens=1, output_tokens=1)
    assert usage.summary(task_id='t')['calls'] == 1
    db.close()


def test_sequential_attempts_are_counted_separately_with_retries(tmp_path):
    db, usage = ledger(tmp_path)
    with usage_scope(ledger=usage, run_id='run-3'):
        for attempt in (1, 2):
            with usage_scope(attempt=attempt), provider_call('m') as row:
                row.update(input_tokens=10, output_tokens=1)
    summary = usage.summary(run_ids=['run-3'])
    assert summary['calls'] == 2 and summary['retries'] == 1
    db.close()


def test_unknown_usage_is_reported_as_unknown_not_zero():
    summary = summarize([{'status': 'completed', 'input_tokens': 10, 'output_tokens': 2},
                         {'status': 'failed'}])
    assert summary['unknown_usage_calls'] == 1
    assert summary['usage_complete'] is False
    assert summarize([])['usage_complete'] is False
