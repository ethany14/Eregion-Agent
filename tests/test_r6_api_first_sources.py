"""R6 offline source-chain coverage for the API-first route (gaps not covered by test_treg / P3).

Covered elsewhere and reused as-is: normal search, no results, paging/dedupe, missing JD,
timeouts and network errors, unknown cost, idempotent retry, disabled API, caps
(tests/test_treg.py, tests/test_integrated_p3.py, tests/test_board_directory.py).
"""
import pytest

from agent_runtime.career.treg_jobs import normalize_search
from test_career_flow import career, execute  # noqa: F401
from test_integrated_p3 import CRAWL_ROWS, JD, Discovery, ask, install_treg, ok, treg_env
from test_remaining_search_completion import prepare


def test_crawl4ai_partial_and_blocked_coverage_is_reported_not_hidden():
    rows = CRAWL_ROWS['rows']
    _, partial = normalize_search('crawl4ai', {'rows': rows, 'meta': {'partial': True, 'warnings': ['page 2']}})
    assert partial['partial'] and partial['warnings'] == 1 and not partial['source_blocked']
    _, clean = normalize_search('crawl4ai', {'rows': rows})
    assert not clean['partial'] and not clean['source_blocked']


def test_blocked_linkedin_search_is_a_blocked_source(career, monkeypatch):
    treg_env(monkeypatch)
    c = career; prepare(c); ask(c, 'Only search LinkedIn for junior data analyst jobs')
    install_treg(c, lambda r: ok({'rows': [], 'meta': {'blocked': True}}))
    c.harness.discovery = Discovery()
    result = execute(c, 'search_jobs', query='junior data analyst', location='New York, NY')
    assert result['error_code'] == 'treg_source_blocked' and result['no_new_evidence'] and result['jobs'] == []


def test_partial_linkedin_search_keeps_candidates_and_discloses_partial_coverage(career, monkeypatch):
    treg_env(monkeypatch)
    c = career; prepare(c); ask(c, 'Only search LinkedIn for junior data analyst jobs')
    install_treg(c, lambda r: ok({**CRAWL_ROWS, 'meta': {'partial': True}}))
    c.harness.discovery = Discovery()
    result = execute(c, 'search_jobs', query='junior data analyst', location='New York, NY')
    assert result['jobs'] and result['treg']['partial'] and 'partial or blocked coverage' in result['note']


def test_closed_posting_from_scrape_is_reported_and_not_reread(career, monkeypatch):
    treg_env(monkeypatch, JOB_AGENT_TREG_CRAWL4AI_SCRAPE_ENABLED='1')
    c = career; prepare(c)
    link = CRAWL_ROWS['rows'][0]['url']
    c.repository.change(c.state['task_id'], search_candidates={'k': {'url': 'https://www.linkedin.com/jobs/view/4468908584/',
        'title': 'Junior Data Analyst', 'company': 'B Co', 'location': 'New York, NY'}})
    closed = JD.replace('## Responsibilities', 'No longer accepting applications.\n## Responsibilities')
    install_treg(c, lambda r: ok({'ok': True, 'markdown': closed, 'content_hash': 'h'}))
    c.harness.discovery = Discovery()
    with pytest.raises(ValueError, match='closed'):
        execute(c, 'read_job', url=link)
    assert ('job', link) not in c.harness.discovery.calls  # not silently re-read elsewhere
    assert not c.repository.get(c.state['task_id']).get('retrieved_jobs')


def test_api_first_without_a_treg_key_uses_free_boards_and_never_calls_treg(career, monkeypatch):
    treg_env(monkeypatch, TREG_TOKEN='')  # explicitly empty: never falls back to the repo .env
    c = career; prepare(c)
    seen = install_treg(c, lambda r: ok(CRAWL_ROWS))
    c.harness.discovery = Discovery(directory=[{'url': 'https://boards.greenhouse.io/x/jobs/1', 'title': 'Data Analyst'}])
    result = execute(c, 'search_jobs', query='junior data analyst', location='New York, NY')
    assert c.harness._treg() is None and seen == []
    assert ('directory', 'junior data analyst') in c.harness.discovery.calls and 'error' not in result


def test_candidate_evidence_is_isolated_between_tasks(career, monkeypatch):
    treg_env(monkeypatch, JOB_AGENT_TREG_CRAWL4AI_SCRAPE_ENABLED='1')
    c = career; prepare(c)
    link = CRAWL_ROWS['rows'][0]['url']
    c.repository.change(c.state['task_id'], search_candidates={'k': {'url': 'https://www.linkedin.com/jobs/view/4468908584/',
        'title': 'Junior Data Analyst', 'company': 'B Co', 'location': 'New York, NY'}})
    install_treg(c, lambda r: ok({'ok': True, 'markdown': JD, 'content_hash': 'h'}))
    c.harness.discovery = Discovery()
    execute(c, 'read_job', url=link)
    other, _ = c.repository.create('another user request', 'isolation-key')
    assert c.repository.get(c.state['task_id']).get('retrieved_jobs')
    assert not c.repository.get(other['task_id']).get('retrieved_jobs')
    assert not c.repository.get(other['task_id']).get('search_candidates')
