"""Offline attempt accounting, not live provider accuracy or cost."""
import json
from collections import Counter

import pytest

from api.services.fit_analysis_service import FitAnalysisService
from custom_agent.handlers import JobAgentStepHandler
from job_agent.schemas import JobAnalysis, ResumeAnalysis, SkillAssessment, SkillEvidence


class Attempts:
    chunked_matching = True

    def __init__(self, count=1, retry=False, metered=False):
        self.count, self.retry, self.metered = count, retry, metered
        self.calls = Counter()

    def cache_namespace(self):
        return 'offline-attempt-contract'

    def __call__(self, schema, system, content):
        from agent_runtime.provider_usage import provider_call
        if self.metered:
            with provider_call('offline-main') as details:
                value = self.compute(schema, content)
                details.update(input_tokens=10, output_tokens=5)
                return value
        return self.compute(schema, content)

    def compute(self, schema, content):
        self.calls[schema.__name__] += 1
        if schema is ResumeAnalysis:
            return ResumeAnalysis(summary='', skills=[], evidence=[], education=[])
        if schema is JobAnalysis:
            return JobAnalysis(title='Engineer', summary='', responsibilities=[], requirements=[{
                'requirement_id':f'r{i}', 'canonical_name':f'project_{i}',
                'original_text':f'Deliver project {i}.', 'atomic_text':f'Deliver project {i}.',
                'category':'responsibility','level':'required'} for i in range(self.count)])
        if self.retry and self.calls[schema.__name__] == 1:
            raise TimeoutError('offline matching attempt failed')
        job=JobAnalysis.model_validate_json(content.split('\n\nJob analysis:\n')[1])
        return SkillAssessment(matches=[SkillEvidence(requirement_id=r.requirement_id,
            job_skill=r.canonical_name, requirement_level=r.level, match_status='missing',
            resume_evidence=[], confidence=1) for r in job.requirements], explanation='', recommendations=[])


def run(service):
    return service._analyze_sync(resume_text='Candidate',
        job_description='\n'.join(f'Deliver project {i}.' for i in range(50)))


@pytest.mark.parametrize('count,retry,expected',[(1,True,4),(50,False,5),(50,True,6)])
def test_every_attempt_is_counted_including_retries_and_chunks(count,retry,expected):
    analyzer=Attempts(count=count,retry=retry)
    result=run(FitAnalysisService(JobAgentStepHandler(analyzer=analyzer),jev_enabled=False))
    assert sum(analyzer.calls.values())==expected
    assert result.model_calls==result.main_model_calls==expected
    assert result.fast_model_calls==0


def test_actual_provider_records_are_not_double_counted_and_failed_usage_is_unknown():
    analyzer=Attempts(retry=True,metered=True)
    service=FitAnalysisService(JobAgentStepHandler(analyzer=analyzer),jev_enabled=False)
    result=run(service)
    assert result.model_calls==4
    assert len(result.provider_attempts)==4
    assert result.provider_usage['calls']==4 and result.provider_usage['failed']==1
    assert result.provider_usage['unknown_usage_calls']==1
    assert not result.provider_usage['usage_complete']
    assert result.provider_usage['input_tokens']==30
    warm=run(service)
    assert warm.model_calls==0 and warm.provider_attempts==[]
    assert warm.provider_usage['calls']==0


@pytest.mark.parametrize('metered',[False,True])
def test_shared_analyzer_25_bullets_uses_four_extraction_batches_two_matching_batches(monkeypatch,metered):
    from custom_agent.handlers import SharedModelAnalyzer
    from job_agent.job_extraction import ReferencedJobExtraction
    from job_agent.resume_extraction import ResumeExtraction
    from job_agent.compact_match import CompactSkillAssessment
    from agent_runtime.provider_usage import provider_call, current_scope, usage_scope
    from contextlib import nullcontext
    from threading import Lock
    calls=[]; lock=Lock()
    def transport(model,schema,prompt,text):
        with lock:calls.append((schema.__name__,current_scope().get('task_id')))
        with provider_call('offline-structured-transport') if metered else nullcontext() as details:
            if details is not None:details.update(input_tokens=10,output_tokens=5)
            if schema is ResumeExtraction:
                return schema(summary='',skills=[],education=[],entries=[])
            payload=json.loads(text)
            if schema is ReferencedJobExtraction:
                return schema(title='Engineer',summary='',responsibility_sentence_ids=[],statements=[{
                    'sentence_id':key,'requirements':[{'canonical_name':payload['source_sentences'][key],
                    'display_name':payload['source_sentences'][key],'atomic_text':payload['source_sentences'][key],
                    'category':'responsibility','verification_mode':'resume_evidence','level':'required'}]
                    } for key in payload['extract_sentence_ids']])
            assert schema is CompactSkillAssessment
            return schema(matches=[{'requirement_id':r['requirement_id'],'status':'missing','evidence_ids':[]}
                for r in payload['requirements']])
    monkeypatch.setattr('custom_agent.handlers.invoke_structured',transport)
    monkeypatch.setattr('job_agent.model.invoke_structured',transport)
    monkeypatch.setattr('job_agent.model.shared_model',lambda **_:object())
    monkeypatch.setattr(SharedModelAnalyzer,'cache_namespace',lambda self:'offline-shared')
    from agent_runtime.fast_decisions import FastDecisions
    service=FitAnalysisService(JobAgentStepHandler(analyzer=SharedModelAnalyzer(),decisions=FastDecisions()),jev_enabled=False)
    with usage_scope(task_id='offline-multibatch'):
        result=service._analyze_sync(resume_text='Candidate',job_description='\n'.join(
            f'- Candidate must deliver unique project {i}.' for i in range(25)))
        warm=service._analyze_sync(resume_text='Candidate',job_description='\n'.join(
            f'- Candidate must deliver unique project {i}.' for i in range(25)))
    assert Counter(s for s,_ in calls)=={'ResumeExtraction':1,'ReferencedJobExtraction':4,'CompactSkillAssessment':2}
    assert all(task=='offline-multibatch' for _,task in calls)
    assert len(result.job_analysis.requirements)==len(result.skill_match.matches)==25
    assert result.model_calls==result.main_model_calls==7
    assert len(result.provider_attempts)==7 and warm.model_calls==0
    assert result.provider_usage['unknown_usage_calls']==(0 if metered else 7)
    assert result.provider_usage['usage_complete']==metered


