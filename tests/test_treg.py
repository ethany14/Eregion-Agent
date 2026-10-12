"""Treg A (P4): configuration, ledger, fixed client and adapter. Mock transport only."""
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import httpx
import pytest

from agent_runtime.career import treg_config, treg_jobs
from agent_runtime.career.external_tool_usage import BudgetExceeded, ExternalToolLedger
from agent_runtime.career.treg_client import TregClient, TregUnavailable
from api.db import create_database

FAKE = 'fake-test-token-not-real'


@pytest.fixture
def ledger(tmp_path):
    db = create_database('sqlite:///' + (tmp_path / 'treg.db').as_posix(), create_schema_for_tests=True)
    yield ExternalToolLedger(db.session_factory)
    db.engine.dispose()


def config(**overrides):
    env = {'TREG_TOKEN': FAKE, 'JOB_AGENT_TREG_ENABLED': '1', **overrides}
    return treg_config.load(environ=env, env_path='nonexistent.env')


def client(cfg, ledger, handler, **kwargs):
    return TregClient(cfg, ledger, transport=httpx.MockTransport(handler), sleep=lambda _s: None, **kwargs)


def ok(body, cost='500', **headers):
    return httpx.Response(200, json=body, headers={'X-Treg-Cost-Micro': cost, 'X-Treg-Call-Id': 'call-1', **headers})


# --- configuration -----------------------------------------------------------------------

def test_config_precedence_empty_override_and_defaults(tmp_path):
    env_file = tmp_path / '.env'
    env_file.write_text('TREG_TOKEN=from-file\nJOB_AGENT_TREG_ENABLED=1\n', encoding='utf-8')
    assert treg_config.load(environ={}, env_path=env_file).token == 'from-file'
    assert treg_config.load(environ={'TREG_TOKEN': 'from-env'}, env_path=env_file).token == 'from-env'
    # An explicitly empty process variable means "not configured"; it never falls back to the file.
    assert treg_config.load(environ={'TREG_TOKEN': ''}, env_path=env_file).token is None
    defaults = treg_config.load(environ={}, env_path=tmp_path / 'missing.env')
    assert not defaults.enabled and not defaults.api_first and defaults.usable() == 'treg_disabled'
    assert defaults.task_max_micro == 100_000 and defaults.daily_max_micro == 500_000 and defaults.call_max_micro == 10_000
    assert treg_config.load(environ={'TREG_TOKEN': 'your-treg-token', 'JOB_AGENT_TREG_ENABLED': '1'},
                            env_path=tmp_path / 'missing.env').usable() == 'treg_token_missing'


@pytest.mark.parametrize('value', ['-0.1', 'NaN', '0.0000001', 'abc'])
def test_invalid_budget_blocks_only_treg(value):
    with pytest.raises(treg_config.TregConfigError):
        config(JOB_AGENT_TREG_TASK_MAX_COST_USD=value)


def test_repr_never_contains_the_token():
    assert FAKE not in repr(config()) and FAKE not in str(config())


# --- client and ledger -------------------------------------------------------------------

def test_success_records_actual_charge_and_sends_cap_and_key(ledger):
    seen = []
    def handler(request):
        seen.append(request)
        return ok({'rows': []}, cost='150')
    result = client(config(), ledger, handler).call('crawl4ai.linkedin.search.jobs', {'query': 'x'}, scope='batch')
    assert result.outcome == 'succeeded' and result.charged_micro == 150
    request = seen[0]
    assert request.method == 'POST' and str(request.url) == 'https://treg.to/call/crawl4ai.linkedin.search.jobs'
    assert request.headers['X-Treg-Route-Max-Cost'] == '0.010000' and request.headers['Idempotency-Key'].startswith('jha-')
    assert ledger.summary('batch')['confirmed_micro'] == 150 and ledger.summary('batch')['complete']


def test_endpoint_allowlist_and_disabled_config(ledger):
    with pytest.raises(ValueError):
        client(config(), ledger, lambda r: ok({})).call('anyapi.linkedin.search.jobs.full', {}, scope='b')
    with pytest.raises(TregUnavailable, match='treg_disabled'):
        client(config(JOB_AGENT_TREG_ENABLED='0'), ledger, lambda r: ok({})).call(
            'crawl4ai.web.scrape', {'url': 'https://a.example'}, scope='b')
    assert ledger.rows('b') == []  # nothing reserved, nothing sent


def test_network_error_retries_once_with_same_key_then_stays_unknown(ledger):
    keys = []
    def handler(request):
        keys.append(request.headers['Idempotency-Key'])
        raise httpx.ConnectError('down', request=request)
    result = client(config(), ledger, handler).call('crawl4ai.web.scrape', {'url': 'https://a.example'}, scope='b')
    assert result.outcome == 'unknown' and len(keys) == 2 and keys[0] == keys[1]
    summary = ledger.summary('b')
    assert summary['unknown_held_micro'] == 10_000 and not summary['complete']  # reservation kept, not zero


