"""Live-readiness report for a set of live acceptance runs (docs/specs, section 9).

Reads each run's acceptance, summary and audit files and reports per scenario and pooled:
status and failures, jobs shown and without substantive error, gap omissions (a hidden
conflict or an unknown presented as met), stop and continuation verdicts, speed and usage.
Set verdict rules are fixed in the spec before any run; this script only applies them.
"""
import argparse
import json
from pathlib import Path

GAP_CHECKS = ('no_hidden_conflict', 'no_unknown_as_met')
INFRA = {'loop_not_completed_cleanly', 'incomplete_usage', 'semantic_audit_incomplete', 'main_call_budget',
         'main_input_budget', 'total_input_budget', 'missing_main_usage'}
REPLY = {'final_reply_not_honest_or_unexplained', 'continuation_missing_or_inaccurate', 'scored_jobs_without_outcome'}


def load(path):
    path = Path(path)
    accept = path / ('acceptance-audit-completed.json' if (path / 'acceptance-audit-completed.json').exists()
                     else 'batch-acceptance.json')
    acc = json.loads(accept.read_text(encoding='utf-8'))
    summary = json.loads((path / 'summary.json').read_text(encoding='utf-8'))
    invocation = json.loads((path / 'invocation.json').read_text(encoding='utf-8'))
    jobs = acc.get('jobs') or []
    usage, audit = summary.get('usage') or {}, summary.get('audit_usage') or {}
    return {'run': path.name, 'scenario': invocation.get('scenario', 'analyst'), 'status': acc['status'],
            'failures': acc['failures'],
            'infra_failures': [f for f in acc['failures'] if f in INFRA],
            'reply_failures': [f for f in acc['failures'] if f in REPLY or f == 'search_stopped_prematurely'],
            'shown': len(jobs), 'clean': sum(all(j['checks'].values()) for j in jobs),
            'gap_omissions': sum(any(not j['checks'].get(c, True) for c in GAP_CHECKS) for j in jobs),
            'by_tier': acc.get('by_tier'), 'stop': acc.get('stop_assessment'),
            'continuation': {k: (acc.get('reply_review') or {}).get(k) for k in ('continuation_stated', 'continuation_accurate')},
            'first_result_s': (summary.get('metrics') or {}).get('seconds_to_first_recommendation'),
            'total_s': summary.get('seconds'), 'main_calls': summary.get('calls'),
            'provider_calls': usage.get('calls'), 'input_tokens': usage.get('input_tokens'),
            'output_tokens': usage.get('output_tokens'), 'unknown_usage': usage.get('unknown_usage_calls'),
            'audit': {k: audit.get(k) for k in ('calls', 'input_tokens', 'output_tokens', 'unknown_usage_calls')}}


def verdict(rows, max_error_rate=0.10, min_shown=15):
    shown = sum(r['shown'] for r in rows)
    errors = sum(r['shown'] - r['clean'] for r in rows)
    gaps = sum(r['gap_omissions'] for r in rows)
    reasons = []
    for r in rows:
        if r['infra_failures']:
            reasons.append(f"{r['scenario']}: run did not complete with complete usage ({', '.join(r['infra_failures'])})")
        if r['reply_failures']:
            reasons.append(f"{r['scenario']}: reply ({', '.join(r['reply_failures'])})")
    if shown < min_shown:
        reasons.append(f'only {shown} shown jobs pooled; at least {min_shown} are needed to estimate an error rate')
    rate = errors / shown if shown else None
    if rate is not None and rate > max_error_rate:
        reasons.append(f'substantive-error rate {rate:.0%} exceeds {max_error_rate:.0%}')
    return {'ready': not reasons, 'reasons': reasons, 'shown': shown, 'substantive_errors': errors,
            'substantive_error_rate': rate, 'gap_omissions': gaps, 'gap_omission_rate': gaps / shown if shown else None,
            'max_error_rate': max_error_rate, 'min_shown': min_shown}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('runs', nargs='+')
    parser.add_argument('--out')
    args = parser.parse_args()
    rows = [load(p) for p in args.runs]
    report = {'runs': rows, 'set': verdict(rows)}
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    for r in rows:
        print(f"{r['scenario']:9} {r['status']:7} shown {r['shown']} clean {r['clean']} gaps {r['gap_omissions']} "
              f"stop {r['stop']} first {r['first_result_s']}s total {r['total_s']}s calls {r['provider_calls']} "
              f"in {r['input_tokens']} out {r['output_tokens']} unknown {r['unknown_usage']} | {', '.join(r['failures'])}")
    print(json.dumps(report['set'], indent=1))


if __name__ == '__main__':
    main()
