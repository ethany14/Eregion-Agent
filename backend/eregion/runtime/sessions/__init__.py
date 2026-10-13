"""Versioned persistence contracts for future agent sessions."""

from eregion.runtime.sessions.errors import (
    InvalidSessionTransitionError,
    MessageConflictError,
    SessionAlreadyExistsError,
    SessionNotFoundError,
    SessionTerminalError,
    StaleSessionError,
    SessionClaimConflictError,
    SessionClaimNotOwnedError,
)
from eregion.runtime.sessions.events import SessionEvent, SessionEventType
from eregion.runtime.sessions.coordinator import SessionCoordinator
from eregion.runtime.sessions.outcome import SessionOutcome, SessionOutcomeStatus
from eregion.runtime.sessions.repository import SessionRepository
from eregion.runtime.sessions.state import (
    PersistedSessionMessage,
    SessionMessageDraft,
    SessionMessageVisibility,
    SessionState,
    SessionStatus,
)
from eregion.runtime.sessions.clock import Clock, FakeClock, SystemClock
from eregion.runtime.sessions.claims import (
    SessionAttemptStatus,
    SessionClaimRepository,
    SessionExecutionAttempt,
)
from eregion.runtime.sessions.recovery import (
    RecoveryAction,
    SessionRecoveryPlan,
    SessionRecoveryPlanner,
)

__all__ = [
    "InvalidSessionTransitionError",
    "MessageConflictError",
    "PersistedSessionMessage",
    "SessionAlreadyExistsError",
    "SessionCoordinator",
    "SessionEvent",
    "SessionEventType",
    "SessionMessageDraft",
    "SessionMessageVisibility",
    "SessionNotFoundError",
    "SessionOutcome",
    "SessionOutcomeStatus",
    "SessionRepository",
    "SessionState",
    "SessionStatus",
    "SessionTerminalError",
    "StaleSessionError",
    "SessionClaimConflictError",
    "SessionClaimNotOwnedError",
    "Clock",
    "FakeClock",
    "SystemClock",
    "SessionAttemptStatus",
    "SessionClaimRepository",
    "SessionExecutionAttempt",
    "RecoveryAction",
    "SessionRecoveryPlan",
    "SessionRecoveryPlanner",
]