def test_replay_counts_zero_and_keeps_original_separately(ledger):
    result = client(config(), ledger, lambda r: ok({'rows': []}, cost='0', **{
        'X-Treg-Idempotent-Replay': 'true', 'X-Treg-Original-Cost-Micro': '150'})).call(
        'crawl4ai.linkedin.search.jobs', {'query': 'x'}, scope='b')
    assert result.replay and result.charged_micro == 0 and result.original_cost_micro == 150
    assert ledger.summary('b')['confirmed_micro'] == 0


def test_402_route_cap_is_free_failure_and_410_is_unknown(ledger):
    capped = client(config(), ledger, lambda r: httpx.Response(402, json={'detail': {'error': 'route_max_cost'}})).call(
        'anyapi.linkedin.search.jobs', {'query': 'x'}, scope='b')
    assert capped.outcome == 'failed' and capped.error == 'route_max_cost' and capped.charged_micro == 0
    gone = client(config(), ledger, lambda r: httpx.Response(410, json={'detail': {'error': 'idempotency_outcome_unknown'}})).call(
        'anyapi.linkedin.search.jobs', {'query': 'x'}, scope='c')
    assert gone.outcome == 'unknown' and ledger.summary('c')['unknown_held_micro'] == 10_000


def test_saturated_503_and_409_retry_with_same_key(ledger):
    calls = []
    def handler(request):
        calls.append(request.headers['Idempotency-Key'])
        if len(calls) == 1:
            return httpx.Response(503, json={'treg_saturated': True}, headers={'Retry-After': '1'})
        return ok({'rows': []}, cost='150')
    result = client(config(), ledger, handler).call('crawl4ai.linkedin.search.jobs', {'query': 'x'}, scope='b')
    assert result.outcome == 'succeeded' and calls[0] == calls[1] and result.attempts == 2


def test_overflow_relay_is_recorded_and_quarantined(ledger):
    result = client(config(), ledger, lambda r: ok({'rows': []}, cost='300', **{'X-Treg-Served-Via': 'overflow:relay'})).call(
        'crawl4ai.linkedin.search.jobs', {'query': 'x'}, scope='b')
    assert result.quarantined and result.charged_micro == 300
    assert ledger.rows('b')[0]['details']['quarantined'] is True


def test_missing_cost_header_on_success_is_unknown(ledger):
    result = client(config(), ledger, lambda r: httpx.Response(200, json={'rows': []})).call(
        'crawl4ai.linkedin.search.jobs', {'query': 'x'}, scope='b')
    assert result.outcome == 'unknown' and ledger.summary('b')['unknown_held_micro'] == 10_000


def test_task_and_attempt_caps_block_before_sending(ledger):
    sent = []
    cfg = config(JOB_AGENT_TREG_TASK_MAX_COST_USD='0.02')
    c = client(cfg, ledger, lambda r: sent.append(1) or ok({'rows': []}, cost='10000'))
    c.call('crawl4ai.linkedin.search.jobs', {'query': 'a'}, scope='t')
    c.call('crawl4ai.linkedin.search.jobs', {'query': 'b'}, scope='t')
    with pytest.raises(TregUnavailable, match='task_cost_cap'):
        c.call('crawl4ai.linkedin.search.jobs', {'query': 'c'}, scope='t')
    assert len(sent) == 2
    small = client(config(JOB_AGENT_TREG_MAX_ATTEMPTS='1'), ledger, lambda r: ok({'rows': []}, cost='1'))
    small.call('crawl4ai.linkedin.search.jobs', {'query': 'a'}, scope='u')
    with pytest.raises(TregUnavailable, match='attempt_cap'):
        small.call('crawl4ai.linkedin.search.jobs', {'query': 'b'}, scope='u')


def test_daily_cap_spans_tasks_and_restart(ledger):
    cfg = config(JOB_AGENT_TREG_DAILY_MAX_COST_USD='0.015')
    client(cfg, ledger, lambda r: ok({'rows': []}, cost='10000')).call('crawl4ai.web.scrape', {'url': 'https://a.example'}, scope='t1')
    restarted = client(cfg, ledger, lambda r: ok({'rows': []}, cost='10000'))  # new process object, same DB
    with pytest.raises(TregUnavailable, match='daily_cost_cap'):
        restarted.call('crawl4ai.web.scrape', {'url': 'https://b.example'}, scope='t2')


