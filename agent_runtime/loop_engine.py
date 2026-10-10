"""Shared decision kernel. Hosts supply capabilities, persistence and completion policy.

The kernel knows neither career stages nor application fields. Scheduling, browser
thread ownership, approvals and external-effect validation belong to its hosts.
"""
import json
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import UTC, datetime


from agent_runtime.loop_context import ConversationWindow, trace_value
from agent_runtime.model_output import output_problem, reply_text, REPAIR_INSTRUCTION
from agent_runtime.request_context import ContextArchive, READ_CONTEXT, prepare_request


class LoopStop(Exception):
    def __init__(self, reason, **details):
        self.result = {'reason': reason, **details}
        super().__init__(reason)


class ToolArgumentsError(ValueError):
    pass


@dataclass
class Turn:
    prompt: str
    snapshot: dict
    tools: list
    revision: int = 0
    images: list = field(default_factory=list)
    batchable: frozenset = frozenset()
    compatibility_tools: list = field(default_factory=list)


def validate_call(call, tools):
    """Validate advertised shape before any host mutation; domain checks stay in tools."""
    definition = next((t['function'] for t in tools if t['function']['name'] == call.get('name')), None)
    if definition is None:
        raise ToolArgumentsError('Choose a tool advertised in the current observation.')
    schema = definition['parameters']
    def check(value, rule, path):
        if '$ref' in rule:
            target = schema
            for part in rule['$ref'].removeprefix('#/').split('/'):
                target = target[part]
            return check(value, target, path)
        if 'anyOf' in rule:
            for option in rule['anyOf']:
                try:
                    check(value, option, path)
                    return
                except ToolArgumentsError:
                    pass
            raise ToolArgumentsError(f'{path} does not match an allowed argument type.')
        kind = rule.get('type')
        valid = {'object': isinstance(value, dict), 'array': isinstance(value, list),
                 'string': isinstance(value, str), 'boolean': type(value) is bool,
                 'integer': type(value) is int, 'number': type(value) in {int, float}, 'null': value is None}
        if kind and not (any(valid.get(k, False) for k in kind) if isinstance(kind, list) else valid.get(kind, True)):
            raise ToolArgumentsError(f'{path} must have type {kind}.')
        if 'enum' in rule and value not in rule['enum']:
            raise ToolArgumentsError(f'{path} must use one of its declared choices.')
        if isinstance(value, dict):
            props = rule.get('properties', {})
            missing = set(rule.get('required', [])) - set(value)
            extra = set(value) - set(props) if rule.get('additionalProperties') is False else set()
            if missing or extra:
                raise ToolArgumentsError(f'{path} has invalid arguments; missing: {sorted(missing)}, unknown: {sorted(extra)}.')
            for key, item in value.items():
                if key in props:
                    check(item, props[key], f'{path}.{key}')
        if isinstance(value, list):
            if len(value) < rule.get('minItems', 0) or len(value) > rule.get('maxItems', float('inf')):
                raise ToolArgumentsError(f'{path} has an invalid number of items.')
            for item in value:
                check(item, rule.get('items', {}), path + '[]')
        if isinstance(value, str) and (len(value) < rule.get('minLength', 0) or len(value) > rule.get('maxLength', float('inf'))):
            raise ToolArgumentsError(f'{path} has an invalid length.')
        if type(value) in {int, float} and not rule.get('minimum', -float('inf')) <= value <= rule.get('maximum', float('inf')):
            raise ToolArgumentsError(f'{path} is outside its allowed range.')
    check(call.get('args'), schema, definition['name'])


