"""Read-only export of synthetic test state and billing counters, including failures.

Usage: python scripts/export_remaining_evidence.py tmp/remaining-live-search
Raw DBs/transcripts remain in tmp; compact JSON is safe for the synthetic fixtures
only. Never run against a real candidate database.
"""
import json
import sqlite3
import sys
from pathlib import Path

def export(root):
    from eregion.runtime.provider_usage import summarize
    results=[]
    for path in sorted(root.glob('*/career.db')):
        with sqlite3.connect(f'file:{path.as_posix()}?mode=ro',uri=True) as db:
            tasks=[json.loads(row[0]) for row in db.execute('select state_json from career_tasks')]
            usage=[{'task_id':row[0],**json.loads(row[1]),'adopted':bool(row[2])}
                for row in db.execute('select task_id,details_json,adopted from provider_usage')]
        for state in tasks:
            if not state.get('model_calls'):continue
            item={k:state.get(k) for k in ('task_id','status','goal','model_calls','error','jobs','packs','application_runs','progress_guard','created_at','updated_at')}
            item['final']=next((m.get('text') for m in reversed(state['messages']) if m['role']=='assistant'),None)
            item['usage']=summarize([r for r in usage if r['task_id']==state['task_id']])
            item['fixture_total_usage']=summarize(usage)
            item['unattributed_usage']=summarize([r for r in usage if not r['task_id']])
            item['fixture']=path.parent.name
            item['tools']=[h['tool'] for h in state['history']]
            results.append(item)
    destination=root/'evidence-summary.json'
    destination.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    for result in results:print(json.dumps({k:result[k] for k in ('fixture','status','model_calls','error','usage')},ensure_ascii=True))
    return results

if __name__=='__main__':
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
    export(Path(sys.argv[1]))
