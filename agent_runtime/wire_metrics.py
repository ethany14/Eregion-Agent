"""Measure the final provider request (P1): what actually stays identical between requests.

Only lengths and short hashes are recorded. Full request text stays in a small in-memory
LRU for the comparison and is never logged or persisted. After a restart there is no
previous request, so the common prefix is unknown (None), not zero.
"""
import hashlib
import json
from collections import OrderedDict
from threading import Lock

_previous = OrderedDict()
_lock = Lock()
_LIMIT = 64
SEPARATOR = '\x1e'


def _digest(text):
    return hashlib.sha256(text.encode('utf-8', 'surrogatepass')).hexdigest()[:16]


def _common_prefix(a, b):
    limit = min(len(a), len(b))
    low, high = 0, limit
    while low < high:  # binary search on equal prefixes, O(n log n) slicing but no Python loop per char
        mid = (low + high + 1) // 2
        if a[:mid] == b[:mid]:
            low = mid
        else:
            high = mid - 1
    return low


def measure(payload, key):
    """Return wire metrics for this request and remember it as the previous one for key."""
    tools = json.dumps(payload.get('tools') or [], ensure_ascii=False, separators=(',', ':'))
    messages = [json.dumps(m, ensure_ascii=False, separators=(',', ':'), default=str)
                for m in payload.get('messages') or []]
    # Providers place tool definitions with the system prompt at the head of the prompt;
    # measure tools first, then messages in order.
    parts = [tools, *messages]
    text = SEPARATOR.join(parts)
    system = next((m for m, raw in zip(messages, payload.get('messages') or [])
                   if isinstance(raw, dict) and raw.get('role') == 'system'), '')
    result = {'wire_chars': len(text), 'wire_tools_chars': len(tools), 'wire_messages': len(messages),
              'wire_tools_hash': _digest(tools), 'wire_system_hash': _digest(system) if system else None,
              'wire_last_message_chars': len(messages[-1]) if messages else 0}
    with _lock:
        previous = _previous.pop(key, None)
        _previous[key] = text
        while len(_previous) > _LIMIT:
            _previous.popitem(last=False)
    if previous is None:
        result.update(wire_common_prefix_chars=None, wire_first_change='unknown_no_previous')
        return result
    common = _common_prefix(previous, text)
    result['wire_common_prefix_chars'] = common
    if common == len(text) == len(previous):
        result['wire_first_change'] = 'identical'
    else:
        offset, location = 0, 'end'
        for index, part in enumerate(parts):
            end = offset + len(part)
            if common < end:
                location = 'tools' if index == 0 else f'message:{index - 1}'
                break
            offset = end + len(SEPARATOR)
        result['wire_first_change'] = location
    return result


def key_for(scope, model_name):
    return '|'.join(str(scope.get(k, '')) for k in ('task_id', 'run_id', 'purpose')) + '|' + str(model_name)


def reset():
    with _lock:
        _previous.clear()
