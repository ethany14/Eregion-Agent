# Unified loop · R3 / M2 validation: Sessions on the shared AgentLoop (2026-10-12)

Design: [`unified-loop-m2-session-host-design.md`](../specs/unified-loop-m2-session-host-design.md). Previous stage: [`unified-loop-m1-validation.md`](unified-loop-m1-validation.md). Executor: Claude. No paid calls, no `.env` change, no real database migration.

## Result

**M2 passes offline, and the exit condition is met in code.**
- **Shared kernel by default:** every new Session turn is decided by `loop_engine.AgentLoop` through `sessions/host.py::SessionHost`. There is no opt-in switch.
- **Legacy drain only:** the old `ToolCallingLoop` decision loop runs only for Session ids explicitly listed in `JOB_AGENT_SESSION_LEGACY_DRAIN`. The list has no wildcard (`*`, `all` and prefixes are ignored).
- **No fallback:** an error on the shared kernel propagates and is not retried on the legacy loop (tested).
- **Finding the ids:** `sessions.host.in_flight_session_ids(repository)` lists the candidates to register before cutover (Sessions that are RUNNING or awaiting approval).
- **Removal:** M7 deletes the legacy decision code.

| Commit | Content |
|---|---|
| `4fd44b6` | Engine: optional `output_problem` / `validate` host hooks (Career and Application define neither, so they are unchanged) |
| `0e30efb` | `SessionHost` + coordinator routing + drain registry |
| `c9c803a` | Parity fixture on 8 Session test modules, plus `test_session_host.py` |
| `d9c150f`, `917f35a` | Two concurrent requests on one Session claim once and decide once; a user message during an in-flight model call is rejected |

The development worktree was a detached checkout of `37d7455` at `<scratchpad>/m2wt`. It was removed after the files were copied back. Code was unchanged between `37d7455` and the copy-back (`git diff --quiet 37d7455 HEAD -- agent_runtime tests`), and the committed files are the ones tested.

## How the agent_loop variant is proven to use the shared kernel

`tests/session_paths.py` runs every test of the 8 Session modules twice:
- `legacy`: the Session is treated as registered for draining.
- `agent_loop`: the default.

For each test the fixture wraps `AgentLoop.run` (thread-local marker set while the host is a `SessionHost`) and `ToolCallingLoop.decide`. **After the test it asserts:**
- under `agent_loop`, every runtime model decision happened inside `AgentLoop.run` with a SessionHost;
- under `legacy`, none did.

Decisions that test code makes directly, to stage a crash window, are excluded by caller file. Each test records its decision count as a JUnit property.

Parity run (code identical to `c9c803a`): **248 passed**.
- Raw files: [`parity.xml`](../benchmarks/unified-loop-m2-20261012/parity.xml) (sha256 `bbff19ae…7b9b`) and [`parity.log`](../benchmarks/unified-loop-m2-20261012/parity.log) (sha256 `31218155…ef57`).
- From the XML: `legacy` has 116 tests and 58 runtime model decisions; `agent_loop` has 116 tests and **58** runtime model decisions, all inside the shared kernel. The equal counts mean the new kernel makes no extra model request.

```
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/test_session_coordinator.py tests/test_session_cancellation_deadlines.py tests/test_session_claims_recovery.py tests/test_session_runtime.py tests/test_session_api.py tests/test_context_runtime.py tests/test_harness_refactor.py tests/test_mcp_app.py tests/test_session_host.py tests/test_host_protocol.py tests/test_loop_stale_results.py --basetemp=<scratchpad>/m2-parity --junitxml=docs/benchmarks/unified-loop-m2-20261012/parity.xml
```

## Acceptance items (migration plan §M2) → evidence

