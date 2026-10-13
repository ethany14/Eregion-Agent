"""P8 L0: does the configured provider accept prompt_cache_key, and does it change cache reads?

Explicit opt-in (JOB_AGENT_LIVE_CACHE_PROBE=1). Six tiny requests with a ~3K-token prompt
and a 1-token answer. Groups use different leading nonces so they never share a prefix.
Prints usage only; never prints the key or model credentials.
"""
import json
import os
import sys
import time
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    if os.environ.get('JOB_AGENT_LIVE_CACHE_PROBE') != '1':
        raise SystemExit('Refusing: set JOB_AGENT_LIVE_CACHE_PROBE=1 for the explicit live probe.')
    from langchain_core.messages import HumanMessage, SystemMessage
    from eregion.domain.model import create_model
    body = ('You are a careful job-search assistant. Rules: ' + ' '.join(
        f'Rule {i}: keep the requested seniority, location and evidence exact and never invent facts.' for i in range(160)))
    groups = {'A_no_key': f'probe-A-{uuid4().hex}', 'B_task_key': f'probe-B-{uuid4().hex}'}
    rows = []
    for round_index in range(3):
        for group, nonce in groups.items():
            kwargs = {'max_tokens': 1}
            if group == 'B_task_key':
                kwargs['model_kwargs'] = {'prompt_cache_key': nonce[:64]}
            model = create_model(purpose='fast', **{})
            model = model.bind(**({'prompt_cache_key': nonce[:64]} if group == 'B_task_key' else {}), max_tokens=1)
            messages = [SystemMessage(content=f'[{nonce}] ' + body), HumanMessage(content='Reply with the single word OK.')]
            started = time.monotonic()
            error = None
            try:
                result = model.invoke(messages)
                usage = (result.response_metadata or {}).get('token_usage') or {}
                details = usage.get('prompt_tokens_details') or {}
                row = {'input': usage.get('prompt_tokens'), 'cached': details.get('cached_tokens'),
                       'output': usage.get('completion_tokens')}
            except Exception as exc:  # record, do not retry
                error = type(exc).__name__ + ': ' + str(exc)[:200]
                row = {}
            rows.append({'round': round_index + 1, 'group': group, 'seconds': round(time.monotonic() - started, 2),
                         'error': error, **row})
            print(json.dumps(rows[-1]))
            if error and group == 'B_task_key':
                groups.pop('B_task_key')
                break
    out = ROOT / '.codex-runs' / 'integrated-20261012' / 'l0-cache-probe.json'
    out.write_text(json.dumps(rows, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
