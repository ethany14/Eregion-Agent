"""Bounded timing counters and stable progress comparison; no prompts or secrets."""
import hashlib
import json
from datetime import UTC, datetime

_VOLATILE = {'observation_id','screenshot_id','observed_at','at','duration_seconds','elapsed_seconds','image','screen'}
def stable_value(value):
    if isinstance(value, dict):return {k:stable_value(v) for k,v in value.items() if k not in _VOLATILE}
    if isinstance(value, list):return [stable_value(v) for v in value]
    return value

def outcome_fingerprint(value):
    return hashlib.sha256(json.dumps(stable_value(value),sort_keys=True,default=str).encode()).hexdigest()

def timing_update(state, stage, seconds, *, failed=False, tool=None, **metadata):
    key = stage + (':' + tool if tool else '')
    stats = dict(state.get('timing_summary',{}))
    row = dict(stats.get(key,{'count':0,'seconds':0.0,'failures':0}))
    row.update(count=row['count']+1,seconds=round(row['seconds']+seconds,3),failures=row['failures']+int(failed))
    stats[key]=row
    timing={'stage':stage,'duration_seconds':round(seconds,3),'failed':failed,
            'chat_revision':state.get('chat_revision',0),'at':datetime.now(UTC).isoformat(),**metadata}
    if tool:timing['tool']=tool
    return {'timing_summary':stats,'timings':[*state.get('timings',[]),timing][-80:]}

def history_context(history, *, current_page=True):
    result=[]
    for index, entry in enumerate(history[-16:]):
        row=dict(entry);data=row.get('result',{})
        if not isinstance(data,dict):
            result.append(row);continue
        # The fresh observation already includes the complete current page.
        if current_page and index < len(history[-16:])-4 and row.get('tool') in {'observe','browser_read','view_browser'} and not data.get('error'):
            row['result']={'observed':True,'note':'Use the current observation for page contents.'}
        elif index < len(history[-16:])-4 and len(json.dumps(data,default=str))>2500:
            row['result']={k:v for k,v in data.items() if k in {'error','error_code','next','filled','failed','verified','saved','waiting_for_user','question','progress_feedback'}} or {'excerpt':json.dumps(data,ensure_ascii=False,default=str)[:2500], 'truncated':True}
        result.append(row)
    return result
