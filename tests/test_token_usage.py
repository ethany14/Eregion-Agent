"""Provider-boundary accounting and lossless, restartable context reduction."""
import json
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from threading import Event

import httpx
import pytest
from langchain_core.messages import AIMessage
from pydantic import BaseModel

from api.db import create_database, upgrade_database
from agent_runtime.provider_usage import UsageLedger, ProviderUsageRow, provider_call, usage_scope
from agent_runtime.loop_context import ConversationWindow
from agent_runtime.loop_model import ModelRequests, ModelInterrupted
from agent_runtime.request_context import ContextArchive, READ_CONTEXT, prepare_request
from agent_runtime.semantics import SemanticDecisions, ClaimDecisions
from job_agent.model import ProviderCompatibleChatOpenAI, invoke_structured


@pytest.fixture
def ledger(tmp_path):
    database = create_database('sqlite:///' + (tmp_path / 'usage.db').as_posix(), create_schema_for_tests=True)
    yield UsageLedger(database.session_factory)
    database.close()


def test_schema_migration_and_usage_round_trip(tmp_path):
    url = 'sqlite:///' + (tmp_path / 'migrate.db').as_posix()
    upgrade_database(url)
    db = create_database(url)
    ledger = UsageLedger(db.session_factory)
    try:
        with usage_scope(ledger=ledger, task_id='task', purpose='score'):
            with provider_call('model') as call:
                call.update(input_tokens=12, output_tokens=4)
        assert ledger.summary(task_id='task')['input_tokens'] == 12
    finally:
        db.close()


class Answer(BaseModel):
    answer: str


def test_real_model_adapter_records_nested_structured_calls_once_and_no_content(ledger):
    def transport(request):
        return httpx.Response(200, json={'id': 'response', 'object': 'chat.completion', 'created': 1, 'model': 'local-test',
            'choices': [{'index': 0, 'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': '{"answer":"private-candidate-text"}'}}],
            'usage': {'prompt_tokens': 120, 'completion_tokens': 15, 'total_tokens': 135,
                      'prompt_tokens_details': {'cached_tokens': 30}, 'completion_tokens_details': {'reasoning_tokens': 5}}})
    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        model = ProviderCompatibleChatOpenAI(model='local-test', api_key='secret-key', base_url='https://test.invalid/v1',
                                            http_client=client, max_retries=0)
        with usage_scope(ledger=ledger, task_id='t', purpose='prepare_materials'):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = [pool.submit(copy_context().run, invoke_structured, model, Answer, 'system', 'private-input') for _ in range(2)]
                assert all(f.result().answer == 'private-candidate-text' for f in results)
    summary = ledger.summary(task_id='t')
    assert (summary['calls'], summary['input_tokens'], summary['output_tokens']) == (2, 240, 30)
    assert summary['cached_input_tokens'] == 60 and summary['reasoning_tokens'] == 10
    assert summary['groups'][0]['purpose'] == 'prepare_materials:Answer'
    assert summary['usage_complete']
    with ledger.sessions() as db:
        from sqlalchemy import select
        for row in db.scalars(select(ProviderUsageRow)):
            assert all(secret not in row.details_json for secret in ['private-input', 'private-candidate-text', 'secret-key'])


def test_unknown_failed_and_linked_application_calls_are_not_counted_as_complete(ledger):
    with usage_scope(ledger=ledger, task_id='t', run_id='application', purpose='fill'):
        with pytest.raises(ValueError), provider_call('test'):
            raise ValueError('secret provider body')
        with provider_call('test'): pass
    summary = ledger.summary(task_id='t', run_ids=['application'])
    assert summary['calls'] == 2  # OR query must not double count linked calls.
    assert summary['failed'] == 1 and summary['unknown_usage_calls'] == 2
    assert not summary['usage_complete']


