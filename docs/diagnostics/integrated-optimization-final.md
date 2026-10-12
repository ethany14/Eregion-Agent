# Integrated optimization final report — 2026-10-12

This continuation delivers default-off offline implementations and reviewer-ready live lanes. **Live business acceptance remains incomplete.** The single new L1 provider attempt failed with ConnectError; L1–L4 are pending networked review under the existing paid-test authorization. No live B6 pass or monetary saving is claimed.

## Identity and scope

Original workspace HEAD: `92b6055` (handoff document commit), following `1ef8ab0` implementation. The existing modified `docs/specs/optimization-plan-v3.md`, untracked master/Treg/closeout specifications, the concurrently added unified-loop migration plan, and unrelated benchmark directories were preserved and excluded from all commits. The master plan was read, never edited or committed. `.env` values, `tmp/`, historical `.codex-runs/b6-evidence/`, qualification rules, `evaluate_search` and the B6 fixture were not changed.

The original `.git` is read-only: `git add` failed creating `index.lock`. As explicitly permitted by the handoff, commits are prepared in an isolated local review repository using original objects read-only. The final deliverable is a verified bundle; the original branch remains at `92b6055`. No push, deploy or real-user database migration occurred.

## Plan disposition

| Step | Status and evidence |
|---|---|
| P0 | Inherited baseline reconciled; current HEAD/worktree checked. Historical evidence gaps remain described in the baseline report. |
| P1 | Inherited final-request serializer metrics retained; offline P6 comparisons use the production serializer and P1 prefix measurement. |
| P2 | Ashby response reuse offline-passed, default off. P2b cross-source parallelism deferred: no new live confirmation justifying extra concurrency; existing limits retained. |
| P3 | Inherited candidate batches/API-first/source-scope code retained, targeted regressions passed, defaults off. |
| P4 | Inherited fixed Treg endpoints, self-configured credentials, ledger and migration retained; temporary DB tests only. |
| P5 | Inherited real API comparison: 15 calls, $0.004, zero unknown, zero LLM. No new Treg calls. Crawl4AI remains the recommended selection, while release activation stays off. |
| P6 | Scoped context, deterministic state deltas and structured checkpoint implemented behind default-off settings. Seven frozen comparisons preserve scoring inputs and two qualified recommendations. See pi-context-experiments.md. |
| P7 | Artifact/version-bound cover-letter patches, rejection fallback, unchanged-paragraph preservation, verification and restart/cap tests passed. Application-answer patches deferred; human style review pending. |
| P8 | Inherited L0 retained (no cache key adopted). L1 frozen-source behavior repaired; one new attempt network-blocked. B0/B4 comparison and L2/L3/L4 pending. Bounded L3 runner and sequential reviewer commands delivered. |
| P9 | Configuration, README index, sanitized evidence, per-switch decisions and bundle delivered. Full offline results and environment-only exceptions below; live acceptance not claimed. |

## Defaults and decisions

| Switch/capability | Release default | Decision |
|---|---|---|
| BOARD_RESPONSE_CACHE | 0 | Keep off; offline reuse evidence only |
| DISCOVERY_PARALLEL | Not implemented | Defer conditional P2b; use existing limits |
| CANDIDATE_BATCHES | 0 | Keep off pending live business comparison |
| JOB_API_FIRST | 0 | Keep off; independent of Treg |
| TREG_ENABLED / CRAWL4AI_SCRAPE_ENABLED | 0 / 0 | API behavior verified previously; opt-in self-funded usage only |
| TREG_SEARCH_PROVIDER | Explicit selection required | Recommend crawl4ai from P5 sample, no automatic paid activation |
| SNAPSHOT_REFS | 0 | Keep off; old B2 protected-overflow evidence retained |
| STABLE_TOOLS | 0 | Keep off; better prefix but larger raw request in this sample |
| PROMPT_TRIM | 0 | Leading L2 size candidate, not adopted |
| SCOPED_CONTEXT | 0 | Long-resume lossless prototype; frozen sample too short to demonstrate benefit |
| STATE_DELTAS | 0 | Keep off; no aggregate size benefit in this sample |
| HISTORY_POLICY | current | structured_checkpoint is an L2 candidate; original cap unchanged |
| VERIFY_AND_SCORE | 0 | Stage 4 live adoption still pending L1 |
| MATERIAL_PATCHES | 0 | Offline correctness passed; real quality/cost comparison pending |
| Prompt cache key / LLM compaction | None | No implementation/adoption; L0 showed implicit caching; no need for model summaries established |
| Router/scoring/verifier reasoning | Existing settings | Unchanged; no low router reasoning |
| Writer medium | Not adopted | Separate future comparison, human review pending |

