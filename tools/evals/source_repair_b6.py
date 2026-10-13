"""Explicit single B6 sample for the 2026-10-12 source repair; no automatic reruns."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tests'), str(ROOT)]

if __name__ == '__main__':
    if os.environ.get('JOB_AGENT_LIVE_API_FIRST_B6') != '1':
        raise SystemExit('Explicit live opt-in required')
    import test_api_first_b6_live as sample
    import pytest
    # New authorization: 20 requests / $0.10; diagnosis used 2 / $0.0003.
    # This one sample reserves at most another 8 requests / $0.05.
    sample.FLAGS['JOB_AGENT_TREG_MAX_ATTEMPTS'] = '8'
    sample.FLAGS['JOB_AGENT_TREG_TASK_MAX_COST_USD'] = '0.05'
    raise SystemExit(pytest.main(['-q', '-p', 'no:cacheprovider',
        'tests/test_api_first_b6_live.py::test_api_first_b6', *sys.argv[1:]]))
