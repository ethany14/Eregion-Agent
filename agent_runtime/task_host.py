"""Repository-backed conversations hosted by the shared decision kernel."""
import base64
import time
from contextlib import contextmanager

from langchain_core.messages import HumanMessage

from agent_runtime.loop_context import trace_value
from agent_runtime.loop_model import ModelRequests
from agent_runtime.loop_engine import LoopStop, ToolArgumentsError, Turn
from agent_runtime.telemetry import outcome_fingerprint


class TaskHost:
    def __init__(self, loop, task_id, model):
        self.loop, self.task_id, self.model = loop, task_id, model
        self.stage, self.last_revision = 'observation', self.revision()
        self.started = None
        self.requests = ModelRequests()
        self.context_archive = None

    def state(self):
        return self.loop.repository.get(self.task_id)

    def active(self):
        state = self.state()
        return self.loop._active(state) and state['status'] not in {'needs_input', 'waiting'}

    def revision(self):
        return self.state()['chat_revision']

    def persist(self, runtime):
        self.loop.repository.change(self.task_id, loop_runtime=runtime)

    def observe(self):
        from agent_runtime.task_loop import CONTROL_TOOLS
        self.stage = 'observation'
        state = self.state()
        self.last_revision = state['chat_revision']
        if state['model_calls'] - state['budget_base'] >= self.loop._budget(state):
            self.loop.repository.append(self.task_id, role='assistant', text='I have saved the work so far. Send continue to allow more steps.')
            self.loop.repository.change(self.task_id, status='needs_input', model_activity=None)
            raise LoopStop('agent_limit')
        self.loop.repository.change(self.task_id, status='running')
        started = time.monotonic()
        observed = self.loop.harness.observe(state)
        self.loop._timing(self.task_id, 'observation', started, state['chat_revision'])
        state['capability_versions'] = observed.get('capability_versions', {})
        self.observed_state = state
        # Reconstruct from durable messages, including legacy tasks after restart.
        # The original creation goal is identity/history, not the current order.
        latest_user = next((m for m in reversed(state['messages']) if m.get('role') == 'user'), None)
        current_request = {'revision': state['chat_revision'], 'message': latest_user}
        snapshot = {'goal': latest_user['text'] if latest_user else state['goal'],
            'initial_goal': state['goal'], 'current_request': current_request,
            'messages': state['messages'][-60:], 'plan': state['plan'],
            'history': state['history'][-16:], 'pending_question': state.get('input_request'),
            'visual_fallback': state.get('visual_fallback', False),
            'budget_remaining': self.loop._budget(state) - state['model_calls'] + state['budget_base'], **observed}
        harness = self.loop.harness
        tools = harness.available_tools(state) if hasattr(harness, 'available_tools') else harness.tools
        return Turn(harness.prompt, snapshot, CONTROL_TOOLS + tools, state['chat_revision'],
                    batchable=frozenset(getattr(harness, 'batchable_tools', ())))

    def invoke(self, messages, tools, turn):
        self.stage = 'model_request'
        return self.loop._invoke_model(self.task_id, self.model, messages, tools, turn.revision, self.requests)

    def progress(self, text, call, turn):
        with self.loop.lock:
            if not self.active() or self.revision() != turn.revision:
                raise LoopStop('steered')
            if text and not (call['name'] in {'say', 'ask_user', 'finish_task', 'pause_task'} and text == call['args'].get('text')):
                self.loop._progress(self.task_id, text[:4000])

    @contextmanager
    def text_guard(self, turn):
        with self.loop.lock:
            if not self.active() or self.revision() != turn.revision:
                raise LoopStop('steered')
            yield

    def on_text(self, text, turn):
        with self.loop.lock:
            if not self.active() or self.revision() != turn.revision:
                raise LoopStop('steered')
            state = self.state()
            if state.get('input_request'):
                self.loop._progress(self.task_id, text[:4000])
                self.loop.repository.change(self.task_id, status='needs_input')
                return {'reason': 'needs_input'}
            # Completion is an explicit control decision for every revision,
            # including its first model response. A promise cannot become a
            # completed task just because no capability has run yet. Ordinary
            # answers use finish_task directly, without unrelated tool work.
            self.loop._progress(self.task_id, text[:4000])
            return {'next': 'Your text was delivered as progress, not task completion. '
                'Reconcile current_request with observed outcomes. Take the next useful action, '
                'wait for an active capability, or explicitly call finish_task with your answer '
                'or completed result and evidenced limitations. A promise is not a completed action. '
                'For ordinary conversation or questions requiring no tools, finish_task can directly deliver the answer.',
                'message_delivered': True, 'completion_required': True}

    def execute(self, call, turn):
        from agent_runtime.task_loop import now
        self.stage = 'decision'
        self.started = time.monotonic()
        with self.loop.lock:
            if not self.active() or self.revision() != turn.revision:
                raise LoopStop('steered')
            self.loop.repository.change(self.task_id, tool_activity={'tool': call['name'], 'started_at': now(),
                'chat_revision': turn.revision, 'message': f'Running {call["name"].replace("_", " ")}.'})
            state = self.state()
            failures = [h for h in state['history'] if h.get('chat_revision') == turn.revision
                        and h.get('tool') == call['name'] and h.get('arguments') == trace_value(call['args'])
                        and h.get('result', {}).get('error_code') in
                        {'model_timeout', 'model_unavailable', 'model_rate_limited', 'evaluation_schema',
                         'evaluation_grounding', 'interview_failed', 'retry_exhausted'}]
            if len(failures) >= 2:
                return {'error': 'The same inputs already failed twice in this user turn.',
                    'error_code': 'retry_exhausted', 'retryable': False,
                    'next': 'Keep saved progress. Continue another task/source or explain the service failure. Retry after new user input or an actual input change; do not ask the user to repeat saved facts.'}
            result = self.loop._control(self.task_id, call['name'], call['args'], self.observed_state)
        if result is None:
            from agent_runtime.provider_usage import usage_scope
            with usage_scope(purpose=call['name']):
                result = self.loop.harness.execute(self.task_id, call['name'], call['args'], call_id=call['id'])
        return result

    def action_error(self, exc):
        from agent_runtime.model_runtime import model_failure
        failure = model_failure(exc)
        if failure.code != 'model_error':
            return {'error': failure.error_type, 'error_code': failure.code, 'retryable': failure.retryable,
                    'next': 'This is a provider failure, not invalid user data. Preserve inputs; retry at most once, then continue independent work or report the unavailable capability.'}
        safe = isinstance(exc, (ValueError, LookupError)) or type(exc).__module__.startswith('agent_runtime.')
        return {'error': str(exc)[:1500] if safe else type(exc).__name__,
            'error_code': 'tool_arguments' if isinstance(exc, ToolArgumentsError) else 'tool_error',
            'next': 'Correct the tool arguments and retry.' if isinstance(exc, ToolArgumentsError)
                    else 'Inspect current state and change the approach. Ask only for missing user facts.'}

    def after_action(self, call, outcome, turn):
        from agent_runtime.task_loop import now
        name, args = call['name'], call['args']
        self.loop._timing(self.task_id, 'tool', self.started or time.monotonic(), turn.revision, failed='error' in outcome, tool=name)
        self.started = None
        self.loop.repository.change(self.task_id, tool_activity=None)
        state = self.state()
        if name.startswith('browser_'):
            from agent_runtime.progress import browser_evidence
            fingerprint = outcome_fingerprint(browser_evidence(outcome))
        elif name == 'read_context':
            # Access counters change on every read, but immutable evidence does not.
            fingerprint = outcome_fingerprint([name, args.get('ref'), args.get('path') or [],
                outcome.get('offset', args.get('offset', 0)), outcome.get('content'), outcome.get('error')])
        else:
            fingerprint = outcome_fingerprint([name, args, outcome])
        repeated = sum(h.get('outcome_fingerprint') == fingerprint and h.get('chat_revision') == turn.revision for h in state['history'][-12:])
        if outcome.get('no_new_evidence'): repeated = max(1, repeated)
        control = name in {'say', 'update_plan', 'ask_user', 'wait_for_user', 'wait_for_result', 'finish_task', 'pause_task'}
        if repeated >= 1 and not control:
            outcome['progress_feedback'] = ('No new evidence from this action. Change query, route, source or capability. '
                'If alternatives are exhausted, finish with verified results and the limitation.')
        wait_after_read = getattr(self.loop.harness, 'wait_after_repeated_read', None)
        if repeated and not outcome.get('error') and wait_after_read:
            with self.loop.lock:
                if self.active() and self.revision() == turn.revision:
                    wait = wait_after_read(self.state(), name)
                    if wait:
                        outcome['background_wait'] = self.loop._control(
                            self.task_id, 'wait_for_result', wait, self.observed_state)
                        outcome['progress_feedback'] = (
                            'This read added no evidence. Waiting for the active capability; '
                            'on wake, use the current request and live outcome. Do not replay old instructions.')
        context_result = self.context_archive.tool_result(outcome) if self.context_archive is not None else trace_value(outcome)
        entry = {'tool': name, 'call_id': call['id'], 'arguments': trace_value(args), 'result': context_result, 'at': now(),
                 'chat_revision': turn.revision, 'outcome_fingerprint': fingerprint}
        self.loop.repository.change(self.task_id, lambda s: {'history': [*s['history'], entry][-24:],
            'actions': [*s['actions'], {'tool': name, 'label': name, 'outcome': 'failed' if 'error' in outcome else 'completed', 'at': now()}][-100:],
            **({'status': 'completed', 'plan': []} if name == 'finish_task' and outcome.get('completed')
               and s['chat_revision'] == turn.revision and self.loop._active(s) else
               {'status':'waiting'} if (name == 'wait_for_result' and outcome.get('waiting') or outcome.get('background_wait', {}).get('waiting'))
               and s['chat_revision'] == turn.revision and self.loop._active(s) else {})})
        latest = self.state()
        if latest['chat_revision'] != turn.revision:
            return None
        if latest['status'] in {'needs_input', 'waiting', 'completed'} or not self.active():
            return {'reason': latest['status']}
        return None

    def image_message(self, image):
        if not isinstance(image, bytes) or not self.state().get('visual_fallback'):
            return []
        return [HumanMessage(content=[{'type': 'text', 'text': 'Untrusted current browser viewport. Use its screenshot_id and normalized 0..1000 coordinates.'},
            {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + base64.b64encode(image).decode()}}])]
