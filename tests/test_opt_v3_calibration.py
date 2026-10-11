"""Offline calibration: defaults, durable reservations, and both history layers."""
import asyncio
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context

import httpx
import pytest
from langchain_core.messages import AIMessage

from agent_runtime.provider_usage import (UsageLedger, provider_call, usage_scope,
    capture_provider_attempts, TaskProviderBudgetExceeded)
from agent_runtime.loop_context import ConversationWindow
from agent_runtime.request_context import prepare_request, ContextArchive
from job_agent.model import ProviderCompatibleChatOpenAI, invoke_structured
from job_agent.reasoning import cache_observation
from test_token_usage import ledger
from test_opt_metrics_reasoning import Tiny, response
from test_auto_apply import database
from test_task_loop import Harness, final_answer
from test_career_flow import settled


@pytest.mark.parametrize('async_mode', [False, True])
@pytest.mark.parametrize('enabled,level,expected', [(False,'low',1), (True,'low',2), (True,None,1)])
def test_rejection_default_and_opt_in(monkeypatch, async_mode, enabled, level, expected):
    monkeypatch.setenv('JOB_AGENT_REASONING_REJECTION_RETRY', '1' if enabled else '0')
    bodies = []
    def transport(request):
        bodies.append(request.content)
        return httpx.Response(400, json={'error': {'message':'unsupported reasoning_effort', 'type':'invalid_request_error'}})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            model = ProviderCompatibleChatOpenAI(model='test', api_key='fake', max_retries=0,
                reasoning_effort=level, http_async_client=client)
            await model.ainvoke('test')
    with cache_observation() as eligible, capture_provider_attempts() as rows:
        with pytest.raises(Exception):
            if async_mode:
                asyncio.run(run())
            else:
                with httpx.Client(transport=httpx.MockTransport(transport)) as client:
                    ProviderCompatibleChatOpenAI(model='test', api_key='fake', max_retries=0,
                        reasoning_effort=level, http_client=client).invoke('test')
        assert eligible() == (expected == 1)
    assert len(bodies) == len(rows) == expected
    assert all(r['status'] == 'failed' for r in rows)


def test_fast_default_identity():
    from agent_runtime.fast_decisions import FastDecisions
    from test_jev_singleflight import QUESTIONS, response as decision_response
    service = FastDecisions(api_key='fake', enabled=True, transport=httpx.MockTransport(lambda r: decision_response()))
    expected = hashlib.sha256(json.dumps([True, service.base_url, service.model, 'fake', 2.5]).encode()).hexdigest()
    assert service.cache_namespace() == expected
    service.evaluate({}, QUESTIONS, purpose='form_options')
    payload = json.dumps({'model': service.model, 'state': {}, 'questions': QUESTIONS}, ensure_ascii=False, sort_keys=True)
    assert list(service._cache) == [hashlib.sha256(('form_options' + payload).encode()).hexdigest()]
    assert service.evaluate({}, QUESTIONS, purpose='form_options').cached


def test_default_structured_and_batch_retry(monkeypatch):
    from job_agent.batch_retry import retry_batch
    monkeypatch.delenv('JOB_AGENT_REASONING_ESCALATION', raising=False)
    bodies = []
    def transport(request):
        bodies.append(request.content)
        return response('{"answer":"invalid"}')
    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        model = ProviderCompatibleChatOpenAI(model='test', api_key='fake', max_retries=0, http_client=client)
        with pytest.raises(Exception):
            retry_batch(lambda: invoke_structured(model, Tiny, 'system', 'human'))
    assert len(bodies) == 1
    calls = []
    def timeout():
        calls.append(1)
        raise TimeoutError()
    with pytest.raises(TimeoutError): retry_batch(timeout)
    assert len(calls) == 2


def append(window, i):
    window.append({'current_request': {'message': 'request'}}, 'text',
        [{'id': str(i), 'name':'read', 'args': {}}], [{'content': 'x' * 200}], i)


