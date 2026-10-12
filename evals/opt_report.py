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


def wire_summary(rows):
    """P1: measured identical prefix of the final request vs provider-reported cache reads.

    The prefix share is measured on serialized request text (characters), the cached share
    is the provider's token counter; they are compared, never substituted for each other.
    """
    measured = [r for r in rows if r.get('wire_chars')]
    known = [r for r in measured if r.get('wire_common_prefix_chars') is not None]
    first_change = {}
    for r in known:
        where = r.get('wire_first_change', 'unknown')
        where = 'message' if where.startswith('message:') else where
        first_change[where] = first_change.get(where, 0) + 1
    cached = [r for r in measured if isinstance(r.get('cached_input_tokens'), int) and r.get('input_tokens')]
    return {'requests': len(measured), 'unknown_previous': len(measured) - len(known),
            'prefix_share': (sum(r['wire_common_prefix_chars'] for r in known) / sum(r['wire_chars'] for r in known))
                if known else None,
            'first_change': first_change,
            'provider_cached_share': (sum(r['cached_input_tokens'] for r in cached) / sum(r['input_tokens'] for r in cached))
                if cached else None,
            'provider_cache_unknown': len(measured) - len(cached),
            # Pi-style heuristic, not a measured cache loss: tokens that could have been
            # read from cache if the shared part of the previous prompt had been reused.
            'heuristic_note': 'prefix_share is chars of identical leading request text; cached share is provider tokens'}


def metrics(rows, *, include_groups=True):
    parts = [r['context_metrics']['request_parts_chars'] for r in rows
             if r.get('context_metrics', {}).get('request_parts_chars') is not None]
    result = {'composition_samples': len(parts), 'composition_averages': {
        k: statistics.mean(p[k] for p in parts if k in p)
        for k in sorted({k for p in parts for k in p})},
        'timing_seconds': {k: percentiles([r[k] for r in rows if isinstance(r.get(k), (int, float))])
            for k in ('duration_seconds', 'queue_wait_seconds', 'provider_duration_seconds', 'persistence_seconds')},
        'missing': {k: sum(k not in r for r in rows) for k in
            ('context_metrics', 'queue_wait_seconds', 'provider_duration_seconds', 'persistence_seconds',
             'input_tokens', 'output_tokens', 'cached_input_tokens', 'reasoning_tokens')}}
    eviction = [r['context_metrics'] for r in rows if 'history_evicted' in r.get('context_metrics', {})]
    result['eviction'] = {'samples': len(eviction), 'requests': sum(m['history_evicted'] for m in eviction),
        'groups': sum(m['replay_groups_evicted'] for m in eviction),
        'frequency': sum(m['history_evicted'] for m in eviction) / len(eviction) if eviction else None}
    totals = [r['context_metrics']['request_text_chars'] for r in rows if 'request_text_chars' in r.get('context_metrics', {})]
    result['total_chars_average'] = statistics.mean(totals) if totals else None
    transitions = {'pairs': 0, 'history': 0, 'persistent': 0, 'request': 0,
                   'both': 0, 'other': 0, 'tools': 0, 'system': 0}
    previous = {}
    for row in rows:
        m = row.get('context_metrics', {})
        key = (row.get('task_id'), row.get('run_id'))
        if 'history_prefix_hash' not in m:
            continue
        # Nested attempts and retries can share one assembled request.
        request = row.get('request_id')
        prior = previous.get(key)
        if prior and request and request == prior[1]:
            continue
        if prior:
            old = prior[0]
            transitions['pairs'] += 1
            changed = m['history_prefix_hash'] != old['history_prefix_hash']
            persistent = changed and bool(m.get('persistent_groups_evicted')) and m.get('persistent_prefix_hash') != old.get('persistent_prefix_hash')
            request_trim = changed and bool(m.get('replay_groups_evicted') or old.get('replay_groups_evicted')) and (
                m.get('history_prefix_hash') != m.get('persistent_prefix_hash') or old.get('history_prefix_hash') != old.get('persistent_prefix_hash'))
            if 'persistent_group_ids' in m:
                # A persistent eviction of an already-unreplayed old group is
                # not the cause of a changed request prefix. Track identity,
                # independently of archive compaction changing group contents.
                prior_id = old.get('history_group_id')
                next_id = m.get('history_group_id')
                retained = m['persistent_group_ids']
                persistent = changed and bool(m.get('persistent_groups_evicted')) and prior_id is not None and prior_id not in retained
                request_trim = changed and prior_id != next_id and bool(
                    m.get('replay_groups_evicted') or old.get('replay_groups_evicted')) and (
                    not persistent or bool(retained and next_id != retained[0]))
            transitions['history'] += int(changed)
            transitions['persistent'] += int(persistent)
            transitions['request'] += int(request_trim)
            transitions['both'] += int(persistent and request_trim)
            transitions['other'] += int(changed and not persistent and not request_trim)
            for name in ('tools', 'system'):
                transitions[name] += int(m.get(name + '_hash') != old.get(name + '_hash'))
        previous[key] = (m, request)
    result['prefix_changes'] = {**transitions, 'shares': {
        k: v / transitions['pairs'] if transitions['pairs'] else None
        for k, v in transitions.items() if k != 'pairs'}}
    result['persistent_evicted_groups'] = sum(r.get('context_metrics', {}).get('persistent_groups_evicted', 0) for r in rows)
    result['wire'] = wire_summary(rows)
    if include_groups:
        group_rows = [{**r, 'context_metrics': {**r['context_metrics'],
            'history_prefix_hash': r['context_metrics']['history_group_hash'],
            'persistent_prefix_hash': r['context_metrics'].get('persistent_group_hash')}}
            for r in rows if 'history_group_hash' in r.get('context_metrics', {})]
        result['group_prefix_changes'] = metrics(group_rows, include_groups=False)['prefix_changes']
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
            columns = {r[1] for r in db.execute('PRAGMA table_info(provider_usage)')}
            identifiers = [k for k in ('task_id', 'run_id', 'request_id') if k in columns]
            query = 'SELECT details_json, adopted' + ''.join(', ' + k for k in identifiers) + ' FROM provider_usage'
            if where:
                query += ' WHERE ' + ' AND '.join(where)
            query += ' ORDER BY ' + ('created_at, rowid' if 'created_at' in columns else 'rowid')
            rows = [{**json.loads(row[0]), 'adopted': bool(row[1]), **dict(zip(identifiers, row[2:]))}
                    for row in db.execute(query, args)]
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
