"""Assert business/scoring parity and summarize measured scripted requests."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[3]
evidence = root / '.codex-runs/opt-v3-stage4'
rows = []
for case in ('r1','r2','r3','correct','directory-positive','directory-negative'):
    a, b = [json.loads((evidence / 'measurements' / f'{case}-{mode}.json').read_text(encoding='utf-8'))
            for mode in ('granular','composite')]
    assert a['scoring_inputs'] == b['scoring_inputs'], case
    for field in ('qualified_count','status','failures'):
        assert a['acceptance'][field] == b['acceptance'][field], (case,field)
    assert a['status'] == b['status'], case
    # The unchanged evaluator supplies each posting's qualification checks.
    assert [j['checks'] for j in a['acceptance']['jobs']] == [j['checks'] for j in b['acceptance']['jobs']], case
    chars = [sum(r['request_text_chars'] for r in v['requests']) for v in (a,b)]
    rows.append({'case':case, 'granular_decisions':a['decisions'], 'composite_decisions':b['decisions'],
        'granular_chars':chars[0], 'composite_chars':chars[1],
        'reduction_percent':round((1-chars[1]/chars[0])*100,2),
        'scoring_inputs_identical':True, 'qualified':b['acceptance']['qualified_count']})
(evidence/'measurements.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
print(json.dumps(rows,indent=2))

# The same gate also applies when the stage-2 request optimizations are enabled.
folder = evidence/'measurements-stage2'
if folder.exists():
    optimized=[]
    for row in rows:
        case=row['case']
        a,b=[json.loads((folder/f'{case}-{mode}.json').read_text(encoding='utf-8'))
             for mode in ('granular','composite')]
        assert a['scoring_inputs']==b['scoring_inputs'],case
        assert a['scoring_inputs']==json.loads((evidence/'measurements'/f'{case}-granular.json').read_text(encoding='utf-8'))['scoring_inputs'],case
        assert a['status']==b['status'],case
        for field in ('qualified_count','status','failures'):
            assert a['acceptance'][field]==b['acceptance'][field],(case,field)
        assert not any(r['protected_overflow'] for v in (a,b) for r in v['requests']),case
        optimized.append({'case':case,'granular_decisions':a['decisions'],'composite_decisions':b['decisions'],
            'granular_chars':sum(r['request_text_chars'] for r in a['requests']),
            'composite_chars':sum(r['request_text_chars'] for r in b['requests']),
            'maximum_request':max(r['request_text_chars'] for r in b['requests']),
            'scoring_inputs_identical':True})
    (evidence/'measurements-stage2.json').write_text(json.dumps(optimized,indent=2),encoding='utf-8')
