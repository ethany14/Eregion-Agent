"""Analysis-only resume/JD matching without draft generation or review state."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import copy_context
from copy import deepcopy
from threading import RLock
from time import perf_counter
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from custom_agent.handlers import JobAgentStepHandler
from custom_agent.state import AgentState, Step
from job_agent.prompts import JOB_PROMPT, MATCH_PROMPT, RESUME_PROMPT, PROMPT_VERSION
from job_agent.schemas import JobAnalysis, ResumeAnalysis, SkillAssessment, SkillMatch, SCHEMA_VERSION

logger = logging.getLogger(__name__)
FIT_ANALYSIS_VERSION = 'parallel-evidence-v1'


class _AnalysisCache:
    """Bounded, process-local results; concurrent identical work shares one request.

    Only successful computations enter the cache. Values are copied on both sides
    so normalizers, API consumers, and subsequent requests cannot mutate them.
    """
    def __init__(self, limit: int = 128):
        if limit < 0:
            raise ValueError('cache_size cannot be negative.')
        self.limit, self.lock = limit, RLock()
        self.values, self.pending = OrderedDict(), {}

    def get(self, key, compute):
        if not self.limit:
            return compute(), False
        with self.lock:
            if key in self.values:
                self.values.move_to_end(key)
                return deepcopy(self.values[key]), True
            future = self.pending.get(key)
            owner = future is None
            if owner:
                future = Future()
                self.pending[key] = future
        if not owner:
            return deepcopy(future.result()), True
        try:
            value = compute()
            stored = deepcopy(value)
            with self.lock:
                self.values[key] = stored
                while len(self.values) > self.limit:
                    self.values.popitem(last=False)
            future.set_result(stored)
            return value, False
        except BaseException as exc:
            future.set_exception(exc)
            raise
        finally:
            with self.lock:
                self.pending.pop(key, None)


class FitAnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis_id: str
    status: str = "completed"
    resume_analysis: ResumeAnalysis
    job_analysis: JobAnalysis
    skill_match: SkillMatch
    model_calls: int = Field(default=3, ge=0)
    latency_seconds: float = Field(ge=0)
    stage_seconds: dict[str, float] = Field(default_factory=dict)
    cache_hits: list[str] = Field(default_factory=list)


class FitAnalysisService:
    """Parallel extraction with validated reuse; the scoring rules stay shared."""

    _STEPS = (
        Step.VALIDATE_INPUT,
        Step.ANALYZE_RESUME,
        Step.VALIDATE_EVIDENCE,
        Step.ANALYZE_JOB,
        Step.MATCH_SKILLS,
    )

    def __init__(
        self,
        handler: JobAgentStepHandler | None = None,
        *,
        timer: Callable[[], float] = perf_counter,
        cache_size: int = 128,
        cache_namespace: Callable[[], str] | None = None,
    ) -> None:
        self._handler = handler or JobAgentStepHandler()
        self._timer = timer
        self._cache = _AnalysisCache(cache_size)
        self._namespace = cache_namespace or getattr(
            self._handler, 'analysis_cache_namespace', lambda: 'custom-handler'
        )

    def cache_signature(self) -> str:
        # Exact prompts/schemas and model configuration invalidate old results.
        content = [
            FIT_ANALYSIS_VERSION, PROMPT_VERSION, SCHEMA_VERSION,
            RESUME_PROMPT, JOB_PROMPT, MATCH_PROMPT, self._namespace(),
            *[schema.model_json_schema() for schema in (ResumeAnalysis, JobAnalysis, SkillAssessment)],
        ]
        return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()

    async def analyze(self, *, resume_text: str, job_description: str) -> FitAnalysisResult:
        return await asyncio.to_thread(
            self._analyze_sync,
            resume_text=resume_text,
            job_description=job_description,
        )

    def _analyze_sync(self, *, resume_text: str, job_description: str) -> FitAnalysisResult:
        started = self._timer()
        state = AgentState(
            run_id=f"analysis-{uuid4()}",
            resume_text=resume_text,
            job_description=job_description,
        )
        state = self._step(Step.VALIDATE_INPUT, state)
        namespace = self.cache_signature()
        resume_key = hashlib.sha256(resume_text.strip().encode()).hexdigest()
        job_key = hashlib.sha256(job_description.strip().encode()).hexdigest()
        data, reused = self._cache.get(
            ('fit', namespace, resume_key, job_key),
            lambda: self._compute(state, namespace, resume_key, job_key),
        )
        result = FitAnalysisResult(
            analysis_id=state.run_id,
            **{key: data[key] for key in ('resume_analysis', 'job_analysis', 'skill_match')},
            model_calls=0 if reused else data['model_calls'],
            stage_seconds={} if reused else data['stage_seconds'],
            cache_hits=['resume', 'job', 'match'] if reused else data['cache_hits'],
            latency_seconds=max(0, self._timer() - started),
        )
        logger.info(
            'Fit analysis completed: model_calls=%s latency_seconds=%.3f cache_hits=%s stages=%s',
            result.model_calls, result.latency_seconds, result.cache_hits, result.stage_seconds,
        )
        return result

    def _step(self, step: Step, state: AgentState) -> AgentState:
        state = AgentState.model_validate({**state.model_dump(mode='python'), 'step': step})
        outcome = self._handler.execute(step, state)
        return AgentState.model_validate({**state.model_dump(mode='python'), **outcome.updates})

    def _compute(self, state: AgentState, namespace: str, resume_key: str, job_key: str):
        def resume():
            parsed = self._step(Step.ANALYZE_RESUME, state)
            validated = self._step(Step.VALIDATE_EVIDENCE, parsed)
            if validated.resume_analysis is None:
                raise RuntimeError('Resume analysis is missing.')
            return validated.resume_analysis

        def job():
            parsed = self._step(Step.ANALYZE_JOB, state)
            if parsed.job_analysis is None:
                raise RuntimeError('Job analysis is missing.')
            return parsed.job_analysis

        def extract(kind, key, compute):
            started = perf_counter()
            value, reused = self._cache.get((kind, namespace, key), compute)
            return value, reused, round(perf_counter() - started, 3)

        # These inputs are independent. Each branch gets its own state and model
        # accounting context; matching waits for both, including evidence validation.
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix='fit-extract') as pool:
            resume_future = pool.submit(copy_context().run, extract, 'resume', resume_key, resume)
            job_future = pool.submit(copy_context().run, extract, 'job', job_key, job)
            resume_result, resume_hit, resume_seconds = resume_future.result()
            job_result, job_hit, job_seconds = job_future.result()
        state = AgentState.model_validate({
            **state.model_dump(mode='python'),
            'resume_analysis': resume_result,
            'job_analysis': job_result,
        })
        started = perf_counter()
        matched = self._step(Step.MATCH_SKILLS, state)
        if matched.skill_match is None:
            raise RuntimeError('Skill match is missing.')
        return {
            'resume_analysis': resume_result,
            'job_analysis': job_result,
            'skill_match': matched.skill_match,
            'model_calls': 1 + int(not resume_hit) + int(not job_hit),
            'cache_hits': [kind for kind, hit in (('resume', resume_hit), ('job', job_hit)) if hit],
            'stage_seconds': {
                'resume': resume_seconds,
                'job': job_seconds,
                'match': round(perf_counter() - started, 3),
            },
        }