| Item | Evidence (both kernels unless noted) |
|---|---|
| Same business results on frozen samples | The whole parity set passes on both variants with identical assertions on outcomes, persisted messages, events and tool records. Model decision counts are equal (58 = 58) |
| Every assistant call reaches a terminal or waiting state | `test_single_and_multiple_tool_calls_persist_in_original_order`, `test_invalid_tool_arguments_become_message_not_terminal_failure`, `test_rejection_is_persisted_as_safe_tool_message_and_model_continues` |
| A restart never repeats a pending side effect | `test_completed_tool_is_replayed_without_execution`, `test_expired_safe_read_retries_but_uncertain_call_becomes_outcome_unknown`, `test_completed_tool_record_is_reused_after_session_message_crash_window` |
| Model failure keeps the waiting-for-user semantics | `test_model_and_ordinary_tool_errors_are_handled_safely` |
| `/sessions` and assistant operations | `test_session_api.py` (create / list / archive / submit / approve / reject / cancel / recover) |
| MCP and skills tools | `test_mcp_app.py` (including MCP approval and an unavailable tool after restart), `test_context_runtime.py` (skill allowlist and hash) |
| Cancel, deadline, budget, approval | `test_session_cancellation_deadlines.py`, `test_persisted_model_and_tool_limits`, `test_approval_pause_resume_resolves_all_pending_before_model` |
| User changes before the model returns | A new user message is refused while RUNNING (`test_user_message_during_an_in_flight_model_call_is_rejected`). Cancel or deadline during a model call discards the result (`test_model_result_is_discarded_after_inflight_cancellation`, `test_deadline_during_model_discards_response`) |
| Tool succeeded, crash before the receipt was persisted | `test_completed_tool_record_is_reused_after_session_message_crash_window`, `test_completed_tool_is_replayed_without_execution` |
| Two concurrent requests on one Session | `test_two_concurrent_requests_on_one_session_decide_once` (shared kernel; the claim layer is shared by both paths) |
| Exit condition: default shared, explicit drain only, no fallback | `test_default_is_the_shared_agent_loop`, `test_only_explicitly_registered_sessions_drain_on_the_legacy_loop`, `test_drain_registry_has_no_wildcard`, `test_shared_loop_error_is_not_retried_on_the_legacy_loop`, `test_in_flight_sessions_are_listed_for_registration` |

## Defect found and fixed during parity

The first parity run hung on `test_pre_operation_deadline_times_out_without_model_call[agent_loop]`. With the deadline already past, the engine's opening `active()` check stopped before the host recorded an outcome, and the wrapper restarted the engine indefinitely. The fix: when the engine stops without an outcome, the coordinator applies the same control transition (timeout / cancel) and the settled-state outcome itself. If the Session version did not change, it raises instead of looping. This is fixed before commit `0e30efb`.

## Offline full suite

Code at `c9c803a`, shared kernel default, no live variables:

```
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests --basetemp=<scratchpad>/m2-full --junitxml=docs/benchmarks/unified-loop-m2-20261012/full-suite-c9c803a.xml
2301 passed, 134 skipped, 16 subtests passed, 0 failed in 1178 s
```

Raw output: [`full-suite-c9c803a.log`](../benchmarks/unified-loop-m2-20261012/full-suite-c9c803a.log) (sha256 `fba3c9f1…45bb`) and [`full-suite-c9c803a.xml`](../benchmarks/unified-loop-m2-20261012/full-suite-c9c803a.xml) (sha256 `4bb8e827…c5d`).

- **Count change:** +125 compared with M1, mostly the parity duplication of the 8 Session modules.
- **Two later test-only commits:** `d9c150f` and `917f35a` added tests to `test_session_host.py` after collection, so they are not in this run. Their result is in the focused run instead: 11 passed.

## Not changed and still open

- The Session request context is still the `SessionContextProjector` projection; aligning it with the engine's `ConversationWindow` is M6.
- The `custom_agent` analysis loop is M3, scheduling is M4/M5, and removing the legacy decision code is M7.
- **Operational cutover:** before deploying, register any in-flight Session ids reported by `in_flight_session_ids`. Deployment is not authorized in this plan and was not done.
