import os, sys, socket
from pathlib import Path
root = Path(os.environ.get('OPT_TEST_ROOT', Path(__file__).resolve().parents[3])).resolve()
sys.path.insert(0, str(root))
import dotenv, dotenv.main
original = dotenv.main.dotenv_values
def values(dotenv_path=None, *a, **k):
    if dotenv_path is None or Path(dotenv_path).resolve() == root / '.env':
        return {}
    return original(dotenv_path, *a, **k)
dotenv.dotenv_values = dotenv.main.dotenv_values = values
for key in list(os.environ):
    if key.startswith(('JOB_AGENT_LIVE_', 'LLM_REASONING_')) or key in {'JOB_AGENT_B6_REPLAY_LIVE_MODEL','JOB_AGENT_REASONING_ESCALATION','JOB_AGENT_REASONING_REJECTION_RETRY','JOB_AGENT_TASK_MAX_PROVIDER_ATTEMPTS','JOB_AGENT_TASK_MAX_INPUT_TOKENS'}:
        os.environ.pop(key, None)
os.environ['JOB_AGENT_ANALYSIS_WARMUP'] = '0'
os.environ['LLM_MODEL_ID'] = 'offline-construction-only'
os.environ['LLM_API_KEY'] = 'offline-fake-key'
os.environ['LLM_BASE_URL'] = 'https://offline.invalid/v1'
original_connect = socket.socket.connect
def connect(sock, address):
    if isinstance(address, tuple) and address[0] not in {'127.0.0.1','::1','localhost'}:
        raise AssertionError('External network disabled for offline verification')
    return original_connect(sock,address)
socket.socket.connect = connect
original_mkdir = os.mkdir
def mkdir(path, mode=0o777, *, dir_fd=None):
    if Path(path).resolve().is_relative_to(root / '.codex-runs' / 'opt-v3-stage0'):
        mode = 0o777
    return original_mkdir(path, mode, dir_fd=dir_fd)
os.mkdir = mkdir
temp = root / '.codex-runs' / 'opt-v3-stage0' / 'temp-open'
temp.mkdir(parents=True, exist_ok=True)
os.environ['TEMP'] = os.environ['TMP'] = str(temp)
import tempfile
tempfile.tempdir = str(temp)
import pytest
sys.exit(pytest.main(sys.argv[1:]))
