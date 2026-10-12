"""Session turns decided by the shared AgentLoop (unified loop M2).

SessionHost adapts one claimed Session turn to the loop_engine Host contract.
Every durable effect goes through the coordinator's existing transitions:
claims, state versions, pending calls, approvals and context snapshots keep
their current semantics. The coordinator owns entry points and resumption of
already-persisted calls; AgentLoop owns the decide/execute cycle.
"""
from __future__ import annotations

import os
from uuid import uuid4

from langchain_core.messages import AIMessage

from agent_runtime.context.snapshots import ContextSnapshotUnavailableError
from agent_runtime.loop_engine import LoopStop, Turn
from agent_runtime.model_runtime import model_failure
from agent_runtime.sessions.errors import (
    InvalidSessionTransitionError,
    SessionClaimNotOwnedError,
    StaleSessionError,
)
from agent_runtime.sessions.events import SessionEvent, SessionEventType
from agent_runtime.sessions.outcome import SessionOutcomeStatus
from agent_runtime.sessions.state import SessionMessageDraft, SessionStatus
from agent_runtime.tools.messages import AgentMessage


def legacy_drain_ids() -> frozenset[str]:
    """Sessions explicitly registered at cutover to finish on the legacy path."""
    raw = os.getenv('JOB_AGENT_SESSION_LEGACY_DRAIN', '')
    return frozenset(item.strip() for item in raw.split(',') if item.strip())


def uses_legacy(session_id: str) -> bool:
    """Only registered in-flight Sessions drain on ToolCallingLoop; there is no
    wildcard and no fallback on error. Every other turn uses the shared AgentLoop."""
    return session_id in legacy_drain_ids()


def in_flight_session_ids(sessions) -> list[str]:
    """Candidates to register before cutover: Sessions mid-turn or awaiting approval."""
    from sqlalchemy import select
    from agent_runtime.sessions.models import AgentSessionRow
    with sessions.session_factory() as db:
        return list(db.scalars(select(AgentSessionRow.session_id).where(AgentSessionRow.status.in_(
            [SessionStatus.RUNNING.value, SessionStatus.AWAITING_TOOL_APPROVAL.value]))))