def test_two_layers_count_without_changing_messages():
    window = ConversationWindow(max_groups=2)
    for i in range(3): append(window, i)
    groups = json.loads(json.dumps(window.groups))
    messages, metrics = prepare_request('system', [], window, {}, ContextArchive(), max_chars=1)
    assert metrics['persistent_groups_evicted'] == 1
    assert metrics['replay_groups_evicted'] == 1
    assert window.groups == groups
    old_window = ConversationWindow(groups, max_groups=2)
    same, again = prepare_request('system', [], old_window, {}, ContextArchive(), max_chars=1)
    assert [m.model_dump() for m in messages] == [m.model_dump() for m in same]
    assert metrics['history_prefix_hash'] == again['history_prefix_hash']
    assert again['persistent_groups_evicted'] == 0
    assert window.dropped_since_request == 0


def test_nested_failed_retry_and_restart_accounting(ledger, monkeypatch):
    monkeypatch.setenv('JOB_AGENT_TASK_MAX_PROVIDER_ATTEMPTS', '3')
    with usage_scope(ledger=ledger, task_id='t', purpose='router'):
        with provider_call('main') as row: row.update(input_tokens=5, output_tokens=1)
        with usage_scope(purpose='scoring'):
            with pytest.raises(ValueError), provider_call('score'):
                raise ValueError('failed')
            with usage_scope(attempt=2), provider_call('score') as row:
                row.update(input_tokens=7, output_tokens=1)
        restarted = UsageLedger(ledger.sessions)
        with usage_scope(ledger=restarted), pytest.raises(TaskProviderBudgetExceeded), provider_call('next'):
            pytest.fail('provider must not run')
    total = restarted.summary(task_id='t')
    assert (total['provider_attempts'], total['failed'], total['retries'], total['input_tokens']) == (3,1,1,12)


def test_input_reservation_pending_failed_and_actual(ledger, monkeypatch):
    monkeypatch.setenv('JOB_AGENT_TASK_MAX_INPUT_TOKENS', '100')
    with usage_scope(ledger=ledger, task_id='t'):
        with provider_call('one', input_token_reservation=80) as row:
            with pytest.raises(TaskProviderBudgetExceeded), provider_call('two', input_token_reservation=30): pass
            row.update(input_tokens=20, output_tokens=1)
        with pytest.raises(ValueError), provider_call('failed', input_token_reservation=70):
            raise ValueError()
        with pytest.raises(TaskProviderBudgetExceeded), provider_call('three', input_token_reservation=11): pass
    total = ledger.summary(task_id='t')
    assert total['input_tokens'] == 20 and total['budget_input_tokens'] == 90
    assert total['calls'] == 2


def test_atomic_parallel_reservations(ledger, monkeypatch):
    monkeypatch.setenv('JOB_AGENT_TASK_MAX_PROVIDER_ATTEMPTS', '1')
    def call():
        try:
            with provider_call('nested'): return True
        except TaskProviderBudgetExceeded: return False
    with usage_scope(ledger=ledger, task_id='t'), ThreadPoolExecutor(max_workers=4) as pool:
        results = [pool.submit(copy_context().run, call) for _ in range(4)]
        assert sum(f.result() for f in results) == 1
    assert ledger.summary(task_id='t')['calls'] == 1


def test_budget_stop_preserves_saved_work(database, monkeypatch):
    from agent_runtime.task_loop import TaskLoop
    from agent_runtime.career.repository import TaskRepository
    monkeypatch.setenv('JOB_AGENT_TASK_MAX_PROVIDER_ATTEMPTS', '2')
    repo = TaskRepository(database.session_factory)
    harness = Harness()
    def execute(task_id, *args, **kwargs):
        repo.change(task_id, plan=['saved before nested score'])
        with usage_scope(purpose='scoring'):
            with provider_call('score'): pass
            with provider_call('score-retry'): pytest.fail('over budget')
    harness.execute = execute
    class Model:
        def invoke(self, messages, tools):
            with provider_call('router'):
                return AIMessage(content='', tool_calls=[{'id':'lookup', 'name':'lookup', 'args':{}}])
    loop = TaskLoop(repo, harness, model_factory=Model)
    try:
        task = loop.start('Find work', 'calibration-budget')
        result = settled(repo, task['task_id'])
        assert result['status'] == 'needs_input'
        assert result['error']['code'] == 'provider_budget'
        assert result['plan'] == ['saved before nested score']
        assert 'not complete' in result['messages'][-1]['text']
        assert UsageLedger(database.session_factory).summary(task_id=task['task_id'])['calls'] == 2
    finally: loop.close()


