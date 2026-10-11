"""Read-only per-attempt optimization report. No provider initialization."""
import argparse
import json
from pathlib import Path
import sqlite3
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_runtime.provider_usage import summarize


def percentiles(values):
    values = sorted(values)
    if not values:
        return None
    def quantile(q):
        position = (len(values) - 1) * q
        lo = int(position)
        hi = min(lo + 1, len(values) - 1)
        return values[lo] + (values[hi] - values[lo]) * (position - lo)
    return {'count': len(values), 'p50': quantile(.5), 'p95': quantile(.95), 'max': values[-1]}


def metrics(rows):
    parts = [r['context_metrics']['request_parts_chars'] for r in rows
             if r.get('context_metrics', {}).get('request_parts_chars') is not None]
    result = {'composition_samples': len(parts), 'composition_averages': {
        k: statistics.mean(p[k] for p in parts if k in p)
        for k in sorted({k for p in parts for k in p})},
        'timing_seconds': {k: percentiles([r[k] for r in rows if isinstance(r.get(k), (int, float))])
            for k in ('queue_wait_seconds', 'provider_duration_seconds', 'persistence_seconds')},
        'missing': {k: sum(k not in r for r in rows) for k in
            ('context_metrics', 'queue_wait_seconds', 'provider_duration_seconds', 'persistence_seconds',
             'input_tokens', 'output_tokens', 'cached_input_tokens', 'reasoning_tokens')}}
    eviction = [r['context_metrics'] for r in rows if 'history_evicted' in r.get('context_metrics', {})]
    result['eviction'] = {'samples': len(eviction), 'requests': sum(m['history_evicted'] for m in eviction),
        'groups': sum(m['replay_groups_evicted'] for m in eviction),
        'frequency': sum(m['history_evicted'] for m in eviction) / len(eviction) if eviction else None}
    totals = [r['context_metrics']['request_text_chars'] for r in rows if 'request_text_chars' in r.get('context_metrics', {})]
    result['total_chars_average'] = statistics.mean(totals) if totals else None
    return result


def report(path, *, task_id=None, run_id=None):
    with sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True) as db:
        db.execute('PRAGMA query_only=ON')
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        rows = []
        if 'provider_usage' in tables:
            where, args = [], []
            for key, value in (('task_id', task_id), ('run_id', run_id)):
                if value:
                    where.append(key + '=?'); args.append(value)
            query = 'SELECT details_json, adopted FROM provider_usage'
            if where:
                query += ' WHERE ' + ' AND '.join(where)
            rows = [{**json.loads(details), 'adopted': bool(adopted)} for details, adopted in db.execute(query, args)]
        actions = [r for r in rows if r.get('source') == 'tool_action']
        rows = [r for r in rows if r.get('source') != 'tool_action']
        result = summarize(rows)
        result.update(metrics(rows))
        result['source'] = str(path)
        result['provider_usage_table_present'] = 'provider_usage' in tables
        result['last_request_snapshots'] = []
        if 'career_tasks' in tables and not run_id:
            query = 'SELECT task_id, state_json FROM career_tasks'
            params = ()
            if task_id:
                query += ' WHERE task_id=?'; params = (task_id,)
            for identifier, state in db.execute(query, params):
                runtime = json.loads(state).get('loop_runtime', {})
                composition = runtime.get('context_metrics')
                if composition:
                    result['last_request_snapshots'].append({'task_id': identifier,
                        'note': 'Last request only; not attributed to every historical attempt.',
                        'context_metrics': composition})
        for group in result['groups']:
            group.update(metrics([r for r in rows if r.get('purpose', 'unspecified') == group['purpose']
                and r.get('model', 'unknown') == group['model']]))
        # Historical runtime is a bounded tail, not all actions in the run.
        result['tool_actions'] = {'count': len(actions), 'execution_seconds': percentiles(
            [r['tool_execution_seconds'] for r in actions if 'tool_execution_seconds' in r]),
            'persistence_seconds': percentiles([r['persistence_seconds'] for r in actions if 'persistence_seconds' in r])}
        result['tool_timing_note'] = 'Persistence measures intent checkpoint; final commit cannot time itself. Absent samples are unknown.'
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', type=Path)
    parser.add_argument('--json', required=True, type=Path)
    parser.add_argument('--task-id')
    parser.add_argument('--run-id')
    args = parser.parse_args()
    if args.json.resolve() == args.database.resolve():
        parser.error('JSON output must not overwrite the input database.')
    result = report(args.database, task_id=args.task_id, run_id=args.run_id)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    for group in result['groups']:
        print(json.dumps(group, ensure_ascii=False))
    print('Missing fields (counts):', result['missing'])
    print('JSON:', args.json)


if __name__ == '__main__':
    main()
