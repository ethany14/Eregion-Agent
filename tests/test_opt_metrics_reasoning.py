"""Offline wire compatibility, attribution, escalation and frozen B6 baseline."""
import json
import os
from pathlib import Path
import httpx
import pytest
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from agent_runtime.provider_usage import (UsageLedger, current_scope, usage_scope,
    capture_provider_attempts, summarize, provider_call)
from job_agent.model import create_model, ProviderCompatibleChatOpenAI, invoke_structured, model_settings_fingerprint
from job_agent.reasoning import purpose_key, SCHEMA_PURPOSES
from evals.opt_report import report, metrics
from test_b6_offline_replay import replay, offline_guard, frozen_web, ScriptedModel
from test_career_flow import career
from test_mock_interview import setup as interview_setup


PURPOSES = [None, 'agent', 'fast', 'extraction', 'scoring', 'pack_writer', 'claim_verifier',
    'interview_question', 'interview_feedback', 'job_screening', 'skill_evidence',
    'skill_evidence_verify', 'question_category', 'memory_relevance', 'form_options',
    'browse', 'application', 'api', 'resume_profile', 'skill_evaluation', 'jev_fit_resolver', 'InterviewQuestion', 'InterviewAnswerAssessment',
    'extract_requirements', 'refine_extraction_yes_no', 'condition_category_yes_no',
    'support_yes_no', 'focused_yes_no', 'clarify_full_support_yes_no', 'verify_citations_yes_no']


def response(content='ok'):
    return httpx.Response(200, json={'id': 'offline', 'object': 'chat.completion', 'created': 1,
        'model': 'test', 'choices': [{'index': 0, 'finish_reason': 'stop',
            'message': {'role': 'assistant', 'content': content}}],
        'usage': {'prompt_tokens': 10, 'completion_tokens': 4, 'total_tokens': 14,
            'prompt_tokens_details': {'cached_tokens': 5}, 'completion_tokens_details': {'reasoning_tokens': 2}}})


@pytest.mark.parametrize('purpose', PURPOSES)
def test_default_payload_bytes_and_override_precedence(tmp_path, purpose):
    bodies = []
    def transport(request):
        bodies.append(request.content)
        return response()
    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        settings = {'LLM_MODEL_ID': 'test', 'LLM_API_KEY': 'fake', 'LLM_BASE_URL': 'https://offline.invalid/v1',
            'LLM_AGENT_REASONING': 'medium', 'LLM_EXTRACTION_REASONING': 'high'}
        legacy = 'high' if purpose == 'extraction' else 'medium' if purpose in {'agent', 'fast'} else None
        old = ChatOpenAI(model='test', api_key='fake', base_url=settings['LLM_BASE_URL'],
            temperature=0, max_retries=0, timeout=45, http_client=client,
            **({'reasoning_effort': legacy} if legacy else {}))
        factory = lambda **kw: ProviderCompatibleChatOpenAI(http_client=client, **kw)
        new = create_model(env_path=tmp_path/'missing', environ=settings, purpose=purpose, model_factory=factory)
        old.invoke([HumanMessage(content='same request')])
        new.invoke([HumanMessage(content='same request')])
        assert bodies[0] == bodies[1]
        override = create_model(env_path=tmp_path/'missing', environ={**settings, purpose_key(purpose): 'low'},
            purpose=purpose, model_factory=factory)
        override.invoke('override')
        assert json.loads(bodies[-1])['reasoning_effort'] == 'low'


@pytest.mark.parametrize('schema,purpose', list(SCHEMA_PURPOSES.items()))
def test_schema_purpose_overrides_bound_shared_model(tmp_path, schema, purpose):
    model = create_model(env_path=tmp_path/'missing', environ={'LLM_MODEL_ID':'test', 'LLM_API_KEY':'fake',
        purpose_key(purpose): 'low'}, purpose='extraction')
    with usage_scope(reasoning_purpose=purpose):
        options, metadata = model._attempt_options({})
    assert options['reasoning_effort'] == 'low'
    assert not metadata['reasoning_escalation']


class Tiny(BaseModel):
    answer: int