class AgentLoop:
    """Observe, decide, execute and reconcile through one host contract.

    Host methods: active, revision, observe, invoke, progress, on_text, execute,
    action_error, after_action, persist. An explicit LoopStop is a durable handoff;
    reaching slice_steps only yields the worker, never asks a question.
    """
    def __init__(self, host, runtime=None, *, slice_steps=12, context_chars=24000, request_chars=64000):
        self.host, self.slice_steps = host, slice_steps
        self.runtime = {'version': 1, 'sequence': 0, 'events': [], **(runtime or {})}
        self.context = ConversationWindow(self.runtime.get('transcript', []), max_chars=context_chars)
        self.notice = self.runtime.get('recovery')
        self.archive = ContextArchive(self.runtime.get('context_archive'))
        self.request_chars = request_chars

    def event(self, kind, **data):
        self.runtime['sequence'] += 1
        self.runtime['events'] = [*self.runtime['events'], {'sequence': self.runtime['sequence'],
            'kind': kind, 'at': datetime.now(UTC).isoformat(), **data}][-80:]

    def save(self):
        self.runtime['transcript'] = self.context.groups
        self.runtime['context_archive'] = self.archive.values
        # Hosts receive a snapshot, never mutable lists shared with the engine.
        self.host.persist(json.loads(json.dumps(self.runtime)))

    def run(self):
        result = {'reason': 'yielded'}
        image_inputs, repair, invalid = [], None, 0
        try:
            interrupted = self.runtime.get('inflight')
            if interrupted:
                self.notice = {'interrupted_action': interrupted,
                    'next': 'This action may have completed before interruption. Inspect actual state before deciding; it is not replayed automatically.'}
                self.runtime['recovery'] = self.notice
                self.event('action_interrupted', tool=interrupted['tool'])
                self.runtime['inflight'] = None
                self.save()
            for _ in range(self.slice_steps):
                if not self.host.active():
                    raise LoopStop('cancelled')
                turn = self.host.observe()
                snapshot = dict(turn.snapshot)
                if self.notice:
                    snapshot['runtime_feedback'] = self.notice
                turn.snapshot = snapshot
                if not snapshot.get('visual_fallback'):
                    image_inputs = []
                turn.tools = [t for t in turn.tools if t['function']['name'] != 'read_context'] + [READ_CONTEXT]
                messages, context_metrics = prepare_request(turn.prompt, turn.tools, self.context, snapshot,
                    self.archive, max_chars=self.request_chars, repair=repair)
                self.runtime['context_metrics'] = context_metrics
                messages.extend(turn.images or image_inputs)
                image_inputs = []
                self.event('model_started', revision=turn.revision)
                response = self.host.invoke(messages, turn.tools, turn)
                if response is None:
                    if not self.host.active():
                        raise LoopStop('cancelled')
                    if self.host.active() and self.host.revision() != turn.revision:
                        self.event('decision_discarded', revision=turn.revision)
                        continue
                    raise LoopStop('suspended')
                if not self.host.active():
                    raise LoopStop('cancelled')
                if self.host.revision() != turn.revision:
                    self.event('decision_discarded', revision=turn.revision)
                    repair = None
                    continue
                problem = output_problem(response)
                if problem:
                    self.event('output_rejected', reason=problem)
                    if invalid:
                        raise LoopStop('invalid_model_response')
                    invalid, repair = 1, REPAIR_INSTRUCTION
                    continue
                invalid, repair, self.notice = 0, None, None
                self.runtime.pop('recovery', None)
                calls = [dict(c) for c in getattr(response, 'tool_calls', []) or []]
                text = reply_text(response)
                self.event('model_completed', revision=turn.revision, tool_count=len(calls))
                if not calls:
                    guard = self.host.text_guard(turn) if hasattr(self.host, 'text_guard') else nullcontext()
                    with guard:
                        self.context.append(snapshot, text, [], [], turn.revision)
                        self.event('assistant_message', revision=turn.revision)
                        # Publish completion only after persistence, and fence
                        # the pair against concurrent user steering when supported.
                        self.save()
                        disposition = self.host.on_text(text, turn)
                    if disposition:
                        if 'reason' in disposition:
                            result = disposition
                            break
                        self.notice = disposition
                    continue
                # Transport compatibility: a final message accompanying {} is an
                # explicit summary, not grounds to replay earlier domain work.
                if calls[0]['name'] == 'finish_task' and calls[0]['args'] == {} and text and len(text) <= 4000:
                    calls[0]['args'] = {'text': text}
                results, stopped = [], None
                batch = all(c['name'] in turn.batchable for c in calls)
                batch_error = None
                if batch and hasattr(self.host, 'validate_batch'):
                    try:
                        self.host.validate_batch(calls, turn)
                    except ToolArgumentsError as exc:
                        batch_error = exc
                for index, call in enumerate(calls):
                    if stopped or (index and not batch) or not self.host.active() or self.host.revision() != turn.revision:
                        results.append({'deferred': True, 'next': 'Read the fresh observation and latest user message before this action.'})
                        continue
                    try:
                        if batch_error:
                            raise batch_error
                        validate_call(call, turn.tools + turn.compatibility_tools)
                        if index == 0:
                            self.host.progress(text, call, turn)
                        self.runtime['inflight'] = {'tool': call['name'], 'call_id': call['id'],
                            'revision': turn.revision, 'arguments': trace_value(call['args'])}
                        self.event('tool_started', tool=call['name'], call_id=call['id'], revision=turn.revision)
                        self.save()  # Journal intent before a capability has effects.
                        outcome = (self.archive.read(call['args']['ref'], call['args'].get('offset', 0))
                                   if call['name'] == 'read_context' else self.host.execute(call, turn))
                    except LoopStop:
                        raise
                    except Exception as exc:
                        outcome = self.host.action_error(exc)
                    if not isinstance(outcome, dict):
                        outcome = {'value': outcome}
                    outcome = dict(outcome)
                    image = outcome.pop('image', None)
                    if image and hasattr(self.host, 'image_message'):
                        image_inputs = self.host.image_message(image)
                    stopped = self.host.after_action(call, outcome, turn)
                    results.append(outcome)
                    self.event('tool_completed', tool=call['name'], call_id=call['id'], failed='error' in outcome)
                    self.runtime['inflight'] = None
                self.context.append(snapshot, text, calls, results, turn.revision)
                self.save()
                if stopped and self.host.revision() == turn.revision:
                    result = stopped
                    break
            return result
        except LoopStop as stop:
            result = stop.result
            return result
        except Exception as exc:
            result = {'reason': 'failed'}
            self.event('loop_failed', error_type=type(exc).__name__)
            raise
        finally:
            self.event('slice_finished', reason=result['reason'])
            self.save()