def test_interrupted_request_finishes_accounting_without_becoming_adopted(ledger):
    started, release = Event(), Event()
    active = Event(); active.set()
    requests = ModelRequests()
    def invoke():
        with provider_call('slow') as call:
            started.set()
            assert release.wait(5)
            call.update(input_tokens=77, output_tokens=9)
        return AIMessage(content='obsolete')
    def execute():
        with usage_scope(ledger=ledger, task_id='t'):
            return requests.call(invoke, active=active.is_set)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(execute)
            assert started.wait(3)
            active.clear()
            with pytest.raises(ModelInterrupted): future.result(timeout=3)
        assert ledger.summary(task_id='t')['discarded'] == 1
        release.set()
        import time
        deadline = time.monotonic() + 3
        while ledger.summary(task_id='t')['pending'] and time.monotonic() < deadline: time.sleep(.01)
        summary = ledger.summary(task_id='t')
        assert summary['input_tokens'] == 77 and summary['discarded'] == 1
    finally:
        release.set(); requests.close()


def test_large_legacy_history_is_retrievable_after_restart_and_preserves_live_controls():
    archive = ContextArchive()
    history = [{'tool': 'read_job', 'arguments': {}, 'result': {'description': 'actual evidence ' * 3000}} for _ in range(16)]
    snapshot = {'goal': 'Apply only after approval', 'history': history, 'messages': [{'id': 'u', 'role': 'user', 'text': 'Do not submit'}],
                'candidate': {'consent': False}, 'pending_question': {'text': 'Which school?'},
                'fields': [{'key': 'phone', 'invalid': True}], 'observation_id': 'current-id'}
    messages, metrics = prepare_request('system', [READ_CONTEXT], ConversationWindow(), snapshot, archive, max_chars=18000)
    view = json.loads(messages[-1].content)
    assert metrics['request_text_chars'] <= 18000 and not metrics['protected_overflow']
    for key in ('messages', 'candidate', 'pending_question', 'fields', 'observation_id'):
        assert view[key] == snapshot[key]
    ref = view['history'][0]['result']['context_ref']
    restored = ContextArchive(json.loads(json.dumps(archive.values)))
    chunks, offset = [], 0
    while offset is not None:
        page = restored.read(ref, offset); chunks.append(page['content']); offset = page['next_offset']
    assert json.loads(''.join(chunks)) == history[0]['result']
    assert 'context_ref' not in snapshot['history'][0]['result']


def test_request_budget_includes_tool_schema_and_drops_whole_tool_exchanges():
    window = ConversationWindow()
    for i in range(4):
        window.append({'goal': 'goal'}, '', [{'id': str(i), 'name': 'read', 'args': {}}], [{'text': 'x' * 2500}], i)
    tools = [{'schema': 'x' * 8000}]
    messages, metrics = prepare_request('s' * 1000, tools, window, {'messages': [{'role': 'user', 'text': 'latest'}]},
                                        ContextArchive(), max_chars=12000)
    assert metrics['request_text_chars'] <= 12000
    calls = {c['id'] for m in messages for c in getattr(m, 'tool_calls', [])}
    results = {m.tool_call_id for m in messages if hasattr(m, 'tool_call_id')}
    assert calls == results
    assert len(window.groups) == 4  # Sending a shorter window does not delete stored history.


def test_protected_overflow_never_erases_user_instruction_or_authorization():
    value = {'messages': [{'role': 'user', 'text': 'latest instruction ' * 1000}],
             'candidate': {'work_authorization': False}, 'pending_question': {'text': 'Needs explicit approval'}}
    messages, metrics = prepare_request('s', [], ConversationWindow(), value, ContextArchive(), max_chars=1000)
    assert json.loads(messages[-1].content) == value
    assert metrics['protected_overflow']