@pytest.mark.parametrize('level,expected', [('low','medium'), ('medium','high'), ('high','high'), (None,None)])
def test_one_validation_escalation_with_ledger(monkeypatch, level, expected):
    monkeypatch.setenv('JOB_AGENT_REASONING_ESCALATION', '1')
    bodies = []
    def transport(request):
        bodies.append(json.loads(request.content))
        return response('{"answer":"bad"}' if len(bodies) == 1 else '{"answer":3}')
    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        model = ProviderCompatibleChatOpenAI(model='test', api_key='fake', http_client=client,
            max_retries=0, reasoning_effort=level)
        with capture_provider_attempts() as rows:
            assert invoke_structured(model, Tiny, 'system', 'human').answer == 3
    assert len(bodies) == 2
    assert bodies[-1].get('reasoning_effort') == expected
    assert rows[-1]['reasoning_escalation'] == (level != expected)
    assert rows[-1]['attempt'] == 2


def test_reject_reasoning_retries_plain_once():
    bodies = []
    def transport(request):
        bodies.append(json.loads(request.content))
        if len(bodies) == 1:
            return httpx.Response(400, json={'error': {'message':'unsupported reasoning_effort', 'type':'invalid_request_error'}})
        return response()
    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        model = ProviderCompatibleChatOpenAI(model='test', api_key='fake', http_client=client,
            reasoning_effort='low', max_retries=0)
        with capture_provider_attempts() as rows, usage_scope(queue_wait_seconds=.25):
            model.invoke('hello')
    assert len(rows) == 2 and rows[0]['status'] == 'failed'
    assert 'reasoning_effort' not in bodies[1]
    assert [r['queue_wait_seconds'] for r in rows] == [.25,0]


@pytest.mark.parametrize('purpose', PURPOSES)
def test_cache_fingerprint_isolates_levels(tmp_path, purpose):
    base = {'LLM_MODEL_ID':'test'}
    a = model_settings_fingerprint(env_path=tmp_path/'missing', environ={**base,purpose_key(purpose):'low'})
    b = model_settings_fingerprint(env_path=tmp_path/'missing', environ={**base,purpose_key(purpose):'medium'})
    assert a != b


def test_jev_and_fast_cache_identity():
    from job_agent.jev_fit.settings import Settings
    from agent_runtime.fast_decisions import FastDecisions
    assert Settings('fake', reasoning={'LLM_REASONING_SUPPORT_YES_NO':'low'}).signature() != Settings(
        'fake', reasoning={'LLM_REASONING_SUPPORT_YES_NO':'medium'}).signature()
    assert FastDecisions(reasoning={'LLM_REASONING_FORM_OPTIONS':'low'}).cache_namespace() != FastDecisions(
        reasoning={'LLM_REASONING_FORM_OPTIONS':'medium'}).cache_namespace()


@pytest.mark.parametrize('case', ['r1', 'r2', 'r3', 'correct'])
def test_b6_composition_baseline(replay, monkeypatch, tmp_path, case):
    rows = []
    original = ScriptedModel.invoke
    def invoke(self, messages, tools):
        scope = current_scope()
        row = {'source':'scripted_offline', 'purpose':'agent', 'model':'b6-scripted-offline',
            'status':'completed', 'input_tokens':0, 'output_tokens':0,
            'context_metrics':scope['context_metrics'], 'queue_wait_seconds':scope['queue_wait_seconds']}
        rows.append(row)
        return original(self, messages, tools)
    monkeypatch.setattr(ScriptedModel, 'invoke', invoke)
    result = replay(case)
    assert len(rows) == result.model.calls
    for row in rows:
        composition = row['context_metrics']
        assert sum(composition['request_parts_chars'].values()) == composition['request_text_chars']
        assert row['queue_wait_seconds'] >= 0
    # Store offline measurements separately; no fabricated provider events in the
    # production replay DB (the unchanged B6 acceptance asserts zero providers).
    import sqlite3
    db_path = tmp_path/'offline-usage.db'
    with sqlite3.connect(db_path) as db:
        db.execute('CREATE TABLE provider_usage (details_json TEXT, adopted BOOLEAN)')
        db.executemany('INSERT INTO provider_usage VALUES (?, 1)', [(json.dumps(r),) for r in rows])
    measured = report(db_path)
    assert measured['calls'] == len(rows) and measured['input_tokens'] == 0
    assert measured['composition_samples'] == len(rows)
    output = os.getenv('OPT_BASELINE_DIR')
    if output:
        target = Path(output); target.mkdir(parents=True, exist_ok=True)
        measured['source'] = 'B6 scripted ' + case
        (target/(case+'.json')).write_text(json.dumps(measured, indent=2)+'\n', encoding='utf-8')


