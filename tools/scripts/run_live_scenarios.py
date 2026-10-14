"""Run the live-readiness scenario set: one paid live acceptance per scenario, in sequence.

Each scenario gets its own new output directory and experiment ledger (same limits as the
single-run acceptance). Nothing is overwritten and nothing is retried automatically; a run
that fails is reported as it is. Afterwards scenario_set_report.py applies the set rules.

    python tools/scripts/run_live_scenarios.py --set-id live-set-01 [--scenarios analyst,backend,student,designer]
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = ('analyst', 'backend', 'student', 'designer')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--set-id', required=True)
    parser.add_argument('--scenarios', default=','.join(SCENARIOS))
    parser.add_argument('--version', default='tiered-recommendations-v5')
    args = parser.parse_args()
    chosen = [s for s in args.scenarios.split(',') if s]
    unknown = set(chosen) - set(SCENARIOS)
    if unknown:
        raise SystemExit(f'Unknown scenarios: {sorted(unknown)}')
    base = ROOT / '.codex-runs' / args.set_id
    base.mkdir(parents=True, exist_ok=False)          # never reuse or overwrite a set
    runs = []
    for scenario in chosen:
        output = base / scenario
        env = {**os.environ, 'PYTHONPATH': 'backend;tools' if os.name == 'nt' else 'backend:tools',
               'JOB_AGENT_LIVE_DEFAULT_BATCH': '1', 'JOB_AGENT_ANALYSIS_WARMUP': '0',
               'MCP_CONFIG_PATH': str(ROOT / '.codex-runs' / 'linkedin-career-mcp.json'),
               'OPT_LIVE_OUTPUT': str(output), 'JOB_AGENT_LIVE_LIMITS': 'expanded',
               'JOB_AGENT_LIVE_ACCEPTANCE': args.version, 'JOB_AGENT_LIVE_SCENARIO': scenario,
               'JOB_AGENT_EXPERIMENT_ID': f'{args.set_id}-{scenario}',
               'JOB_AGENT_EXPERIMENT_LEDGER': str(ROOT / '.codex-runs' / 'experiments' / f'{args.set_id}-{scenario}.sqlite3'),
               'JOB_AGENT_EXPERIMENT_MAX_PROVIDER_ATTEMPTS': '106', 'JOB_AGENT_EXPERIMENT_MAX_INPUT_TOKENS': '1700000'}
        with open(base / f'{scenario}.pytest.log', 'w', encoding='utf-8') as log:
            code = subprocess.call([sys.executable, '-m', 'pytest', 'tests/test_default_route_batch_live.py::test_default_route_search',
                                    '-q', '-s', '-p', 'no:cacheprovider'], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        print(f'{scenario}: exit {code}', flush=True)
        if (output / 'summary.json').exists():
            runs.append(str(output))
    if runs:
        subprocess.call([sys.executable, 'tools/scripts/scenario_set_report.py', *runs, '--out', str(base / 'set-report.json')],
                        cwd=ROOT, env={**os.environ, 'PYTHONPATH': 'backend;tools' if os.name == 'nt' else 'backend:tools'})


if __name__ == '__main__':
    main()
