"""P2a: Ashby whole-board response reuse. Mock transport and fake resolver only."""
import json
import socket
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import httpx
import pytest

from agent_runtime.career.discovery import BoardResponseCache, JobDiscovery

BOARD = {'jobs': [{'id': f'id-{i}', 'title': f'Data Analyst {i}', 'location': 'New York, NY', 'isListed': True,
                   'jobUrl': f'https://jobs.ashbyhq.com/acme/id-{i}', 'descriptionPlain': 'Requirements: SQL. ' * 50}
                  for i in range(3)]}
API = 'https://api.ashbyhq.com/posting-api/job-board/acme'


def discovery(handler):
    resolver = lambda host, port, type=None: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', port))]
    d = JobDiscovery(transport=httpx.MockTransport(handler), resolver=resolver)
    d.min_interval = 0
    return d


@pytest.fixture
def board_calls():
    return []


def handler_for(calls, body=BOARD, status=200):
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(status, json=body)
    return handler


def test_search_then_details_download_the_board_once(monkeypatch, board_calls):
    monkeypatch.setenv('JOB_AGENT_OPT_BOARD_RESPONSE_CACHE', '1')
    d = discovery(handler_for(board_calls))
    found = d.search('data analyst', 'New York, NY', boards=[{'platform': 'ashby', 'company': 'acme'}])
    assert len(found['jobs']) == 3
    for i in range(3):
        job = d.job(f'https://jobs.ashbyhq.com/acme/id-{i}')
        assert job['title'] == f'Data Analyst {i}' and 'SQL' in job['description']
    assert board_calls == [API]
    assert d._board_cache.stats['hits'] == 3


def test_flag_off_keeps_the_old_path(monkeypatch, board_calls):
    monkeypatch.delenv('JOB_AGENT_OPT_BOARD_RESPONSE_CACHE', raising=False)
    d = discovery(handler_for(board_calls))
    d.search('data analyst', 'New York, NY', boards=[{'platform': 'ashby', 'company': 'acme'}])
    d.job('https://jobs.ashbyhq.com/acme/id-0')
    assert board_calls == [API, API]


def test_ttl_expiry_and_failures_are_not_cached(monkeypatch):
    monkeypatch.setenv('JOB_AGENT_OPT_BOARD_RESPONSE_CACHE', '1')
    now = [0.0]
    cache = BoardResponseCache(clock=lambda: now[0])
    fetches = []
    def fetch():
        fetches.append(1)
        return ('{"jobs":[]}', API)
    cache.get(API, fetch)
    cache.get(API, fetch)
    now[0] = BoardResponseCache.TTL_SECONDS + 1
    cache.get(API, fetch)
    assert len(fetches) == 2
    def boom():
        raise ValueError('upstream failed')
    other = API + '-x'
    with pytest.raises(ValueError):
        cache.get(other, boom)
    assert cache.get(other, fetch)[0] == '{"jobs":[]}'  # failure was not stored


def test_concurrent_readers_share_one_download(monkeypatch):
    monkeypatch.setenv('JOB_AGENT_OPT_BOARD_RESPONSE_CACHE', '1')
    cache = BoardResponseCache()
    barrier, fetches = Barrier(4), []
    import time
    def fetch():
        fetches.append(1)
        time.sleep(0.2)
        return ('{"jobs":[]}', API)
    def read(_):
        barrier.wait()
        return cache.get(API, fetch)
    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(read, range(4)))
    assert len(fetches) == 1 and all(r == results[0] for r in results)


def test_oversize_response_is_returned_but_not_stored(monkeypatch):
    cache = BoardResponseCache()
    big = 'x' * (BoardResponseCache.MAX_BYTES // 2 + 1)
    calls = []
    fetch = lambda: calls.append(1) or (big, API)
    assert cache.get(API, fetch)[0] is big and cache.get(API, fetch)[0] is big
    assert len(calls) == 2 and cache.stats['not_cached_oversize'] == 2


def test_only_ashby_board_api_is_cacheable(monkeypatch):
    monkeypatch.setenv('JOB_AGENT_OPT_BOARD_RESPONSE_CACHE', '1')
    assert BoardResponseCache.applies(API)
    assert not BoardResponseCache.applies('https://boards-api.greenhouse.io/v1/boards/acme/jobs')
    assert not BoardResponseCache.applies('https://jobs.ashbyhq.com/acme/id-1')