def test_old_report_does_not_invent_missing_fields(tmp_path):
    import sqlite3
    path = tmp_path/'old.db'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE provider_usage (details_json TEXT, adopted BOOLEAN)')
        db.execute('INSERT INTO provider_usage VALUES (?,1)', (json.dumps({'status':'completed',
            'input_tokens':100, 'output_tokens':20, 'duration_seconds':1.25}),))
    result = report(path)
    assert result['cache_hit_ratio'] is None and result['reasoning_share'] is None
    assert result['composition_samples'] == 0
    assert result['timing_seconds']['provider_duration_seconds'] is None
    assert result['timing_seconds']['duration_seconds'] == {'count':1,'p50':1.25,'p95':1.25,'max':1.25}


def test_career_kernel_provider_rows_include_repair_and_timing(tmp_path):
    from agent_runtime.loop_engine import AgentLoop, Turn
    from agent_runtime.loop_model import ModelRequests
    from api.db import create_database
    from sqlalchemy import select
    from agent_runtime.provider_usage import ProviderUsageRow
    database = create_database('sqlite:///' + (tmp_path/'kernel.db').as_posix(), create_schema_for_tests=True)
    ledger = UsageLedger(database.session_factory)
    calls = []
    def transport(request):
        calls.append(request.content)
        return response('' if len(calls) == 1 else 'done')
    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        model = ProviderCompatibleChatOpenAI(model='test', api_key='fake', http_client=client, max_retries=0)
        class Host:
            def __init__(self): self.requests = ModelRequests()
            def active(self): return True
            def revision(self): return 0
            def observe(self): return Turn('system', {'current_request': {'message': {'role':'user','text':'hello'}}}, [])
            def invoke(self, messages, tools, turn):
                return self.requests.call(lambda: model.invoke(messages), active=lambda:True)
            def persist(self, runtime): self.runtime = runtime
            def on_text(self, text, turn): return {'reason':'completed'}
        host = Host()
        try:
            with usage_scope(ledger=ledger, task_id='task', purpose='agent'):
                assert AgentLoop(host).run()['reason'] == 'completed'
            with ledger.sessions() as db:
                rows = [json.loads(r.details_json) for r in db.scalars(select(ProviderUsageRow))]
            assert len(rows) == 2
            assert rows[0]['context_metrics']['request_parts_chars']['repair'] == 0
            assert rows[1]['context_metrics']['request_parts_chars']['repair'] > 0
            for row in rows:
                for key in ('queue_wait_seconds','provider_duration_seconds','persistence_seconds'):
                    assert row[key] >= 0
                assert row['input_tokens'] == 10
        finally:
            host.requests.close()
            database.close()


def test_batch_schema_retry_has_one_owner(monkeypatch):
    from job_agent.batch_retry import retry_batch
    monkeypatch.setenv('JOB_AGENT_REASONING_ESCALATION', '1')
    bodies = []
    def transport(request):
        bodies.append(json.loads(request.content))
        return response('{"answer":"bad"}')
    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        model = ProviderCompatibleChatOpenAI(model='test', api_key='fake', http_client=client,
            reasoning_effort='low', max_retries=0)
        with pytest.raises(Exception):
            retry_batch(lambda: invoke_structured(model, Tiny, 'system', 'human'))
    assert [b['reasoning_effort'] for b in bodies] == ['low','medium']


def test_schema_retry_off_by_default(monkeypatch):
    monkeypatch.delenv('JOB_AGENT_REASONING_ESCALATION', raising=False)
    bodies = []
    def transport(request):
        bodies.append(request.content)
        return response('{"answer":"bad"}')
    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        model = ProviderCompatibleChatOpenAI(model='test', api_key='fake', http_client=client, max_retries=0)
        with pytest.raises(Exception):
            invoke_structured(model, Tiny, 'system', 'human')
    assert len(bodies) == 1


