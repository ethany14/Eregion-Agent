"""Deterministic analysis workflow with transactional state and events.

Fixed steps (validate -> analyse resume -> evidence -> job -> match -> write ->
verify -> human review -> bounded revision) are advanced one checkpointed step
at a time. No model call decides the next step; TransitionPolicy does.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any
from uuid import uuid4

from eregion.domain.workflow.errors import InvalidTransitionError, StaleStateError, StateNotFoundError
from eregion.domain.workflow.events import AgentEvent, AgentEventType
from eregion.domain.workflow.policy import Transition, TransitionPolicy
from eregion.domain.workflow.repository import StateRepository
from eregion.domain.workflow.state import AgentState, AgentStatus, Step
from eregion.domain.workflow.steps import StepHandler
from eregion.domain.domain import retain_verbatim_resume_evidence
from eregion.domain.results import public_result
from eregion.domain.schemas import ResumeAnalysis


class AnalysisWorkflow:
    def __init__(
        self,
        *,
        repository: StateRepository,
        handler: StepHandler,
        policy: TransitionPolicy | None = None,
        result_projector: Callable[[dict[str, Any]], dict[str, Any]] = public_result,
    ) -> None:
        self._repository = repository
        self._handler = handler
        self._policy = policy or TransitionPolicy()
        self._result_projector = result_projector

    def start(
        self,
        *,
        resume_text: str,
        job_description: str,
        run_id: str | None = None,
        max_revisions: int = 1,
    ) -> AgentState:
        state = AgentState(
            run_id=run_id or str(uuid4()),
            resume_text=resume_text,
            job_description=job_description,
            max_revisions=max_revisions,
        )
        event = self._event(state, AgentEventType.RUN_CREATED, Step.VALIDATE_INPUT)
        state = self._repository.create(state, event)
        return self.run_until_pause(state.run_id)

    def run_until_pause(self, run_id: str) -> AgentState:
        """Advance until human review (or failure); each step is its own checkpoint."""
        state = self._repository.require(run_id)
        if state.terminal:
            raise InvalidTransitionError("A terminal run cannot continue.")
        while state.step != Step.HUMAN_REVIEW:
            state = self.advance(state)
        return state

    def advance(self, state: AgentState) -> AgentState:
        """Run exactly one computation step and persist its transition."""
        if state.terminal or state.step == Step.HUMAN_REVIEW:
            raise InvalidTransitionError("Only a running computation step can advance.")
        try:
            outcome = self._execute_step(state)
            produced_fields = set(outcome.updates)
            updates = dict(outcome.updates)
            if state.step == Step.REVISE_RESUME:
                updates.update(
                    {
                        "revision_count": state.revision_count + 1,
                        "approved": None,
                        "human_feedback": None,
                        "verification": None,
                    }
                )
            computed = self._updated(state, updates)
            transition = self._policy.after_step(
                computed,
                produced_fields=produced_fields,
            )
            next_state = self._transitioned(computed, transition)
            event = self._event(
                next_state,
                transition.event_type,
                state.step,
                {
                    "next_step": transition.step.value,
                    **transition.event_payload,
                },
            )
            return self._repository.save(
                next_state,
                event,
                expected_version=state.version,
                result=self._project(next_state),
            )
        except Exception as exc:
            if isinstance(
                exc, (InvalidTransitionError, StaleStateError, StateNotFoundError)
            ):
                raise
            failed = self._updated(
                state,
                {
                    "step": Step.FAILED,
                    "status": AgentStatus.FAILED,
                    "error_message": "The agent could not complete this run.",
                },
            )
            event = self._event(
                failed,
                AgentEventType.RUN_FAILED,
                state.step,
                {"error_type": type(exc).__name__},
            )
            self._repository.save(
                failed,
                event,
                expected_version=state.version,
                result=None,
            )
            raise

    def _execute_step(self, state: AgentState):
        """Execute one step, with bounded recovery for malformed model quotes.

        Resume evidence validation remains strict.  The active custom runtime
        retries extraction once before retaining only the verbatim candidates
        from a mixed response.  An extraction with no grounded evidence still
        fails rather than manufacturing evidence.
        """
        if state.step != Step.ANALYZE_RESUME:
            return self._handler.execute(state.step, state)

        last_error: ValueError | None = None
        for _ in range(2):
            outcome = self._handler.execute(state.step, state)
            if "resume_analysis" not in outcome.updates:
                return outcome
            analysis = ResumeAnalysis.model_validate(
                outcome.updates["resume_analysis"]
            )
            candidate = self._updated(state, {"resume_analysis": analysis})
            try:
                self._handler.execute(Step.VALIDATE_EVIDENCE, candidate)
                return outcome
            except ValueError as exc:
                last_error = exc

        grounded = retain_verbatim_resume_evidence(analysis, state.resume_text)
        if not grounded.evidence:
            assert last_error is not None
            raise last_error
        self._handler.execute(Step.VALIDATE_EVIDENCE,
                              self._updated(state, {"resume_analysis": grounded}))
        return type(outcome)(updates={"resume_analysis": grounded})

    def review(
        self,
        run_id: str,
        *,
        approved: bool,
        feedback: str | None,
        expected_version: int | None = None,
    ) -> AgentState:
        state = self._repository.require(run_id)
        if expected_version is not None and expected_version != state.version:
            raise StaleStateError(f"Custom agent run '{run_id}' has a stale state version.")
        transition = self._policy.after_review(
            state, approved=approved, feedback=feedback
        )
        reviewed = self._transitioned(state, transition)
        event = self._event(
            reviewed,
            transition.event_type,
            Step.HUMAN_REVIEW,
            dict(transition.event_payload),
        )
        reviewed = self._repository.save(
            reviewed,
            event,
            expected_version=state.version,
            result=self._project(reviewed),
        )
        if reviewed.step == Step.COMPLETED:
            return reviewed
        return self.run_until_pause(run_id)

    @staticmethod
    def _updated(state: AgentState, updates: Mapping[str, Any]) -> AgentState:
        return AgentState.model_validate({**state.model_dump(), **updates})

    @classmethod
    def _transitioned(cls, state: AgentState, transition: Transition) -> AgentState:
        return cls._updated(
            state,
            {
                **transition.updates,
                "step": transition.step,
                "status": transition.status,
            },
        )

    @staticmethod
    def _event(
        state: AgentState,
        event_type: AgentEventType,
        step: Step,
        payload: dict | None = None,
    ) -> AgentEvent:
        return AgentEvent(
            run_id=state.run_id,
            sequence=state.event_sequence + 1,
            event_type=event_type,
            step=step,
            payload=payload or {},
        )

    def _project(self, state: AgentState) -> dict | None:
        if state.status not in {
            AgentStatus.AWAITING_REVIEW,
            AgentStatus.APPROVED,
        }:
            return None
        if (
            state.resume_analysis is None
            or state.job_analysis is None
            or state.skill_match is None
            or state.tailored_resume is None
            or state.verification is None
        ):
            return None
        return self._result_projector(state.job_state())
