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
import time
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from custom_agent.handlers import JobAgentStepHandler
from custom_agent.state import AgentState, Step
from job_agent.prompts import JOB_PROMPT, MATCH_PROMPT, RESUME_PROMPT, PROMPT_VERSION
from job_agent.schemas import JobAnalysis, ResumeAnalysis, SkillAssessment, SkillMatch, SCHEMA_VERSION

logger = logging.getLogger(__name__)
FIT_ANALYSIS_VERSION = 'parallel-evidence-v2'


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

    def get(self, key, compute, *, valid=None):
        if not self.limit:
            return compute(), False
        with self.lock:
            if key in self.values and valid is not None and not valid(self.values[key]):
                del self.values[key]
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
    main_model_calls: int = Field(default=3, ge=0)
    fast_model_calls: int = Field(default=0, ge=0)
    decision_routing: list[dict] = Field(default_factory=list)
    latency_seconds: float = Field(ge=0)
    stage_seconds: dict[str, float] = Field(default_factory=dict)
    cache_hits: list[str] = Field(default_factory=list)


class FitAnalysisService:
    """Route fit scoring to pure Jev or the original analysis pipeline."""

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
        analysis_cache=None,
        jev_config=None,
        jev_transport=None,
        jev_enabled=None,
    ) -> None:
        self._handler = handler or JobAgentStepHandler(analysis_cache=analysis_cache)
        self._timer = timer
        self._cache = _AnalysisCache(cache_size)
        self._analysis_cache = analysis_cache
        self._jev_config, self._jev_transport = jev_config, jev_transport
        self._jev_enabled = jev_enabled
        self._namespace = cache_namespace or getattr(
            self._handler, 'analysis_cache_namespace', lambda: 'custom-handler'
        )

    def cache_signature(self) -> str:
        if self.uses_jev():
            from job_agent.jev_fit.resolve import identity
            config=self._jev_settings()
            return 'jev-only:' + config.signature() + ':' + identity(config.resolve_unknowns)
        # Exact prompts/schemas and model configuration invalidate old results.
        content = [
            FIT_ANALYSIS_VERSION, PROMPT_VERSION, SCHEMA_VERSION,
            RESUME_PROMPT, JOB_PROMPT, MATCH_PROMPT, self._namespace(),
            *[schema.model_json_schema() for schema in (ResumeAnalysis, JobAnalysis, SkillAssessment)],
        ]
        return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()

    def uses_jev(self):
        from job_agent.jev_fit.settings import enabled
        return enabled() if self._jev_enabled is None else bool(self._jev_enabled() if callable(self._jev_enabled) else self._jev_enabled)

    def _jev_settings(self):
        from job_agent.jev_fit.settings import Settings, database_cache_path
        return self._jev_config or Settings.load(cache_path=database_cache_path(self._analysis_cache))

    async def analyze(self, *, resume_text: str, job_description: str, candidate_facts=None) -> FitAnalysisResult:
        return await asyncio.to_thread(
            self._analyze_sync,
            resume_text=resume_text,
            job_description=job_description,
            candidate_facts=candidate_facts,
        )

    def _analyze_sync(self, *, resume_text: str, job_description: str, candidate_facts=None) -> FitAnalysisResult:
        if self.uses_jev():
            config=self._jev_settings()
            from job_agent.jev_fit.settings import digest
            # Short-lived top-level reuse also shares concurrent identical calls.
            # Persisted decision expiry remains authoritative across processes.
            from job_agent.jev_fit.resolve import identity
            key=('jev-fit',config.signature(),identity(config.resolve_unknowns),digest([resume_text,job_description,candidate_facts or {}]))
            data,reused=self._cache.get(key,lambda:self._jev_many_sync(resume_text=resume_text,
                jobs=[{'id':'single','job_description':job_description}],candidate_facts=candidate_facts)['single'],
                valid=lambda result:(result.skill_match.valid_until or 0)>time.time())
            if reused:
                return data.model_copy(update={'analysis_id':f'analysis-{uuid4()}', 'model_calls':0,
                    'main_model_calls':0,'fast_model_calls':0,'decision_routing':[],
                    'latency_seconds':0,'stage_seconds':{},'cache_hits':['jev_fit']})
            return data
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
            main_model_calls=0 if reused else data['main_model_calls'],
            fast_model_calls=0 if reused else data['fast_model_calls'],
            decision_routing=[] if reused else data['decision_routing'],
            stage_seconds={} if reused else data['stage_seconds'],
            cache_hits=['resume', 'job', 'match'] if reused else data['cache_hits'],
            latency_seconds=max(0, self._timer() - started),
        )
        logger.info(
            'Fit analysis completed: model_calls=%s latency_seconds=%.3f cache_hits=%s stages=%s',
            result.model_calls, result.latency_seconds, result.cache_hits, result.stage_seconds,
        )
        return result

    def _jev_many_sync(self, *, resume_text, jobs, candidate_facts=None):
        from job_agent.jev_fit.service import JevFitService
        service=JevFitService(self._jev_settings(),owner=getattr(self._analysis_cache,'owner','local'),
                              transport=self._jev_transport)
        values=service.analyze_many(resume_text=resume_text,jobs=jobs,candidate_facts=candidate_facts)
        return {key:FitAnalysisResult(**value)for key,value in values.items()}

    async def analyze_many(self, *, resume_text, jobs, candidate_facts=None):
        if self.uses_jev():
            return await asyncio.to_thread(self._jev_many_sync,resume_text=resume_text,jobs=jobs,candidate_facts=candidate_facts)
        values=await asyncio.gather(*(self.analyze(resume_text=resume_text,job_description=j['job_description'])for j in jobs))
        return {j['id']:value for j,value in zip(jobs,values)}

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
            from agent_runtime.analysis_cache import cache_events
            with cache_events() as events:
                value, reused = self._cache.get((kind, namespace, key), compute)
            reused = reused or any(e['kind'] == kind and e['hit'] for e in events)
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
        from agent_runtime.fast_decisions import capture_routing
        from agent_runtime.analysis_cache import cache_events
        with capture_routing() as routing, cache_events() as events:
            matched = self._step(Step.MATCH_SKILLS, state)
        match_hit = any(e['kind'] == 'match' and e['hit'] for e in events)
        match_records = [r for r in routing if r['purpose'] == 'skill_evidence']
        main_calls = 0 if match_hit else (match_records[-1]['main_model_calls'] if match_records else 1)
        main_calls += int(not resume_hit) + int(not job_hit)
        fast_calls = sum(r['requests'] for r in routing)
        if matched.skill_match is None:
            raise RuntimeError('Skill match is missing.')
        return {
            'resume_analysis': resume_result,
            'job_analysis': job_result,
            'skill_match': matched.skill_match,
            'model_calls': main_calls + fast_calls,
            'main_model_calls': main_calls, 'fast_model_calls': fast_calls,
            'decision_routing': routing,
            'cache_hits': [kind for kind, hit in (('resume', resume_hit), ('job', job_hit), ('match', match_hit)) if hit],
            'stage_seconds': {
                'resume': resume_seconds,
                'job': job_seconds,
                'match': round(perf_counter() - started, 3),
            },
        }
