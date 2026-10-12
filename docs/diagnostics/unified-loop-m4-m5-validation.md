# Unified loop · R4 / M4–M5 validation: one execution owner (2026-10-12)

Plan: [`claude-unified-execution-plan-20261012.md`](../specs/claude-unified-execution-plan-20261012.md) R4; migration plan §M4, §M5. Previous stage: [`unified-loop-m3-validation.md`](unified-loop-m3-validation.md). Executor: Claude. No paid calls, no schema migration, no `.env` change.

## Result

| Commit | Content |
|---|---|
| `214c51c` | `ExecutionService` + unit, composition and guard tests |
| `4eb1bcb` | M4: multi-agent pool on the service; `SessionRuntime.execution` |
| `27604c6` | M5: career tasks, interview inputs / feedback and application recovery on the service |
| `236f94e` | Review M45-SHUTDOWN-001: per-kind `stop_kind`. TaskLoop and InterviewQueue drain their work before CareerService closes discovery / Treg / browser |
| `e86459b` | Follow-up: if interview work outlives its 30 s drain (injectable), resources stay open and `close()` returns False. The lifespan retries once |
| `9d2f159` | A new owner reopens an interview queue that a previous owner closed (regression found by the full run below) |

**Design.** New `agent_runtime/execution/ExecutionService`, the single process owner of background work. Durable ownership stays where it already was: each domain's SQL tables with their claims, leases and versions. That is why no table migration was needed. The service owns the process side:

- **Bounded pools:** a bounded worker pool per job kind, so one kind cannot starve another.
- **De-duplication:** at most one queued-or-running job per `(kind, key)`. A job that re-schedules its own key from its tail (TaskLoop, InterviewQueue) submits without a key and keeps its own bookkeeping, so a re-run is never silently dropped.
- **Once-only recovery:** startup recovery runs once per kind per process, even if a component is rebuilt.
- **Resource-affine owners:** browser-bound application runs have no pool here, because Playwright objects belong to their thread, but their recovery is still owned by the service.
- **Single shutdown:** one `close()`, plus an inventory of dedicated resource threads and their roles.

**Composition root.** `create_session_runtime` creates one `ExecutionService` (`SessionRuntime.execution`) and passes it to:
- the multi-agent scheduler;
- `ApplicationLoop` (auto-apply routes);
- `CareerService`, which passes it on to `TaskLoop` and `InterviewQueue`.

`SessionRuntime.close()` closes it last, after the app lifespan has closed the career and application services. Components built without a service (tests, CLI) create a private one and close it themselves.

## Owners before and after

| Work | Before | After |
|---|---|---|
| Multi-agent tasks (M4) | Private `ThreadPoolExecutor(max_concurrent_tasks)` in `AgentTaskScheduler` | Kind `agent_task`, keyed by SQL attempt id, so a new claim is never merged into an older run. SQL claim / lease / heartbeat / expiry unchanged. Poller registered as resource `agent-task-scheduler` |
| Career tasks (M5) | Private pool (2) + startup re-queue loop in `TaskLoop.__init__` | Kind `career_task` (2 workers) with registered once-only recovery. `TaskLoop.running` still guards one drive per task. `task-events` monitor registered (wakes waiting tasks, enqueue only) |
| Interview inputs (M5) | One unbounded new `Thread` per task | Kind `interview_inputs` (4 workers) with registered recovery. Per-task FIFO kept: one runner per task via `InterviewQueue.running`, and the arrival-order queue is unchanged |
| Interview feedback (M5) | New `Thread` per answer, limited by a `Semaphore(3)` | Kind `interview_feedback` (3 workers) |
| Application runs (M5) | Startup `repository.recover()` in `ApplicationLoop.__init__` | Owner `application_run`: browser-affine `WorkerPool` threads unchanged (runs stay on their thread, same-site runs share a worker), recovery run once through the service |
| Job alerts | Timer thread | Unchanged: it only enqueues career tasks (claim by `request_key`). Registered as resource `career-job-alerts` |
| Trash purge | Daily thread | Unchanged; registered as resource `career-trash` (no task ownership) |

