"""Strict human-gold fit evaluation. Offline by default; --live spends API calls.

Pending labels and absent cached predictions never become zero-error successes.
Predicted requirement matching uses only human-approved wording and quotes.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import UTC, datetime
import hashlib
import json
import math
from pathlib import Path
import re
from statistics import mean, median
from time import perf_counter
from uuid import uuid4

ALGORITHMS = ('main', 'jev')
FORMATS = ('structured', 'flat')
STATUSES = {'matched', 'partial', 'missing', 'unknown', 'needs_confirmation', 'confirmed_condition'}
THRESHOLDS = {'format_delta_max': 10, 'format_delta_passing_fraction': 0.9,
    'requirement_count_ratio_min': 0.8, 'requirement_count_ratio_max': 1.25,
    'mismatch_fit_auc_min': 0.9, 'mismatch_median_max': 15, 'fit_mean_drop_max': 5,
    'main_four_cold_spread_max': 8, 'typical_jd_requirements_max': 30,
    'concurrent_runs': 32, 'concurrency': 6, 'allowed_timeouts': 0}


def sha(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def norm(value):
    return ' '.join(re.sub(r'[^\w\s]', ' ', value.casefold()).split())


def number(value):
    return type(value) in {int, float} and math.isfinite(value)


def human(review):
    person = (review or {}).get('reviewer') or {}
    return (review or {}).get('status') == 'confirmed' and person.get('kind') == 'human' and bool(
        person.get('name') and person.get('confirmed_at'))


def validate(data):
    errors, pending = [], []
    people, jobs, pairs = data.get('applicants', []), data.get('jobs', []), data.get('pairs', [])
    if data.get('schema_version') != 1: errors.append('schema_version must be 1')
    if data.get('thresholds') != THRESHOLDS: errors.append('Original thresholds changed or omitted')
    if (len(people), len(jobs), len(pairs)) != (6, 12, 72): errors.append('Expected 6 applicants x 12 jobs = 72 pairs')
    fields = Counter(j.get('field') for j in jobs)
    if len(fields) != 4 or set(fields.values()) != {3}: errors.append('Expected four fields, three jobs each')
    by_person = {a.get('applicant_id'): a for a in people}
    by_job = {j.get('job_id'): j for j in jobs}
    if len(by_person) != len(people) or len(by_job) != len(jobs): errors.append('Duplicate applicant/job ID')
    for a in people:
        if a.get('synthetic') is not True or not a.get('resume'): errors.append('Only nonempty synthetic applicants allowed')
        if sha(a.get('resume', '')) != a.get('resume_sha256'): errors.append(f"Resume hash mismatch: {a.get('applicant_id')}")
    for j in jobs:
        key = j.get('job_id'); source = j.get('source') or {}
        if not all(j.get(v) for v in ('title', 'company', 'location', 'url', 'structured', 'flat')):
            errors.append(f'Missing source identity/body: {key}')
        for form in FORMATS:
            if sha(j.get(form, '')) != j.get(form+'_sha256'): errors.append(f'Body hash mismatch: {key}/{form}')
        if j.get('flat') != ' '.join(j.get('structured', '').split()): errors.append(f'Flattening changed content: {key}')
        checks = source.get('boundary_checks') or {}
        if not all(checks.get(v) is True for v in ('identity', 'title', 'location', 'single_record_body')):
            errors.append(f'Unverified source scope: {key}')
        if not source.get('raw_sha256') or not source.get('api_url'): errors.append(f'Missing primary provenance: {key}')
        for label, review in [('source', source.get('human_review')), ('requirements', j.get('requirements_review'))]:
            if not human(review):
                pending.append(f'{key}:{label}')
                if (review or {}).get('status') == 'confirmed': errors.append(f'Confirmed {label} lacks human provenance: {key}')
        requirements = (j.get('requirements_review') or {}).get('requirements') or []
        if human(j.get('requirements_review')) and not requirements: errors.append(f'Confirmed requirements empty: {key}')
        seen = set()
        for r in requirements:
            rid = r.get('requirement_id')
            if not rid or rid in seen: errors.append(f'Duplicate/missing human requirement ID: {key}')
            seen.add(rid)
            start, end = r.get('source_start'), r.get('source_end')
            if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(j.get('structured', '')) or j['structured'][start:end] != r.get('quote'):
                errors.append(f'Invalid exact JD quote/span: {key}/{rid}')
            if r.get('level') not in {'required', 'preferred'}: errors.append(f'Invalid requirement level: {key}/{rid}')
            if not r.get('atomic_text'): errors.append(f'Missing atomic requirement text: {key}/{rid}')
    expected = {(a, j) for a in by_person for j in by_job}; observed = set()
    for p in pairs:
        key = (p.get('applicant_id'), p.get('job_id'))
        if key in observed or key not in expected: errors.append(f'Duplicate or unknown pair: {key}')
        observed.add(key)
        if not all(isinstance(k, str) for k in key) or p.get('pair_id') != '::'.join(key): errors.append(f'Wrong pair ID: {key}')
        if not human(p.get('review')):
            pending.append(p.get('pair_id'))
            if (p.get('review') or {}).get('status') == 'confirmed': errors.append(f'Pair confirmed without human provenance: {key}')
            continue
        if not number(p.get('labelled_score')) or not 0 <= p['labelled_score'] <= 100: errors.append(f'Missing/invalid labelled score: {key}')
        if p.get('fit_label') not in {'fit', 'mismatch'}: errors.append(f'Missing fit/mismatch human label: {key}')
        job = by_job.get(key[1], {})
        requirements = (job.get('requirements_review') or {}).get('requirements') or []
        labels = p.get('requirement_statuses') or []
        ids = [v.get('requirement_id') for v in labels]
        if len(set(ids)) != len(ids) or set(ids) != {r['requirement_id'] for r in requirements}: errors.append(f'Incomplete per-requirement human labels: {key}')
        resume = by_person.get(key[0], {}).get('resume', '')
        for v in labels:
            if v.get('status') not in STATUSES: errors.append(f'Invalid human status: {key}')
            if v.get('status') in {'matched', 'partial'} and not v.get('resume_quotes'): errors.append(f'Matched/partial needs exact resume evidence: {key}')
            for quote in v.get('resume_quotes') or []:
                if not quote or quote not in resume: errors.append(f'Invalid resume quote: {key}')
            if not v.get('rationale'): errors.append(f'Missing human rationale: {key}')
    if observed != expected: errors.append('Pair cartesian product incomplete')
    return {'errors': errors, 'pending_reviews': pending, 'human_gold_complete': not errors and not pending}


def row_key(row):
    return row['applicant_id'], row['job_id'], row['algorithm'], row['format']


def freeze_manifest(data, signatures, *, run_id=None, created_at=None):
    manifest = {'schema_version': 1, 'run_id': run_id or str(uuid4()),
        'created_at': created_at or datetime.now(UTC).isoformat(),
        'dataset_id': data['dataset_id'], 'dataset_revision': data['revision'],
        'inputs': {'applicants': {a['applicant_id']: a['resume_sha256'] for a in data['applicants']},
            'jobs': {j['job_id']: {f: j[f+'_sha256'] for f in FORMATS} | {'revision': j['revision']} for j in data['jobs']}},
        'algorithms': {a: {'production_cache_signature': signatures[a]} for a in ALGORITHMS}}
    manifest['manifest_sha256'] = sha(json.dumps(manifest, sort_keys=True, separators=(',', ':')))
    return manifest


def validate_manifest(data, manifest, expected=None):
    if not isinstance(manifest, dict): return ['Missing frozen run manifest']
    errors = []
    unsigned = {k: v for k, v in manifest.items() if k != 'manifest_sha256'}
    if manifest.get('manifest_sha256') != sha(json.dumps(unsigned, sort_keys=True, separators=(',', ':'))):
        errors.append('Run manifest digest mismatch')
    if manifest.get('schema_version') != 1 or not manifest.get('run_id') or not manifest.get('created_at'):
        errors.append('Incomplete run identity')
    signatures = {a: (manifest.get('algorithms', {}).get(a) or {}).get('production_cache_signature') for a in ALGORITHMS}
    if not all(isinstance(v, str) and v for v in signatures.values()): errors.append('Missing algorithm production signature')
    reference = freeze_manifest(data, signatures, run_id=manifest.get('run_id'), created_at=manifest.get('created_at'))
    if any(manifest.get(k) != reference[k] for k in ('dataset_id', 'dataset_revision', 'inputs')):
        errors.append('Dataset revision/body/resume hashes differ from frozen run')
    if expected is not None:
        # Compare against an explicit frozen reference, never implicit current .env.
        if any(manifest.get(k) != expected.get(k) for k in ('dataset_id','dataset_revision','inputs','algorithms')):
            errors.append('Run version differs from explicit expected manifest; use a new run, preserve history')
    return errors


def validate_predictions(data, rows, manifest=None, expected_manifest=None):
    people = {a['applicant_id']: a for a in data['applicants']}
    jobs = {j['job_id']: j for j in data['jobs']}
    seen, errors = set(), []
    if rows or manifest is not None:
        errors.extend({'row': None, 'error': 'ManifestError', 'reason': reason}
            for reason in validate_manifest(data, manifest, expected_manifest))
    if errors: return errors
    for row in rows:
        try:
            key = row_key(row)
            if key in seen: raise ValueError('Duplicate prediction key')
            seen.add(key)
            if row['algorithm'] not in ALGORITHMS or row['format'] not in FORMATS: raise ValueError('Unknown algorithm/format')
            if row.get('run_id') != manifest['run_id'] or row.get('manifest_sha256') != manifest['manifest_sha256']:
                raise ValueError('Missing/mixed row run manifest identity')
            if row.get('scoring_signature') != manifest['algorithms'][row['algorithm']]['production_cache_signature']:
                raise ValueError('Missing/mixed/outdated row scoring signature')
            if row['resume_sha256'] != people[row['applicant_id']]['resume_sha256']: raise ValueError('Stale applicant hash')
            if row['job_sha256'] != jobs[row['job_id']][row['format']+'_sha256']: raise ValueError('Stale JD hash')
            if 'result' not in row and not row.get('error_type'): raise ValueError('Prediction has neither result nor explicit failure')
            if row.get('result'):
                from api.services.fit_analysis_service import FitAnalysisResult
                FitAnalysisResult.model_validate(row['result'])
        except (KeyError, ValueError, TypeError) as exc:
            errors.append({'row': row.get('pair_id'), 'error': type(exc).__name__, 'reason': str(exc)[:250]})
    return errors


def auc(labels, scores):
    positives = [s for label, s in zip(labels, scores) if label == 'fit']
    negatives = [s for label, s in zip(labels, scores) if label == 'mismatch']
    if not positives or not negatives: return None
    return sum((a > b) + .5*(a == b) for a in positives for b in negatives)/(len(positives)*len(negatives))


def score(row):
    value = ((row or {}).get('result') or {}).get('skill_match', {}).get('overall_score')
    return value if number(value) else None


def metrics(data, rows, algorithm, form):
    index = {row_key(r): r for r in rows}
    jobs = {j['job_id']: j for j in data['jobs']}
    tp = predicted_count = gold_count = status_correct = level_correct = 0
    absolute_errors, labels, scores, mismatch_scores = [], [], [], []
    for pair in data['pairs']:
        row = index.get((pair['applicant_id'], pair['job_id'], algorithm, form), {})
        result = row.get('result') or {}; job = result.get('job_analysis') or {}
        gold = jobs[pair['job_id']]['requirements_review']['requirements']
        predicted = job.get('requirements') or []
        matches = {m['requirement_id']: m for m in (result.get('skill_match') or {}).get('matches', [])}
        statuses = {v['requirement_id']: v['status'] for v in pair['requirement_statuses']}
        used = set(); predicted_count += len(predicted); gold_count += len(gold)
        for requirement in predicted:
            names = {norm(requirement.get(k) or '') for k in ('atomic_text', 'source_text', 'original_text')}- {''}
            atomic=norm(requirement.get('atomic_text') or '')
            # A shared source sentence can support several independent atoms.
            # Prefer the specific atom/approved alias; only fall back to an
            # unambiguous quote. Check all gold (including used identities) so
            # a duplicate cannot consume another atom via their shared quote.
            equivalent=[r for r in gold if atomic and atomic in {
                norm(v) for v in [r['atomic_text'],*r.get('accepted_prediction_texts',[])]}]
            if not equivalent:
                equivalent=[r for r in gold if names & {
                    norm(v) for v in [r['atomic_text'],*r.get('accepted_prediction_texts',[])]}]
            if not equivalent:equivalent=[r for r in gold if norm(r['quote']) in names]
            if len(equivalent)!=1 or equivalent[0]['requirement_id'] in used:continue
            target = equivalent[0]; rid = target['requirement_id']; used.add(rid); tp += 1
            level_correct += requirement.get('level') == target['level']
            status_correct += matches.get(requirement['requirement_id'], {}).get('match_status') == statuses[rid]
        value = score(row)
        if value is not None:
            scores.append(value); labels.append(pair['fit_label']); absolute_errors.append(abs(value-pair['labelled_score']))
            if pair['fit_label'] == 'mismatch': mismatch_scores.append(value)
    complete_scores = len(scores) == len(data['pairs'])
    return {'requirement_precision': tp/predicted_count if predicted_count else 0,
        'requirement_recall': tp/gold_count if gold_count else None,
        'status_accuracy': status_correct/gold_count if gold_count else None,
        'level_accuracy': level_correct/gold_count if gold_count else None,
        'score_mae': mean(absolute_errors) if complete_scores else None,
        'mismatch_fit_auc': auc(labels, scores) if complete_scores else None,
        'mismatch_median': median(mismatch_scores) if complete_scores and mismatch_scores else None,
        'gold_requirements': gold_count, 'predicted_requirements': predicted_count,
        'point_score_count': len(scores), 'missing_or_interval_only_scores': len(data['pairs'])-len(scores),
        'matching_policy': 'Unique exact atomic/human-approved alias first, then unique quote fallback; ambiguous shared quotes are rejected. One-to-one across all gold identities, including already-used identities; duplicates, unmatched and missing requirements are penalized. No model-assigned gold matching.'}


def evaluate(data, rows, manifest=None, expected_manifest=None):
    validation = validate(data)
    prediction_errors = validate_predictions(data, rows, manifest, expected_manifest) if not validation['errors'] else []
    expected = len(data.get('pairs', []))*len(ALGORITHMS)*len(FORMATS)
    successful = sum(bool(r.get('result')) and not r.get('error_type') for r in rows)
    complete = validation['human_gold_complete'] and not prediction_errors and successful == expected
    status = ('invalid' if validation['errors'] or prediction_errors else
        'pending_human_review' if validation['pending_reviews'] else
        'incomplete_predictions' if successful != expected else 'evaluated')
    index = {row_key(r): r for r in rows} if not prediction_errors and not validation['errors'] else {}
    format_metrics = {}
    for algorithm in ALGORITHMS:
        comparisons = []
        for pair in data.get('pairs', []):
            a = index.get((pair['applicant_id'], pair['job_id'], algorithm, 'structured'))
            b = index.get((pair['applicant_id'], pair['job_id'], algorithm, 'flat'))
            sa, sb = score(a), score(b)
            ca = len(((a or {}).get('result') or {}).get('job_analysis', {}).get('requirements', []))
            cb = len(((b or {}).get('result') or {}).get('job_analysis', {}).get('requirements', []))
            comparisons.append({'pair_id': pair['pair_id'], 'score_delta': abs(sa-sb) if sa is not None and sb is not None else None,
                'requirement_count_ratio': cb/ca if ca and b and b.get('result') else None})
        all_numeric = bool(comparisons) and all(c['score_delta'] is not None and c['requirement_count_ratio'] is not None for c in comparisons)
        fraction = mean(c['score_delta'] <= 10 for c in comparisons) if all_numeric else None
        ratios = all(.8 <= c['requirement_count_ratio'] <= 1.25 for c in comparisons) if all_numeric else None
        format_metrics[algorithm] = {'comparisons': comparisons, 'within_10_fraction': fraction,
            'all_count_ratios_in_0_8_to_1_25': ratios,
            'acceptance': 'passed' if complete and fraction is not None and fraction >= .9 and ratios else
                'failed' if complete else 'not_evaluable'}
    return {'dataset_id': data.get('dataset_id'), 'generated_at': datetime.now(UTC).isoformat(),
        'status': status, 'overall_acceptance': 'not_passed',
        'validation': validation, 'prediction_errors': prediction_errors,
        'run_manifest': manifest,
        'version_scope': 'Explicit expected frozen version' if expected_manifest else
            'Historical frozen run; not asserted to match current runtime/configuration' if manifest else 'No prediction run exists',
        'coverage': {'expected_pairs': 72, 'actual_pairs': len(data.get('pairs', [])),
            'expected_prediction_rows': 288, 'cached_rows': len(rows), 'successful_rows': successful,
            'failed_rows': sum(bool(r.get('error_type')) for r in rows),
            'missing_rows': max(0, expected-len(rows)), 'human_reviews_pending': len(validation['pending_reviews'])},
        'quality_metrics': {a: {f: metrics(data, rows, a, f) if complete else None for f in FORMATS} for a in ALGORITHMS},
        'format_delta': format_metrics, 'thresholds': THRESHOLDS,
        'unmeasured_acceptance': ['A1 four equivalent cold runs, <=30 typical requirements, 32 runs/6 concurrency/zero timeouts',
            'A4 fit mean drop <=5 requires frozen baseline; no partial weight changes',
            'A2 alert calibration requires reviewed labels; no threshold calibration from pending labels'],
        'note': 'Missing labels/predictions are explicit pending/incomplete, never skipped-case success. Interval-only production scores are not replaced by invented point scores. This report alone does not pass all A1/A2/A4.'}


def live_rows(data, cached, output, limit):
    from api.db import create_database, upgrade_database
    from api.services.fit_analysis_service import FitAnalysisService
    from agent_runtime.provider_usage import UsageLedger, usage_scope
    from job_agent.workflow.handlers import JobAgentStepHandler
    from agent_runtime.fast_decisions import FastDecisions
    from job_agent.jev_fit.settings import Settings
    output.parent.mkdir(parents=True, exist_ok=True)
    database_url = 'sqlite:///'+str(output.with_suffix('.usage.db').resolve()).replace('\\', '/')
    db = create_database(database_url)
    upgrade_database(database_url); ledger = UsageLedger(db.session_factory)
    services = {'main': FitAnalysisService(JobAgentStepHandler(decisions=FastDecisions()), jev_enabled=False),
        'jev': FitAnalysisService(jev_enabled=True, jev_config=Settings.load(cache_path=output.with_suffix('.jev.db')))}
    rows = list(cached.get('rows') or [])
    current = freeze_manifest(data, {a: services[a].cache_signature() for a in ALGORITHMS})
    manifest = cached.get('manifest')
    if manifest is not None or rows:
        errors = validate_predictions(data, rows, manifest, current)
        if errors: raise ValueError('Stale/unsigned/mixed existing cache; create a new run path and preserve the old run')
    else:
        manifest = current
    cache = {'manifest': manifest, 'rows': rows}
    # Freeze configuration before any paid operation, including an early failure.
    output.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding='utf-8')
    people = {a['applicant_id']: a for a in data['applicants']}; jobs = {j['job_id']: j for j in data['jobs']}
    known = {row_key(r) for r in rows}; new = 0
    for pair in data['pairs']:
        for algorithm in ALGORITHMS:
            for form in FORMATS:
                key = (pair['applicant_id'], pair['job_id'], algorithm, form)
                if key in known: continue  # Failed prior rows are retained, not silently paid-retried.
                if limit is not None and new >= limit: return cache
                a, j = people[key[0]], jobs[key[1]]; task = str(uuid4()); started = perf_counter()
                row = dict(zip(('applicant_id', 'job_id', 'algorithm', 'format'), key))
                row.update(pair_id=pair['pair_id'], resume_sha256=a['resume_sha256'], job_sha256=j[form+'_sha256'], task_id=task,
                    scoring_signature=manifest['algorithms'][algorithm]['production_cache_signature'],
                    run_id=manifest['run_id'], manifest_sha256=manifest['manifest_sha256'])
                try:
                    with usage_scope(task_id=task, ledger=ledger, purpose=f'fit_labels:{algorithm}:{form}'):
                        result = services[algorithm]._analyze_sync(resume_text=a['resume'], job_description=j[form])
                        row['result'] = result.model_dump(mode='json')
                except Exception as exc:
                    row['error_type'] = type(exc).__name__  # Never provider bodies/credentials.
                row.update(seconds=perf_counter()-started, usage=ledger.summary(task_id=task))
                rows.append(row); new += 1
                output.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding='utf-8')
    return cache


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, default=Path('evals/fit_labels_v1.json'))
    parser.add_argument('--cached', type=Path, default=Path('docs/benchmarks/fit-labels-v1-predictions.json'))
    parser.add_argument('--output', type=Path, default=Path('docs/benchmarks/fit-labels-v1-report.json'))
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--expected-manifest', type=Path, help='Optional frozen version to require; offline never reads current .env')
    parser.add_argument('--limit', type=int)
    args = parser.parse_args()
    data = json.loads(args.dataset.read_text(encoding='utf-8'))
    cache = json.loads(args.cached.read_text(encoding='utf-8')) if args.cached.exists() else {'manifest': None, 'rows': []}
    expected = json.loads(args.expected_manifest.read_text(encoding='utf-8')) if args.expected_manifest else None
    if expected and 'manifest' in expected: expected = expected['manifest']
    if args.live:
        check = validate(data)
        if check['errors'] or validate_predictions(data, cache['rows'], cache.get('manifest'), expected): parser.error('Invalid dataset/cache; no provider calls made')
        if args.limit is not None and args.limit < 1: parser.error('--limit must be positive')
        cache = live_rows(data, cache, args.cached, args.limit)
    report = evaluate(data, cache['rows'], cache.get('manifest'), expected)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    args.output.with_suffix('.md').write_text('# Fit labels v1 evaluation\n\n'+
        f"Status: **{report['status']}**. Overall acceptance: **{report['overall_acceptance']}**.\n\n"+
        'Human labels are pending until explicitly confirmed. Missing cases are not skipped successes.\n\n'+
        '```json\n'+json.dumps({k:report[k] for k in ('coverage','quality_metrics','thresholds','unmeasured_acceptance')},ensure_ascii=False,indent=2)+'\n```\n',encoding='utf-8')
    print(json.dumps({'status': report['status'], 'coverage': report['coverage']}))
    return 0 if report['status'] == 'evaluated' else 2


if __name__ == '__main__':
    raise SystemExit(main())
