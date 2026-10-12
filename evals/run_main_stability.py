"""A1 stability only. Default creates an offline plan; --live spends real API calls.

Fresh services and disabled result/persistent caches per trial. No automatic resume
or repeat of a failed trial. Human-labelled accuracy remains a separate gate.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
import hashlib
import json
import math
from pathlib import Path
from threading import Lock
from time import perf_counter
from uuid import uuid4

THRESHOLDS = {'cold_runs_per_pair': 4, 'spread_max': 8, 'requirements_max': 30,
              'stress_runs': 32, 'concurrency': 6, 'timeouts_max': 0}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def implementation_signature():
    root = Path(__file__).resolve().parents[1]
    paths = ['job_agent/job_extraction.py', 'job_agent/batch_retry.py', 'job_agent/fast_match.py',
             'job_agent/jev_fit/core.py', 'job_agent/prompts.py', 'job_agent/schemas.py',
             'job_agent/domain.py', 'job_agent/partial_support.py', 'job_agent/resume_extraction.py', 'job_agent/compact_match.py',
             'job_agent/workflow/handlers.py', 'api/services/fit_analysis_service.py',
             'job_agent/model.py', 'job_agent/requirement_catalog.py',
             'agent_runtime/provider_usage.py', 'agent_runtime/fast_decisions.py',
             'evals/run_main_stability.py']
    return digest({path: hashlib.sha256((root/path).read_bytes()).hexdigest() for path in paths})


def make_plan(data, *, suite='all', runtime=None):
    from evals.run_fit_labels import validate
    checked = validate(data)
    if checked['errors']:
        raise ValueError('Dataset failed strict validation: ' + '; '.join(checked['errors']))
    trials = []
    people = {a['applicant_id']: a for a in data['applicants']}
    jobs = {j['job_id']: j for j in data['jobs']}
    def trial(pair, lane, repeat):
        a, j = people[pair['applicant_id']], jobs[pair['job_id']]
        return {'trial_id': f"{lane}:{pair['pair_id']}:{repeat}", 'lane': lane, 'repeat': repeat,
                'pair_id': pair['pair_id'], 'applicant_id': a['applicant_id'], 'job_id': j['job_id'],
                'format': 'structured', 'resume_sha256': a['resume_sha256'],
                'body_sha256': j['structured_sha256']}
    if suite in {'all', 'cold4'}:
        trials.extend(trial(pair, 'cold4', repeat) for pair in data['pairs'] for repeat in range(4))
    if suite == 'sample':
        # Reduced, user-approved sample: 8 evenly spaced pairs x 4 cold runs. It reports
        # the same per-pair spread rule but is NOT the full 72-pair cold4 criterion.
        sampled = [data['pairs'][i * len(data['pairs']) // 8] for i in range(8)]
        trials.extend(trial(pair, 'cold4', repeat) for pair in sampled for repeat in range(4))
    if suite in {'all', 'stress32', 'sample'}:
        trials.extend(trial(data['pairs'][i * len(data['pairs']) // 32], 'stress32', i) for i in range(32))
    plan = {'schema_version': 1, 'run_id': str(uuid4()), 'created_at': datetime.now(UTC).isoformat(),
            'dataset_revision': data['revision'], 'dataset_sha256': digest(data),
            'implementation_signature': implementation_signature(), 'runtime': runtime,
            'mode': 'live' if runtime else 'offline_plan', 'suite': suite,
            'thresholds': dict(THRESHOLDS), 'partial_credit': .5,
            'cache_policy': 'fresh service per trial; cache_size=0; persistent cache=None; Jev/fast disabled',
            'pending_human_reviews': checked['pending_reviews'], 'trials': trials}
    plan['manifest_sha256'] = digest(plan)
    return plan


def check_manifest(plan, data):
    content = {k: v for k, v in plan.items() if k != 'manifest_sha256'}
    if (digest(content) != plan.get('manifest_sha256') or digest(data) != plan.get('dataset_sha256')
            or plan.get('thresholds') != THRESHOLDS or plan.get('partial_credit') != .5):
        raise ValueError('Frozen manifest/input/threshold mismatch')
    expected = make_plan(data, suite=plan['suite'], runtime=plan['runtime'])['trials']
    if plan['trials'] != expected:
        raise ValueError('Frozen trial coverage changed; no partial suite can pass as complete')


def cold_service():
    from agent_runtime.fast_decisions import FastDecisions
    from job_agent.workflow.handlers import JobAgentStepHandler
    from api.services.fit_analysis_service import FitAnalysisService
    return FitAnalysisService(JobAgentStepHandler(decisions=FastDecisions(), analysis_cache=None),
                              cache_size=0, analysis_cache=None, jev_enabled=False)


def live_runtime():
    # This function alone reads application configuration. Offline paths never do.
    from langchain_core.globals import get_llm_cache
    if get_llm_cache() is not None:
        raise ValueError('Global LLM response cache must be disabled for genuine cold trials')
    from job_agent.model import create_model
    options = create_model(purpose='extraction', model_factory=lambda **options: options)
    if options['timeout'] < 180 or options['max_retries'] != 0:
        raise ValueError('Live A1 requires LLM_TIMEOUT>=180 and LLM_MAX_RETRIES=0; no configuration changed')
    return {'cache_signature': cold_service().cache_signature(), 'model_id': options['model'],
            'purpose': 'extraction', 'temperature': options['temperature'],
            'timeout_seconds': options['timeout'], 'sdk_retries': options['max_retries'],
            'reasoning': options.get('reasoning_effort'), 'typesafe_enabled': False,
            'typesafe_policy': 'Explicit FastDecisions() without credentials; main-only handler'}


def live_trial(trial, plan, data, sessions):
    from agent_runtime.provider_usage import UsageLedger, usage_scope
    from agent_runtime.model_runtime import model_failure
    # Track attempted persistence independently: a broken ledger cannot become
    # zero-cost or complete usage merely because only some rows were saved.
    class TrialLedger(UsageLedger):
        def __init__(self):
            super().__init__(sessions)
            self.attempted, self.finished, self.lock = set(), {}, Lock()
        def start(self, call_id, scope, details):
            with self.lock: self.attempted.add(call_id)
            return super().start(call_id, scope, details)
        def finish(self, call_id, details):
            with self.lock: self.finished[call_id] = {'call_id':call_id, **details}
            return super().finish(call_id, details)
    ledger = TrialLedger()
    task_id = str(uuid4())
    service = cold_service()
    signature = plan['runtime']['cache_signature']
    if service.cache_signature() != signature or implementation_signature() != plan['implementation_signature']:
        raise ValueError('Runtime version changed before trial; no provider called')
    person = next(a for a in data['applicants'] if a['applicant_id'] == trial['applicant_id'])
    job = next(j for j in data['jobs'] if j['job_id'] == trial['job_id'])
    row = {'task_id': task_id, 'scoring_signature': signature}
    try:
        with usage_scope(ledger=ledger, task_id=task_id, purpose='a1_main_stability'):
            result = service._analyze_sync(resume_text=person['resume'], job_description=job['structured'])
        row.update(status='completed', score=result.skill_match.overall_score,
                   requirement_count=len(result.job_analysis.requirements), cache_hits=result.cache_hits,
                   analysis=result.model_dump(mode='json'))
    except Exception as exc:
        failure = model_failure(exc)
        row.update(status='failed', error_type=failure.error_type, error_code=failure.code)
    row['provider_calls'] = list(ledger.finished.values())
    from agent_runtime.provider_usage import summarize
    row['observed_usage'] = summarize(row['provider_calls'])
    try:
        row['usage'] = ledger.summary(task_id=task_id)
        row['ledger_complete'] = (row['usage']['usage_complete'] and not row['usage']['pending']
            and row['usage']['calls'] == len(ledger.attempted) == len(ledger.finished))
    except Exception as exc:
        row['usage'] = {'calls':None, 'usage_complete':False, 'error_type':type(exc).__name__}
        row['ledger_complete'] = False
    try:
        row['signature_unchanged'] = (service.cache_signature() == signature
            and implementation_signature() == plan['implementation_signature'])
    except Exception as exc:
        row['signature_unchanged'] = False
        row['version_check_error'] = type(exc).__name__
    row['timeout_count'] = sum('timeout' in c.get('error_type', '').casefold()
                               for c in row['provider_calls'])
    row['timeout_count'] = max(row['timeout_count'], int(row.get('error_code') == 'model_timeout'))
    return row


def report(plan, rows, peak):
    expected = {t['trial_id']: t for t in plan['trials']}
    ids = [r.get('trial_id') for r in rows]
    integrity = (len(ids) == len(set(ids)) and set(ids) <= set(expected)
        and all(r.get('manifest_sha256') == plan['manifest_sha256'] and
                r.get('input_sha256') == digest(expected[r['trial_id']]) for r in rows))
    def valid(r):
        return (r.get('status') == 'completed' and r.get('ledger_complete') is True
                and r.get('signature_unchanged') is True and r.get('cache_hits') == []
                and r.get('scoring_signature') == (plan.get('runtime') or {}).get('cache_signature')
                and type(r.get('score')) in (int, float) and math.isfinite(r['score'])
                and 0 <= r['score'] <= 100 and type(r.get('requirement_count')) is int
                and 0 < r['requirement_count'] <= 30)
    groups = {}
    for row in rows:
        if expected.get(row.get('trial_id'), {}).get('lane') == 'cold4':
            groups.setdefault(expected[row['trial_id']]['pair_id'], []).append(row)
    cold_expected = {t['pair_id'] for t in expected.values() if t['lane'] == 'cold4'}
    spreads = {key: max(r['score'] for r in group)-min(r['score'] for r in group)
               for key, group in groups.items() if len(group) == 4 and all(valid(r) for r in group)}
    cold = None if not cold_expected else (set(spreads) == cold_expected and all(v <= 8 for v in spreads.values()))
    stress_rows = [r for r in rows if expected.get(r.get('trial_id'), {}).get('lane') == 'stress32']
    stress = None if not any(t['lane'] == 'stress32' for t in expected.values()) else (
        len(stress_rows) == 32 and peak == 6 and all(valid(r) and r.get('timeout_count') == 0 for r in stress_rows))
    complete = integrity and len(ids) == len(expected) and all(valid(r) for r in rows)
    passed = (plan['mode'] == 'live' and complete and cold is not False and stress is not False)
    return {'status': 'passed_selected_stability_suite' if passed else 'not_passed',
            'suite': plan.get('suite'),
            'coverage_note': ('reduced sample: 8 of 72 pairs for cold4; full A1 cold4 criterion not measured'
                              if plan.get('suite') == 'sample' else None),
            'mode': plan['mode'], 'manifest_sha256': plan['manifest_sha256'], 'integrity': integrity,
            'expected_trials': len(expected), 'observed_trials': len(rows), 'peak_active_trials': peak,
            'failed_trials': [r['trial_id'] for r in rows if not valid(r)],
            'timeout_events': sum(r.get('timeout_count', 0) for r in rows),
            'cold4_spread_check': cold, 'cold4_spreads': spreads, 'stress32_check': stress,
            'human_quality_metrics': None, 'pending_human_reviews': len(plan['pending_human_reviews']),
            'A2_A4': 'unmeasured: human gold and frozen comparison baseline required',
            'A5': 'failed/deferred by user; not run here', 'thresholds': dict(THRESHOLDS)}


def execute_plan(plan, data, output, run_trial):
    check_manifest(plan, data)
    # A new directory prevents overwriting failures or silently resuming paid work.
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output/'manifest.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
    (output/'frozen-inputs.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    lock, active, peak, rows = Lock(), 0, 0, []
    def worker(trial):
        nonlocal active, peak
        with lock: active += 1; peak = max(peak, active)
        started = perf_counter()
        try:
            row = run_trial(trial, plan, data, output)
        except Exception as exc:
            from agent_runtime.model_runtime import model_failure
            failure = model_failure(exc)
            row = {'status': 'failed', 'error_type': failure.error_type, 'error_code': failure.code,
                   'timeout_count': int(failure.code == 'model_timeout')}
        finally:
            with lock: active -= 1
        finished = perf_counter()
        return {**row, 'trial_id': trial['trial_id'], 'manifest_sha256': plan['manifest_sha256'],
                'input_sha256': digest(trial), 'started_monotonic': started,
                'finished_monotonic': finished, 'wall_seconds': finished-started}
    # Every future is consumed, including failures; successful chunks/trials are
    # never replayed. Each completed row and partial report is flushed immediately.
    with (output/'trials.jsonl').open('x', encoding='utf-8') as stream:
        with ThreadPoolExecutor(max_workers=6, thread_name_prefix='a1-cold') as pool:
            for future in as_completed([pool.submit(worker, t) for t in plan['trials']]):
                row = future.result(); rows.append(row)
                stream.write(json.dumps(row, ensure_ascii=False)+'\n'); stream.flush()
                (output/'report.json').write_text(json.dumps(report(plan, rows, peak), indent=2), encoding='utf-8')
    return report(plan, rows, peak)


def evaluate_run(source):
    """Recompute a frozen historical run offline; never consult current .env."""
    source=Path(source)
    plan=json.loads((source/'manifest.json').read_text(encoding='utf-8'))
    data=json.loads((source/'frozen-inputs.json').read_text(encoding='utf-8'))
    check_manifest(plan,data)
    path=source/'trials.jsonl'
    rows=[json.loads(s) for s in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []
    events=[]
    for row in rows:
        start,end=row.get('started_monotonic'),row.get('finished_monotonic')
        if not all(type(n) in (int,float) and math.isfinite(n) for n in (start,end)) or end<start:
            raise ValueError('Missing/invalid actual concurrency timing')
        events.extend(((start,1),(end,-1)))
    active=peak=0
    for _,delta in sorted(events):active+=delta;peak=max(peak,active)
    return {**report(plan,rows,peak),'evaluation_scope':'historical frozen run; current model configuration not read or verified',
        'implementation_matches_current_files':plan['implementation_signature']==implementation_signature()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, default=Path('evals/fit_labels_v1.json'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--suite', choices=['all', 'cold4', 'stress32', 'sample'], default='all')
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--evaluate-run', type=Path, help='Recompute existing frozen run offline; does not resume paid work')
    args = parser.parse_args()
    if args.evaluate_run:
        if args.live:parser.error('--evaluate-run cannot be combined with --live')
        result=evaluate_run(args.evaluate_run)
        args.output.mkdir(parents=True,exist_ok=False)
        (args.output/'report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps({'status':result['status'],'observed_trials':result['observed_trials']}))
        return 0 if result['status']=='passed_selected_stability_suite' else 2
    data = json.loads(args.dataset.read_text(encoding='utf-8'))
    plan = make_plan(data, suite=args.suite, runtime=live_runtime() if args.live else None)
    if not args.live:
        args.output.mkdir(parents=True, exist_ok=False)
        (args.output/'manifest.json').write_text(json.dumps(plan, indent=2), encoding='utf-8')
        (args.output/'frozen-inputs.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        result = report(plan, [], 0)
        (args.output/'report.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps({'status': 'offline_plan_only', 'expected_trials': len(plan['trials']), 'paid_calls': 0}))
        return 2
    from api.db import create_database
    # execute_plan owns exclusive output creation; the DB lives in that directory.
    db_holder = {}
    db_lock = Lock()
    def run(trial, plan, data, output):
        with db_lock:
            if 'db' not in db_holder:
                db_holder['db'] = create_database('sqlite:///'+(output/'usage.sqlite3').resolve().as_posix(), create_schema_for_tests=True)
        return live_trial(trial, plan, data, db_holder['db'].session_factory)
    try:
        result = execute_plan(plan, data, args.output, run)
    finally:
        if db_holder.get('db'): db_holder['db'].close()
    print(json.dumps({k: result[k] for k in ('status', 'expected_trials', 'observed_trials', 'timeout_events')}))
    return 0 if result['status'] == 'passed_selected_stability_suite' else 1


if __name__ == '__main__':
    raise SystemExit(main())