def test_grounding_repair_escalates_only_second_interview_attempt(interview_setup, monkeypatch):
    from agent_runtime.mock_interview.types import MockAnswerEvaluation, MockStatus
    monkeypatch.setenv('JOB_AGENT_REASONING_ESCALATION', '1')
    controller, scripted, application, db = interview_setup
    started = controller.start(application, idempotency_key='grounding-escalation')
    original = scripted.evaluate
    bodies, pending = [], []
    def transport(request):
        bodies.append(json.loads(request.content))
        return response(pending[-1].model_dump_json())
    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        model = ProviderCompatibleChatOpenAI(model='test', api_key='fake', http_client=client,
            reasoning_effort='low', max_retries=0)
        def evaluate(context):
            draft = original(context)
            if not bodies:
                draft = draft.model_copy(update={'exact_answer_quotes':['Invented 50% revenue.']})
            pending.append(draft)
            return invoke_structured(model, MockAnswerEvaluation, 'system', json.dumps(context))
        scripted.evaluate = evaluate
        with capture_provider_attempts() as rows:
            result = controller.answer(started.mock_interview_id, 'Built Python APIs.',
                expected_version=started.version, idempotency_key='grounded-answer')
    assert result.status != MockStatus.FAILED
    assert [b['reasoning_effort'] for b in bodies] == ['low','medium']
    assert [r['reasoning_escalation'] for r in rows] == [False,True]


@pytest.mark.parametrize('purpose', ['job_screening','skill_evidence','skill_evidence_verify',
                                   'question_category','memory_relevance','form_options'])
def test_fast_wire_default_and_isolated_result_cache(purpose):
    from agent_runtime.fast_decisions import FastDecisions
    from test_jev_singleflight import QUESTIONS, response as decision_response
    bodies = []
    def transport(request):
        bodies.append(json.loads(request.content)); return decision_response()
    service = FastDecisions(api_key='fake', enabled=True, transport=httpx.MockTransport(transport))
    service.evaluate({}, QUESTIONS, purpose=purpose)
    assert bodies[0] == {'model':'jev-latest','state':{},'questions':QUESTIONS}
    service.reasoning[purpose_key(purpose)] = 'low'
    assert not service.evaluate({}, QUESTIONS, purpose=purpose).cached
    service.reasoning[purpose_key(purpose)] = 'medium'
    assert not service.evaluate({}, QUESTIONS, purpose=purpose).cached
    assert service.evaluate({}, QUESTIONS, purpose=purpose).cached
    assert [b.get('reasoning_effort') for b in bodies] == [None,'low','medium']


@pytest.mark.parametrize('purpose', ['extract_requirements','refine_extraction_yes_no',
    'condition_category_yes_no','support_yes_no','focused_yes_no','clarify_full_support_yes_no','verify_citations_yes_no'])
def test_jev_wire_default_and_validation_retry(monkeypatch, purpose):
    from contextvars import copy_context
    from job_agent.jev_fit.settings import Settings
    from job_agent.jev_fit.transport import Broker
    bodies = []
    def transport(request):
        payload = json.loads(request.content); bodies.append(payload)
        answers = {} if len(bodies) == 2 else {'q':{'type':'noul','noul':.9}}
        return httpx.Response(200, json={'model':payload['model'],'answers':answers})
    config = Settings('fake')
    broker = Broker(config, None, transport=httpx.MockTransport(transport))
    questions = {'q':{'type':'noul','instructions':{'question':'Supported?'}}}
    try:
        assert broker._request({}, questions, purpose, copy_context())[1] == 'ok'
        assert bodies[0] == {'model':config.model,'state':{},'questions':questions}
        monkeypatch.setenv('JOB_AGENT_REASONING_ESCALATION','1')
        config.reasoning[purpose_key(purpose)] = 'low'
        with capture_provider_attempts() as rows:
            assert broker._request({}, questions, purpose, copy_context())[1] == 'ok'
        assert [b.get('reasoning_effort') for b in bodies] == [None,'low','medium']
        assert rows[-1]['reasoning_escalation']
    finally:
        broker.close()


