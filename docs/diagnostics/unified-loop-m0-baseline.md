# Unified loop · M0 baseline (2026-10-12)

Plan: [`claude-unified-execution-plan-20261012.md`](../specs/claude-unified-execution-plan-20261012.md) §3, [`unified-loop-migration-plan-20261012.md`](../specs/unified-loop-migration-plan-20261012.md) §5 M0. Executor: Claude.

## Version and workspace

| Item | Value |
|---|---|
| Branch | `codex/remaining-e2e-fixes-20261011` (not pushed) |
| HEAD | **`158e55781c0467fb97d70710471d3444090af596`**: the R1 closeout repair. The branch was fast-forwarded from `92b6055` through `ff0bb6e…57c63ab` (Codex optimization continuation) to `158e557` by importing `docs/benchmarks/r1-closeout-20261012/r1-closeout.bundle` (verified) |
| Code and tests vs `158e557` | **identical**: all 38 files the bundle changes matched the working tree byte for byte (ignoring CR), before the fast-forward |
| Working-tree changes kept (not mine; not committed by me) | `README.md`, `docs/configuration.md`: post-amendment links to the R1 report and adoption table. `docs/specs/optimization-plan-v3.md`: another session. `.env.example` differed only in line endings |
| Untracked, other sessions (untouched) | `docs/specs/{claude-unified-execution-plan, execution-roadmap-linkedin-mcp, integrated-optimization-execution-plan, opt-v3-closeout-decisions-validation, opt-v3-stage-1b-treg-ab, r1-optimization-closeout-and-r2-gate, r1-r2-api-first-gate-amendment, treg-ab-execution-handoff, unified-loop-migration-plan}-*.md` |
| Manifest check | `docs/benchmarks/r1-closeout-20261012/sync-receipt.json` lists the files copied from the isolated checkout. The code paths match `158e557`; the README / configuration differences are the expected post-amendment edits |

## Configuration and adoption (unchanged from R1)

All experiment switches stay at their source defaults `0` / `current`:
- `BOARD_RESPONSE_CACHE`, `CANDIDATE_BATCHES`, `JOB_API_FIRST`, `VERIFY_AND_SCORE`;
- `SNAPSHOT_REFS`, `STABLE_TOOLS`, `SCOPED_CONTEXT`, `STATE_DELTAS`, `PROMPT_TRIM`, `HISTORY_POLICY=current`;
- `MATERIAL_PATCHES`, `TREG_ENABLED`, `TREG_CRAWL4AI_SCRAPE_ENABLED`.

Adopted: the budget-stop delivery of saved results and the material live-lane writer/verifier binding (R1 adoption table). The maintainer `.env` is not modified.

## Known failures and open business gates (kept)

| Item | State |
|---|---|
| Old browser-first B6 (L4) | **FAILED**: 1 qualifying saved, original complete-delivery count 0. No longer blocks migration (gate amendment); not rerun |
| L1 frozen-web real router | Failed on frozen-source coverage; B4 and L2 not run |
| L3 material full (real) | `needs_revision`; the test binding is fixed, the real re-check is pending → **R3** |
| API-first B6 business gate | Pending → **R6 / R9** |
| A5 eight-job performance | User-paused |
| Fast model lane | Not configured, untested |
| Spend ledger | R1 rerun 71 attempts, 741,045 input / 48,953 output (dollars unknown); old L1 reservation 29,997 kept (402,777 / 2.5M). Treg: 15 calls, $0.004, 0 unknown |

Offline baseline evidence reused, since the code is unchanged since R1:
- full suite at `57c63ab`: 2136 passed / 134 skipped / 16 subtests;
- post-repair affected suite: 53 passed / 2 paid skips;
- the 13 historical sandbox-only failures pass in a normal environment.

## Entry points and execution owners (static inventory)

