"""Bounded timing counters and stable progress comparison; no prompts or secrets."""
import hashlib
import json
import traceback
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
    for metric in ('context_chars', 'input_tokens', 'output_tokens'):
        if metric in metadata and metadata.get('requests', 1):
            row[metric + '_total'] = row.get(metric + '_total', 0) + metadata[metric]
            row[metric + '_samples'] = row.get(metric + '_samples', 0) + 1
    if stage in {'model', 'answer_verification', 'fast_options'}:
        calls = max(0, int(metadata.get('requests', 1)))
        row['provider_calls'] = row.get('provider_calls', row['count'] - 1) + calls
        page = outcome_fingerprint(state.get('page_history', []))[:16]
        pages = dict(row.get('per_page', {}))
        pages[page] = pages.get(page, 0) + calls
        row['per_page'] = pages
    stats[key]=row
    timing={'stage':stage,'duration_seconds':round(seconds,3),'failed':failed,
            'chat_revision':state.get('chat_revision',0),'at':datetime.now(UTC).isoformat(),**metadata}
    if tool:timing['tool']=tool
    return {'timing_summary':stats,'timings':[*state.get('timings',[]),timing][-80:]}

def model_metrics(messages, tools, response=None):
    """Sizes and provider token counters only; never persist prompts or images."""
    result = {'context_chars': sum(len(m.content) for m in messages if isinstance(m.content, str)),
              'tool_schema_chars': len(json.dumps(tools, ensure_ascii=False, separators=(',', ':'))),
              'message_count': len(messages), 'tool_count': len(tools)}
    usage = getattr(response, 'usage_metadata', None) or {}
    for key in ('input_tokens', 'output_tokens'):
        value = usage.get(key)
        if type(value) is int and value >= 0:
            result[key] = value
    return result


def safe_traceback(error, limit=12):
    """File/line/function frames only. Exception messages can carry candidate data."""
    frames = traceback.extract_tb(error.__traceback__)[-limit:]
    return "".join(f"  {frame.filename}:{frame.lineno} in {frame.name}\n" for frame in frames)


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


def application_perf_summary(state):
    stats = state.get('timing_summary', {})
    models = [row for key, row in stats.items() if key in {'model', 'answer_verification', 'fast_options'}]
    totals = {metric: (sum(row.get(metric + '_total', 0) for row in models),
                      sum(row.get(metric + '_samples', 0) for row in models))
              for metric in ('context_chars', 'input_tokens', 'output_tokens')}
    per_page = {}
    for row in models:
        for page, count in row.get('per_page', {}).items():
            per_page[page] = per_page.get(page, 0) + count
    try:
        start = datetime.fromisoformat(state['created_at'].replace('Z', '+00:00'))
        wall = max(0, (datetime.now(UTC) - start.replace(tzinfo=start.tzinfo or UTC)).total_seconds())
    except (KeyError, ValueError, TypeError):
        wall = 0
    return {'model_calls': sum(row.get('provider_calls', row['count']) for row in models), 'model_calls_per_page': per_page,
        'model_seconds': round(sum(row['seconds'] for row in models), 3),
        'browser_seconds': round(max(0, sum(row['seconds'] for key, row in stats.items()
            if key == 'observation' or key.startswith('tool:')) -
            sum(stats.get(key, {}).get('seconds', 0) for key in ('fast_options', 'answer_verification'))), 3),
        'wall_seconds': round(wall, 3),
        **{'average_' + metric: round(total / samples, 1) if samples else None
           for metric, (total, samples) in totals.items()}}
