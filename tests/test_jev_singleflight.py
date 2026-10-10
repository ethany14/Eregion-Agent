"""Identical concurrent decisions share transport, never share browser actions."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Barrier

import httpx
import pytest

from agent_runtime.fast_decisions import FastDecisions

QUESTIONS = {'q':{'type':'choice', 'criteria':{'yes':'Supported', 'no':'Unsupported'}}}


def response():
    return httpx.Response(200, json={'answers':{'q':{'type':'choice', 'choice':'yes', 'confidence':1,
        'probabilities':{'yes':1, 'no':0}}}, 'usage':{'input_tokens':42, 'output_tokens':1}})


def test_concurrent_identical_calls_send_once_and_return_independent_answers():
    started, release = Event(), Event()
    calls = []
    def handle(request):
        calls.append(request)
        started.set()
        assert release.wait(3)
        return response()
    service = FastDecisions(api_key='fixture', enabled=True, timeout=2, transport=httpx.MockTransport(handle))
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(service.evaluate, {'field':'Country'}, QUESTIONS, purpose='option') for _ in range(4)]
        assert started.wait(2)
        release.set()
        results = [f.result(3) for f in futures]
    assert len(calls) == 1 and sum(r.requests for r in results) == 1
    assert sum(r.input_tokens for r in results) == 42
    assert all(r.status == 'ok' for r in results)
    results[0].answers['q']['choice'] = 'no'
    assert all(r.answers['q']['choice'] == 'yes' for r in results[1:])
    assert not service._inflight


def test_different_page_state_and_purpose_never_share_decisions():
    meeting, calls = Barrier(3, timeout=3), []
    def handle(request): calls.append(request); meeting.wait(); return response()
    service = FastDecisions(api_key='fixture', enabled=True, transport=httpx.MockTransport(handle))
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(service.evaluate, state, QUESTIONS, purpose=purpose)
            for state, purpose in [({'page':'one'},'option'), ({'page':'two'},'option'), ({'page':'one'},'other')]]
        assert all(f.result(4).status == 'ok' for f in futures)
    assert len(calls) == 3


def test_waiter_timeout_does_not_send_a_duplicate_request():
    started, release = Event(), Event()
    calls = []
    def handle(request): calls.append(request); started.set(); release.wait(3); return response()
    service = FastDecisions(api_key='fixture', enabled=True, timeout=.1, transport=httpx.MockTransport(handle))
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(service.evaluate, {}, QUESTIONS, purpose='option')
        try:
            assert started.wait(2)
            other = service.evaluate({}, QUESTIONS, purpose='option')
            assert other.status == 'inflight_timeout' and other.requests == 0 and not other.answers
        finally: release.set()
        assert first.result(3).status == 'ok'
    assert len(calls) == 1


def test_mutating_a_callers_page_does_not_change_the_keyed_request(monkeypatch):
    started, release, captured = Event(), Event(), []
    service = FastDecisions(api_key='fixture', enabled=True)
    def request(payload):
        started.set()
        assert release.wait(3)
        captured.append(payload['state']['page'])
        return response()
    monkeypatch.setattr(service, '_request', request)
    state = {'page':'original'}
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(service.evaluate, state, QUESTIONS, purpose='option')
        assert started.wait(2)
        state['page'] = 'new'
        release.set()
        assert first.result(3).status == 'ok'
    assert service.evaluate(state, QUESTIONS, purpose='option').status == 'ok'
    assert captured == ['original','new']


def test_escaping_budget_error_releases_inflight_entry_and_waiters(monkeypatch):
    started, release, joined = Event(), Event(), Event()
    service = FastDecisions(api_key='fixture', enabled=True, timeout=2)
    def fail(*args): started.set(); release.wait(3); raise RuntimeError('Budget stop')
    monkeypatch.setattr(service, '_evaluate_payload', fail)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(service.evaluate, {}, QUESTIONS, purpose='option')
        assert started.wait(2)
        flight = next(iter(service._inflight.values()))
        original = flight.result
        def waiting(**kwargs): joined.set(); return original(**kwargs)
        monkeypatch.setattr(flight, 'result', waiting)
        second = pool.submit(service.evaluate, {}, QUESTIONS, purpose='option')
        assert joined.wait(2)
        release.set()
        with pytest.raises(RuntimeError, match='Budget'): first.result(3)
        assert second.result(3).status == 'inflight_failed'
    assert not service._inflight