def test_unset_budget_retains_unmetered_and_unknown_usage(ledger, monkeypatch):
    for name in ('JOB_AGENT_TASK_MAX_INPUT_TOKENS', 'JOB_AGENT_TASK_MAX_PROVIDER_ATTEMPTS'):
        monkeypatch.delenv(name, raising=False)
    with usage_scope(task_id='t'), provider_call('no-ledger'): pass
    with usage_scope(task_id='t', ledger=ledger):
        for _ in range(5):
            with provider_call('unknown'): pass
    assert ledger.summary(task_id='t')['calls'] == 5


def test_default_analysis_future_and_durable_cache(ledger):
    from agent_runtime.analysis_cache import AnalysisCache
    from threading import Event
    cache = AnalysisCache(ledger.sessions)
    entered, release = Event(), Event()
    calls = []
    def compute():
        calls.append(1); entered.set()
        assert release.wait(5)
        return {'answer': [1]}
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(cache.get, 'job', 'default', 'same', compute)
        assert entered.wait(5)
        second = pool.submit(cache.get, 'job', 'default', 'same', compute)
        release.set()
        a, b = first.result(), second.result()
    a['answer'].append(2)
    assert b == {'answer': [1]} and calls == [1]
    restarted = AnalysisCache(ledger.sessions)
    assert restarted.get('job', 'default', 'same', lambda: pytest.fail('durable cache miss')) == b


def test_report_attributes_layers_and_separates_runs():
    from evals.opt_report import metrics
    def row(task, history, persistent, dropped=0, request=0, tools='t', system='s'):
        return {'task_id':task, 'context_metrics':{'history_prefix_hash':history,
            'persistent_prefix_hash':persistent, 'persistent_groups_evicted':dropped,
            'replay_groups_evicted':request, 'tools_hash':tools, 'system_hash':system}}
    rows = [row('a','a','a'), row('b','z','z'), row('a','b','b',1),
            row('a','c','b',request=1,tools='new'), row('a','d','d',1,system='new')]
    result = metrics(rows)['prefix_changes']
    assert result == {'pairs':3,'history':3,'persistent':2,'request':2,'both':1,'other':0,
        'tools':2,'system':1,'shares':{'history':1,'persistent':2/3,'request':2/3,
                                     'both':1/3,'other':0,'tools':2/3,'system':1/3}}


def test_window_pending_counter_survives_slice_restart():
    from agent_runtime.loop_engine import AgentLoop
    class Host:
        def persist(self, runtime): self.runtime = runtime
    host = Host()
    loop = AgentLoop(host)
    for i in range(10): append(loop.context, i)
    loop.save()
    resumed = AgentLoop(host, host.runtime)
    assert resumed.context.dropped_since_request == 2


def test_report_does_not_blame_eviction_of_already_omitted_group():
    from evals.opt_report import metrics
    rows = [{'context_metrics': {'history_prefix_hash': 'c', 'history_group_id':'c',
        'persistent_prefix_hash':'a', 'persistent_group_ids':['a','b','c'], 'replay_groups_evicted':2}},
        {'context_metrics': {'history_prefix_hash':'d', 'history_group_id':'d',
        'persistent_prefix_hash':'b', 'persistent_group_ids':['b','c','d'],
        'persistent_groups_evicted':1, 'replay_groups_evicted':2}}]
    result = metrics(rows)['prefix_changes']
    assert result['history'] == result['request'] == 1
    assert result['persistent'] == result['both'] == 0


