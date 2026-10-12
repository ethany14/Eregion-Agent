# Unified loop · final report (R2–R5 / M1–M7, 2026-10-12)

Plan: [`claude-unified-execution-plan-20261012.md`](../specs/claude-unified-execution-plan-20261012.md); migration rules: [`unified-loop-migration-plan-20261012.md`](../specs/unified-loop-migration-plan-20261012.md). Executor: Claude, with review by Codex (supervision notes M1-EVIDENCE-001, M3-GROUNDING-001, M45-SHUTDOWN-001, M6-COVERAGE-001, all addressed below).

**Status.**
- **Migration stages M1–M7:** done in code and validated offline.
- **Not done:**
  - real-database dry-run and deployment (not authorized);
  - human style review of materials;
  - R6 API-first B6, R7 LinkedIn MCP, R8 source policy, R9 delivery (later stages of the plan).

## Entry graph after M7

```
API / CLI / timers
 ├─ career chat ─────────── CareerService ─ TaskLoop ─┐
 ├─ auto-apply ──────────── ApplicationLoop (browser-affine workers) ─┤
 ├─ /sessions, assistant ── SessionCoordinator (claims, versions, approvals) ─┤
 │                                                     ▼
 │                       agent_runtime.loop_engine.AgentLoop  ← the only autonomous kernel
 │                         Hosts: TaskHost · ApplicationHost · SessionHost · _RunHost (compat)
 ├─ /runs, main.py ──────── job_agent.workflow.AnalysisWorkflow (deterministic steps, no router)
 ├─ packs / materials ───── ApplicationPackWorkflow (deterministic writer / verifier)
 ├─ multi-agent API ─────── AgentTaskScheduler (SQL claims) → typed workers (deterministic DAG template)
 └─ job alerts ──────────── timer → CareerService.start (enqueue only)

Background ownership: one ExecutionService per runtime
  kinds: career_task · agent_task · interview_inputs · interview_feedback
  owner: application_run (browser-affine)
  resources: task-events · agent-task-scheduler · career-job-alerts · career-trash
Provider requests: job_agent.model (provider_call / adapter_attempt) · fast_decisions · jev_fit transport
```

The structure is pinned by `tests/test_unified_architecture.py`, which inspects the AST rather than file names:
- `AgentLoop` is constructed only from `agent_runtime.loop_engine`, in its four owners;
- `ToolCallingLoop.decide` is called only from `SessionHost.invoke` and `_RunHost.invoke`;
- provider entry points are only the accounted layer;
- no production code imports `custom_agent`.

## Removed / kept

| Removed | Kept (compatibility only) |
|---|---|
| Session legacy decision loop in `SessionCoordinator._continue_claimed` and the `JOB_AGENT_SESSION_LEGACY_DRAIN` switch (M7) | `ToolCallingLoop.decide` / `process_tool_call` as single-step operations; `ToolCallingLoop.run()` as a compatibility entry that forwards to `AgentLoop` (`_RunHost`) |
| `ToolCallingLoop.run`'s own while-loop | `custom_agent.*` import paths: `sys.modules` aliases of `job_agent.workflow.*` (same objects, same ORM tables); `custom_agent.loop.AgentLoop` = `AnalysisWorkflow` |
| `custom_agent.loop.AgentLoop` as a separate executor (M3) | `/runs` and `main.py` result contracts |
| Private pools and startup recovery in `TaskLoop`, `AgentTaskScheduler`, `InterviewQueue`, plus the `ApplicationLoop` recovery call (M4 / M5) | Dedicated resource threads, each registered with its role |

## Stage evidence

| Stage | Report | Key result |
|---|---|---|
| M0 | [`unified-loop-m0-baseline.md`](unified-loop-m0-baseline.md) | Baseline `158e557`, entry inventory |
| M1 | [`unified-loop-m1-validation.md`](unified-loop-m1-validation.md) | Host contract; invalid / truncated calls never run; Treg close; one API-first switch; full suite 2176 / 0 failed at `37d7455` (raw log saved) |
| M2 | [`unified-loop-m2-validation.md`](unified-loop-m2-validation.md) | SessionHost; 116 + 116 parity tests, 58 = 58 decisions all inside AgentLoop; full suite 2301 / 0 failed at `c9c803a` (XML) |
| M3 | [`unified-loop-m3-validation.md`](unified-loop-m3-validation.md) | `AnalysisWorkflow`; L3 opening false positive fixed with a strict span rule (two review rounds); full suite 2339 / 0 failed at `53a3c86`; one approved paid L3 full sample `awaiting_review` (2 attempts, 2,413 / 6,855 tokens) |
| M4–M5 | [`unified-loop-m4-m5-validation.md`](unified-loop-m4-m5-validation.md) | One `ExecutionService`; shutdown drains before resources (two review rounds); one regression found and fixed |
| M6 | [`unified-loop-m6-validation.md`](unified-loop-m6-validation.md) | Identity mapping; coverage dry-run with independent expectation, truncation and omission counterexamples, interview sample, WAL-safe snapshot |
| M7 | this report | Legacy decision paths removed; AST architecture test |

**Final single-version full suite: NOT YET ACCEPTED.**
- **The `fc5dc79` run hung.** It stopped at 503 results (about 20 %) in `test_career_flow.py::test_discovery_score_documents_application_and_interview_share_one_task`: process alive, CPU flat, no log growth for more than 25 min.
- **Diagnosis from the read-only process check plus an isolated single-test reproduction with `faulthandler_timeout`:** a self-deadlock in `InterviewQueue.start_feedback` → `_execution()` → `bind()`. A non-reentrant lock was taken twice. It was introduced by `9d2f159` and fixed in `e5d6d69` (`RLock` plus a regression test that fails with the old lock). Dump: [`hang-diagnosis-isolated-fc5dc79.log`](../benchmarks/unified-loop-final-20261012/hang-diagnosis-isolated-fc5dc79.log).
- **The hung process was left running for review,** not stopped automatically. Its partial log is kept.
- **Next:**
  1. stop the hung run once approved;
  2. run one clean full suite at `e5d6d69` (or later) with no edits during the run;
  3. sign off only if it passes.

## In-flight tasks and deployment to-dos (not authorized here)

No schema change, so the mapping is the identity. Every in-flight Session state resumes on the shared kernel; no object needs a legacy owner (M6). Before deploying:
1. Back up `job_agent.db` (with `-wal` / `-shm`) and `.browser-sessions/`.
2. Run `scripts/unified_loop_dry_run.py --source job_agent.db --work <dir> --allow-user-database --report <file>` (it reads a snapshot) and review `coverage_complete`, `manual_submission_unknown` and `history_unchanged`.
3. Deploy.

Rollback means restoring the files and the previous build; there is no migration to undo.

## Remaining non-migration items

- Materials: human style review pending; patch variant not compared live. `MATERIAL_PATCHES=0`.
- API-first B6 business gate (≥2 qualified NYC junior Data Analyst recommendations within 60 calls / 1M input): R6, not started here.
- LinkedIn MCP T0–T2 (R7), source policy (R8), delivery (R9): not started.
- `docs/configuration.md` and README carry edits from other sessions; this stage did not commit them.
