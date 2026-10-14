"""Explicit paid decision replay: the real main model decides already scored jobs.

Restores a saved live sample at the point where its jobs were scored, without any
source read, qualification or scoring call (those tools are recorded, not run), and
caps the replay at 10 main-model calls. It checks that the model reaches a decision
for every scored job and moves on, instead of paging the same reports.
"""
import json
import os
import shutil
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

WORK_TOOLS = {'search_jobs', 'screen_jobs', 'read_job', 'import_job', 'verify_and_score', 'verify_and_score_jobs',
              'score_job', 'score_jobs'}
MAX_MODEL_CALLS = 10
LIMITS = {'JOB_AGENT_JOB_API_FIRST': '1', 'JOB_AGENT_TREG_ENABLED': '0',
          'JOB_AGENT_TASK_MAX_PROVIDER_ATTEMPTS': '100', 'JOB_AGENT_TASK_MAX_INPUT_TOKENS': '1500000',
          'JOB_AGENT_LINKEDIN_MAX_CALLS': '100', 'JOB_AGENT_ANALYSIS_WARMUP': '0'}


class ReplayStop(RuntimeError):
    pass


@pytest.mark.skipif(os.getenv('JOB_AGENT_LIVE_DECISION_REPLAY') != '1', reason='Explicit paid live opt-in')
def test_decision_replay(tmp_path, monkeypatch):
    from eregion.api.db import create_database
    from eregion.runtime.career.repository import TaskRepository
    from eregion.runtime.career.service import CareerService
    from eregion.runtime.career.harness import CareerHarness
    from eregion.runtime.career import qualification
    from eregion.runtime.provider_usage import UsageLedger
    from eregion.runtime.tasks.loop import TaskModel
    from test_career_flow import (JobWorkspaceRepository, CareerEvidenceRepository, PackRepository,
                                  ApplicationLoop, ApplyRepository, upgrade_database)

    source = Path(os.environ['REPLAY_SOURCE'])
    output = Path(os.environ['OPT_LIVE_OUTPUT'])
    assert not output.exists(), 'Never overwrite or automatically repeat a live sample'
    output.mkdir(parents=True)
    for key, value in LIMITS.items():
        monkeypatch.setenv(key, value)
    database = tmp_path / 'career.db'
    with sqlite3.connect(f'file:{(source / "career.sqlite3").as_posix()}?mode=ro', uri=True) as original, \
            sqlite3.connect(database) as copy:
        original.backup(copy)
    url = f'sqlite:///{database.as_posix()}'
    upgrade_database(url)
    db = create_database(url)
    workspace = JobWorkspaceRepository(db.session_factory)
    runtime = SimpleNamespace(database=db, workspace=workspace, evidence=CareerEvidenceRepository(db.session_factory),
                              packs=PackRepository(db.session_factory), pack_workflow=None, mock_interviewer=None)
    repository = TaskRepository(db.session_factory)
    applications = ApplicationLoop(ApplyRepository(db.session_factory), browser_factory=lambda url: None)

    def no_paid_semantics(*_, **__):
        raise AssertionError('Decision replay must not call qualification or scoring.')
    monkeypatch.setattr(qualification, 'judge', no_paid_semantics)

    # Same scorer configuration as the live sample, so its saved scores stay current;
    # scoring itself is never executed here.
    from dataclasses import replace
    from eregion.api.services.fit_analysis_service import FitAnalysisService
    from eregion.domain.jev_fit.settings import Settings
    harness = CareerHarness(runtime, applications, repository)
    harness.analysis._fit_service = FitAnalysisService(jev_enabled=True,
        jev_config=replace(Settings.load(cache_path=tmp_path / 'fit.sqlite3'), resolve_unknowns=False))
    task_id = next(s['task_id'] for s in repository.list())
    state = repository.get(task_id)
    scored = sorted(state.get('scored_job_evidence') or {})
    assert scored, 'The source sample has no scored jobs to decide.'
    # Free precondition: every saved score is current for this resume and scorer.
    _, resume_text = harness.candidate()
    for app in scored:
        snapshot = runtime.workspace.get_application(app).current_snapshot_id
        assert state['analyses'].get(app) == harness.analysis_fingerprint(resume_text, snapshot),             'Replay setup does not reproduce the sample scorer; no model call made.'
    # Restore the moment the jobs were scored: no decisions, no stalled transcript.
    repository.change(task_id, recommendations=[], job_decisions={}, error=None, status='queued', pause_requested=False,
                      progress_guard={}, loop_runtime=None, history=[], input_request=None, wait=None,
                      messages=[m for m in state['messages'] if m.get('role') == 'user'])

    attempted, invocations = [], []
    original_execute = harness.execute

    def execute(task, name, args, *, call_id):
        if name in WORK_TOOLS:
            # Recorded, not executed: the replay ends once the model moves on to new work.
            attempted.append({'tool': name, 'arguments': args})
            repository.change(task, pause_requested=True)
            return {'replay_not_executed': True, 'next': 'Recorded by the decision replay; not executed.'}
        return original_execute(task, name, args, call_id=call_id)
    harness.execute = execute

    class Counted:
        def __init__(self):
            self.model = TaskModel()

        def invoke(self, messages, tools):
            if len(invocations) >= MAX_MODEL_CALLS:
                repository.change(task_id, pause_requested=True)
                raise ReplayStop('Replay model-call cap reached.')
            invocations.append(time.monotonic())
            return self.model.invoke(messages, tools)

    ledger = UsageLedger(db.session_factory)
    before = ledger.summary(task_id=task_id)
    # The sample's recorded spend is history; the replay's own spend is bounded by the
    # 10-model-call cap and the shared experiment ledger, not by what the sample used.
    monkeypatch.setenv('JOB_AGENT_TASK_MAX_PROVIDER_ATTEMPTS', str(before['calls'] + 40))
    monkeypatch.setenv('JOB_AGENT_TASK_MAX_INPUT_TOKENS', str(before.get('budget_input_tokens', before['input_tokens']) + 1_500_000))
    service = CareerService(runtime, applications, harness=harness, model_factory=Counted, start_alert_scheduler=False)
    started = time.monotonic()
    try:
        service.loop.schedule(task_id)
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            current = repository.get(task_id)
            if task_id not in service.loop.running and current['status'] != 'queued':
                break
            time.sleep(.5)
    finally:
        service.close()
    final = repository.get(task_id)
    after = ledger.summary(task_id=task_id)
    decisions = {a: ('recommended' if any(r.get('application_id') == a for r in final.get('recommendations', []))
                     else (final.get('job_decisions') or {}).get(a, {}).get('decision'))
                 for a in scored}
    reads = [json.dumps({'tool': h['tool'], 'arguments': h.get('arguments')}, sort_keys=True)
             for h in final.get('history', []) if h['tool'] in {'read_context', 'inspect_job'}]
    repeated_reads = len(reads) - len(set(reads))
    moved_on = any(a['tool'] in WORK_TOOLS for a in attempted)
    result = {'source': str(source), 'scored_jobs': len(scored), 'decisions': decisions,
              'all_decided': all(decisions.values()), 'repeated_reads': repeated_reads,
              'reads': len(reads), 'moved_on_to': attempted[:1], 'model_calls': len(invocations),
              'tools': [h['tool'] for h in final.get('history', [])],
              'usage_delta': {k: after.get(k, 0) - before.get(k, 0) for k in ('calls', 'input_tokens', 'output_tokens', 'unknown_usage_calls')},
              'seconds': round(time.monotonic() - started, 2), 'error': final.get('error'), 'cost_usd': None}
    recommendations = final.get('recommendations', [])
    result['tiers'] = {r['application_id']: {'title': r.get('title'), 'tier': r.get('tier'), 'gaps': r.get('gaps'),
                       'to_confirm': r.get('to_confirm'), 'next_steps': r.get('next_steps'), 'reason': r.get('reason'),
                       'match_score': r.get('match_score')} for r in recommendations}
    result['excluded_or_unclear'] = {a: d for a, d in (final.get('job_decisions') or {}).items()}
    result['passed'] = bool(result['all_decided'] and not repeated_reads and moved_on
                            and result['model_calls'] <= MAX_MODEL_CALLS)
    if os.getenv('REPLAY_TIER_AUDIT') == '1' and recommendations:
        # Independent tiered-recommendations-v1 audit of the replay's presentations,
        # under its own 6-call / 200k cap (and the shared experiment budget).
        from evals.tiered_audit import review, contract_checks
        from evals.search_semantic_audit import candidate_hash
        from eregion.runtime.provider_usage import usage_scope
        jobs = [harness.job_summary(a, detail=True) for a in scored]
        facts = harness.fit_facts()
        candidate = (resume_text or '') + ('\nCANDIDATE-STATED FACTS\n' + json.dumps(facts, sort_keys=True) if facts else '')
        audit_task = 'replay-audit-' + task_id
        monkeypatch.setenv('JOB_AGENT_TASK_MAX_PROVIDER_ATTEMPTS', '6')
        monkeypatch.setenv('JOB_AGENT_TASK_MAX_INPUT_TOKENS', '200000')
        audit_started = time.monotonic()
        with usage_scope(task_id=audit_task, ledger=ledger):
            audit = review(final['goal'], jobs, recommendations, candidate)
        checks = {j['url']: contract_checks(j, audit, final['goal'], candidate_hash(candidate)) for j in jobs
                  if any(r.get('url') == j['url'] for r in recommendations)}
        result['audit'] = {'usage': {k: ledger.summary(task_id=audit_task).get(k) for k in
                                     ('calls', 'input_tokens', 'output_tokens', 'unknown_usage_calls')},
                           'seconds': round(time.monotonic() - audit_started, 2),
                           'counted': sum(all(v.values()) for v in checks.values()), 'checks': checks,
                           'independent_tiers': {u: (row.get('independent') or {}).get('tier') for u, row in audit.items()},
                           'presentation': {u: row.get('presentation') for u, row in audit.items() if row.get('presentation')}}
    (output / 'replay.json').write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    (output / 'transcript.json').write_text(json.dumps(final, indent=2, ensure_ascii=False, default=str), encoding='utf-8')
    db.close()
    assert result['passed'], result
