"""Exercise the real schedulers/repository/kernel without invoking pytest."""
import json
import sys
import time
import unittest
import tempfile
from pathlib import Path
from threading import Event

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from api.db import create_database
from agent_runtime.career.repository import TaskRepository
from agent_runtime.task_loop import TaskLoop, function
from agent_runtime.loop_context import ConversationWindow


def call(name, args=None, identifier='call'):
    return {'name': name, 'args': args or {}, 'id': identifier}


def finish(text):
    return AIMessage(content='',tool_calls=[call('finish_task',{'text':text},'finish')])


def settled(repo, task_id, timeout=6):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = repo.get(task_id)
        if state['status'] in {'needs_input', 'completed', 'waiting'}:
            return state
        time.sleep(.01)
    raise AssertionError({k: state.get(k) for k in ('status', 'error', 'history', 'model_calls')})


class Harness:
    prompt = 'Use these local capabilities to fulfill the request.'
    tools = [function('read_item', 'Read an item.', {'id': {'type': 'integer'}}),
             function('write_item', 'Update an item.', {'value': {'type': 'string'}})]
    batchable_tools = {'read_item'}
    def __init__(self):
        self.reads, self.writes, self.version = [], [], 1
    def observe(self, state):
        return {'items': list(self.writes), 'capability_versions': {'work': {'child': self.version}}}
    def execute(self, task_id, name, args, **kwargs):
        if name == 'read_item':
            self.reads.append(args['id'])
            return {'value': f"record-{args['id']}"}
        self.writes.append(args['value'])
        return {'saved': args['value']}
    def validate_finish(self, state): pass
    def control(self, state, action): pass
    def validate_wait(self, state, args): pass
    def wait_token(self, args): return self.version
    def wake(self, state): return self.version != state['wait']['token']


class Model:
    def __init__(self, replies):
        self.replies, self.messages = iter(replies), []
    def invoke(self, messages, tools):
        self.messages.append(messages)
        result = next(self.replies)
        return result(messages) if callable(result) else result


class LoopChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='northstar-loop-')
        url = 'sqlite:///' + (Path(self.temp.name) / 'test.db').as_posix()
        self.db = create_database(url, create_schema_for_tests=True)
        self.repo, self.harness = TaskRepository(self.db.session_factory), Harness()
        self.loops = []
    def tearDown(self):
        for loop in self.loops: loop.close()
        self.db.close()
        self.temp.cleanup()
    def start(self, model, key='case', **kwargs):
        loop = TaskLoop(self.repo, self.harness, model_factory=lambda: model, **kwargs)
        self.loops.append(loop)
        state = loop.start('Read and help me.', key)
        return loop, state['task_id']

    def test_plain_reply_completes_without_fabricated_question(self):
        model = Model([finish('Hello!')])
        _, task = self.start(model)
        state = settled(self.repo, task)
        self.assertEqual(state['status'], 'completed')
        self.assertIsNone(state['input_request'])
        self.assertEqual([m['text'] for m in state['messages'] if m['role'] == 'assistant'], ['Hello!'])
        self.assertTrue(state['loop_runtime']['events'])

    def test_read_batch_and_complete_transcript(self):
        def verify_batch(messages):
            outputs = [m for m in messages if isinstance(m, ToolMessage)]
            self.assertEqual([m.tool_call_id for m in outputs], ['a', 'b'])
            return finish('Both records were read.')
        model = Model([AIMessage(content='Reading both records.', tool_calls=[
            call('read_item', {'id': 1}, 'a'), call('read_item', {'id': 2}, 'b')]), verify_batch])
        _, task = self.start(model)
        self.assertEqual(settled(self.repo, task)['status'], 'completed')
        self.assertEqual(self.harness.reads, [1, 2])

    def test_mutations_wait_for_fresh_observation(self):
        model = Model([AIMessage(content='', tool_calls=[call('write_item', {'value': 'first'}, 'a'),
            call('write_item', {'value': 'second'}, 'b')]), finish('One write completed.')])
        _, task = self.start(model)
        state = settled(self.repo, task)
        self.assertEqual(self.harness.writes, ['first'])
        results = state['loop_runtime']['transcript'][0]['results']
        self.assertTrue(results[1]['value']['deferred'])

    def test_invalid_tool_args_recover_without_effect(self):
        model = Model([AIMessage(content='', tool_calls=[call('read_item', {'id': 'wrong'})]),
                       AIMessage(content='', tool_calls=[call('read_item', {'id': 2}, 'correct')]),
                       finish('Read successfully.')])
        _, task = self.start(model)
        state = settled(self.repo, task)
        self.assertEqual(self.harness.reads, [2])
        self.assertEqual(state['history'][0]['result']['error_code'], 'tool_arguments')

    def test_tool_context_survives_worker_slice(self):
        responses = [AIMessage(content='', tool_calls=[call('read_item', {'id': i}, f'r{i}')]) for i in range(13)]
        responses.append(finish('Finished all reads.'))
        model = Model(responses)
        _, task = self.start(model)
        state = settled(self.repo, task)
        self.assertEqual(state['status'], 'completed')
        self.assertEqual(self.harness.reads, list(range(13)))
        self.assertTrue(any(isinstance(m, ToolMessage) for m in model.messages[12]))

    def test_pause_then_restart_keeps_context_without_replaying(self):
        model = Model([AIMessage(content='', tool_calls=[call('write_item', {'value': 'saved'})]),
            AIMessage(content='', tool_calls=[call('ask_user', {'text': 'Which record next?', 'wait_for_reply': True}, 'ask')])])
        loop, task = self.start(model)
        self.assertEqual(settled(self.repo, task)['status'], 'needs_input')
        loop.close(); self.loops.remove(loop)
        def resumed(messages):
            self.assertTrue(any(isinstance(m, ToolMessage) and 'saved' in m.content for m in messages))
            return finish('The saved write is still here.')
        next_model = Model([resumed])
        second = TaskLoop(self.repo, self.harness, model_factory=lambda: next_model)
        self.loops.append(second)
        second.chat(task, 'Just summarize.', 'reply-id')
        self.assertEqual(settled(self.repo, task)['status'], 'completed')
        self.assertEqual(self.harness.writes, ['saved'])

    def test_steering_invalidates_slow_decision(self):
        entered, release = Event(), Event()
        def slow(messages):
            entered.set(); release.wait(8)
            return AIMessage(content='', tool_calls=[call('write_item', {'value': 'obsolete'})])
        model = Model([slow, finish('Following the correction.')])
        loop, task = self.start(model)
        try:
            self.assertTrue(entered.wait(3))
            loop.chat(task, 'Change direction; just answer.', 'correction')
            state = settled(self.repo, task, timeout=2)
            self.assertEqual(self.harness.writes, [])
            self.assertEqual(state['messages'][-1]['text'], 'Following the correction.')
        finally: release.set()

    def test_model_retry_preserves_already_completed_action(self):
        class ProviderError(Exception):
            status_code = 503
        def unavailable(messages):
            raise ProviderError('synthetic-private-provider-body')
        model = Model([AIMessage(content='', tool_calls=[call('write_item', {'value': 'once'})]),
                       unavailable, finish('The write already completed.')])
        _, task = self.start(model, retry_delays=(0,))
        state = settled(self.repo, task)
        self.assertEqual(state['status'], 'completed')
        self.assertEqual(self.harness.writes, ['once'])
        self.assertEqual(state['model_calls'], 3)
        self.assertNotIn('synthetic-private-provider-body', json.dumps(state))

    def test_truncated_response_cannot_execute_or_appear_in_chat(self):
        model = Model([AIMessage(content='Unfinished private text', response_metadata={'finish_reason': 'length'},
            tool_calls=[call('write_item', {'value': 'bad'})]), finish('A complete reply.')])
        _, task = self.start(model)
        state = settled(self.repo, task)
        self.assertEqual(self.harness.writes, [])
        self.assertNotIn('Unfinished private text', json.dumps(state))

    def test_visual_context_is_ephemeral_and_revocable(self):
        original = self.harness.execute
        def execute(task_id, name, args, **kwargs):
            result = original(task_id, name, args, **kwargs)
            if args['id'] == 1:
                result['image'] = b'fixture-image'
            else:
                self.repo.change(task_id, visual_fallback=False)
            return result
        self.harness.execute = execute
        def seen(messages):
            self.assertTrue(any(isinstance(m.content, list) for m in messages))
            return AIMessage(content='', tool_calls=[call('read_item', {'id': 2}, 'second')])
        def revoked(messages):
            self.assertFalse(any(isinstance(m.content, list) for m in messages))
            return finish('Done.')
        model = Model([AIMessage(content='', tool_calls=[call('read_item', {'id': 1})]), seen, revoked])
        loop = TaskLoop(self.repo, self.harness, model_factory=lambda: model)
        self.loops.append(loop)
        task = loop.start('Read the screen.', 'image', visual_fallback=True)['task_id']
        state = settled(self.repo, task)
        self.assertEqual(state['status'], 'completed')
        self.assertNotIn('fixture-image', json.dumps(state))
        self.assertNotIn('Zml4dHVyZS1pbWFnZQ==', json.dumps(state))

    def test_inflight_action_recovers_by_observing(self):
        state, _ = self.repo.create('Resume a local task.', 'recover')
        self.repo.change(state['task_id'], loop_runtime={'inflight': {'tool': 'write_item', 'call_id': 'uncertain', 'revision': 0}})
        def inspect(messages):
            snapshot = json.loads(next(m.content for m in reversed(messages) if isinstance(m, HumanMessage)))
            self.assertEqual(snapshot['runtime_feedback']['interrupted_action']['tool'], 'write_item')
            return finish('The interrupted action needs observation; it was not replayed.')
        model = Model([inspect])
        loop = TaskLoop(self.repo, self.harness, model_factory=lambda: model)
        self.loops.append(loop)
        self.assertEqual(settled(self.repo, state['task_id'])['status'], 'completed')
        self.assertEqual(self.harness.writes, [])

    def test_interrupted_action_notice_survives_a_provider_failure(self):
        class ProviderError(Exception):
            status_code = 401
        def fail(messages):
            raise ProviderError('private provider body')
        state, _ = self.repo.create('Resume work.', 'recover-failure')
        task = state['task_id']
        self.repo.change(task, loop_runtime={'inflight': {'tool': 'write_item', 'call_id': 'unknown', 'revision': 0}})
        model = Model([fail, finish('The interrupted action was not replayed.')])
        loop = TaskLoop(self.repo, self.harness, model_factory=lambda: model)
        self.loops.append(loop)
        self.assertEqual(settled(self.repo, task)['status'], 'needs_input')
        self.assertIn('recovery', self.repo.get(task)['loop_runtime'])
        loop.chat(task, 'Retry after the provider recovers.', 'provider-recovered')
        self.assertEqual(settled(self.repo, task)['status'], 'completed')
        snapshot = json.loads(next(m.content for m in reversed(model.messages[-1]) if isinstance(m, HumanMessage)))
        self.assertIn('interrupted_action', snapshot['runtime_feedback'])
        self.assertEqual(self.harness.writes, [])

    def test_pending_question_allows_independent_work(self):
        model = Model([AIMessage(content='', tool_calls=[call('ask_user', {'text': 'Which city?', 'wait_for_reply': False})]),
            AIMessage(content='', tool_calls=[call('read_item', {'id': 1}, 'read')]),
            AIMessage(content='', tool_calls=[call('wait_for_user', {}, 'wait')])])
        _, task = self.start(model)
        state = settled(self.repo, task)
        self.assertEqual(self.harness.reads, [1])
        self.assertEqual(len([m for m in state['messages'] if m['role'] == 'assistant']), 1)
        self.assertEqual(state['input_request']['text'], 'Which city?')

    def test_wait_wakes_on_capability_change(self):
        model = Model([AIMessage(content='', tool_calls=[call('wait_for_result', {'kind': 'work', 'id': 'child'})]),
                       finish('The result arrived.')])
        _, task = self.start(model)
        self.assertEqual(settled(self.repo, task)['status'], 'waiting')
        self.harness.version = 2
        time.sleep(.6)
        self.assertEqual(settled(self.repo, task)['status'], 'completed')


if __name__ == '__main__': unittest.main(verbosity=2)
