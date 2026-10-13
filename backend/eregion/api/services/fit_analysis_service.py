"""Analysis-only resume/JD matching without draft generation or review state."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
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

from eregion.domain.workflow.handlers import JobAgentStepHandler
from eregion.domain.workflow.state import AgentState, Step
from eregion.domain.prompts import JOB_PROMPT, MATCH_PROMPT, RESUME_PROMPT, PROMPT_VERSION
from eregion.domain.schemas import JobAnalysis, ResumeAnalysis, SkillAssessment, SkillMatch, SCHEMA_VERSION

logger = logging.getLogger(__name__)
FIT_ANALYSIS_VERSION = 'parallel-evidence-v4-attempts-frozen-catalogue'


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
            value, eligible = future.result()
            if not eligible:
                from eregion.domain.reasoning import mark_uncacheable
                mark_uncacheable()
            return deepcopy(value), True
        try:
            from eregion.domain.reasoning import cache_observation
            with cache_observation() as eligible:
                value = compute()
            if not eligible():
                future.set_result((deepcopy(value), False))
                return value, False
            stored = deepcopy(value)
            with self.lock:
                self.values[key] = stored
                while len(self.values) > self.limit:
                    self.values.popitem(last=False)
            future.set_result((stored, True))
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
    model_calls: int = Field(default=0, ge=0)
    main_model_calls: int = Field(default=0, ge=0)
    fast_model_calls: int = Field(default=0, ge=0)
    decision_routing: list[dict] = Field(default_factory=list)
    latency_seconds: float = Field(ge=0)
    stage_seconds: dict[str, float] = Field(default_factory=dict)
    cache_hits: list[str] = Field(default_factory=list)
    provider_attempts: list[dict] = Field(default_factory=list)
    provider_usage: dict = Field(default_factory=dict)
    catalogue_identity: dict | None = None


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
            from eregion.domain.jev_fit.resolve import identity
            config=self._jev_settings()
            return 'jev-only:' + config.signature() + ':' + identity(config.resolve_unknowns)
        # Exact prompts/schemas and model configuration invalidate old results.
        content = [
            FIT_ANALYSIS_VERSION, PROMPT_VERSION, SCHEMA_VERSION,
            RESUME_PROMPT, JOB_PROMPT, MATCH_PROMPT, self._namespace(),
            *[schema.model_json_schema() for schema in (ResumeAnalysis, JobAnalysis, SkillAssessment)],
            # Switching local/extract, or changing the local catalogue builder, must recompute.
            self.catalogue_identity(),
        ]
        return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()

    @staticmethod
    def catalogue_mode():
        return 'extract' if os.getenv('JOB_AGENT_MAIN_CATALOG', 'local').strip().lower() == 'extract' else 'local'

    @classmethod
    def catalogue_identity(cls):
        mode = cls.catalogue_mode()
        if mode == 'extract':
            return [mode]
        from pathlib import Path
        from eregion.domain import requirement_catalog
        from eregion.domain.jev_fit import core
        sources = [hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest() for m in (requirement_catalog, core)]
        return [mode, requirement_catalog.LOCAL_PRODUCER, *sources]

    def uses_jev(self):
        from eregion.domain.jev_fit.settings import enabled
        return enabled() if self._jev_enabled is None else bool(self._jev_enabled() if callable(self._jev_enabled) else self._jev_enabled)

    def _jev_settings(self):
        from eregion.domain.jev_fit.settings import Settings, database_cache_path
        return self._jev_config or Settings.load(cache_path=database_cache_path(self._analysis_cache))

    async def analyze(self, *, resume_text: str, job_description: str, candidate_facts=None,
                      fixed_job_catalog=None) -> FitAnalysisResult:
        return await asyncio.to_thread(
            self._analyze_sync,
            resume_text=resume_text,
            job_description=job_description,
            candidate_facts=candidate_facts,
            fixed_job_catalog=fixed_job_catalog,
        )

    @staticmethod
    def _default_catalogue(body):
        """Local deterministic catalogue unless JOB_AGENT_MAIN_CATALOG=extract.

        Returns None (free extraction) when the text has no recognisable requirement.
        """
        if FitAnalysisService.catalogue_mode() == 'extract':
            return None
        from eregion.domain.requirement_catalog import FrozenRequirementCatalog
        catalogue = FrozenRequirementCatalog.from_local_units(body)
        # Only personal conditions (or nothing) recognised: the posting states no skill
        # requirements in a recognisable form, so let the model extract implied ones.
        skills = [r for r in json.loads(catalogue.payload_json)['requirements'] if r['category'] != 'eligibility']
        return catalogue if skills else None

    @staticmethod
    def _validate_catalogue_input(catalogue, body, *, jev_route):
        if catalogue is None:
            return None
        from eregion.domain.requirement_catalog import FrozenRequirementCatalog
        if not isinstance(catalogue, FrozenRequirementCatalog):
            raise ValueError('Expected a trusted internal frozen catalogue')
        job = catalogue.validate_for(body)
        if jev_route:
            raise ValueError('Fixed catalogue input is for main matching, not Jev extraction')
        return job

    def _analyze_sync(self, *, resume_text: str, job_description: str, candidate_facts=None,
                      fixed_job_catalog=None) -> FitAnalysisResult:
        # Trusted internal input only. Validate before cache lookup or any provider.
        jev_route = self.uses_jev()
        fixed_job = self._validate_catalogue_input(fixed_job_catalog,job_description,jev_route=jev_route)
        if not jev_route and fixed_job_catalog is None:
            # Default main route (A1): score against a deterministic local catalogue so
            # the requirement list, and therefore the score, is the same every run.
            fixed_job_catalog = self._default_catalogue(job_description)
            if fixed_job_catalog is not None:
                fixed_job = fixed_job_catalog.validate_for(job_description)
        if jev_route:
            config=self._jev_settings()
            from eregion.domain.jev_fit.settings import digest
            # Short-lived top-level reuse also shares concurrent identical calls.
            # Persisted decision expiry remains authoritative across processes.
            from eregion.domain.jev_fit.resolve import identity
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
        if fixed_job_catalog is not None:
            namespace += ':catalogue:' + fixed_job_catalog.cache_signature()
        resume_key = hashlib.sha256(resume_text.strip().encode()).hexdigest()
        job_key = hashlib.sha256(job_description.strip().encode()).hexdigest()
        data, reused = self._cache.get(
            ('fit', namespace, resume_key, job_key),
            lambda: self._compute(state, namespace, resume_key, job_key, fixed_job=fixed_job,
                catalogue_signature=fixed_job_catalog.cache_signature() if fixed_job_catalog else None),
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
            provider_attempts=[] if reused else data['provider_attempts'],
            provider_usage=data['empty_usage'] if reused else data['provider_usage'],
            catalogue_identity=({'catalogue_sha256':fixed_job_catalog.catalogue_sha256,
                'producer_signature':fixed_job_catalog.producer_signature,
                'body_sha256':fixed_job_catalog.body_sha256} if fixed_job_catalog else None),
        )
        logger.info(
            'Fit analysis completed: model_calls=%s latency_seconds=%.3f cache_hits=%s stages=%s',
            result.model_calls, result.latency_seconds, result.cache_hits, result.stage_seconds,
        )
        return result

    def _jev_many_sync(self, *, resume_text, jobs, candidate_facts=None):
        from eregion.domain.jev_fit.service import JevFitService
        service=JevFitService(self._jev_settings(),owner=getattr(self._analysis_cache,'owner','local'),
                              transport=self._jev_transport)
        values=service.analyze_many(resume_text=resume_text,jobs=jobs,candidate_facts=candidate_facts)
        return {key:FitAnalysisResult(**value)for key,value in values.items()}

    async def analyze_many(self, *, resume_text, jobs, candidate_facts=None):
        jev_route = self.uses_jev()
        # All-or-nothing preflight before scheduling even the first job. Otherwise
        # a later invalid catalogue can race with paid work for an earlier job.
        for job in jobs:
            self._validate_catalogue_input(job.get('fixed_job_catalog'),job['job_description'],jev_route=jev_route)
        if jev_route:
            return await asyncio.to_thread(self._jev_many_sync,resume_text=resume_text,jobs=jobs,candidate_facts=candidate_facts)
        values=await asyncio.gather(*(self.analyze(resume_text=resume_text,job_description=j['job_description'],
            fixed_job_catalog=j.get('fixed_job_catalog'))for j in jobs))
        return {j['id']:value for j,value in zip(jobs,values)}

    def _step(self, step: Step, state: AgentState) -> AgentState:
        state = AgentState.model_validate({**state.model_dump(mode='python'), 'step': step})
        outcome = self._handler.execute(step, state)
        return AgentState.model_validate({**state.model_dump(mode='python'), **outcome.updates})

    def _compute(self, state, namespace, resume_key, job_key, *, fixed_job=None, catalogue_signature=None):
        from eregion.runtime.provider_usage import capture_provider_attempts, summarize, usage_scope
        with capture_provider_attempts() as attempts, usage_scope(fit_catalogue_signature=catalogue_signature):
            try:
                data = self._compute_steps(state, namespace, resume_key, job_key, fixed_job=fixed_job)
            except Exception as exc:
                # Terminal failures still expose attempts; durable ledger retains
                # independently recorded unknown spend. Never retry telemetry.
                exc.fit_provider_attempts = deepcopy(attempts)
                exc.fit_provider_usage = summarize(attempts)
                raise
        data.update(provider_attempts=deepcopy(attempts), provider_usage=summarize(attempts),
            empty_usage=summarize([]), model_calls=len(attempts),
            fast_model_calls=sum(a.get('model_route')=='fast' for a in attempts),
            main_model_calls=sum(a.get('model_route')!='fast' for a in attempts))
        return data

    def _compute_steps(self, state: AgentState, namespace: str, resume_key: str, job_key: str, *, fixed_job=None):
        def resume():
            parsed = self._step(Step.ANALYZE_RESUME, state)
            validated = self._step(Step.VALIDATE_EVIDENCE, parsed)
            if validated.resume_analysis is None:
                raise RuntimeError('Resume analysis is missing.')
            return validated.resume_analysis

        def job():
            if fixed_job is not None:
                return fixed_job.model_copy(deep=True)
            parsed = self._step(Step.ANALYZE_JOB, state)
            if parsed.job_analysis is None:
                raise RuntimeError('Job analysis is missing.')
            return parsed.job_analysis

        def extract(kind, key, compute):
            started = perf_counter()
            from eregion.runtime.analysis_cache import cache_events
            # Resume analysis never depends on the job's catalogue; keying it by the
            # catalogue re-analysed the same resume for every locally catalogued job.
            scope = namespace.split(':catalogue:', 1)[0] if kind == 'resume' else namespace
            with cache_events() as events:
                value, reused = self._cache.get((kind, scope, key), compute)
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
        from eregion.runtime.fast_decisions import capture_routing
        from eregion.runtime.analysis_cache import cache_events
        with capture_routing() as routing, cache_events() as events:
            matched = self._step(Step.MATCH_SKILLS, state)
        match_hit = any(e['kind'] == 'match' and e['hit'] for e in events)
        if matched.skill_match is None:
            raise RuntimeError('Skill match is missing.')
        if fixed_job is not None:
            expected = [r.requirement_id for r in fixed_job.requirements]
            actual = [m.requirement_id for m in matched.skill_match.matches]
            if actual != expected or matched.job_analysis != fixed_job:
                raise ValueError('Matching changed the frozen catalogue or ordered IDs')
        return {
            'resume_analysis': resume_result,
            'job_analysis': job_result,
            'skill_match': matched.skill_match,
            'decision_routing': routing,
            'cache_hits': [kind for kind, hit in (('resume', resume_hit), ('job', job_hit), ('match', match_hit)) if hit],
            'stage_seconds': {
                'resume': resume_seconds,
                'job': job_seconds,
                'match': round(perf_counter() - started, 3),
            },
        }
