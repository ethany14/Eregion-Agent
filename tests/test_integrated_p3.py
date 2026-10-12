"""P3 candidate batches + API-first routing, P4d Treg wiring. Mock transport, temp DB, no model."""
from types import SimpleNamespace

import httpx
import pytest

from agent_runtime.career import treg_config
from agent_runtime.career.external_tool_usage import ExternalToolLedger
from agent_runtime.career.treg_client import TregClient
from test_career_flow import career, execute  # noqa: F401
from test_remaining_search_completion import URL, prepare

CRAWL_ROWS = {'rows': [{'job_id': '4468908584', 'url': 'https://www.linkedin.com/jobs/view/junior-data-analyst-4468908584',
                        'title': 'Junior Data Analyst', 'company': 'B Co', 'location': 'New York, NY', 'posted_on': '2026-10-01'}]}
JD = ('Junior Data Analyst at B Co\n\n## Responsibilities\n' + 'Build dashboards and reports. ' * 40 +
      '\n## Requirements\n1-3 years of SQL experience. ' + 'Python and Tableau. ' * 20)


class Discovery:
    def __init__(self, directory=(), job=None):
        self.directory, self._job, self.calls = list(directory), job, []

    def search_directory(self, query, location='', limit=10, *, cancelled=None, **_):
        self.calls.append(('directory', query))
        return {'jobs': list(self.directory), 'errors': [], 'sources_checked': [], 'skipped_sources': [], 'board_outcomes': []}

    def search(self, query, location='', boards=None, limit=10, excluded_hosts=(), excluded_sources=()):
        self.calls.append(('public', query))
        return {'jobs': [], 'errors': [], 'sources_checked': [], 'skipped_sources': []}

    def job(self, url):
        self.calls.append(('job', url))
        return self._job or {'url': url, 'title': 'Data Analyst', 'company': 'Synthetic', 'location': 'New York, NY',
                             'description': 'Requirements: 0-2 years of marketing or analytics experience. SQL.'}


def treg_env(monkeypatch, **extra):
    env = {'TREG_TOKEN': 'fake-test-token', 'JOB_AGENT_TREG_ENABLED': '1', 'JOB_AGENT_JOB_API_FIRST': '1',
           'JOB_AGENT_TREG_SEARCH_PROVIDER': 'crawl4ai', **extra}
    for k, v in env.items():
        monkeypatch.setenv(k, v)


def install_treg(c, handler):
    cfg = treg_config.load()
    seen = []
    def wrapped(request):
        seen.append(str(request.url))
        return handler(request)
    c.harness._treg_client = TregClient(cfg, ExternalToolLedger(c.repository.sessions),
                                        transport=httpx.MockTransport(wrapped), sleep=lambda _s: None)
    return seen


def ok(body, cost='150'):
    return httpx.Response(200, json=body, headers={'X-Treg-Cost-Micro': cost, 'X-Treg-Call-Id': 'c1'})


def ask(c, text):
    c.repository.append(c.state['task_id'], role='user', text=text)


# --- routing ------------------------------------------------------------------------------

def test_flags_off_keep_the_old_search_route(career, monkeypatch):
    c = career
    prepare(c)
    c.harness.discovery = Discovery()
    execute(c, 'search_jobs', query='junior data analyst', location='New York, NY')
    assert c.harness.discovery.calls == [('public', 'junior data analyst')]
    assert c.harness._treg() is None


def test_api_first_uses_the_directory_without_treg(career, monkeypatch):
    monkeypatch.setenv('JOB_AGENT_JOB_API_FIRST', '1')
    c = career
    prepare(c)
    c.harness.discovery = Discovery()
    result = execute(c, 'search_jobs', query='junior data analyst', location='New York, NY')
    assert c.harness.discovery.calls == [('directory', 'junior data analyst')]
    assert 'treg_supplement' in result and result['treg_supplement']['error_code'] == 'treg_unavailable'


def test_linkedin_only_never_traverses_other_boards(career, monkeypatch):
    monkeypatch.setenv('JOB_AGENT_JOB_API_FIRST', '1')
    c = career
    prepare(c)
    ask(c, 'Find junior data analyst jobs only on LinkedIn.')
    c.harness.discovery = Discovery()
    result = execute(c, 'search_jobs', query='junior data analyst', location='New York, NY')
    assert result['error_code'] == 'treg_unavailable' and c.harness.discovery.calls == []


def test_linkedin_only_with_treg_returns_candidate_cards_and_records_spend(career, monkeypatch):
    treg_env(monkeypatch)
    c = career
    prepare(c)
    ask(c, '只在LinkedIn上找初级数据分析师')
    seen = install_treg(c, lambda r: ok(CRAWL_ROWS))
    c.harness.discovery = Discovery()
    result = execute(c, 'search_jobs', query='junior data analyst', location='New York, NY')
    assert seen == ['https://treg.to/call/crawl4ai.linkedin.search.jobs'] and c.harness.discovery.calls == []
    assert result['jobs'][0]['completeness'] == 'card' and result['treg']['charged_micro'] == 150
    ledger = ExternalToolLedger(c.repository.sessions).summary(c.state['task_id'])
    assert ledger['confirmed_micro'] == 150 and ledger['complete']