| Entry | Decision / execution path | Owner today | Target |
|---|---|---|---|
| Career chat (`api/career_routes.py` → `career/service.py` → `task_loop.TaskLoop`) | **`loop_engine.AgentLoop`** + `task_host.TaskHost` (+ `career/harness.py`) | TaskLoop threads (`task_loop.py`), recovery on service start | Keep Host; lifecycle → ExecutionService (M5) |
| Auto-apply (`api/auto_apply_routes.py` → `auto_apply/loop.py`, `runner.py`, `worker.py`) | **`loop_engine.AgentLoop`** + `ApplicationHost` (`runner.py:398`) | Auto-apply worker thread; chat-answer recovery (`auto_apply/loop.py`) | Keep Host; scheduling / recovery → M5 |
| Sessions (`api/session_routes.py`, `session_dependencies.py:196`) | **`tools/loop.ToolCallingLoop`**: a separate decision loop; `sessions/coordinator.py` claim / version / events; `tools/model_adapter.py` | Coordinator; `recover_session` route; MCP manager start | SessionHost on AgentLoop (**M2**) |
| Analysis runs (`api/routes/runs.py`, `api/services/run_service.py`, `api/runtime.py:23`, CLI `main.py:50`) | **`custom_agent.loop.AgentLoop`**: a fixed-step runner with human review (a different class with the same name) | RunService | Deterministic AnalysisWorkflow (**M3**) |
| Multi-agent (`api/multi_agent_routes.py` → `multi_agent/scheduler.py`) | SQL claim / lease / heartbeat scheduler thread (`session_dependencies.py:310`) | AgentScheduler thread | Typed jobs under one ExecutionService (**M4**) |
| Interviews (`interview_routes`, `mock_interview_routes`, `career/interview_queue.py`) | Controllers + FIFO queue threads | Interview queue threads | Keep FIFO and binding; scheduling unified (**M5**) |
| Job alerts (`job_alert_routes`, `career/alert_scheduler.py`) | Timer → starts career tasks | AlertScheduler thread | Enqueue only (**M5**) |
| Packs / materials (`pack_routes`, `material_routes` → `application_pack/workflow.py`) | Deterministic writer / verifier, bounded revision | Called in-process (worker thread in workflow) | Deterministic workflow (**M3**) |
| Fit analysis (`api/services/fit_analysis_service.py`) | Deterministic; thread pool for extraction | Caller | Keep (domain service) |
| Background helpers | `analysis_cache` resume warmup pool, career trash sweeper, `loop_model` executor | Process threads | Resource pools, not decision owners |

Model call paths:
- `job_agent/model.py::ProviderCompatibleChatOpenAI` (all LangChain clients; ledger via `provider_call`; P1 wire metrics);
- `agent_runtime/fast_decisions.py` (TypeSafe / Jev HTTP);
- `tools/model_adapter.py` (Session path).

Paid tools: Treg (`career/treg_client.py`, own ledger `external_tool_operations`).

## Defects already visible for M1 (to be fixed in R2)

1. `tools/model_adapter.py`: tool-call arguments that are not valid JSON become `{}` (lines 131–138) and can be executed; finish / stop reason and provider metadata are not carried.
2. `CareerHarness.close()` closes discovery but not the lazily created Treg client.
3. API-first switches change routing and add a snapshot `source_policy`, but the career prompt and tool descriptions still carry browser-first wording. They must come from one configuration.

## Per-stage file scope (planned)

| Stage | Files |
|---|---|
| R2 / M1 | `tools/model_adapter.py`, `tools/loop.py` (invalid-call handling only), new `agent_runtime/host_protocol.py`, `career/harness.py` (close), `career/prompt.py` + `request_options.py` (API-first consistency), tests |
| R3 / M2 | new `sessions/host.py`, `sessions/coordinator.py`, `tools/loop.py`, `api/session_dependencies.py` |
| R3 / M3 | `custom_agent/loop.py`, `handlers.py`, `api/runtime.py`, `run_service.py`, `main.py`, `application_pack/workflow.py` |
| R4 / M4–M5 | `multi_agent/*`, `job_workflow/*`, `task_loop.py`, `career/service.py`, `auto_apply/{loop,worker,runner}.py`, interview queues, alert scheduler |
| R5 / M6–M7 | migrations (copy only), legacy path removal |