Rollback changes only the relevant switches (history to current). Evidence, candidates, versions, costs and pending Treg reservations remain. Deltas are disposable request projections; current database observations reconstruct the baseline. No schema downgrade or deletion is needed.

## Measurements and costs

All seven P6 samples use scripted decisions and simulated scoring: 11 router calls, two qualifying persisted recommendations, identical formal scoring-input hashes, zero protected overflow. PROMPT_TRIM reduces total request characters by 6.24%; structured_checkpoint by 1.10%. These are offline sizes, not token or dollar savings. The combined candidate does not clearly beat prompt trimming alone. Per-request bytes/chars/prefix/read-back counts are in `../benchmarks/integrated-optimization-20261012/p6/`.

New paid activity: one L1 provider attempt, zero completed, one failed, no retry, unknown input/output/cache billing. Ledger retains 29,997 input-token reservation. The recorded zero known usage totals do **not** mean zero billable use. Provider error: ConnectError; pytest attempt wall time 8.80 s; the ledger measured 2.071 s in the failed provider attempt, 0.00034 s queue wait and 0.00320 s persistence. Model dollar pricing and successful task-completion latency are unavailable. No new Treg, summary or separate retry spend occurred. Inherited L0 used six tiny requests (~18.6K input) and reported 98.8% implicit prefix caching; it is not a new measurement in this continuation.

Historical acceptance remains separate: **B6 FAILED (1/2 qualified)**; C16 main-model P6 passed (p50 19.6 s), fast unconfigured; E5 prior P4/P5 samples passed but style review pending; A5 user-paused, not reopened.

## Validation

- P7/application-pack/frozen B6 gate: 52 passed, 1 paid opt-in skipped, 63.28 s.
- Final fixed targeted regression at commit `428ac96` (17 modules named in validation.json): **259 passed, 3 skipped**, 370.97 s. Skips: frozen-web paid model (1), paid L3 full/patch (2). The earlier 16-module run had 254 passed/1 skipped; final regression includes all added boundaries.
- Final boundary gate: 31 passed, 2 paid L3 variants skipped, 26.58 s; includes checkpoint checksum validation and patch-commit crash replay.
- P6 single-variable matrix: 6 passed; subsequent combination: 1 passed. Scoring hashes compared across all seven.
- Full offline suite: **2120 passed, 134 skipped, 9 failed, 4 errors**, plus 4 passing subtests, 1137.91 s. All 13 exception nodes match failures reproduced at original `92b6055`: 4 Chrome setup errors, 4 browser-recovery failures and 5 MCP subprocess failures. Root cause: Windows named-pipe/subprocess `WinError 5`; no new failure nodes. The 134 skip reasons and multiplicities are fully enumerated in validation.json (118 browser opt-ins, 15 live/paid opt-ins, 1 unavailable symlink).
- Full-suite collection preceded the final checkpoint-checksum hardening and added crash/combination cases; the final fixed-commit regression above covers those final changes. The reviewer still reruns the full suite outside the sandbox.

Python 3.13 creates mode-0700 directories with an owner-only Windows ACL inaccessible to the sandbox identity. Initial attempts failed before business tests; the explicit `pytest_workspace.py` runner preserves inherited ACLs for scratch creation. It does not disable `tests/conftest.py`, network isolation, assertions or opt-in requirements. Reviewers should rerun the full suite outside the sandbox using ordinary pytest as requested in the handoff.

## Pending reviewer work

Follow `integrated-live-validation-plan.md` one run at a time: inspect the connection failure, continue the bounded alternating L1 B0/B4 matrix, select a baseline, run L2 single variables, then L3 full/patch pair with human style review, and L4 one full networked analyst B6. Keep all attempts and unknown reservations; stop on correctness/mechanism failure. No additional permission is needed for these previously approved paid lanes. No adoption should be inferred from this offline report.
