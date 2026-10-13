"""Bounded source-only comparison. No model calls; token estimates are not billing usage."""
import json, os, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from eregion.runtime.career.treg_jobs import search_body,normalize_search,SEARCH_ENDPOINTS,SCRAPE_ENDPOINT,assess_scrape
from eregion.runtime.career.search_filters import filter_cards
QUERIES=[('junior data analyst','New York, NY','entry'),('graduate data analyst','New York, NY','entry'),('software engineer intern','New York, NY','internship')]
def size(value):
    text=json.dumps(value,ensure_ascii=False,separators=(',',':'))
    return {'chars':len(text),'utf8_bytes':len(text.encode()),'token_estimate_chars_div4':round(len(text)/4),
            'token_estimator':'rough chars/4; not model-specific or billed usage'}
def main():
    if os.getenv('JOB_AGENT_TREG_LIVE_API_TEST')!='1': raise SystemExit('Explicit live opt-in required')
    from eregion.api.db import create_database
    from eregion.runtime.career.treg_config import load
    from eregion.runtime.career.external_tool_usage import ExternalToolLedger
    from eregion.runtime.career.treg_client import TregClient
    out=ROOT/'.codex-runs/filter-api-mcp-20261012';out.mkdir(parents=True,exist_ok=True)
    cfg=load(environ={**os.environ,'JOB_AGENT_TREG_ENABLED':'1','JOB_AGENT_TREG_MAX_ATTEMPTS':'30',
        'JOB_AGENT_TREG_TASK_MAX_COST_USD':'0.10','JOB_AGENT_TREG_DAILY_MAX_COST_USD':'0.10','JOB_AGENT_TREG_CALL_MAX_COST_USD':'0.01'})
    db=create_database('sqlite:///'+(out/'ledger.db').as_posix(),create_schema_for_tests=True)
    ledger=ExternalToolLedger(db.session_factory,deployment='filter-api-mcp')
    client=TregClient(cfg,ledger,deadline_seconds=90)
    records=[];targets={};scope='filter-api-mcp-20261012'
    try:
        # Alternating order reduces a simple provider-order confound. Only first pages.
        for i,(query,location,level) in enumerate(QUERIES):
            for provider in (('anyapi','crawl4ai') if i%2==0 else ('crawl4ai','anyapi')):
                label=f'{i}-{provider}';path=out/(label+'.json')
                if path.exists(): saved=json.loads(path.read_text(encoding='utf-8'))
                else:
                    body=search_body(provider,query,location,experience_level=level,limit=20)
                    start=time.monotonic();call=client.call(SEARCH_ENDPOINTS[provider],body,scope=scope,revision=label)
                    saved={'query':query,'location':location,'provider':provider,'body_sent':body,'seconds':round(time.monotonic()-start,3),
                        'outcome':call.outcome,'http_status':call.http_status,'charged_micro':call.charged_micro,'cache':call.cache,
                        'quarantined':call.quarantined,'response':call.body,'attempts':call.attempts}
                    path.write_text(json.dumps(saved,ensure_ascii=False,indent=2),encoding='utf-8')
                jobs,info=normalize_search(provider,saved['response'],max_results=20) if saved['outcome']=='succeeded' and not saved['quarantined'] else ([],{})
                kept,screen=filter_cards(jobs,{'goal':f'Find {query} jobs in {location}'})
                for j in kept: targets.setdefault(j['provider_job_id'],j)
                record={k:v for k,v in saved.items() if k!='response'}
                record.update(candidates=len(jobs),retained=len(kept),coverage=info,screen=screen,raw_size=size(saved['response']),normalized_size=size(kept),model_calls=0,model_tokens=0)
                records.append(record);print(json.dumps({k:v for k,v in record.items() if k not in ('screen','coverage','body_sent') }),flush=True)
                if saved['quarantined'] or saved['outcome']=='unknown':return
        # Fixed shared detail targets saved for subsequent MCP comparison.
        selected=list(targets.values())[:3]
        (out/'shared-targets.json').write_text(json.dumps(selected,indent=2),encoding='utf-8')
        for candidate in selected:
            label='detail-'+candidate['provider_job_id'];path=out/(label+'.json')
            if path.exists(): saved=json.loads(path.read_text(encoding='utf-8'))
            else:
                start=time.monotonic();call=client.call(SCRAPE_ENDPOINT,{'url':candidate['url'],'format':'md'},scope=scope,revision=label)
                saved={'target':candidate,'seconds':round(time.monotonic()-start,3),'outcome':call.outcome,'quarantined':call.quarantined,
                       'charged_micro':call.charged_micro,'cache':call.cache,'response':call.body}
                path.write_text(json.dumps(saved,ensure_ascii=False,indent=2),encoding='utf-8')
            verdict=assess_scrape(candidate,saved['response']) if saved['outcome']=='succeeded' and not saved['quarantined'] else {}
            records.append({k:v for k,v in saved.items() if k!='response'}|{'verdict':{k:v for k,v in verdict.items() if k!='description_text'},'raw_size':size(saved['response']),'model_calls':0,'model_tokens':0})
            if saved['quarantined'] or saved['outcome']=='unknown':break
    finally:
        result={'scope':'source-only, first-page, small sample; not end-to-end B6 or statistical reliability','records':records,'ledger':ledger.summary(scope)}
        report=ROOT/'docs/benchmarks/filter-api-mcp-20261012/api-results.json';report.parent.mkdir(parents=True,exist_ok=True)
        report.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');client.close()
        print(json.dumps(result['ledger']),flush=True)
if __name__=='__main__':main()
