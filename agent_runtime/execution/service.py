"""One owner for background work: bounded pools, per-key de-duplication and recovery.

Every long-running job kind (career tasks, multi-agent tasks, application runs,
interview inputs and feedback) is registered here instead of creating its own
thread pool and startup recovery loop. Durable ownership stays in each domain's
SQL tables (claims, leases, versions); this service owns the process side:

- a bounded worker pool per kind, so one kind cannot starve another;
- at most one queued-or-running job per (kind, key), which keeps per-instance
  FIFO work and prevents duplicate runs of the same task;
- startup recovery that runs exactly once per kind per service;
- a single close() that stops accepting work and drains pools;
- an inventory of dedicated resource threads (timers, browser-affine workers,
  SQL pollers) that are allowed to exist outside the pools, with their role.
"""
from __future__ import annotations

import logging
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Callable
from uuid import uuid4

log = logging.getLogger(__name__)


class ExecutionClosed(RuntimeError):
    """Raised when work is submitted after the service was closed."""


@dataclass
class JobKind:
    name: str
    max_workers: int
    recover: Callable[[], Any] | None = None
    pool: ThreadPoolExecutor | None = field(default=None, repr=False)
    recovered: bool = False
    active: dict[str, Future] = field(default_factory=dict, repr=False)


class ExecutionService:
    def __init__(self) -> None:
        self._lock = RLock()
        self._kinds: dict[str, JobKind] = {}
        self._resources: dict[str, str] = {}
        self._closed = False

    # -- registration -------------------------------------------------------------

    def register_kind(self, name: str, *, max_workers: int,
                      recover: Callable[[], Any] | None = None) -> JobKind:
        """Declare a job kind once; a second registration must agree on its bounds."""
        if max_workers < 1:
            raise ValueError("A job kind needs at least one worker.")
        with self._lock:
            self._require_open()
            existing = self._kinds.get(name)
            if existing is not None:
                if existing.max_workers != max_workers:
                    raise ValueError(f"Job kind '{name}' is already registered with another bound.")
                if recover is not None and existing.recover is None:
                    existing.recover = recover
                return existing
            kind = JobKind(name, max_workers, recover,
                           ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix=f"exec-{name}"))
            self._kinds[name] = kind
            return kind

    def register_owner(self, name: str, *, recover: Callable[[], Any] | None, role: str) -> JobKind:
        """A job kind executed on resource-affine threads (e.g. browser-bound runs).

        It has no pool here (its threads must own their resources) but its startup
        recovery is still run exactly once through this service.
        """
        with self._lock:
            self._require_open()
            existing = self._kinds.get(name)
            if existing is not None:
                if existing.pool is not None:
                    raise ValueError(f"Job kind '{name}' is already registered with a pool.")
                if recover is not None and existing.recover is None:
                    existing.recover = recover
                return existing
            kind = JobKind(name, 0, recover, None)
            self._kinds[name] = kind
            self._resources[name] = role
            return kind

    def register_resource(self, name: str, role: str) -> None:
        """Record a dedicated thread allowed outside the pools (timer, poller, browser owner)."""
        with self._lock:
            self._resources[name] = role

    # -- execution ----------------------------------------------------------------

    def submit(self, kind: str, key: str | None, function: Callable, *args, **kwargs) -> Future | None:
        """Queue function unless (kind, key) is already queued or running.

        Returns the job's Future, or None when the key is already active.

        key=None skips de-duplication for callers that coordinate re-runs themselves
        (a job that re-schedules its own key from its tail would otherwise be dropped).
        """
        with self._lock:
            self._require_open()
            job = self._kinds[kind]
            if job.pool is None:
                raise ValueError(f"Job kind '{kind}' runs on its own resource-affine threads.")
            if key is None:
                key = f"~{uuid4()}"
            current = job.active.get(key)
            if current is not None and not current.done():
                return None
            future = job.pool.submit(self._run, job, key, function, args, kwargs)
            job.active[key] = future
            return future

    def _run(self, job: JobKind, key: str, function, args, kwargs):
        try:
            return function(*args, **kwargs)
        finally:
            with self._lock:
                # Release the key before the future completes so a follow-up
                # submit for the same key (e.g. a new chat message) is accepted.
                job.active.pop(key, None)

    def running(self, kind: str, key: str) -> bool:
        with self._lock:
            job = self._kinds.get(kind)
            return bool(job and key in job.active)

    def recover(self, kind: str) -> bool:
        """Run the kind's startup recovery once; later calls are no-ops."""
        with self._lock:
            job = self._kinds[kind]
            if job.recovered or job.recover is None:
                return False
            job.recovered = True
            recover = job.recover
        recover()
        return True

    # -- lifecycle ----------------------------------------------------------------

    def close(self, *, wait: bool = False) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            kinds = list(self._kinds.values())
        for job in kinds:
            if job.pool is not None:
                job.pool.shutdown(wait=wait, cancel_futures=True)

    @property
    def closed(self) -> bool:
        return self._closed

    def inventory(self) -> dict:
        """Who owns background work in this process (for diagnostics and tests)."""
        with self._lock:
            return {
                "kinds": {name: {"max_workers": job.max_workers, "recovered": job.recovered,
                                 "active": sorted(key for key in job.active if not key.startswith("~")),
                                 "active_count": len(job.active)}
                          for name, job in self._kinds.items()},
                "resources": dict(self._resources),
            }

    def _require_open(self) -> None:
        if self._closed:
            raise ExecutionClosed("The execution service is closed.")
