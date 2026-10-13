"""R6 API-first B6 business gate (explicit paid opt-in; never part of the offline suite).

Same synthetic analyst, target, harness and evaluate_search assertions as the
browser-first node in test_remaining_live.py (kept unchanged with its historical
failure). Only the source sentence of the user task changes, per the gate
amendment, and the API-first configuration is switched on for this process.

Run exactly this node (PowerShell or Git Bash), with a NEW output directory:
    JOB_AGENT_LIVE_API_FIRST_B6=1 OPT_LIVE_OUTPUT=<new dir> \
    .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider \
      tests/test_api_first_b6_live.py::test_api_first_b6 --basetemp=<new dir>/tmp
"""
import json
import os
import subprocess
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from test_career_flow import career  # noqa: F401

LIVE = pytest.mark.skipif(os.getenv('JOB_AGENT_LIVE_API_FIRST_B6') != '1',
                          reason='Explicit paid real-model + Treg API-first B6 business gate')

# Model limits of the original B6 acceptance; Treg limits stay within the remaining
# authorized Treg batch ($0.10 / 20 requests): 15 calls before R6, run-1 used 2, so 3 remain.
FLAGS = {
    'JOB_AGENT_JOB_API_FIRST': '1',
    'JOB_AGENT_TREG_ENABLED': '1',
    'JOB_AGENT_TREG_SEARCH_PROVIDER': 'crawl4ai',
    'JOB_AGENT_TREG_CRAWL4AI_SCRAPE_ENABLED': '1',
    'JOB_AGENT_TREG_MAX_ATTEMPTS': '3',
    'JOB_AGENT_TREG_TASK_MAX_COST_USD': '0.05',
    'JOB_AGENT_TREG_CALL_MAX_COST_USD': '0.01',
    'JOB_AGENT_TASK_MAX_INPUT_TOKENS': '1000000',
    'JOB_AGENT_TASK_MAX_PROVIDER_ATTEMPTS': '60',
}
SOURCE_SENTENCE = ('Prefer the configured, contract-verified job-board APIs and Treg sources for candidates; '
                   'read the page only when the job description is missing or the evidence conflicts, and use '
                   'the browser for verification only when needed.')
GOAL = ('Find two current junior data analyst in New York positions for my saved resume. ' + SOURCE_SENTENCE + ' '
        'Read and score jobs you can verify, recommend any you can verify, and summarize the actual result. '
        'Respect the requested seniority and disclose blocked sources or insufficient results. '
        'Do not apply or create a schedule.')


def test_goal_drops_the_browser_first_instruction():
    assert 'Start with LinkedIn or Indeed' not in GOAL and 'job-board APIs' in GOAL


@LIVE
def test_api_first_b6(career, monkeypatch):
    from eregion.runtime.career.discovery import JobDiscovery
    from eregion.runtime.career.external_tool_usage import ExternalToolLedger
    from eregion.runtime.career.service import CareerService
    from eregion.api.services.fit_analysis_service import FitAnalysisService
    from eregion.domain.jev_fit.settings import Settings
    from eregion.domain.pdf_rendering import render_letter_pdf
    from scripts.e2e_repair_evaluation import APPLICANTS
    from test_remaining_live import settle_live

    output = Path(os.environ['OPT_LIVE_OUTPUT'])
    assert not output.exists(), 'Use a new output directory; never overwrite a paid sample'
    output.mkdir(parents=True)
    for key, value in FLAGS.items():
        monkeypatch.setenv(key, value)
    head = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    (output / 'invocation.json').write_text(json.dumps({'head': head, 'flags': FLAGS, 'goal': GOAL,
        'applicant': 'analyst', 'node': 'tests/test_api_first_b6_live.py::test_api_first_b6'}, indent=2),
        encoding='utf-8')

    c = career
    c.repository.change(c.state['task_id'], status='cancelled', pause_requested=True)
    c.applications.repository.save_candidate(
        {'first_name': 'Synthetic', 'last_name': 'analyst', 'email': 'analyst@example.com'},
        resume=render_letter_pdf(APPLICANTS['analyst']), name='synthetic.pdf', extracted=True)
    c.harness.discovery = JobDiscovery()
    c.harness.analysis._fit_service = FitAnalysisService(jev_enabled=True,
        jev_config=replace(Settings.load(cache_path=output / 'fit.sqlite3'), resolve_unknowns=False))
    service = CareerService(c.runtime, c.applications, harness=c.harness, start_alert_scheduler=False)
    service.loop.budget = 60
    task = None
    try:
        task = service.start(GOAL, str(uuid4()))
        result = settle_live(service, task['run_id'], output, 'analyst')
        assert not result['application_runs']
    finally:
        if task is not None:
            ledger = ExternalToolLedger(c.repository.sessions).summary(task['run_id'])
            (output / 'treg-ledger.json').write_text(json.dumps(ledger, indent=2, default=str), encoding='utf-8')
        service.close()
