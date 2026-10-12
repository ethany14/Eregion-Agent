"""Fixed-endpoint Treg HTTP client (P4c). Contract: docs/diagnostics/treg-ab-contract.md.

Only three endpoints. No redirects, no transport-level retries, no proxy from the
environment, bounded responses, a per-call cost cap header on every request, and a
persisted idempotency key reused for the single allowed retry. Charges come only from
X-Treg-Cost-Micro; an unknown outcome keeps its reservation in the ledger.
"""
from dataclasses import dataclass, field
import json
import threading
import time
from uuid import uuid4

import httpx

from .external_tool_usage import BudgetExceeded

GATEWAY = 'https://treg.to/call/'
ENDPOINTS = frozenset({'anyapi.linkedin.search.jobs', 'crawl4ai.linkedin.search.jobs', 'crawl4ai.web.scrape'})
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
RETRYABLE_STATUS = {409, 429}


class TregUnavailable(Exception):
    """Treg is disabled, unconfigured or over budget; other sources keep working."""
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


@dataclass
class TregCallResult:
    operation_id: str
    endpoint: str
    outcome: str                      # succeeded | failed | unknown | cancelled
    http_status: int | None = None
    body: object = None
    charged_micro: int | None = None
    original_cost_micro: int | None = None
    replay: bool = False
    call_id: str | None = None
    served_via: str | None = None
    cache: str | None = None
    error: str | None = None
    attempts: int = 0
    seconds: float = 0.0
    details: dict = field(default_factory=dict)

    @property
    def quarantined(self):
        """A provider substitution (overflow relay) is recorded but not used as evidence."""
        return bool(self.served_via and self.served_via.startswith('overflow'))


