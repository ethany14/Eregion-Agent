"""Optional, bounded semantic decisions. No browser effects or generated text.

Uses TypeSafe's HTTP API with the existing httpx dependency. Only metadata is
logged; cache keys are hashes. Callers own evidence, budgets and freshness.
"""
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from concurrent.futures import Future, TimeoutError as FutureTimeout
import logging
from dataclasses import dataclass, field
import hashlib
import json
import math
import os
from pathlib import Path
from threading import RLock
import time
from urllib.parse import urlsplit

import httpx
from dotenv import dotenv_values


@dataclass
class DecisionBatch:
    answers: dict = field(default_factory=dict)
    status: str = 'disabled'
    seconds: float = 0
    model: str = ''
    input_tokens: int = 0
    cached: bool = False
    requests: int = 0

    def metadata(self):
        return {key: getattr(self, key) for key in
                ('status', 'seconds', 'model', 'input_tokens', 'cached', 'requests')}


def accepted(answer, *, confidence=.90, probability=.95):
    """Initial conservative thresholds, not a claim of calibrated accuracy."""
    return bool(answer and answer['choice'] != 'unknown'
                and answer['confidence'] >= confidence
                and answer['probabilities'][answer['choice']] >= probability)


class FastDecisions:
    def __init__(self, *, api_key='', base_url='https://api.typesafe.ai',
                 model='jev-latest', enabled=False, timeout=2.5, transport=None):
        self._key = api_key
        self.base_url, self.model = base_url.rstrip('/'), model
        self.enabled = bool(enabled and api_key)
        self.timeout, self.transport = timeout, transport
        self._cache, self._lock, self._retry_at = OrderedDict(), RLock(), 0
        self._inflight = {}

    def cache_namespace(self):
        return hashlib.sha256(json.dumps([self.enabled, self.base_url, self.model,
            self._key, self.timeout]).encode()).hexdigest()

    def clear_cache(self):
        """Explicit cold benchmark; never resets outage cooldown."""
        with self._lock:
            self._cache.clear()

    def _request(self, payload):
        from agent_runtime.provider_usage import provider_call, token_counts
        with provider_call(self.model, context_chars=len(json.dumps(payload, ensure_ascii=False))) as usage:
            response = self._request_unmetered(payload)
            if response.status_code >= 400:
                usage.update(status='failed', http_status=response.status_code)
            try:
                usage.update(token_counts(response.json().get('usage')))
            except (ValueError, AttributeError):
                pass
            return response

    def _request_unmetered(self, payload):
        from agent_runtime.multi_agent.model_usage import current_model_call
        with httpx.Client(timeout=self.timeout, transport=self.transport,
                          follow_redirects=False) as client:
            response = client.post(self.base_url + '/v1/systemone', json=payload,
                headers={'Authorization': 'Bearer ' + self._key})
        call = current_model_call()
        if response.status_code == 200 and call is not None:
            try:
                usage = response.json()['usage']
                if all(type(usage[k]) is int and usage[k] >= 0
                       for k in ('input_tokens', 'output_tokens')):
                    call['usage'] = {k: usage[k] for k in ('input_tokens', 'output_tokens')}
            except (ValueError, KeyError, TypeError):
                pass
        return response

    def evaluate(self, state, questions, *, purpose):
        start = time.monotonic()
        result = DecisionBatch(model=self.model)
        if not self.enabled:
            return result
        payload = {'model': self.model, 'state': state, 'questions': questions}
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if not questions or len(questions) > 40 or len(encoded) > 90000:
            result.status = 'input_limit'
            return result
        for q in questions.values():
            if q.get('type') != 'choice' or not 2 <= len(q.get('criteria', {})) <= 255:
                result.status = 'input_limit'
                return result
        # Bind transport and validation to the exact snapshot used as the key;
        # a caller mutating its input while another thread runs cannot change it.
        payload = json.loads(encoded)
        questions = payload['questions']
        digest = hashlib.sha256((purpose + encoded).encode()).hexdigest()
        with self._lock:
            cached = self._cache.get(digest)
            if cached and start - cached[0] < 300:
                self._cache.move_to_end(digest)
                return DecisionBatch(json.loads(cached[1]), 'ok', 0, cached[2], 0, True)
            if start < self._retry_at:
                result.status = 'cooldown'
                return result
            flight = self._inflight.get(digest)
            shared = flight is not None
            if not shared:
                flight = Future()
                self._inflight[digest] = flight
        if shared:
            # Pure semantic decisions only. Identical concurrent callers share
            # one HTTP request, never browser effects, passwords or new facts.
            # Waiting is bounded and never starts a duplicate request on timeout.
            try:
                value = flight.result(timeout=self.timeout)
            except FutureTimeout:
                return DecisionBatch(status='inflight_timeout', model=self.model,
                                     seconds=round(time.monotonic() - start, 3))
            return DecisionBatch(answers=json.loads(value['answers']), status=value['status'],
                model=value['model'], cached=value['status'] == 'ok',
                seconds=round(time.monotonic() - start, 3))
        try:
            return self._evaluate_payload(payload, questions, digest, start, result, purpose)
        finally:
            # Resolve waiters even if a caller's budget/cancellation exception
            # escapes. No exception text, prompt or response body is shared.
            value = {'answers':json.dumps(result.answers), 'model':result.model,
                     'status':result.status if result.status != 'disabled' else 'inflight_failed'}
            with self._lock:
                flight.set_result(value)
                self._inflight.pop(digest, None)

    def _evaluate_payload(self, payload, questions, digest, start, result, purpose):
        try:
            # No redirects: never forward an API credential to another host.
            from agent_runtime.multi_agent.model_usage import invoke_model
            from agent_runtime.provider_usage import usage_scope
            result.requests = 1
            with usage_scope(purpose='jev:' + purpose, model_route='fast'):
                response = invoke_model(self._request, payload)
            if response.status_code != 200:
                result.status = 'http_' + str(response.status_code)
            else:
                data = response.json()
                answers = data['answers']
                if set(answers) != set(questions):
                    raise ValueError('Incomplete decision batch')
                for name, answer in answers.items():
                    options = questions[name]['criteria']
                    probabilities = answer['probabilities']
                    values = [answer['confidence'], *probabilities.values()]
                    if (answer.get('type') != 'choice' or set(probabilities) != set(options)
                            or answer['choice'] not in options
                            or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in values)
                            or abs(sum(probabilities.values()) - 1) > .020000001
                            or probabilities[answer['choice']] + 1e-12 < max(probabilities.values())):
                        raise ValueError('Invalid decision result')
                result.answers, result.status = answers, 'ok'
                result.model = str(data.get('model', self.model))[:100]
                result.input_tokens = max(0, int(data.get('usage', {}).get('input_tokens', 0)))
                with self._lock:
                    self._cache[digest] = (time.monotonic(), json.dumps(answers), result.model)
                    while len(self._cache) > 128:
                        self._cache.popitem(last=False)
        except httpx.TimeoutException:
            result.status = 'timeout'
        except httpx.HTTPError:
            result.status = 'connection_error'
        except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
            result.status = 'invalid_response'
        result.seconds = round(time.monotonic() - start, 3)
        if result.status != 'ok':
            # Fail open to the main model; do not retry each dropdown on an outage.
            with self._lock:
                self._retry_at = time.monotonic() + 30
        return result


