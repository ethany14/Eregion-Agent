"""Closeout C3: stage 2/4 four-config offline matrix on the post-fix baseline.

Every OPT flag is set explicitly (never inherited). Each config runs in its own pytest
process with its own temp/DB start; scripted model, frozen web, offline scoring.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[3]
out = root / '.codex-runs' / 'opt-v3-closeout-20261012' / 'matrix'
STAGE2_OFF = {'SNAPSHOT_REFS': '0', 'PROMPT_TRIM': '0', 'STABLE_TOOLS': '0', 'HISTORY_POLICY': 'current'}
STAGE2_ON = {'SNAPSHOT_REFS': '1', 'PROMPT_TRIM': '1', 'STABLE_TOOLS': '0', 'HISTORY_POLICY': 'checkpoint'}
CONFIGS = {'B0': (STAGE2_OFF, 'granular'), 'B4': (STAGE2_OFF, 'composite'),
           'B2': (STAGE2_ON, 'granular'), 'B24': (STAGE2_ON, 'composite')}
failed = []
for name, (stage2, mode) in CONFIGS.items():
    env = {k: v for k, v in os.environ.items() if not k.startswith('JOB_AGENT_OPT_')}
    env.update({f'JOB_AGENT_OPT_{k}': v for k, v in stage2.items()})
    env['OPT_STAGE4_OUTPUT'] = str(out / name)
    (out / name).mkdir(parents=True, exist_ok=True)
    with (out / f'{name}.log').open('w', encoding='utf-8') as log:
        code = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider',
            f'tests/test_opt_v3_stage4.py::test_replay_measurements', '-k', mode,
            f'--basetemp={out / (name + "-tmp")}'], cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT).returncode
    print(name, code, flush=True)
    failed += [name] if code else []

rows = []
for name in CONFIGS:
    for path in sorted((out / name).glob('*.json')):
        data = json.loads(path.read_text(encoding='utf-8'))
        reqs = data['requests']
        rows.append({'config': name, 'case': data['case'], 'qualified': data['acceptance']['qualified_count'],
                     'acceptance': data['acceptance']['status'], 'status': data['status'], 'decisions': data['decisions'],
                     'total_chars': sum(r.get('request_text_chars', 0) for r in reqs),
                     'max_request': max((r.get('request_text_chars', 0) for r in reqs), default=0),
                     'protected_overflow': sum(bool(r.get('protected_overflow')) for r in reqs),
                     'scoring_hashes': sorted(h['sha256'] for h in data['scoring_inputs'])})
(out / 'matrix.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
raise SystemExit(bool(failed))