class SessionHost:
    def __init__(self, coordinator, session_id, attempt):
        self._c, self.session_id, self.attempt = coordinator, session_id, attempt
        self.outcome = None
        self._prepared = self._messages = self._context = self._timeout = None
        self._decision_state = None

    # -- contract ---------------------------------------------------------------

    def active(self):
        """Not cancelled and within deadlines; the host's own transitions are not interruptions."""
        if self.outcome is not None:
            return False
        state, now = self._state(), self._c._clock.now()
        expired = any(limit is not None and now >= limit
                      for limit in (state.turn_deadline_at, state.session_expires_at))
        return not state.cancel_requested and not expired

    def revision(self):
        # User messages are accepted only while the Session is not RUNNING, so
        # one claimed turn cannot be steered; cancellation is seen by active().
        return 0

    def observe(self):
        c = self._c
        state = self._state()
        # Resume decisions that are already persisted before deciding again.
        while True:
            self._stop_on(c._control_outcome(state))
            self._stop_on(self._settled_outcome(state))
            if not state.pending_tool_call_ids:
                break
            state, outcome = c._process_first_pending(state, self.attempt)
            self._stop_on(outcome)
            state = self._state()
        if state.loop_iteration >= state.max_loop_iterations:
            self._stop_on(c._fail(state, code='max_loop_iterations_exceeded',
                message='The persisted model-iteration limit was reached.', limit=True))
        state = self._prepare(state)
        tools = [{'type': 'function', 'function': {'name': item['name'], 'description': item['description'],
                  'parameters': item['input_schema']}}
                 for item in c._loop._registry.model_schemas(self._context)]
        return Turn('', {}, tools, 0, batchable=frozenset(t['function']['name'] for t in tools))

    def invoke(self, messages, tools, turn):
        """One model request on the projected Session context; the decision is persisted here."""
        c = self._c
        state = self._decision_state
        try:
            response = c._loop.decide(self._messages, self._context, timeout_seconds=self._timeout)
        except SessionClaimNotOwnedError:
            raise
        except Exception as exc:
            self.outcome = self._model_failure(state, exc)
            return None
        current = self._state()
        control = c._control_outcome(current, discarded_event=SessionEventType.MODEL_RESULT_DISCARDED)
        if control is not None:
            self.outcome = control
            return None
        if current.version != state.version:
            raise StaleSessionError('The session changed while the model call was in flight.')
        self.attempt = c._heartbeat(self.attempt)
        assistant = response.message
        if assistant.role != 'assistant':
            self.outcome = c._fail(current, code='invalid_model_response',
                message='The model returned an invalid message role.')
            return None
        pending = [item.tool_call_id for item in assistant.tool_calls]
        decided = c._updated(current, {
            'status': SessionStatus.RUNNING if pending else SessionStatus.ACTIVE,
            'pending_assistant_message_id': assistant.message_id if pending else None,
            'pending_tool_call_ids': pending,
            'loop_iteration': current.loop_iteration + 1,
            'total_input_tokens': current.total_input_tokens + response.usage.input_tokens,
            'total_output_tokens': current.total_output_tokens + response.usage.output_tokens,
            'turn_deadline_at': current.turn_deadline_at if pending else None,
            'current_context_snapshot_id': None,
            'last_context_snapshot_id': self._prepared.snapshot.snapshot_id,
        })
        try:
            c._sessions.save_transition(decided, SessionEvent(session_id=current.session_id,
                    event_type=SessionEventType.MODEL_DECISION_PERSISTED,
                    payload={'tool_call_count': len(pending)}),
                expected_version=current.version, messages=[SessionMessageDraft(message=assistant)])
        except StaleSessionError:
            control = c._control_outcome(self._state(), discarded_event=SessionEventType.MODEL_RESULT_DISCARDED)
            if control is None:
                raise
            self.outcome = control
            return None
        c._context_snapshots.mark_used(self._prepared.snapshot.snapshot_id)
        return AIMessage(content=assistant.content, tool_calls=[
            {'name': item.tool_name, 'args': item.arguments, 'id': item.tool_call_id}
            for item in assistant.tool_calls])

    def output_problem(self, response):
        # Invalid calls become failed tool results and an empty reply is a valid
        # answer, exactly as before; Sessions never spend a repair request.
        return None

    def validate(self, call, turn):
        # The ToolExecutor validates arguments, so every persisted call reaches a
        # terminal or waiting state instead of being dropped before execution.
        return None

    def progress(self, text, call, turn):
        pass

    def on_text(self, text, turn):
        self.outcome = self._c._response_outcome(self._state())
        return {'reason': 'completed'}

    def execute(self, call, turn):
        state = self._state()
        if not state.pending_tool_call_ids or state.pending_tool_call_ids[0] != call['id']:
            raise InvalidSessionTransitionError('The decided call is not the first pending call.')
        state, outcome = self._c._process_first_pending(state, self.attempt)
        if outcome is not None:
            self.outcome = outcome
            return {'stopped': str(outcome.status)}
        return {'persisted': call['id']}

    def action_error(self, exc):
        # Tool failures are already converted to tool messages by the executor
        # path; anything reaching here is a coordination error and must surface.
        raise exc

    def after_action(self, call, outcome, turn):
        if self.outcome is not None:
            return {'reason': str(self.outcome.status)}
        return None

    def persist(self, runtime):
        # The Session tables are the durable record; recovery reads them, not
        # an engine journal.
        pass

    # -- helpers ----------------------------------------------------------------

    def _state(self):
        return self._c._sessions.require(self.session_id)

    def _settled_outcome(self, state):
        """The coordinator's answer for a Session that is not RUNNING (same order and errors)."""
        c = self._c
        if state.status == SessionStatus.AWAITING_TOOL_APPROVAL:
            return c._approval_outcome(state)
        if state.status == SessionStatus.AWAITING_USER:
            return c._outcome(SessionOutcomeStatus.AWAITING_USER, state)
        if state.status == SessionStatus.ACTIVE:
            return c._response_outcome(state)
        if state.status in {SessionStatus.FAILED, SessionStatus.CANCELLED, SessionStatus.COMPLETED}:
            return c._outcome_for_stable_state(state)
        if state.status != SessionStatus.RUNNING:
            raise InvalidSessionTransitionError('The session cannot continue.')
        return None

    def _stop_on(self, outcome):
        if outcome is not None:
            self.outcome = outcome
            raise LoopStop('session', status=str(outcome.status))

    def _prepare(self, state):
        c = self._c
        self.attempt = c._heartbeat(self.attempt)
        created = None
        try:
            prepared = (c._context_projector.rebuild(state, state.current_context_snapshot_id)
                        if state.current_context_snapshot_id else c._context_projector.prepare(state))
            if not state.current_context_snapshot_id:
                created = prepared.snapshot.snapshot_id
                state = c._sessions.save_transition(
                    c._updated(state, {'current_context_snapshot_id': created}),
                    SessionEvent(session_id=state.session_id,
                        event_type=SessionEventType.CONTEXT_SNAPSHOT_PREPARED,
                        payload={'snapshot_id': created}),
                    expected_version=state.version)
            # Semantic retrieval may take time: renew, then compute the budget.
            self.attempt = c._heartbeat(self.attempt)
            self._timeout = c._effective_timeout(state, self.attempt, c._model_timeout_seconds)
            self._context = c._context(state, self.attempt, timeout_seconds=self._timeout,
                                       allowed_tools=prepared.snapshot.effective_tools)
        except SessionClaimNotOwnedError:
            raise
        except Exception:
            if created is not None:
                try:
                    c._context_snapshots.abandon(created, reason='context_pointer_not_persisted')
                except ContextSnapshotUnavailableError:
                    pass
            current = self._state()
            self._stop_on(c._control_outcome(current))
            self._stop_on(c._fail(current, code='context_snapshot_unavailable',
                message='The model context could not be prepared safely.'))
        self._prepared, self._messages, self._decision_state = prepared, prepared.messages, state
        return state

    def _model_failure(self, state, exc):
        c = self._c
        c._abandon_context(state, 'model_invocation_failed')
        current = self._state()
        control = c._control_outcome(current)
        if control is not None:
            return control
        failure = model_failure(exc)
        if not failure.retryable:
            return c._fail(current, code='model_invocation_failed',
                message='The model could not complete the session turn.')
        message = AgentMessage(message_id=str(uuid4()), role='assistant', content=(
            'The model service is temporarily unavailable. Your conversation and completed '
            'work are saved. Send another message to continue.'))
        resumed = c._sessions.save_transition(
            c._updated(current, {
                'status': SessionStatus.AWAITING_USER,
                'error_code': failure.code, 'error_message': message.content,
                'turn_deadline_at': None, 'current_context_snapshot_id': None,
                'terminal_reason': None,
            }),
            SessionEvent(session_id=current.session_id, event_type=SessionEventType.WAITING_FOR_USER,
                payload={'reason': failure.code, 'retryable': True}),
            expected_version=current.version, messages=[SessionMessageDraft(message=message)])
        return c._outcome(SessionOutcomeStatus.AWAITING_USER, resumed, final_text=message.content,
            error_code=failure.code, error_message=message.content)