_instances, _instances_lock = {}, RLock()


def configured_decisions(*, env_path=None, environ=None, scope='general'):
    path = env_path or Path(__file__).resolve().parents[1] / '.env'
    settings = {**dotenv_values(path), **(os.environ if environ is None else environ)}
    key = str(settings.get('TYPESAFE_API_KEY') or '').strip()
    base = str(settings.get('TYPESAFE_BASE_URL') or 'https://api.typesafe.ai').strip().rstrip('/')
    model = str(settings.get('TYPESAFE_DEFAULT_MODEL') or 'jev-latest').strip()
    enabled = str(settings.get('TYPESAFE_ENABLED') or 'false').lower() in {'1', 'true', 'yes'}
    if scope == 'career':
        enabled = enabled and str(settings.get('TYPESAFE_CAREER_ENABLED') or 'false').lower() in {'1', 'true', 'yes'}
    elif scope != 'general':
        raise ValueError('Unknown decision scope.')
    try:
        timeout = float(settings.get('TYPESAFE_TIMEOUT') or 2.5)
        if not .1 <= timeout <= 10:
            raise ValueError()
        parts = urlsplit(base)
        if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError()
    except ValueError:
        return FastDecisions()
    fingerprint = hashlib.sha256(json.dumps([key, base, model, enabled, timeout]).encode()).hexdigest()
    with _instances_lock:
        if fingerprint not in _instances:
            if len(_instances) >= 8:
                _instances.clear()
            _instances[fingerprint] = FastDecisions(api_key=key, base_url=base, model=model,
                                                   enabled=enabled, timeout=timeout)
        return _instances[fingerprint]


_routing = ContextVar('fast_decision_routing', default=None)


@contextmanager
def capture_routing():
    records = []
    token = _routing.set(records)
    try:
        yield records
    finally:
        _routing.reset(token)


def record_routing(purpose, batch, **counts):
    record = {'purpose': purpose, **batch.metadata(), **counts}
    records = _routing.get()
    if records is not None and len(records) < 100:
        records.append(record)
    logging.getLogger(__name__).info('Fast decision routing: %s', record)