def test_directory_empty_gets_one_treg_supplement_unless_linkedin_excluded(career, monkeypatch):
    treg_env(monkeypatch)
    c = career
    prepare(c)
    seen = install_treg(c, lambda r: ok(CRAWL_ROWS))
    c.harness.discovery = Discovery(directory=[])
    result = execute(c, 'search_jobs', query='junior data analyst', location='New York, NY')
    assert seen and result['jobs'] and result['treg_supplement']['treg']['provider'] == 'crawl4ai'
    ask(c, 'Search again for data analyst roles, no LinkedIn please.')
    before = len(seen)
    execute(c, 'search_jobs', query='data analyst', location='New York, NY')
    assert len(seen) == before


# --- reading ------------------------------------------------------------------------------

def test_api_first_does_not_force_browser_for_an_already_open_page(career, monkeypatch):
    monkeypatch.setenv('JOB_AGENT_JOB_API_FIRST', '1')
    c = career
    prepare(c)
    browser_calls = []
    c.harness._browsing = SimpleNamespace(inspect=lambda _t: {'url': URL, 'title': 'open'},
        call=lambda *a, **k: browser_calls.append(a) or {}, close=lambda: None)
    c.harness.discovery = Discovery()
    job = execute(c, 'read_job', url=URL)
    assert job['description'] and browser_calls == [] and ('job', URL) in c.harness.discovery.calls


def test_treg_scrape_used_only_for_a_complete_bound_jd(career, monkeypatch):
    treg_env(monkeypatch, JOB_AGENT_TREG_CRAWL4AI_SCRAPE_ENABLED='1')
    c = career
    prepare(c)
    link = CRAWL_ROWS['rows'][0]['url']
    c.repository.change(c.state['task_id'], search_candidates={'k': {'url': 'https://www.linkedin.com/jobs/view/4468908584/',
        'title': 'Junior Data Analyst', 'company': 'B Co', 'location': 'New York, NY'}})
    install_treg(c, lambda r: ok({'ok': True, 'markdown': JD, 'content_hash': 'h'}))
    c.harness.discovery = Discovery()
    job = execute(c, 'read_job', url=link)
    assert job['source'] == 'treg:crawl4ai.web.scrape' and ('job', link) not in c.harness.discovery.calls


def test_treg_scrape_login_wall_falls_back_and_ats_urls_skip_treg(career, monkeypatch):
    treg_env(monkeypatch, JOB_AGENT_TREG_CRAWL4AI_SCRAPE_ENABLED='1')
    c = career
    prepare(c)
    seen = install_treg(c, lambda r: ok({'ok': True, 'markdown': 'Sign in to view this job. ' + JD}))
    c.harness.discovery = Discovery()
    link = 'https://www.linkedin.com/jobs/view/junior-data-analyst-4468908584'
    execute(c, 'read_job', url=link)
    assert ('job', link) in c.harness.discovery.calls  # not proven complete: existing path
    before = len(seen)
    execute(c, 'read_job', url='https://boards.greenhouse.io/acme/jobs/123')
    assert len(seen) == before  # supported ATS: never a paid scrape


# --- candidate batches --------------------------------------------------------------------

def test_candidate_gate_finishes_started_work_before_more_discovery(career, monkeypatch):
    monkeypatch.setenv('JOB_AGENT_OPT_CANDIDATE_BATCHES', '1')
    c = career
    prepare(c)
    c.harness.discovery = Discovery()
    execute(c, 'read_job', url=URL)  # read, not imported
    blocked = execute(c, 'search_jobs', query='junior data analyst', location='New York, NY')
    assert blocked['error_code'] == 'candidates_in_progress' and blocked['in_progress'][0]['stage'] == 'import'
    job = execute(c, 'import_job', url=URL)
    blocked = execute(c, 'search_jobs', query='junior data analyst', location='New York, NY')
    assert blocked['error_code'] == 'candidates_in_progress' and blocked['in_progress'][0]['stage'] == 'score'
    execute(c, 'score_job', application_id=job['application_id'])
    blocked = execute(c, 'search_jobs', query='junior data analyst', location='New York, NY')
    assert blocked['error_code'] == 'pending_decisions'  # the decision gate takes over
    execute(c, 'decide_job', application_id=job['application_id'], decision='exclude',
            reason='Requires on-site work in another city than requested.')
    assert 'error_code' not in execute(c, 'search_jobs', query='junior data analyst', location='New York, NY')


def test_candidate_view_bounds_detail_and_reports_target(career, monkeypatch):
    monkeypatch.setenv('JOB_AGENT_OPT_CANDIDATE_BATCHES', '1')
    c = career
    prepare(c)
    candidates = {f'k{i}': {'url': f'https://boards.greenhouse.io/acme/jobs/{100 + i}', 'title': f'Data Analyst {i}'}
                  for i in range(12)}
    c.repository.change(c.state['task_id'], search_candidates=candidates)
    view = c.harness.observe(c.repository.get(c.state['task_id']))['candidate_queue']
    assert len(view['next_unread']) == 5 and view['deferred_unread'] >= 3 and not view['target_reached']
