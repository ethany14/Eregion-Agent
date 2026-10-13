import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from threading import Barrier, Event

import pytest

from eregion.domain.workflow.state import Step
from eregion.domain.workflow.steps import StepOutcome
from eregion.api.services.fit_analysis_service import FitAnalysisService
from eregion.domain.schemas import JobAnalysis, ResumeAnalysis, SkillMatch


@pytest.fixture(autouse=True)
def legacy_fit_engine(monkeypatch):
    # These tests exercise the original pipeline, independent of local .env.
    monkeypatch.setenv('TYPESAFE_ENABLED', 'false')


class AnalysisOnlyHandler:
    def __init__(self) -> None:
        self.steps: list[Step] = []

    def execute(self, step: Step, state) -> StepOutcome:
        # Synthetic transport boundaries: a handler with no model IO must not
        # silently be counted as three paid provider calls.
        if step in {Step.ANALYZE_RESUME,Step.ANALYZE_JOB,Step.MATCH_SKILLS}:
            from eregion.runtime.provider_usage import provider_call
            with provider_call('offline-handler-fixture'):
                return self.compute(step,state)
        return self.compute(step,state)

    def compute(self, step: Step, state) -> StepOutcome:
        self.steps.append(step)
        if step == Step.VALIDATE_INPUT:
            if not state.resume_text.strip() or not state.job_description.strip():
                raise ValueError("invalid input")
            return StepOutcome()
        if step == Step.ANALYZE_RESUME:
            return StepOutcome(updates={"resume_analysis": ResumeAnalysis(
                summary="Python developer", skills=["Python"], evidence=[], education=[]
            )})
        if step == Step.VALIDATE_EVIDENCE:
            return StepOutcome()
        if step == Step.ANALYZE_JOB:
            return StepOutcome(updates={"job_analysis": JobAnalysis(
                title="Backend Engineer", summary="Python", requirements=[],
                responsibilities=[]
            )})
        if step == Step.MATCH_SKILLS:
            return StepOutcome(updates={"skill_match": SkillMatch.model_validate({
                "matches": [], "explanation": "Deterministic match",
                "recommendations": [], "missing_required_requirements": [],
                "missing_preferred_requirements": [], "overall_score": 100,
                "score_breakdown": {"overall_score": 100},
                "confirmation_requirements": [],
            })})
        raise AssertionError(f"Fit analysis called forbidden step {step.value}")


def test_fit_analysis_stops_before_writer_and_verifier():
    handler = AnalysisOnlyHandler()
    ticks = iter([10.0, 10.25])
    result = FitAnalysisService(handler, timer=lambda: next(ticks))._analyze_sync(
        resume_text="Python developer",
        job_description="Requires Python",
    )
    assert handler.steps[0] == Step.VALIDATE_INPUT
    assert handler.steps[-1] == Step.MATCH_SKILLS
    assert set(handler.steps) == {Step.VALIDATE_INPUT,Step.ANALYZE_RESUME,
        Step.VALIDATE_EVIDENCE,Step.ANALYZE_JOB,Step.MATCH_SKILLS}
    assert handler.steps.index(Step.ANALYZE_RESUME)<handler.steps.index(Step.VALIDATE_EVIDENCE)
    assert result.status == "completed"
    assert result.skill_match.overall_score == 100
    assert result.model_calls == 3
    assert result.latency_seconds == .25


def test_independent_extractions_overlap_and_preserve_call_context():
    meeting = Barrier(2,timeout=3)
    context = ContextVar('fit-test-context',default=None)
    class ParallelHandler(AnalysisOnlyHandler):
        def execute(self,step,state):
            assert context.get()=='meter-context'
            if step in {Step.ANALYZE_RESUME,Step.ANALYZE_JOB}:
                assert state.resume_analysis is None and state.job_analysis is None
                meeting.wait()  # A serial pipeline cannot reach this barrier.
            if step==Step.MATCH_SKILLS:
                assert state.resume_analysis and state.job_analysis
                assert Step.VALIDATE_EVIDENCE in self.steps
            return super().execute(step,state)
    token = context.set('meter-context')
    try:
        result = asyncio.run(FitAnalysisService(ParallelHandler()).analyze(
            resume_text='Python developer',job_description='Requires Python'))
    finally:context.reset(token)
    assert result.model_calls==3 and set(result.stage_seconds)=={'resume','job','match'}


def test_unchanged_resume_reused_for_new_job_and_exact_repeat_uses_no_model():
    handler = AnalysisOnlyHandler()
    service = FitAnalysisService(handler)
    def run(resume='Python developer',job='Requires Python'):
        return service._analyze_sync(resume_text=resume,job_description=job)
    first = run()
    second = run(job='Requires Python and SQL')
    assert first.model_calls==3 and first.cache_hits==[]
    assert second.model_calls==2 and second.cache_hits==['resume']
    assert handler.steps.count(Step.ANALYZE_RESUME)==1
    first.resume_analysis.skills.append('Not real')
    first.skill_match.explanation='Changed by caller'
    repeated = run()
    assert repeated.model_calls==0 and repeated.analysis_id!=first.analysis_id
    assert repeated.resume_analysis.skills==['Python']
    assert repeated.skill_match.explanation=='Deterministic match'
    changed = run(resume='Python developer with SQL')
    assert changed.model_calls==2 and changed.cache_hits==['job']