def test_claims_share_posting_once_without_cross_job_evidence_leak():
    captured = {}
    class Decisions(SemanticDecisions):
        def _invoke(self, schema, instruction, payload):
            captured.update(payload)
            return ClaimDecisions(decisions=[{'claim_id': c['claim_id'], 'supported': True} for c in payload['claims']])
    claims = [{'claim_id': str(i), 'claim': 'Grounded sentence', 'evidence': [{'quote': 'Confirmed fact'}],
               'employer_context': 'job A ' * 2000} for i in range(4)]
    claims.append({'claim_id': 'other', 'claim': 'Different role', 'evidence': [], 'employer_context': 'job B'})
    claims.append({'claim_id': 'none', 'claim': 'No employer context', 'evidence': []})
    assert Decisions().claims(claims) == {c['claim_id'] for c in claims}
    assert len(captured['employer_contexts']) == 2
    assert len(json.dumps(captured)) < len(json.dumps(claims)) * .4
    assert captured['claims'][0]['employer_context_id'] != captured['claims'][4]['employer_context_id']
    assert 'employer_context_id' not in captured['claims'][5]
    assert 'employer_context' in claims[0]  # Caller contract remains unchanged.


def test_jev_is_counted_once_and_cache_hits_do_not_add_provider_calls(ledger):
    from agent_runtime.fast_decisions import FastDecisions
    def handle(request):
        return httpx.Response(200, json={'answers': {'q': {'type': 'choice', 'choice': 'yes', 'confidence': 1,
            'probabilities': {'yes': 1, 'no': 0}}}, 'usage': {'input_tokens': 42, 'output_tokens': 1}})
    service = FastDecisions(api_key='test-key', enabled=True, transport=httpx.MockTransport(handle))
    questions = {'q': {'type': 'choice', 'criteria': {'yes': 'yes', 'no': 'no'}}}
    with usage_scope(ledger=ledger, task_id='t'):
        first = service.evaluate({}, questions, purpose='options')
        second = service.evaluate({}, questions, purpose='options')
    assert first.status == 'ok' and second.cached
    summary = ledger.summary(task_id='t')
    assert summary['calls'] == 1 and summary['input_tokens'] == 42
    assert summary['groups'][0]['purpose'] == 'jev:options'


def test_kernel_reads_archived_result_without_dispatching_a_domain_action(tmp_path):
    from test_shared_agent_loop import Harness, Model, call, settled
    from agent_runtime.career.repository import TaskRepository
    from agent_runtime.task_loop import TaskLoop
    from langchain_core.messages import ToolMessage
    db = create_database('sqlite:///' + (tmp_path / 'kernel.db').as_posix(), create_schema_for_tests=True)
    repo, harness = TaskRepository(db.session_factory), Harness()
    state, _ = repo.create('Review saved job', 'archive-test')
    repo.change(state['task_id'], history=[{'tool': 'read_job', 'result': {'description': 'Confirmed detail ' * 1000}}])
    def read(messages):
        observation = json.loads(messages[-1].content)
        return AIMessage(content='', tool_calls=[call('read_context', {'ref': observation['history'][0]['result']['context_ref']})])
    def finish(messages):
        output = next(m for m in reversed(messages) if isinstance(m, ToolMessage))
        result = json.loads(output.content)
        assert 'Confirmed detail' in result['content'] and result['next_offset'] == 3000
        return AIMessage(content='The source is available.')
    loop = TaskLoop(repo, harness, model_factory=lambda: Model([read, finish]))
    try:
        done = settled(repo, state['task_id'])
        assert done['status'] == 'completed'
        assert harness.writes == [] and done['loop_runtime']['context_archive']
    finally:
        loop.close(); db.close()


def test_context_read_pages_are_not_recursively_archived():
    from agent_runtime.request_context import compact_snapshot
    archive = ContextArchive()
    reference = archive.reference({'evidence': 'quoted source ' * 1500})['context_ref']
    page = archive.read(reference)
    original_refs = set(archive.values)
    for _ in range(12):
        snapshot = compact_snapshot({'history': [{'tool': 'read_context',
            'arguments': {'ref': reference}, 'result': page}]}, archive)
        assert snapshot['history'] == []  # Access pages live only in the current ToolMessage.
        assert archive.read(reference) == page
    assert set(archive.values) == original_refs
