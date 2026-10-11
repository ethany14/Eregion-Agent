"""Validated analysis reuse, shared by quick fit, workflow workers and warmup."""
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
import logging
from threading import RLock

from sqlalchemy import String, Text, select, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column
from api.db import Base

log = logging.getLogger(__name__)
_events = ContextVar('analysis_cache_events', default=None)

class AnalysisCacheRow(Base):
    __tablename__ = 'analysis_cache'
    cache_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    last_used_at: Mapped[str] = mapped_column(String(40), nullable=False, index=True)

def cache_key(kind, namespace, content, *, owner='local'):
    return hashlib.sha256(json.dumps([owner, kind, namespace, content],
        sort_keys=True, ensure_ascii=False, separators=(',', ':'), default=str).encode()).hexdigest()

@contextmanager
def cache_events():
    events = []
    token = _events.set(events)
    try:
        yield events
    finally:
        _events.reset(token)

class AnalysisCache:
    def __init__(self, sessions, *, owner='local', memory_limit=128, disk_limit=1024):
        self.sessions, self.owner = sessions, owner
        self.memory_limit, self.disk_limit = memory_limit, disk_limit
        self.lock, self.values, self.pending = RLock(), OrderedDict(), {}

    def get(self, kind, namespace, content, compute):
        key = cache_key(kind, namespace, content, owner=self.owner)
        with self.lock:
            if key in self.values:
                self.values.move_to_end(key)
                return self._result(kind, self.values[key], True)
            future = self.pending.get(key)
            owner = future is None
            if owner:
                future = self.pending[key] = Future()
        if not owner:
            value, eligible = future.result()
            if not eligible:
                from job_agent.reasoning import mark_uncacheable
                mark_uncacheable()
            return self._result(kind, value, True)
        try:
            now = datetime.now(UTC).isoformat()
            with self.sessions.begin() as session:
                row = session.get(AnalysisCacheRow, key)
                value = json.loads(row.payload_json) if row else None
                if row:
                    row.last_used_at = now
            hit = value is not None
            if not hit:
                from job_agent.reasoning import cache_observation
                with cache_observation() as eligible:
                    value = compute()  # caller completes all validation BEFORE storage
                if not eligible():
                    future.set_result((deepcopy(value), False))
                    return self._result(kind, value, False)
                encoded = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
                try:
                    with self.sessions.begin() as session:
                        session.add(AnalysisCacheRow(cache_key=key, kind=kind, payload_json=encoded,
                            created_at=now, last_used_at=now))
                        session.flush()
                        stale = list(session.scalars(select(AnalysisCacheRow.cache_key)
                            .order_by(AnalysisCacheRow.last_used_at.desc()).offset(self.disk_limit)))
                        if stale:
                            session.execute(delete(AnalysisCacheRow).where(AnalysisCacheRow.cache_key.in_(stale)))
                except IntegrityError:
                    pass  # another process stored the same validated computation
            with self.lock:
                self.values[key] = deepcopy(value)
                while len(self.values) > self.memory_limit:
                    self.values.popitem(last=False)
            future.set_result((deepcopy(value), True))
            return self._result(kind, value, hit)
        except BaseException as exc:
            future.set_exception(exc)
            raise
        finally:
            with self.lock:
                self.pending.pop(key, None)

    @staticmethod
    def _result(kind, value, hit):
        events = _events.get()
        if events is not None:
            events.append({'kind': kind, 'hit': hit})
        return deepcopy(value)

_warm_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='resume-warmup')
_warming, _warm_lock = set(), RLock()

def warm_resume(sessions, text, *, owner='local'):
    """Bounded best-effort precomputation. Upload responses never await a model."""
    import os
    from job_agent.jev_fit.settings import enabled
    if enabled():
        return  # Jev-only fit must not launch an unrequested main-model warmup.
    if os.getenv('JOB_AGENT_ANALYSIS_WARMUP', '1').lower() in {'0', 'false', 'off'}:
        return
    key = cache_key('warmup', owner, text)
    with _warm_lock:
        if key in _warming or len(_warming) >= 4:
            return
        _warming.add(key)
    def run():
        try:
            from custom_agent.handlers import JobAgentStepHandler
            from custom_agent.state import AgentState, Step
            handler = JobAgentStepHandler(analysis_cache=AnalysisCache(sessions, owner=owner))
            handler.execute(Step.ANALYZE_RESUME, AgentState(run_id='resume-warmup', resume_text=text, job_description=''))
        except Exception as exc:
            log.info('Resume warmup deferred: %s', type(exc).__name__)
        finally:
            with _warm_lock:
                _warming.discard(key)
    from contextvars import copy_context
    from agent_runtime.provider_usage import UsageLedger, usage_scope
    with usage_scope(ledger=UsageLedger(sessions), purpose='resume_warmup'):
        return _warm_pool.submit(copy_context().run, run)
