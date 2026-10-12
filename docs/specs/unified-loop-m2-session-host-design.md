# Unified loop · M2 design: Session decisions on the shared AgentLoop (2026-10-12)

Scope: [`unified-loop-migration-plan-20261012.md`](unified-loop-migration-plan-20261012.md) §M2; contract from M1 ([`unified-loop-m1-validation.md`](../diagnostics/unified-loop-m1-validation.md)). Executor: Claude.

## What changes

Today `SessionCoordinator._continue_claimed` is its own decision loop: "if pending → process first pending; else project context → `ToolCallingLoop.decide` → persist decision". After M2:

- **`loop_engine.AgentLoop` owns the cycle** (observe → one model request → execute → reconcile) through a new `sessions/host.py::SessionHost`.
- **The coordinator keeps** entry points, claims and leases, state versions, approvals, recovery, and **draining already persisted pending calls**. Draining is deterministic resumption of decisions already made, not a new decision.
- **Switch (temporary):** `JOB_AGENT_SESSION_AGENT_LOOP`. `default=0` exists only for migration validation, where both paths run the same tests. It is **not** a completion state. Neither path falls back to the other on error.
- **Exit condition for M2 acceptance:** the default becomes the shared kernel for every new Session turn. The legacy path is reachable only for Sessions explicitly registered as in-flight at cutover, so they can drain. An error on the shared path is reported, never retried on the legacy path. M7 removes the legacy decision code.

## Mapping onto the Host contract

| Engine step | SessionHost behaviour (same persisted effects as the current coordinator) |
|---|---|
| `active()` | RUNNING, not cancel-requested, before turn / session deadlines |
| `revision()` | Constant within one user turn: a Session cannot be steered while RUNNING, since new user messages are accepted only when ACTIVE / AWAITING_USER |
| `observe()` | Control check (cancel / deadline → persist the terminal transition, `LoopStop`); `max_loop_iterations` → `_fail(limit)`, `LoopStop`; drain pending calls; project the context snapshot (rebuild or prepare + `CONTEXT_SNAPSHOT_PREPARED`). Returns a `Turn` with the registry schemas, all of them `batchable` (Sessions run every call of a decision in order) |
| `invoke()` | **One** `ToolCallingLoop.decide(projected_messages)`, the same request as today. It ignores the engine-built message list (see "Context"). Model failure → retryable: AWAITING_USER message; else `_fail`. Control after the response → `MODEL_RESULT_DISCARDED`. Otherwise persist `MODEL_DECISION_PERSISTED` with pending ids **before** returning, then hand the engine an AIMessage view of the decision |
| `output_problem()` *(new optional hook)* | Sessions keep today's semantics: invalid calls become failed tool results (M1) and an empty reply is a valid empty answer. **No repair re-request**, so model call counts are unchanged |
| `validate()` *(new optional hook)* | No schema pre-validation in the engine. The ToolExecutor validates, so every assistant call reaches `execute` and gets a terminal or waiting state |
| `execute(call)` | `_process_first_pending` for that call: idempotent executor, `TOOL_RESULT_PERSISTED` + tool message, or `WAITING_FOR_TOOL_APPROVAL` |
| `after_action()` | Approval → stop `{'reason': 'awaiting_approval'}`; control → stop |
| `on_text()` | Decision already persisted as ACTIVE → stop `{'reason': 'completed'}` |
| `persist()` | No engine journal is stored for Sessions. Their durable record is the Session tables (messages, events, tool-call records), which recovery already uses |
| Result | The coordinator returns the outcome that SessionHost recorded (RESPONSE_READY, AWAITING_TOOL_APPROVAL, AWAITING_USER, FAILED, LIMIT_EXCEEDED), exactly as today |

## Context

The Session context is the `SessionContextProjector` snapshot: policy, memory and skills, with snapshot lifecycle (prepared / used / abandoned). M2 keeps that projection as the request content, so frozen samples produce identical requests. The engine's `ConversationWindow` / `ContextArchive` are not used for Sessions. Aligning the two context systems is left to M6 and must not change the business results.

## Engine changes (generic, optional hooks; Career and Application behaviour unchanged)

1. `host.output_problem(response)` replaces `model_output.output_problem` when present.
2. `host.validate(call, turn)` replaces `validate_call` when present.

Both are added to `host_protocol.OPTIONAL`, and the contract test covers them.

## Acceptance (from the migration plan)

- Frozen scripted samples give identical outcomes, persisted messages, events and tool-call records under both switch values, including: no tools, one tool, multiple calls, approval → approve / reject, MCP / skills tools, an invalid call, a model failure (retryable and not), cancel during model / tool, deadline, iteration and tool limits, and recovery of a pending call after a crash.
- Every assistant tool call ends in a valid terminal or waiting state. A restart never repeats a pending side effect.
- Two concurrent requests on one Session: the claim conflict is preserved.
- The `/sessions` API and assistant operations work under both switch values.