@pytest.mark.parametrize('purpose', [None,'agent','fast'])
@pytest.mark.parametrize('setting', ['low','medium','off'])
def test_interview_legacy_payload_bytes(tmp_path, monkeypatch, purpose, setting):
    import agent_runtime.mock_interview.model as module
    bodies = []
    monkeypatch.setenv('LLM_INTERVIEW_REASONING',setting)
    monkeypatch.setattr(module, 'DEFAULT_ENV_PATH', tmp_path/'missing', raising=False)
    import job_agent.model as shared
    monkeypatch.setattr(shared, 'DEFAULT_ENV_PATH', tmp_path/'missing')
    settings = {'LLM_MODEL_ID':'test','LLM_FAST_MODEL_ID':'test-fast','LLM_API_KEY':'fake',
                'LLM_AGENT_REASONING':'high'}
    for key,value in settings.items(): monkeypatch.setenv(key,value)
    def transport(request):
        bodies.append(request.content); return response()
    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        def factory(**kw):
            return create_model(env_path=tmp_path/'missing', model_factory=lambda **options:
                ProviderCompatibleChatOpenAI(http_client=client, **options), **kw)
        monkeypatch.setattr(module,'create_model',factory)
        new = module.interview_model(purpose)
        legacy = setting if setting != 'off' else 'high' if purpose in {'agent','fast'} else None
        old = ChatOpenAI(model='test-fast' if purpose == 'fast' else 'test', api_key='fake',
            temperature=0, max_retries=0, timeout=45, http_client=client,
            **({'reasoning_effort':legacy} if legacy else {}))
        old.invoke('same question'); new.invoke('same question')
    assert bodies[0] == bodies[1]


def test_fit_result_signature_includes_reasoning(tmp_path, monkeypatch):
    from api.services.fit_analysis_service import FitAnalysisService
    monkeypatch.setattr('job_agent.model.dotenv_values', lambda *a, **kw: {})
    service = FitAnalysisService(jev_enabled=False)
    monkeypatch.setenv('LLM_REASONING_SCORING','low')
    low = service.cache_signature()
    monkeypatch.setenv('LLM_REASONING_SCORING','medium')
    assert service.cache_signature() != low


def test_async_provider_plain_fallback_is_bounded():
    import asyncio
    bodies = []
    def transport(request):
        bodies.append(json.loads(request.content))
        if len(bodies) == 1:
            return httpx.Response(400, json={'error':{'message':'unsupported reasoning_effort','type':'invalid_request_error'}})
        return response()
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            model = ProviderCompatibleChatOpenAI(model='test', api_key='fake', http_async_client=client,
                reasoning_effort='low', max_retries=0)
            with capture_provider_attempts() as rows:
                await model.ainvoke('hello')
            assert len(rows) == 2 and rows[-1]['effective_reasoning'] is None
    asyncio.run(run())
    assert [b.get('reasoning_effort') for b in bodies] == ['low',None]


@pytest.mark.parametrize('lane',['fast','fit'])
def test_typesafe_plain_fallback_is_bounded(lane):
    from contextvars import copy_context
    from agent_runtime.fast_decisions import FastDecisions
    from job_agent.jev_fit.settings import Settings
    from job_agent.jev_fit.transport import Broker
    from test_jev_singleflight import QUESTIONS, response as decision_response
    bodies = []
    def transport(request):
        body = json.loads(request.content); bodies.append(body)
        if len(bodies) == 1:
            return httpx.Response(400, text='unsupported reasoning_effort')
        return decision_response() if lane == 'fast' else httpx.Response(200, json={
            'model':body['model'],'answers':{'q':{'type':'noul','noul':.9}}})
    with capture_provider_attempts() as rows:
        if lane == 'fast':
            service = FastDecisions(api_key='fake', enabled=True, transport=httpx.MockTransport(transport),
                reasoning={'LLM_REASONING_FORM_OPTIONS':'low'})
            assert service.evaluate({}, QUESTIONS, purpose='form_options').status == 'ok'
        else:
            broker = Broker(Settings('fake', reasoning={'LLM_REASONING_SUPPORT_YES_NO':'low'}), None,
                transport=httpx.MockTransport(transport))
            try:
                assert broker._request({}, {'q':{'type':'noul','instructions':{'question':'Supported?'}}},
                    'support_yes_no', copy_context())[1] == 'ok'
            finally:
                broker.close()
    assert [b.get('reasoning_effort') for b in bodies] == ['low',None]
    assert len(rows) == 2 and rows[-1]['effective_reasoning'] is None