def _int(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


class TregClient:
    def __init__(self, config, ledger, *, transport=None, worker=None, deadline_seconds=90.0,
                 timeout=None, sleep=time.sleep):
        self.config, self.ledger = config, ledger
        self.worker = worker or uuid4().hex[:12]
        self.deadline_seconds = deadline_seconds
        self.sleep = sleep
        self._slots = threading.BoundedSemaphore(max(1, config.max_concurrency))
        self._client = httpx.Client(transport=transport, follow_redirects=False, trust_env=False,
            timeout=timeout or httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0))

    def close(self):
        self._client.close()

    def _headers(self, key):
        headers = {'X-Treg-Token': self.config.token, 'Idempotency-Key': key, 'Content-Type': 'application/json',
                   'X-Treg-Route-Max-Cost': f'{self.config.call_max_micro / 1_000_000:.6f}'}
        if self.config.org:
            headers['X-Treg-Org'] = self.config.org
        return headers

    def call(self, endpoint, body, *, scope, task_id=None, run_id=None, revision=None, cancelled=lambda: False):
        if endpoint not in ENDPOINTS:
            raise ValueError('Endpoint is not in the fixed Treg allowlist.')
        reason = self.config.usable()
        if reason:
            raise TregUnavailable(reason)
        try:
            operation_id = self.ledger.reserve(scope=scope, endpoint=endpoint, body=body,
                reserve_micro=self.config.call_max_micro, task_max_micro=self.config.task_max_micro,
                daily_max_micro=self.config.daily_max_micro, max_attempts=self.config.max_attempts,
                task_id=task_id, run_id=run_id, revision=revision)
        except BudgetExceeded as exc:
            raise TregUnavailable(exc.reason) from None
        started = time.monotonic()
        result = TregCallResult(operation_id=operation_id, endpoint=endpoint, outcome='unknown')
        with self._slots:
            for attempt in (1, 2):
                if cancelled():
                    if attempt == 1:
                        self.ledger.settle(operation_id, status='cancelled', charged_micro=0,
                                           details={'cancelled_before_send': True})
                        result.outcome = 'cancelled'
                        return result
                    break  # an earlier attempt may have reached Treg: leave it unknown
                if time.monotonic() - started > self.deadline_seconds:
                    result.error = 'deadline'
                    break
                try:
                    key, result.attempts = self.ledger.claim_attempt(operation_id, worker=self.worker,
                                                                     max_attempts=self.config.max_attempts)
                except BudgetExceeded as exc:
                    result.error = exc.reason
                    break
                retry_after = self._attempt(result, endpoint, body, key)
                if retry_after is None or attempt == 2:
                    break
                remaining = self.deadline_seconds - (time.monotonic() - started)
                if retry_after > remaining:
                    break
                self.sleep(max(0.0, retry_after))
        result.seconds = round(time.monotonic() - started, 3)
        details = {k: v for k, v in {'http_status': result.http_status, 'served_via': result.served_via,
                   'cache': result.cache, 'replay': result.replay, 'error': result.error,
                   'seconds': result.seconds, 'quarantined': result.quarantined}.items() if v not in (None, False)}
        status = {'succeeded': 'succeeded', 'failed': 'failed'}.get(result.outcome, 'unknown')
        result.outcome = self.ledger.settle(operation_id, status=status, charged_micro=result.charged_micro,
            original_cost_micro=result.original_cost_micro, call_id=result.call_id, details=details)
        return result

    def _attempt(self, result, endpoint, body, key):
        """One network attempt. Returns seconds to wait before a same-key retry, or None."""
        try:
            with self._client.stream('POST', GATEWAY + endpoint, headers=self._headers(key),
                                     content=json.dumps(body).encode()) as response:
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_RESPONSE_BYTES:
                        result.http_status, result.error = response.status_code, 'response_too_large'
                        self._read_headers(result, response)
                        result.outcome = 'unknown' if result.charged_micro is None else 'failed'
                        return None
                    chunks.append(chunk)
                raw = b''.join(chunks)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            # Treg says network errors and timeouts are never billed, but the outcome of
            # a request that may have reached the provider is unknown until confirmed.
            result.error = type(exc).__name__
            result.outcome = 'unknown'
            return 1.0
        result.http_status = response.status_code
        self._read_headers(result, response)
        try:
            result.body = json.loads(raw.decode('utf-8')) if raw else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            result.body = None
            result.error = result.error or 'invalid_json'
        status = response.status_code
        detail = result.body.get('detail') if isinstance(result.body, dict) else None
        code = (detail.get('error') if isinstance(detail, dict) else None) or (
            result.body.get('error') if isinstance(result.body, dict) else None)
        if 200 <= status < 300:
            result.outcome = 'succeeded' if result.body is not None else 'unknown'
            return None
        if status == 503 and isinstance(result.body, dict) and result.body.get('treg_saturated'):
            result.error, result.outcome = 'treg_saturated', 'unknown'
            return _int(response.headers.get('Retry-After')) or 2
        if status in RETRYABLE_STATUS:
            result.error, result.outcome = f'http_{status}', 'unknown'
            return _int(response.headers.get('Retry-After')) or 2
        if status == 410:
            # The original call completed (or may have) and was charged; never re-call with a new key.
            result.error, result.outcome = str(code or 'idempotency_gone'), 'unknown'
            return None
        # 402 route_max_cost / balance, 4xx input errors, provider 4xx/5xx: nothing charged.
        result.error = str(code or f'http_{status}')
        if result.charged_micro is None:
            result.charged_micro = 0
        result.outcome = 'failed'
        return None

    @staticmethod
    def _read_headers(result, response):
        headers = response.headers
        cost = _int(headers.get('X-Treg-Cost-Micro'))
        if cost is not None:
            result.charged_micro = cost
        result.replay = str(headers.get('X-Treg-Idempotent-Replay', '')).lower() == 'true'
        result.original_cost_micro = _int(headers.get('X-Treg-Original-Cost-Micro'))
        result.call_id = headers.get('X-Treg-Call-Id') or result.call_id
        result.served_via = headers.get('X-Treg-Served-Via') or None
        result.cache = headers.get('X-Treg-Cache') or None
