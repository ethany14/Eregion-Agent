"""P5 / S4: small live AnyAPI vs Crawl4AI comparison through Treg. Opt-in, no LLM calls.

Requires JOB_AGENT_TREG_LIVE_API_TEST=1 in the process environment. Uses the user's own
Treg key through the normal config loader (never printed). One persistent batch scope in an
isolated ledger DB: $0.10 total, at most 20 gateway requests, at most $0.01 per call;
restarts resume against the same ledger and never reset the budget.
"""
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent_runtime.career import treg_config  # noqa: E402
from agent_runtime.career.external_tool_usage import ExternalToolLedger  # noqa: E402
from agent_runtime.career.treg_client import TregClient, TregUnavailable  # noqa: E402
from agent_runtime.career.treg_jobs import SCRAPE_ENDPOINT, SEARCH_ENDPOINTS, assess_scrape, normalize_search, search_body  # noqa: E402

BATCH = 'treg-ab-live-20261012'
OUT = ROOT / '.codex-runs' / 'integrated-20261012' / 'treg-live'
# Frozen before any call: target search scope (documented personas), common inputs only.
GROUPS = [
    {'id': 'G1', 'query': 'junior data analyst', 'location': 'New York, NY', 'posted': 'week',
     'role': {'data', 'analyst'}, 'place': ('new york', ' ny', 'nyc'), 'unapplied': ['seniority (junior)']},
    {'id': 'G2', 'query': 'senior backend engineer', 'location': 'United States', 'posted': 'week',
     'role': {'backend', 'engineer'}, 'place': ('united states', 'remote', ', us'), 'unapplied': ['remote', 'seniority (senior)']},
    {'id': 'G3', 'query': 'machine learning intern', 'location': 'California', 'posted': 'week',
     'role': {'machine', 'learning'}, 'place': ('california', ', ca', 'san francisco', 'san jose', 'palo alto', 'mountain view'),
     'unapplied': ['internship type']},
    {'id': 'G4', 'query': 'junior UX designer', 'location': 'Austin, TX', 'posted': 'week',
     'role': {'designer'}, 'place': ('austin', ', tx'), 'unapplied': ['seniority (junior)']},
    {'id': 'G5', 'query': 'entry level data scientist', 'location': 'United States', 'posted': 'week',
     'role': {'data', 'scientist'}, 'place': ('united states', ', us', ' remote'), 'unapplied': ['seniority (entry)']},
]
SCRAPE_TARGET = 5


def relevant(group, row):
    title = (row.get('title') or '').lower()
    location = (row.get('location') or '').lower()
    role = all(w in re.findall(r'[a-z]+', title) for w in group['role'])
    place = any(p in f' {location}' for p in group['place']) if location else None
    return {'role_match': role, 'location_match': place, 'relevant': role and place is not False}