def test_cache_changes_with_model_namespace_prompts_and_schema(monkeypatch):
    import eregion.api.services.fit_analysis_service as module
    namespace=['model-a']
    service=FitAnalysisService(AnalysisOnlyHandler(),cache_namespace=lambda:namespace[0])
    def run():return service._analyze_sync(resume_text='Python developer',job_description='Requires Python')
    assert run().model_calls==3 and run().model_calls==0
    namespace[0]='model-b'
    assert run().model_calls==3
    monkeypatch.setattr(module,'MATCH_PROMPT',module.MATCH_PROMPT+' Updated')
    assert run().model_calls==3
    monkeypatch.setattr(module,'SCHEMA_VERSION','changed-schema')
    assert run().model_calls==3


def test_concurrent_identical_analysis_shares_requests():
    entered, release = Event(), Event()
    class WaitingHandler(AnalysisOnlyHandler):
        def execute(self,step,state):
            if step==Step.MATCH_SKILLS:
                entered.set()
                assert release.wait(3)
            return super().execute(step,state)
    handler=WaitingHandler();service=FitAnalysisService(handler)
    def run():return service._analyze_sync(resume_text='Python developer',job_description='Requires Python')
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(run)
        assert entered.wait(3)
        second=pool.submit(run)
        release.set()
        results=[first.result(),second.result()]
    assert sorted(r.model_calls for r in results)==[0,3]
    assert handler.steps.count(Step.ANALYZE_RESUME)==1
    assert handler.steps.count(Step.ANALYZE_JOB)==1
    assert handler.steps.count(Step.MATCH_SKILLS)==1


def test_ungrounded_resume_is_never_cached_or_matched():
    from eregion.domain.workflow.handlers import JobAgentStepHandler
    from eregion.domain.schemas import ResumeEvidence
    calls=[]
    def analyze(schema,*_):
        calls.append(schema)
        if schema is ResumeAnalysis:
            return ResumeAnalysis(summary='Python',skills=['Python'],education=[],evidence=[ResumeEvidence(
                evidence_id='temporary',source_section='Experience',exact_text='Invented experience')])
        if schema is JobAnalysis:return JobAnalysis(title='Engineer',summary='',requirements=[],responsibilities=[])
        raise AssertionError('Matching must not run with ungrounded evidence')
    service=FitAnalysisService(JobAgentStepHandler(analyzer=analyze))
    for _ in range(2):
        with pytest.raises(ValueError,match='Evidence is not present'):
            service._analyze_sync(resume_text='Python developer',job_description='Requires Python')
    assert calls.count(ResumeAnalysis)==2


def test_failed_match_retries_using_validated_extractions():
    class FailingHandler(AnalysisOnlyHandler):
        failed=False
        def execute(self,step,state):
            if step==Step.MATCH_SKILLS and not self.failed:
                self.failed=True
                raise RuntimeError('Provider unavailable')
            return super().execute(step,state)
    service=FitAnalysisService(FailingHandler())
    with pytest.raises(RuntimeError,match='Provider unavailable'):
        service._analyze_sync(resume_text='Python developer',job_description='Requires Python')
    retry=service._analyze_sync(resume_text='Python developer',job_description='Requires Python')
    assert retry.model_calls==1 and retry.cache_hits==['resume','job']


def test_cache_eviction_and_disabled_cache_bound_retention():
    from eregion.api.services.fit_analysis_service import _AnalysisCache
    cache=_AnalysisCache(1)
    assert cache.get('a',lambda:'first')==('first',False)
    cache.get('b',lambda:'second')
    assert cache.get('a',lambda:'refetched')==('refetched',False)
    service=FitAnalysisService(AnalysisOnlyHandler(),cache_size=0)
    for _ in range(2):
        assert service._analyze_sync(resume_text='Python developer',job_description='Requires Python').model_calls==3


def test_parallel_cached_pipeline_keeps_evidence_and_score_identical_to_serial():
    from eregion.domain.workflow.handlers import JobAgentStepHandler
    from eregion.domain.workflow.state import AgentState
    from test_job_workflow import fake_analyze
    handler=JobAgentStepHandler(analyzer=fake_analyze)
    state=AgentState(run_id='baseline',resume_text='Built Python APIs.',job_description='Requires Python APIs.')
    for step in FitAnalysisService._STEPS:
        state=AgentState.model_validate({**state.model_dump(),'step':step})
        state=AgentState.model_validate({**state.model_dump(),**handler.execute(step,state).updates})
    service=FitAnalysisService(handler)
    for _ in range(2):
        result=service._analyze_sync(resume_text=state.resume_text,job_description=state.job_description)
        assert result.resume_analysis==state.resume_analysis
        assert result.job_analysis==state.job_analysis
        assert result.skill_match==state.skill_match


def test_writer_failure_cannot_affect_fit_analysis():
    class WriterBombHandler(AnalysisOnlyHandler):
        def execute(self, step, state):
            if step in {Step.WRITE_RESUME, Step.VERIFY_RESUME}:
                raise RuntimeError("writer/verifier unavailable")
            return super().execute(step, state)

    result = FitAnalysisService(WriterBombHandler())._analyze_sync(
        resume_text="Python developer",
        job_description="Requires Python",
    )
    assert result.skill_match.overall_score == 100
