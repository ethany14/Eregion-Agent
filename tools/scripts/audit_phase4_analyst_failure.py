"""Read-only terminal audit. Ledger/action labels are not full tool arguments."""
import hashlib
import json
import sqlite3
from pathlib import Path


def main():
    case=Path('tmp/remaining-live-analyst-phase4-recovery/test_long_real_search_conversa0')
    state=json.loads((case/'transcript.json').read_text(encoding='utf-8'))
    history=state['history']
    variants=list(dict.fromkeys(j['url'] for h in history for j in h.get('result',{}).get('jobs',[])
        if 'joblist.com/' in j.get('url','')))
    fixture={'provenance':{'task_id':state['task_id'],'transcript':str(case/'transcript.json'),
        'sha256':hashlib.sha256((case/'transcript.json').read_bytes()).hexdigest(),
        'scope':'Only the retained final 24 tool actions have arguments/results; NOT all 52 model calls.'},
        'joblist_variants':variants,'history':history,
        'state':{k:state.get(k) for k in ('goal','messages','chat_revision','user_turn_id',
            'observed_job_candidates','job_read_attempts','candidate_rejections','retrieved_jobs',
            'search_candidates','search_source_health','jobs')}}
    fixture['state']['recommendations']=state.get('recommendations',[])
    with sqlite3.connect('file:'+str((case/'career.db').resolve()).replace('\\','/')+'?mode=ro',uri=True) as db:
        ledger=[{'call_id':row[0],**json.loads(row[1])} for row in db.execute(
            'select call_id,details_json from provider_usage where task_id=? order by created_at',(state['task_id'],))]
    paths=[case/name for name in ('summary.json','transcript.json','acceptance.json')]
    paths.extend(Path('tmp')/('remaining-live-analyst-phase4-recovery.'+ext) for ext in ('xml','log','exitcode'))
    audit={'task_id':state['task_id'],'summary':json.loads((case/'summary.json').read_text(encoding='utf-8')),
        'acceptance':json.loads((case/'acceptance.json').read_text(encoding='utf-8')),
        'actual_final':state['messages'][-1]['text'],
        'history_boundary':{'retained_actions':len(history),
            'no_new_evidence':sum(bool(h.get('no_new_evidence') or h.get('result',{}).get('no_new_evidence')) for h in history),
            'search_jobs':sum(h['tool']=='search_jobs' for h in history),
            'action_labels_only':state.get('actions',[]),
            'limitation':'52 durable action labels have timestamps/outcome labels only, not missing early arguments/results. Bounded runtime exchanges/archive cannot reconstruct all earlier decisions.'},
        'ledger':ledger,'usage':{'calls':len(ledger),'input':sum(r.get('input_tokens',0) for r in ledger),
            'output':sum(r.get('output_tokens',0) for r in ledger),
            'main_input':sum(r.get('input_tokens',0) for r in ledger if r.get('purpose')=='agent'),
            'usage_complete':all(r.get('status')=='completed' and r.get('input_tokens') is not None and r.get('output_tokens') is not None for r in ledger)},
        'recorded_last_request_metrics':state['loop_runtime']['context_metrics'],
        'artifacts':[{'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths]}
    from eregion.runtime.career.alerts import job_key
    from eregion.runtime.progress import search_evidence
    from eregion.runtime.telemetry import outcome_fingerprint
    audit['tracking_before']={'variants':variants,'job_key_count':len({job_key(u) for u in variants}),
        'search_fingerprint_count':len({outcome_fingerprint(search_evidence({'jobs':[{'url':u,'source':'public_search'}]})) for u in variants})}
    for dest,value in ((Path('tests/fixtures/remaining_phase4_analyst_failure.json'),fixture),
        (Path('docs/diagnostics/remaining-2026-10-11/analyst-phase4-recovery-failure-and-usage.json'),audit)):
        if dest.exists():raise FileExistsError(dest)
        dest.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'task_id':state['task_id'],'usage':audit['usage'],'tracking':audit['tracking_before'],
        'retained_actions':len(history)},ensure_ascii=False))


if __name__=='__main__':
    import sys
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
    main()
