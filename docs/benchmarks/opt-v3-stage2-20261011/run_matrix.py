"""Run frozen offline business/measurement gates for each independent history policy."""
import os
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[3]
output = root / '.codex-runs/opt-v3-stage2'
wrapper = Path(__file__).with_name('run_offline.py')
failed = []
for mode in ('off', 'current', 'checkpoint', 'aligned', 'recommended'):
    env = dict(os.environ)
    env.pop('OPT_TEST_ROOT', None)
    for flag in ('SNAPSHOT_REFS','STABLE_TOOLS','PROMPT_TRIM'):
        env['JOB_AGENT_OPT_' + flag] = '0' if mode == 'off' else '1'
    env['JOB_AGENT_OPT_HISTORY_POLICY'] = 'current' if mode == 'off' else 'checkpoint' if mode == 'recommended' else mode
    if mode == 'recommended': env['JOB_AGENT_OPT_STABLE_TOOLS'] = '0'
    label = 'recommended' if mode == 'recommended' else 'verified-' + mode
    env['OPT_STAGE2_OUTPUT'] = str(output / label)
    with (output / (label + '.log')).open('w', encoding='utf-8') as log:
        result = subprocess.run([sys.executable, str(wrapper), '-q', '-ra', '-p', 'no:cacheprovider',
            'tests/test_opt_v3_stage2.py', 'tests/test_b6_offline_replay.py', 'tests/test_board_directory_replay.py',
            '--basetemp=' + str(output / (label + '-temp')),
            '--junitxml=' + str(output / (label + '.xml'))],
            cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT)
    print(mode, result.returncode, flush=True)
    if result.returncode: failed.append(mode)
raise SystemExit(bool(failed))
