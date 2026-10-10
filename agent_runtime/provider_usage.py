"""Provider-call ledger. Stores counts and identifiers, never prompts or credentials."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
import json
import logging
import time
from functools import wraps
from uuid import uuid4

from sqlalchemy import Boolean, Column, String, Text, or_, select, update
from api.db import Base

log = logging.getLogger(__name__)
_scope = ContextVar('provider_usage_scope', default={})


class ProviderUsageRow(Base):
    __tablename__ = 'provider_usage'
    call_id = Column(String(40), primary_key=True)
    task_id = Column(String(40), index=True)
    run_id = Column(String(40), index=True)
    request_id = Column(String(40), index=True)
    adopted = Column(Boolean, nullable=False, default=True)
    created_at = Column(String(40), nullable=False)
    details_json = Column(Text, nullable=False)


@contextmanager
def usage_scope(**values):
    token = _scope.set({**_scope.get(), **values})
    try:
        yield
    finally:
        _scope.reset(token)


def current_scope():
    return dict(_scope.get())


def track_run(identifier, purpose):
    """Re-establish attribution on worker resume, including after a server restart."""
    def decorate(function):
        @wraps(function)
        def tracked(self, run_id, *args, **kwargs):
            sessions = getattr(self.repository, 'sessions', None)
            with usage_scope(**{identifier: run_id}, purpose=purpose,
                             ledger=UsageLedger(sessions) if sessions is not None else None):
                return function(self, run_id, *args, **kwargs)
        return tracked
    return decorate


def token_counts(usage):
    """Normalize LangChain and OpenAI/TypeSafe counters; absent is not zero."""
    usage = usage if isinstance(usage, dict) else {}
    result = {}
    for name, alias in (('input_tokens', 'prompt_tokens'), ('output_tokens', 'completion_tokens')):
        value = usage.get(name, usage.get(alias))
        if type(value) is int and value >= 0:
            result[name] = value
    for name, paths in {
        'cached_input_tokens': [('input_token_details', 'cache_read'), ('prompt_tokens_details', 'cached_tokens')],
        'reasoning_tokens': [('output_token_details', 'reasoning'), ('completion_tokens_details', 'reasoning_tokens')],
    }.items():
        for parent, child in paths:
            nested = usage.get(parent)
            value = nested.get(child) if isinstance(nested, dict) else None
            if type(value) is int and value >= 0:
                result[name] = value
                break
    return result


class UsageLedger:
    def __init__(self, sessions):
        self.sessions = sessions

    def start(self, call_id, scope, details):
        with self.sessions.begin() as db:
            discarded = scope.get('request_discarded')
            db.add(ProviderUsageRow(call_id=call_id, task_id=scope.get('task_id'),
                run_id=scope.get('run_id'), request_id=scope.get('request_id'), adopted=not (discarded and discarded.is_set()),
                created_at=datetime.now(UTC).isoformat(), details_json=json.dumps(details)))

    def finish(self, call_id, details):
        # Do not overwrite the independently updated adoption flag on a late response.
        with self.sessions.begin() as db:
            db.execute(update(ProviderUsageRow).where(ProviderUsageRow.call_id == call_id)
                .values(details_json=json.dumps(details)))

    def discard(self, request_id):
        with self.sessions.begin() as db:
            db.execute(update(ProviderUsageRow).where(ProviderUsageRow.request_id == request_id).values(adopted=False))

    def summary(self, *, task_id=None, run_ids=()):
        conditions = []
        if task_id: conditions.append(ProviderUsageRow.task_id == task_id)
        if run_ids: conditions.append(ProviderUsageRow.run_id.in_(run_ids))
        if not conditions:
            return summarize([])
        with self.sessions() as db:
            rows = db.scalars(select(ProviderUsageRow).where(or_(*conditions)))
            return summarize([{**json.loads(row.details_json), 'adopted': row.adopted} for row in rows])


def summarize(rows):
    result = {'calls': 0, 'completed': 0, 'failed': 0, 'pending': 0, 'discarded': 0, 'retries': 0,
              'input_tokens': 0, 'output_tokens': 0, 'unknown_usage_calls': 0, 'groups': []}
    groups = {}
    for row in rows:
        result['calls'] += 1
        result[row.get('status', 'pending')] += 1
        result['discarded'] += int(not row.get('adopted', True))
        result['retries'] += int(row.get('attempt', 1) > 1)
        known = all(key in row for key in ('input_tokens', 'output_tokens'))
        result['unknown_usage_calls'] += int(not known)
        key = (row.get('purpose', 'unspecified'), row.get('model', 'unknown'))
        group = groups.setdefault(key, {'purpose': key[0], 'model': key[1], 'calls': 0,
            'input_tokens': 0, 'output_tokens': 0, 'unknown_usage_calls': 0})
        group['calls'] += 1
        group['unknown_usage_calls'] += int(not known)
        for metric in ('input_tokens', 'output_tokens', 'cached_input_tokens', 'reasoning_tokens'):
            if metric in row:
                result[metric] = result.get(metric, 0) + row[metric]
                group[metric] = group.get(metric, 0) + row[metric]
    result['groups'] = list(groups.values())
    result['usage_complete'] = result['calls'] > 0 and result['unknown_usage_calls'] == 0
    return result


@contextmanager
def provider_call(model, **sizes):
    scope = current_scope()
    ledger = scope.get('ledger')
    started = time.monotonic()
    call_id = str(uuid4())
    details = {'model': str(model), 'purpose': scope.get('purpose', 'unspecified'),
               'attempt': scope.get('attempt', 1),
               'status': 'pending', **{k: v for k, v in sizes.items() if k in
                {'context_chars', 'tool_schema_chars', 'image_count'}}}
    def persist(method):
        if ledger is not None:
            try:
                if method == 'start': ledger.start(call_id, scope, details)
                else: ledger.finish(call_id, details)
            except Exception as exc:
                # Telemetry failure must not repeat a paid request or a browser action.
                log.warning('Provider usage persistence failed: %s', type(exc).__name__)
    persist('start')
    try:
        yield details
        if details['status'] == 'pending': details['status'] = 'completed'
    except BaseException as exc:
        details.update(status='failed', error_type=type(exc).__name__)
        raise
    finally:
        details['duration_seconds'] = round(time.monotonic() - started, 3)
        persist('finish')
        discarded = scope.get('request_discarded')
        if ledger is not None and discarded and discarded.is_set():
            try: ledger.discard(scope['request_id'])
            except Exception as exc: log.warning('Late usage discard failed: %s', type(exc).__name__)


def record_chat_usage(details, result):
    generations = getattr(result, 'generations', [])
    message = generations[0].message if generations else None
    usage = getattr(message, 'usage_metadata', None) or (getattr(result, 'llm_output', None) or {}).get('token_usage')
    details.update(token_counts(usage))
