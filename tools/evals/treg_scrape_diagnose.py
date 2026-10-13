"""Two saved B6 LinkedIn targets; opt-in, no model, isolated persistent $0.10/20-call ledger."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

def main():
    if os.environ.get('JOB_AGENT_TREG_LIVE_API_TEST') != '1':
        raise SystemExit('Explicit live opt-in required')
    from eregion.api.db import create_database
    from eregion.runtime.career import treg_config
    from eregion.runtime.career.external_tool_usage import ExternalToolLedger
    from eregion.runtime.career.treg_client import TregClient
    from eregion.runtime.career.treg_jobs import assess_scrape, SCRAPE_ENDPOINT
    out = ROOT / '.codex-runs' / 'codex-source-repair-20261012'
    out.mkdir(parents=True, exist_ok=True)
    cfg = treg_config.load(environ={**os.environ, 'JOB_AGENT_TREG_ENABLED':'1',
        'JOB_AGENT_TREG_TASK_MAX_COST_USD':'0.10', 'JOB_AGENT_TREG_DAILY_MAX_COST_USD':'0.10',
        'JOB_AGENT_TREG_CALL_MAX_COST_USD':'0.01', 'JOB_AGENT_TREG_MAX_ATTEMPTS':'20'})
    db = create_database('sqlite:///' + (out / 'ledger.db').as_posix(), create_schema_for_tests=True)
    ledger = ExternalToolLedger(db.session_factory, deployment='codex-source-repair')
    client = TregClient(cfg, ledger)
    state = json.loads((ROOT / 'docs/benchmarks/api-first-b6-20261012/run-2/transcript.json').read_text(encoding='utf-8'))
    urls = [c['url'] for c in state['search_candidates'].values()
        if 'linkedin:' + c.get('provider_job_id','') in state['job_read_attempts']][:2]
    try:
        for url in urls:
            candidate = next(c for c in state['search_candidates'].values() if c.get('url') == url)
            path = out / (candidate['provider_job_id'] + '.json')
            if path.exists():
                continue
            call = client.call(SCRAPE_ENDPOINT, {'url':url,'format':'md'}, scope='codex-source-repair-20261012', revision='diagnose-v1')
            verdict = assess_scrape(candidate, call.body)
            path.write_text(json.dumps({'target':candidate, 'body':call.body, 'outcome':call.outcome,
                'quarantined':call.quarantined,'cost_micro':call.charged_micro,'operation_id':call.operation_id,
                'verdict':verdict}, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({'id':candidate['provider_job_id'], 'outcome':call.outcome,
                'cost_micro':call.charged_micro, 'checks':verdict['checks'], 'status':verdict['status']}))
            if call.outcome != 'succeeded' or call.quarantined:
                break
    finally:
        summary=ledger.summary('codex-source-repair-20261012')
        (out/'ledger-summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
        print(json.dumps(summary))
        client.close()

if __name__ == '__main__':
    main()