def test_concurrent_reservations_for_last_budget_admit_only_one(ledger):
    cfg = config(JOB_AGENT_TREG_TASK_MAX_COST_USD='0.01')
    barrier = Barrier(4)
    def reserve(i):
        barrier.wait()
        try:
            return ledger.reserve(scope='race', endpoint='crawl4ai.web.scrape', body={'i': i}, reserve_micro=10_000,
                                  task_max_micro=cfg.task_max_micro, daily_max_micro=cfg.daily_max_micro,
                                  max_attempts=cfg.max_attempts)
        except BudgetExceeded:
            return None
    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(reserve, range(4)))
    assert sum(r is not None for r in results) == 1


def test_cancel_before_send_is_free_and_second_worker_cannot_claim(ledger):
    cancelled = client(config(), ledger, lambda r: ok({})).call('crawl4ai.web.scrape', {'url': 'https://a.example'},
                                                                  scope='c', cancelled=lambda: True)
    assert cancelled.outcome == 'cancelled' and ledger.summary('c')['confirmed_micro'] == 0
    op = ledger.reserve(scope='w', endpoint='crawl4ai.web.scrape', body={}, reserve_micro=10, task_max_micro=100,
                        daily_max_micro=10**6, max_attempts=5)
    ledger.claim_attempt(op, worker='A', max_attempts=5)
    with pytest.raises(BudgetExceeded, match='claimed_by_other_worker'):
        ledger.claim_attempt(op, worker='B', max_attempts=5)


def test_token_never_in_ledger_or_errors(ledger):
    def handler(request):
        raise httpx.ReadTimeout('slow', request=request)
    result = client(config(), ledger, handler).call('crawl4ai.web.scrape', {'url': 'https://a.example'}, scope='s')
    assert FAKE not in json.dumps(ledger.rows('s')) and FAKE not in str(result)


# --- adapter -----------------------------------------------------------------------------

ANYAPI = {'output': {'data': {'items': [
    {'id': '4419969671', 'url': 'https://www.linkedin.com/jobs/view/data-analyst-at-acme-4419969671', 'title': 'Data Analyst',
     'company': 'Acme', 'location': 'New York, NY', 'createdUtc': 1789171200},
    {'id': '4419969671', 'url': 'https://www.linkedin.com/jobs/view/4419969671?trk=x', 'title': 'Data Analyst', 'company': 'Acme'},
    {'title': 'No identity'}]}, 'found': True}}
CRAWL = {'rows': [{'job_id': '4468908584', 'url': 'https://www.linkedin.com/jobs/view/x-4468908584', 'title': 'Junior Data Analyst',
                   'company': 'B', 'location': 'New York, NY', 'posted_on': '2026-10-01'}]}


def test_normalize_search_dedupes_by_job_id_and_drops_unidentified():
    rows, info = treg_jobs.normalize_search('anyapi', ANYAPI)
    assert [r['provider_job_id'] for r in rows] == ['4419969671'] and info['dropped_without_identity'] == 1
    assert rows[0]['url'] == 'https://www.linkedin.com/jobs/view/4419969671/' and rows[0]['completeness'] == 'card'
    crawl, _ = treg_jobs.normalize_search('crawl4ai', CRAWL)
    assert crawl[0]['posted_on'] == '2026-10-01' and crawl[0]['source_endpoint'] == 'crawl4ai.linkedin.search.jobs'


def test_search_body_uses_only_common_inputs():
    assert treg_jobs.search_body('anyapi', 'data analyst', 'New York, NY', 'week') == {
        'query': 'data analyst', 'location': 'New York, NY', 'postedLimit': 'week'}
    assert treg_jobs.search_body('crawl4ai', 'data analyst', 'New York, NY', 'week') == {
        'query': 'data analyst', 'limit': 10, 'location': 'New York, NY', 'posted': 'week'}


def test_scrape_assessment_rejects_login_wall_short_text_and_wrong_job():
    target = {'title': 'Junior Data Analyst'}
    good = ('Junior Data Analyst at Acme\n\n## Responsibilities\n' + 'Build dashboards. ' * 40 +
            '\n## Requirements\n0-2 years of SQL experience. ' + 'Python and Tableau. ' * 20)
    assert treg_jobs.assess_scrape(target, {'ok': True, 'markdown': good})['status'] == 'complete_jd'
    assert treg_jobs.assess_scrape(target, {'ok': True, 'markdown': 'Sign in to view this job. ' + good})['status'] == 'blocked'
    assert treg_jobs.assess_scrape(target, {'ok': True, 'markdown': 'Junior Data Analyst'})['status'] == 'insufficient'
    other = good.replace('Junior Data Analyst', 'Senior Platform Engineer')
    assert not treg_jobs.assess_scrape(target, {'ok': True, 'markdown': other})['complete']
    closed = good + '\nNo longer accepting applications'
    assert treg_jobs.assess_scrape(target, {'ok': True, 'markdown': closed})['status'] == 'closed'