@pytest.mark.parametrize('lane', ['fast','fit'])
def test_typesafe_default_rejection_one_attempt(lane, monkeypatch):
    from agent_runtime.fast_decisions import FastDecisions
    from job_agent.jev_fit.settings import Settings
    from job_agent.jev_fit.transport import Broker
    from test_jev_singleflight import QUESTIONS
    monkeypatch.delenv('JOB_AGENT_REASONING_REJECTION_RETRY', raising=False)
    bodies = []
    def transport(request):
        bodies.append(request.content)
        return httpx.Response(400, text='unsupported reasoning_effort')
    with capture_provider_attempts() as rows:
        if lane == 'fast':
            service = FastDecisions(api_key='fake', enabled=True, transport=httpx.MockTransport(transport),
                reasoning={'LLM_REASONING_FORM_OPTIONS':'low'})
            assert service.evaluate({}, QUESTIONS, purpose='form_options').status != 'ok'
        else:
            broker = Broker(Settings('fake', reasoning={'LLM_REASONING_SUPPORT_YES_NO':'low'}), None,
                transport=httpx.MockTransport(transport))
            try:
                assert broker._request({}, {'q':{'type':'noul','instructions':{'question':'Supported?'}}},
                    'support_yes_no', copy_context())[1] == 'http_400'
            finally: broker.close()
    assert len(rows) == len(bodies) == 1


@pytest.mark.parametrize('async_mode', [False, True])
@pytest.mark.parametrize('limited', [False, True])
def test_sdk_transport_retries_are_individual_attempts(ledger, monkeypatch, async_mode, limited):
    if limited: monkeypatch.setenv('JOB_AGENT_TASK_MAX_PROVIDER_ATTEMPTS', '1')
    bodies = []
    def transport(request):
        bodies.append(request.content)
        if len(bodies) == 1:
            return httpx.Response(503, headers={'retry-after-ms':'1'}, json={'error':{'message':'unavailable'}})
        return response()
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            model = ProviderCompatibleChatOpenAI(model='test', api_key='fake', max_retries=1, http_async_client=client)
            return await model.ainvoke('test')
    def invoke():
        if async_mode: return asyncio.run(run())
        with httpx.Client(transport=httpx.MockTransport(transport)) as client:
            model = ProviderCompatibleChatOpenAI(model='test', api_key='fake', max_retries=1, http_client=client)
            return model.invoke('test')
    with usage_scope(ledger=ledger, task_id='t'):
        if limited:
            with pytest.raises(TaskProviderBudgetExceeded): invoke()
        else: invoke()
    summary = ledger.summary(task_id='t')
    assert summary['calls'] == len(bodies) == (1 if limited else 2)
    assert summary['failed'] == 1
    assert summary['retries'] == (0 if limited else 1)
    if not limited: assert bodies[0] == bodies[1]


@pytest.mark.parametrize('async_mode', [False, True])
def test_transport_retry_does_not_reenable_reasoning_after_fallback(monkeypatch, async_mode):
    monkeypatch.setenv('JOB_AGENT_REASONING_REJECTION_RETRY', '1')
    bodies = []
    def transport(request):
        bodies.append(json.loads(request.content))
        if len(bodies) == 1:
            return httpx.Response(400, json={'error':{'message':'unsupported reasoning_effort'}})
        if len(bodies) == 2:
            return httpx.Response(503, headers={'retry-after-ms':'1'}, json={'error':{'message':'unavailable'}})
        return response()
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            return await ProviderCompatibleChatOpenAI(model='test', api_key='fake',
                reasoning_effort='low', http_async_client=client).ainvoke('test')
    with capture_provider_attempts() as rows:
        if async_mode: asyncio.run(run())
        else:
            with httpx.Client(transport=httpx.MockTransport(transport)) as client:
                ProviderCompatibleChatOpenAI(model='test', api_key='fake',
                    reasoning_effort='low', http_client=client).invoke('test')
    assert [body.get('reasoning_effort') for body in bodies] == ['low',None,None]
    assert [r['attempt'] for r in rows] == [1,2,3]
    assert [r.get('reasoning_fallback',False) for r in rows] == [False,True,True]