def test_fast_escalation_then_plain_fallback_counts_actual_attempts(monkeypatch):
    from agent_runtime.fast_decisions import FastDecisions
    from test_jev_singleflight import QUESTIONS, response as decision_response
    monkeypatch.setenv('JOB_AGENT_REASONING_ESCALATION','1')
    bodies = []
    def transport(request):
        bodies.append(json.loads(request.content))
        if len(bodies) == 1: return httpx.Response(200, json={'answers':{}})
        if len(bodies) == 2: return httpx.Response(400, text='unsupported reasoning_effort')
        return decision_response()
    service = FastDecisions(api_key='fake', enabled=True, transport=httpx.MockTransport(transport),
        reasoning={'LLM_REASONING_FORM_OPTIONS':'low'})
    with capture_provider_attempts() as rows:
        result = service.evaluate({}, QUESTIONS, purpose='form_options')
    assert result.status == 'ok' and result.requests == 3
    assert [r['effective_reasoning'] for r in rows] == ['low','medium',None]
    assert [r['reasoning_escalation'] for r in rows] == [False,True,False]
    assert [r['attempt'] for r in rows] == [1,2,3]
    assert not service.evaluate({}, QUESTIONS, purpose='form_options').cached
    assert len(bodies) == 4 and bodies[-1]['reasoning_effort'] == 'low'
    assert service.evaluate({}, QUESTIONS, purpose='form_options').cached


def test_jev_broker_keys_track_effective_purpose_level():
    from types import SimpleNamespace
    from job_agent.jev_fit.settings import Settings
    from job_agent.jev_fit.transport import Broker
    config = Settings('fake',reasoning={'LLM_REASONING_SUPPORT_YES_NO':'low'})
    broker = Broker(config,None)
    try:
        pending = SimpleNamespace(scope={},purpose='support_yes_no',state={})
        before = broker._key(pending, {'question':'same'})
        config.reasoning['LLM_REASONING_SUPPORT_YES_NO'] = 'medium'
        assert broker._key(pending, {'question':'same'}) != before
    finally:
        broker.close()


@pytest.mark.parametrize('flag', ['reasoning_escalation','reasoning_fallback'])
@pytest.mark.parametrize('kind', ['fit','durable'])
def test_changed_effective_level_does_not_populate_original_cache(tmp_path, flag, kind):
    from api.services.fit_analysis_service import _AnalysisCache
    from agent_runtime.analysis_cache import AnalysisCache
    from api.db import create_database
    db = create_database('sqlite:///' + (tmp_path/'cache.db').as_posix(), create_schema_for_tests=True)
    cache = _AnalysisCache() if kind == 'fit' else AnalysisCache(db.session_factory)
    calls = []
    changed = True
    def compute():
        calls.append(1)
        with usage_scope(**{flag:changed}), provider_call('offline') as row:
            row.update(input_tokens=0, output_tokens=0)
        return {'value':len(calls)}
    def get():
        return cache.get('key',compute)[0] if kind == 'fit' else cache.get('resume','low','same',compute)
    try:
        assert get()['value'] == 1
        assert get()['value'] == 2
        changed = False
        assert get()['value'] == 3
        assert get()['value'] == 3
        assert len(calls) == 3
    finally:
        db.close()


def test_jev_escalated_answer_does_not_populate_low_cache(monkeypatch):
    from job_agent.jev_fit.settings import Settings
    from job_agent.jev_fit.transport import Broker
    monkeypatch.setenv('JOB_AGENT_REASONING_ESCALATION','1')
    calls = []
    class Cache:
        def __init__(self): self.writes = []
        def get_many(self, *a): return {}
        def put_many(self, rows, model): self.writes.extend(rows)
    cache = Cache()
    def transport(request):
        payload=json.loads(request.content); calls.append(payload)
        return httpx.Response(200,json={'model':payload['model'],'answers':{} if len(calls)==1 else {
            key:{'type':'noul','noul':.9} for key in payload['questions']}})
    broker=Broker(Settings('fake',reasoning={'LLM_REASONING_SUPPORT_YES_NO':'low'}),cache,
        transport=httpx.MockTransport(transport))
    def call():
        return broker.submit(state={},questions={'q':{'type':'noul','instructions':{'question':'Supported?'}}},
            purpose='support_yes_no',scope={'owner':'test','resume':'r','facts':'f'},task_id='test')
    try:
        assert call()[1] == [] and not cache.writes
        assert [c['reasoning_effort'] for c in calls] == ['low','medium']
        assert call()[1] == [] and len(cache.writes) == 1
    finally:
        broker.close()