Threads and pools that remain outside the service, with their responsibility:
- **Scoped fan-out inside one job,** bounded and context-managed, no ownership: `application_pack/workflow.py` `pack-writer` (3), `fit_analysis_service` `fit-extract` (2), `job_agent/fast_match` (3), `job_extraction` (3), `jev_fit/service` (≤4).
- **Resource-affine or provider-transport threads:** `auto_apply/worker.BrowserWorker` (Playwright thread affinity), `browser/manager.BrowserWorker` (the career research browser), `loop_model` `agent-provider` (one in-flight model request with timeout / cancel), `jev_fit/transport` broker.
- **Background warm-up:** `analysis_cache` `resume-warmup` (1), which caches only and owns nothing.
- **Per-attempt heartbeats:** the multi-agent per-attempt heartbeat thread, which renews the SQL lease of its own attempt.

A guard test forbids a new `ThreadPoolExecutor(` in the task owners (`task_loop`, `career/service`, `interview_queue`, `multi_agent/scheduler`, `auto_apply/loop`).

## Acceptance (M4 / M5) → evidence

| Item | Evidence |
|---|---|
| One owner per child; partial success recoverable; cancel, timeout and failure propagate by parent policy | Unchanged SQL paths in `AgentTaskScheduler._run_claimed` / repository; `tests/test_multi_agent.py`, `tests/test_job_workflow.py` (42 passed on the service) |
| Parent and child costs not double-counted; context passes only structured inputs | Unchanged (`model_usage_scope`, `AgentContextPolicy`); same tests |
| No second model planner and no parallel-budget source of truth | The plan is a server-owned deterministic template (`job_workflow/plan.py`); budget is per root in SQL (`budget_for`). `workflow_mode` is recorded history and only used to filter multi-agent roots in the API, not to pick an executor |
| A restart recovers only once | `test_startup_recovery_is_once_per_process_even_if_a_loop_is_rebuilt`; `ExecutionService.recover` once per kind |
| Bounded concurrency | `test_pool_is_bounded_per_kind`; per-kind bounds above |
| The same browser never contends across threads | Browser-affine owner unchanged; auto-apply suites (294 passed / 54 skipped) |
| Concurrent end / skip / answer / feedback on interviews never mix up questions | Arrival-order queue and per-task single runner unchanged; interview suites |
| No new external write after cancel | Unchanged cancel paths; career / auto-apply suites |
| Repeated alert triggers create no duplicate task | Unchanged claim by `request_key`; `tests/test_job_alerts.py` |
| Interview features not turned into multi-round router-driven flows | No interview behaviour changed |

## Verification

- **Pre-commit full run** (working tree, not a version): 1 failure. The auto-apply route always passed `execution=` and broke a test's factory stand-in. Fixed before `27604c6` by passing it only when present.
- **Full run started at `27604c6`:** 2345 passed / 134 skipped / **1 failed** (1962 s). **This is not a single-version result:** I committed `236f94e`, `e86459b` and `75c5e6d` into the same working tree while it ran, so late-imported modules may have run newer code. Log and XML are kept as-is: [`full-suite-27604c6.log`](../benchmarks/unified-loop-m4-m5-20261012/full-suite-27604c6.log) / [`.xml`](../benchmarks/unified-loop-m4-m5-20261012/full-suite-27604c6.xml).
  - The failure, `test_failed_feedback_waits_for_explicit_retry_and_queued_end_keeps_saved_answer`, reproduced 3 / 3 in isolation. It was a real regression from `236f94e`: a CareerService rebuilt around the same harness kept the closed InterviewQueue. Fixed in `9d2f159`, with a regression test.
- **Targeted runs after the shutdown fixes:** 190 passed / 2 skipped at `236f94e` ([`shutdown-fix-targeted`](../benchmarks/unified-loop-m4-m5-20261012/shutdown-fix-targeted.xml)); 211 passed / 2 skipped at `e86459b` ([`shutdown-timeout-targeted`](../benchmarks/unified-loop-m4-m5-20261012/shutdown-timeout-targeted.xml)). Removing each fix makes its test fail: the drain (`test_career_close_waits_…`) and the timeout branch (`test_interview_drain_timeout_…`).
- **Clean single-version full suite:** see [`unified-loop-final.md`](unified-loop-final.md). It ran at `fc5dc79` with no edits during the run.

## Notes

- Fixed workflows (analysis, material packs in `single_custom` mode) are deterministic request-scoped work, not autonomous task owners (M3).
- **Next:** R5 / M6–M7 (data dry-run on a database copy, then removal of the legacy decision code).