def test_mixed_fast_main_requests_are_attributed_without_logical_stage_fallback():
    import httpx
    from agent_runtime.fast_decisions import FastDecisions
    class MixedHandler(JobAgentStepHandler):
        def _match_skills(self,state):
            result=fast.evaluate({}, {'q':{'type':'choice','instructions':{},'criteria':{'yes':'yes','no':'no'}}},purpose='offline-probe')
            assert result.status=='ok'
            return super()._match_skills(state)
    def transport(request):
        return httpx.Response(200,json={'model':'offline-fast','answers':{'q':{'type':'choice','choice':'yes',
            'confidence':1,'probabilities':{'yes':1,'no':0}}},'usage':{'input_tokens':7,'output_tokens':2}})
    fast=FastDecisions(api_key='offline',enabled=True,model='offline-fast',transport=httpx.MockTransport(transport))
    service=FitAnalysisService(MixedHandler(analyzer=Attempts(metered=True)),jev_enabled=False)
    result=run(service)
    assert result.model_calls==4 and result.main_model_calls==3 and result.fast_model_calls==1
    assert result.provider_usage['usage_complete']
    assert result.provider_usage['input_tokens']==37
    assert run(service).model_calls==0
    new_job=service._analyze_sync(resume_text='Candidate',job_description='Deliver project 0. Other role.')
    assert new_job.model_calls==2 and new_job.main_model_calls==2 and new_job.fast_model_calls==0
    assert 'resume' in new_job.cache_hits  # fast service cache also adds no attempt


def test_terminal_failure_retains_both_unknown_attempts():
    analyzer=Attempts(metered=True)
    original=analyzer.compute
    def fail(schema,content):
        if schema is SkillAssessment:raise TimeoutError('offline terminal timeout')
        return original(schema,content)
    analyzer.compute=fail
    with pytest.raises(TimeoutError) as error:
        run(FitAnalysisService(JobAgentStepHandler(analyzer=analyzer),jev_enabled=False))
    usage=error.value.fit_provider_usage
    assert usage['calls']==4 and usage['failed']==2 and usage['unknown_usage_calls']==2
    assert len(error.value.fit_provider_attempts)==4


def test_attempt_capture_survives_ledger_write_failure_and_preserves_scope():
    from agent_runtime.provider_usage import usage_scope, current_scope
    class FailedLedger:
        def start(self,*args):raise OSError('offline ledger write failure')
        def finish(self,*args):raise OSError('offline ledger write failure')
    analyzer=Attempts(retry=True,metered=True)
    with usage_scope(ledger=FailedLedger(),task_id='offline-ledger-failure'):
        result=run(FitAnalysisService(JobAgentStepHandler(analyzer=analyzer),jev_enabled=False))
        assert current_scope()['task_id']=='offline-ledger-failure'
    assert result.model_calls==4 and result.provider_usage['unknown_usage_calls']==1


def test_handler_without_model_io_reports_zero_instead_of_three_logical_stages():
    from test_fit_analysis_service import AnalysisOnlyHandler
    class NoIO(AnalysisOnlyHandler):
        def execute(self,step,state):return self.compute(step,state)
    result=run(FitAnalysisService(NoIO(),jev_enabled=False))
    assert result.model_calls==0 and result.provider_usage['calls']==0
    assert not result.provider_usage['usage_complete']
