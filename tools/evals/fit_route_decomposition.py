"""Explicit paid decomposition of the Jev vs main-model fit score gap on saved postings.

A: Jev end to end.  B: main model end to end (no Jev/Typesafe in this process).
C: main-model judgments on A's source-span-verified requirement catalogue, so B vs C
isolates requirement extraction and A vs C isolates per-requirement judgments.
D: A's statuses under the main route's formula (local arithmetic, no calls), so A vs D
isolates the score formula. Fresh caches only; no source request.
"""
import argparse
import json
import os
from pathlib import Path
import time
from uuid import uuid4


def main_formula(matches, unknown):
    """The main route's weights; unknown handled three ways (None / excluded / missing)."""
    if unknown == 'none' and any(m['status'] == 'unknown' for m in matches):
        return None
    earned = possible = 0.0
    for m in matches:
        status = m['status']
        if status in {'needs_confirmation', 'confirmed_condition'}:
            continue
        if status == 'unknown':
            if unknown == 'excluded':
                continue
            status = 'missing'
        weight = 2.0 if m['level'] == 'required' else 1.0
        earned += weight * {'matched': 1.0, 'partial': .5}.get(status, 0.0)
        possible += weight
    return round(100 * earned / possible, 1) if possible else None


def statuses(result):
    return [{'id': m.requirement_id, 'level': m.requirement_level, 'status': m.match_status,
             'text': m.job_skill} for m in result.skill_match.matches]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--url', action='append', required=True)
    parser.add_argument('--max-attempts', type=int, default=60)
    args = parser.parse_args()
    if args.output.exists(): raise FileExistsError(args.output)
    args.output.mkdir(parents=True)
    # Main route = a user without Jev/Typesafe: fast decisions off. The Jev key stays
    # available only for route A, which is forced explicitly.
    os.environ.update(TYPESAFE_ENABLED='false', TYPESAFE_CAREER_ENABLED='false',
                      JOB_AGENT_TASK_MAX_PROVIDER_ATTEMPTS=str(args.max_attempts),
                      JOB_AGENT_TASK_MAX_INPUT_TOKENS='600000')
    from dataclasses import replace
    from eregion.api.db import create_database
    from eregion.api.services.fit_analysis_service import FitAnalysisService
    from eregion.domain.jev_fit.settings import Settings
    from eregion.domain.requirement_catalog import FrozenRequirementCatalog
    from eregion.runtime.provider_usage import UsageLedger, usage_scope
    from scripts.e2e_repair_evaluation import APPLICANTS
    resume = APPLICANTS['analyst']
    captured = json.loads((args.source / 'transcript.json').read_text(encoding='utf-8'))
    bodies = {j['url']: j for j in captured['retrieved_jobs'].values()}
    db = create_database('sqlite:///' + (args.output / 'usage.sqlite3').as_posix(), create_schema_for_tests=True)
    ledger = UsageLedger(db.session_factory)
    rows, started = [], time.monotonic()
    config = replace(Settings.load(cache_path=args.output / 'fit.sqlite3'), resolve_unknowns=False)
    try:
        for url in args.url:
            body = bodies[url]['description']
            row = {'url': url, 'title': bodies[url].get('title')}
            phases = {}
            def phase(name, compute):
                task = str(uuid4()); t0 = time.monotonic()
                with usage_scope(task_id=task, ledger=ledger, purpose='decomposition:' + name):
                    value = compute()
                usage = ledger.summary(task_id=task)
                phases[name] = {'seconds': round(time.monotonic() - t0, 2), 'calls': usage['calls'],
                                'input_tokens': usage['input_tokens'], 'output_tokens': usage['output_tokens'],
                                'unknown_usage_calls': usage['unknown_usage_calls']}
                return value
            a = phase('A_jev', lambda: FitAnalysisService(jev_enabled=True, jev_config=config)._analyze_sync(
                resume_text=resume, job_description=body))
            catalog = FrozenRequirementCatalog.from_jev_result(a, body, producer_signature='jev:' + config.signature(),
                                                               provenance='fit-route-decomposition')
            b = phase('B_main', lambda: FitAnalysisService(jev_enabled=False)._analyze_sync(
                resume_text=resume, job_description=body))
            c = phase('C_main_on_jev_catalog', lambda: FitAnalysisService(jev_enabled=False)._analyze_sync(
                resume_text=resume, job_description=body, fixed_job_catalog=catalog))
            sa, sb, sc = statuses(a), statuses(b), statuses(c)
            by_id = {m['id']: m['status'] for m in sc}
            agreement = {'same_catalog_items': len(sa),
                         'same_status': sum(by_id.get(m['id']) == m['status'] for m in sa),
                         'pairs': {f"{m['status']}->{by_id.get(m['id'])}": 0 for m in sa}}
            for m in sa:
                agreement['pairs'][f"{m['status']}->{by_id.get(m['id'])}"] += 1
            row.update(phases=phases, scores={
                'A_jev': a.skill_match.overall_score, 'B_main': b.skill_match.overall_score,
                'C_main_on_jev_catalog': c.skill_match.overall_score,
                'D_jev_statuses_main_formula': {u: main_formula(sa, u) for u in ('none', 'excluded', 'missing')}},
                requirement_counts={'A_jev': len(sa), 'B_main': len(sb), 'C_main_on_jev_catalog': len(sc)},
                status_counts={k: {s: sum(m['status'] == s for m in v) for s in
                                   ('matched', 'partial', 'missing', 'unknown', 'needs_confirmation')}
                               for k, v in (('A_jev', sa), ('B_main', sb), ('C_main_on_jev_catalog', sc))},
                jev_vs_main_on_same_catalog=agreement,
                requirements={'A_jev': sa, 'B_main': sb, 'C_main_on_jev_catalog': sc})
            rows.append(row)
            print(json.dumps({k: row[k] for k in ('title', 'scores', 'requirement_counts')}, ensure_ascii=False), flush=True)
    finally:
        (args.output / 'results.json').write_text(json.dumps(rows, indent=2, ensure_ascii=False, default=str), encoding='utf-8')
        totals = {k: sum(r['phases'][p][k] for r in rows for p in r['phases'])
                  for k in ('calls', 'input_tokens', 'output_tokens', 'unknown_usage_calls')}
        (args.output / 'summary.json').write_text(json.dumps({'totals': totals, 'seconds': round(time.monotonic() - started, 2),
            'jobs': len(rows), 'cost_usd': None, 'kind': 'paid fit-route decomposition on captured postings; not a live search'},
            indent=2), encoding='utf-8')
        db.close()


if __name__ == '__main__':
    main()