def test_interview_retains_legacy_retry_without_flag(monkeypatch):
    from agent_runtime.mock_interview import model as interview
    monkeypatch.delenv('JOB_AGENT_REASONING_REJECTION_RETRY', raising=False)
    bodies = []
    def transport(request):
        bodies.append(json.loads(request.content))
        if len(bodies) == 1:
            return httpx.Response(400, json={'error':{'message':'unsupported reasoning_effort'}})
        return response('{"answer":3}')
    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        model = ProviderCompatibleChatOpenAI(model='test', api_key='fake', max_retries=0,
            reasoning_effort='low', http_client=client)
        monkeypatch.setattr(interview, 'interview_model', lambda purpose: model)
        assert interview._invoke_interview(None, Tiny, 'system', 'test').answer == 3
    assert [body.get('reasoning_effort') for body in bodies] == ['low',None]


def _status_error(status, message):
    import httpx
    from openai import APIStatusError
    request = httpx.Request('POST', 'https://provider.test/v1/chat/completions')
    return APIStatusError(message, response=httpx.Response(status, request=request), body=None)


@pytest.mark.parametrize('exc,expected', [
    (lambda: _status_error(400, "Unsupported parameter: 'reasoning_effort'"), True),
    (lambda: _status_error(422, 'reasoning_effort is not supported by this model'), True),
    # Review repro: a connection failure that mentions reasoning is not a rejection.
    (lambda: __import__('openai').APIConnectionError(message='reasoning backend connection lost',
        request=__import__('httpx').Request('POST', 'https://provider.test')), False),
    (lambda: _status_error(503, 'reasoning service unavailable'), False),
    (lambda: _status_error(400, 'Invalid messages: content too long'), False),
    (lambda: TimeoutError('reasoning timed out'), False),
])
def test_only_explicit_parameter_rejection_counts_as_reasoning_rejection(exc, expected):
    from job_agent.reasoning import reasoning_parameter_rejected
    assert reasoning_parameter_rejected(exc()) is expected


def test_connection_error_mentioning_reasoning_does_not_trigger_plain_retry(monkeypatch):
    # Review repro: "reasoning backend connection lost" made the adapter call with low,
    # then again without reasoning, on top of the transport retries.
    import httpx
    from openai import APIConnectionError
    from job_agent.model import ProviderCompatibleChatOpenAI
    from langchain_core.messages import HumanMessage
    monkeypatch.setenv('JOB_AGENT_REASONING_REJECTION_RETRY', '1')
    model = ProviderCompatibleChatOpenAI(model='m', api_key='k', base_url='https://provider.test/v1',
                                         reasoning_effort='low', max_retries=1)
    sent = []
    def fail(self, messages, stop=None, run_manager=None, **kwargs):
        sent.append(kwargs.get('reasoning_effort'))
        raise APIConnectionError(message='reasoning backend connection lost', request=httpx.Request('POST', 'https://provider.test'))
    monkeypatch.setattr('langchain_openai.ChatOpenAI._generate', fail)
    monkeypatch.setattr('time.sleep', lambda *_: None)
    with pytest.raises(APIConnectionError):
        model._generate([HumanMessage(content='x')])
    assert sent == ['low', 'low']  # transport retries only, never a plain retry


def test_plain_retry_shares_one_retry_budget(monkeypatch):
    import httpx
    from openai import APIConnectionError
    from job_agent.model import ProviderCompatibleChatOpenAI
    from langchain_core.messages import HumanMessage
    monkeypatch.setenv('JOB_AGENT_REASONING_REJECTION_RETRY', '1')
    model = ProviderCompatibleChatOpenAI(model='m', api_key='k', base_url='https://provider.test/v1',
                                         reasoning_effort='low', max_retries=2)
    sent = []
    def respond(self, messages, stop=None, run_manager=None, **kwargs):
        sent.append(kwargs.get('reasoning_effort'))
        if len(sent) == 1:
            raise _status_error(400, "Unsupported parameter: 'reasoning_effort'")
        raise APIConnectionError(message='connection lost', request=httpx.Request('POST', 'https://provider.test'))
    monkeypatch.setattr('langchain_openai.ChatOpenAI._generate', respond)
    monkeypatch.setattr('time.sleep', lambda *_: None)
    with pytest.raises(APIConnectionError):
        model._generate([HumanMessage(content='x')])
    assert sent == ['low', None, None]  # 3 attempts total = max_retries + 1, not 3 + 3
