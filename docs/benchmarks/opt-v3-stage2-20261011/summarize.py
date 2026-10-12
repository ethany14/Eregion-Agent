"""Validate and publish compact measurements; raw logs remain in .codex-runs."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RAW = ROOT / '.codex-runs/opt-v3-stage2'
OUT = Path(__file__).parent
CASES = ('r1','r2','r3','correct')
MODES = ('off','current','checkpoint','aligned','recommended')

def business(value):
    if isinstance(value, list): return [business(v) for v in value]
    if isinstance(value, dict): return {k:business(v) for k,v in value.items() if k != 'application_id'}
    return value

results = {}
for mode in MODES:
    results[mode] = {}
    for case in CASES:
        data = json.loads((RAW / ('recommended' if mode == 'recommended' else 'verified-' + mode) / (case+'.json')).read_text())
        rows = data['requests']
        changes = lambda key: sum(a[key] != b[key] for a,b in zip(rows,rows[1:]))
        entry = {'calls':len(rows), 'fixed_base_byte_checks':data.get('fixed_base_byte_checks',0), 'total_chars':sum(r['request_text_chars'] for r in rows),
            'max_chars':max(r['request_text_chars'] for r in rows), 'limit_chars':rows[0]['limit_chars'],
            'group_changes':changes('history_group_id'), 'exact_group_changes':changes('history_group_hash'),
            'pairs':len(rows)-1, 'tools_changes':changes('tools_hash'), 'system_changes':changes('system_hash'),
            'persistent_evictions':sum(r['persistent_groups_evicted'] for r in rows),
            'request_evictions':sum(r['replay_groups_evicted'] for r in rows),
            'requests_without_history':sum(r['history_group_id'] is None for r in rows),
            'orphan_free':all(r['orphan_free'] for r in rows),
            'latest_user_protected':all(r['latest_user_protected'] for r in rows),
            'mean_parts':{key:round(sum(r['request_parts_chars'][key] for r in rows)/len(rows),2) for key in rows[0]['request_parts_chars']},
            'outcome':business(data['acceptance']), 'status':data['status'], 'scoring_inputs':data['scoring_inputs'],
            'requests':[{k:r[k] for k in ('request_text_chars','limit_chars','history_group_id','history_group_hash',
                'persistent_groups_evicted','replay_groups_evicted','request_parts_chars','protected_overflow')} for r in rows]}
        assert entry['orphan_free'] and entry['latest_user_protected']
        if mode != 'off':
            base = results['off'][case]
            assert entry['outcome'] == base['outcome'] and entry['status'] == base['status']
            assert entry['scoring_inputs'] == base['scoring_inputs']
            assert entry['max_chars'] <= entry['limit_chars']
            assert entry['total_chars'] < base['total_chars']
            if mode != 'recommended': assert entry['tools_changes'] == 0
            entry['reduction_percent'] = round(100*(1-entry['total_chars']/base['total_chars']),2)
        results[mode][case] = entry
result = {'base':'6691b0bb75651aa71d40b8287f086411623025a9', 'selected':'checkpoint', 'recommended_flags':{'SNAPSHOT_REFS':'1','PROMPT_TRIM':'1','STABLE_TOOLS':'0','HISTORY_POLICY':'checkpoint'},
    'source_hashes':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in [ROOT/'agent_runtime'/name for name in ('request_options.py','request_context.py','loop_context.py','loop_engine.py','task_host.py','career/prompt.py','career/harness.py')]},
    'modes':results}
(OUT/'measurements.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
for mode, cases in results.items():
    for case,r in cases.items():
        print(mode, case, r['total_chars'], r['max_chars'], str(r['group_changes'])+'/'+str(r['pairs']),
              r['request_evictions'], r['persistent_evictions'], r.get('reduction_percent',''))