def main():
    if os.environ.get('JOB_AGENT_TREG_LIVE_API_TEST') != '1':
        raise SystemExit('Refusing: set JOB_AGENT_TREG_LIVE_API_TEST=1 for the explicit live comparison.')
    OUT.mkdir(parents=True, exist_ok=True)
    environ = {**os.environ, 'JOB_AGENT_TREG_ENABLED': '1', 'JOB_AGENT_TREG_TASK_MAX_COST_USD': '0.10',
               'JOB_AGENT_TREG_DAILY_MAX_COST_USD': '0.10', 'JOB_AGENT_TREG_CALL_MAX_COST_USD': '0.01',
               'JOB_AGENT_TREG_MAX_ATTEMPTS': '20', 'JOB_AGENT_TREG_MAX_CONCURRENCY': '1'}
    cfg = treg_config.load(environ=environ)
    if cfg.usable():
        raise SystemExit(f'Blocked: {cfg.usable()}')
    from api.db import create_database
    db = create_database('sqlite:///' + (OUT / 'ledger.db').as_posix(), create_schema_for_tests=True)
    ledger = ExternalToolLedger(db.session_factory, deployment='treg-ab-live')
    client = TregClient(cfg, ledger)
    evidence_path = OUT / 'evidence.json'
    evidence = json.loads(evidence_path.read_text(encoding='utf-8')) if evidence_path.exists() else {'searches': {}, 'scrapes': {}}
    print('ledger before:', json.dumps(ledger.summary(BATCH)))
    stop = None
    try:
        for index, group in enumerate(GROUPS):
            order = ['anyapi', 'crawl4ai'] if index % 2 == 0 else ['crawl4ai', 'anyapi']
            for provider in order:
                key = f"{group['id']}:{provider}"
                if key in evidence['searches']:
                    continue  # resume: never re-run a recorded call
                body = search_body(provider, group['query'], group['location'], group['posted'])
                try:
                    call = client.call(SEARCH_ENDPOINTS[provider], body, scope=BATCH, task_id=BATCH)
                except TregUnavailable as exc:
                    stop = exc.reason
                    raise
                rows, info = normalize_search(provider, call.body, max_results=10) if call.outcome == 'succeeded' else ([], {})
                for row in rows:
                    row.update(relevant(group, row))
                evidence['searches'][key] = {'group': group['id'], 'provider': provider, 'endpoint': SEARCH_ENDPOINTS[provider],
                    'body': body, 'unapplied_filters': group['unapplied'], 'outcome': call.outcome, 'http_status': call.http_status,
                    'charged_micro': call.charged_micro, 'cache': call.cache, 'replay': call.replay, 'served_via': call.served_via,
                    'call_id': call.call_id, 'error': call.error, 'seconds': call.seconds, 'info': info, 'rows': rows,
                    'raw_meta': (call.body or {}).get('meta') if isinstance(call.body, dict) else None}
                evidence_path.write_text(json.dumps(evidence, indent=1, ensure_ascii=False), encoding='utf-8')
                print(key, call.outcome, call.http_status, call.charged_micro, info.get('raw_items'), info.get('unique'))
        # Fixed selection rule: relevant, deduplicated by LinkedIn job id; intersection first,
        # then alternating provider-only rows across groups; at most 5 distinct pages.
        by_group = {}
        for record in evidence['searches'].values():
            for row in record['rows']:
                if row.get('relevant'):
                    by_group.setdefault(record['group'], {}).setdefault(row['provider_job_id'], {'row': row, 'providers': set()})[
                        'providers'].add(record['provider'])
        picks = []
        for tier in ('both', 'anyapi', 'crawl4ai'):
            for group in GROUPS:
                for job_id, item in by_group.get(group['id'], {}).items():
                    providers = item['providers']
                    match = len(providers) == 2 if tier == 'both' else providers == {tier}
                    if match and job_id not in {p['job_id'] for p in picks} and len(picks) < SCRAPE_TARGET:
                        picks.append({'job_id': job_id, 'group': group['id'], 'tier': tier, 'row': item['row']})
                        break
        evidence['scrape_selection'] = [{k: p[k] for k in ('job_id', 'group', 'tier')} for p in picks]
        for pick in picks:
            if pick['job_id'] in evidence['scrapes']:
                continue
            url = pick['row']['original_url']
            try:
                call = client.call(SCRAPE_ENDPOINT, {'url': url, 'format': 'md'}, scope=BATCH, task_id=BATCH)
            except TregUnavailable as exc:
                stop = exc.reason
                raise
            verdict = assess_scrape(pick['row'], call.body) if call.outcome == 'succeeded' else None
            markdown = (call.body or {}).get('markdown') if isinstance(call.body, dict) else None
            if markdown:
                (OUT / f"scrape-{pick['job_id']}.md").write_text(markdown, encoding='utf-8')
            evidence['scrapes'][pick['job_id']] = {'url': url, 'group': pick['group'], 'tier': pick['tier'],
                'title': pick['row'].get('title'), 'outcome': call.outcome, 'http_status': call.http_status,
                'charged_micro': call.charged_micro, 'cache': call.cache, 'call_id': call.call_id, 'error': call.error,
                'seconds': call.seconds, 'assessment': verdict}
            evidence_path.write_text(json.dumps(evidence, indent=1, ensure_ascii=False), encoding='utf-8')
            print('scrape', pick['job_id'], call.outcome, call.charged_micro, (verdict or {}).get('status'))
    except TregUnavailable:
        print('stopped:', stop)
    finally:
        evidence['ledger'] = ledger.summary(BATCH)
        evidence['ledger_rows'] = ledger.rows(BATCH)
        evidence['stop_reason'] = stop
        evidence['llm_calls'] = 0
        evidence_path.write_text(json.dumps(evidence, indent=1, ensure_ascii=False, default=str), encoding='utf-8')
        print('ledger after:', json.dumps(evidence['ledger']))
        client.close()


if __name__ == '__main__':
    main()