@pytest.mark.parametrize('kind', ['fit','durable'])
def test_shared_upgraded_result_cannot_poison_parent_cache(tmp_path, monkeypatch, kind):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from api.services.fit_analysis_service import _AnalysisCache
    from agent_runtime.analysis_cache import AnalysisCache
    from api.db import create_database
    db = create_database('sqlite:///' + (tmp_path/'shared.db').as_posix(), create_schema_for_tests=True)
    child = _AnalysisCache() if kind == 'fit' else AnalysisCache(db.session_factory)
    parent = _AnalysisCache()
    started, release, waiting = Event(), Event(), Event()
    def compute():
        started.set(); assert release.wait(3)
        with usage_scope(reasoning_escalation=True), provider_call('offline'):
            return {'value':'upgraded'}
    def get():
        return child.get('inner',compute)[0] if kind == 'fit' else child.get('resume','low','same',compute)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            owner = pool.submit(get)
            assert started.wait(3)
            future = next(iter(child.pending.values()))
            original = future.result
            def result(*args, **kwargs):
                waiting.set(); return original(*args, **kwargs)
            monkeypatch.setattr(future,'result',result)
            waiter = pool.submit(parent.get,'outer',get)
            try:
                assert waiting.wait(3)
            finally:
                release.set()
            assert owner.result(3) == waiter.result(3)[0] == {'value':'upgraded'}
        assert not child.values and not parent.values
    finally:
        release.set(); db.close()


def test_shared_fast_upgrade_cannot_poison_parent_cache(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from api.services.fit_analysis_service import _AnalysisCache
    from agent_runtime.fast_decisions import FastDecisions
    from test_jev_singleflight import QUESTIONS, response as decision_response
    monkeypatch.setenv('JOB_AGENT_REASONING_ESCALATION','1')
    started, release, waiting = Event(), Event(), Event()
    calls = []
    def transport(request):
        calls.append(1)
        if len(calls) == 1:
            started.set(); assert release.wait(3)
            return httpx.Response(200,json={'answers':{}})
        return decision_response()
    service = FastDecisions(api_key='fake',enabled=True,transport=httpx.MockTransport(transport),
        reasoning={'LLM_REASONING_FORM_OPTIONS':'low'})
    parent = _AnalysisCache()
    get = lambda: service.evaluate({},QUESTIONS,purpose='form_options')
    with ThreadPoolExecutor(max_workers=2) as pool:
        owner=pool.submit(get); assert started.wait(3)
        future=next(iter(service._inflight.values())); original=future.result
        def result(*args,**kwargs):
            waiting.set(); return original(*args,**kwargs)
        monkeypatch.setattr(future,'result',result)
        waiter=pool.submit(parent.get,'outer',get)
        try:
            assert waiting.wait(3)
        finally:
            release.set()
        assert owner.result(3).status == waiter.result(3)[0].status == 'ok'
    assert not service._cache and not parent.values


@pytest.mark.parametrize('explicit', ['high','none',None])
def test_existing_invocation_override_keeps_payload_bytes(explicit):
    bodies = []
    def transport(request):
        bodies.append(request.content); return response()
    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        options = dict(model='test',api_key='fake',http_client=client,reasoning_effort='low',max_retries=0)
        old, new = ChatOpenAI(**options), ProviderCompatibleChatOpenAI(**options)
        old.invoke('unchanged',reasoning_effort=explicit)
        new.invoke('unchanged',reasoning_effort=explicit)
    assert bodies[0] == bodies[1]


@pytest.mark.parametrize('route,semantic,legacy_key', [
    ('extraction','scoring','LLM_EXTRACTION_REASONING'),
    ('extraction','jev_fit_resolver','LLM_EXTRACTION_REASONING'),
    ('agent','interview_feedback','LLM_AGENT_REASONING'),
    ('fast','job_screening','LLM_AGENT_REASONING')])
def test_route_override_does_not_leak_to_other_semantic_purpose(tmp_path, route, semantic, legacy_key):
    model = create_model(env_path=tmp_path/'missing', purpose=route, environ={
        'LLM_MODEL_ID':'test','LLM_API_KEY':'fake',legacy_key:'high',purpose_key(route):'low'})
    assert model.reasoning_effort == 'low'
    with usage_scope(reasoning_purpose=semantic):
        assert model._attempt_options({})[0]['reasoning_effort'] == 'high'
    with usage_scope(reasoning_purpose=route):
        assert model._attempt_options({})[0]['reasoning_effort'] == 'low'
