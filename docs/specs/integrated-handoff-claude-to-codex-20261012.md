# Integrated optimization: Claude → Codex handoff (2026-10-12)

Master plan: [`integrated-optimization-execution-plan-20261012.md`](integrated-optimization-execution-plan-20261012.md) (untracked; from another session, keep as is). Claude implemented P0–P5 and part of P7/P8 in this session and is handing over at its usage limit. **Read the master plan first; this file only says where things stand and what is left.** Base HEAD for your work: `1ef8ab0`.

The user approved **all paid tests** for this plan. There is still no dollar price for the model, so keep within the token caps in [`integrated-live-validation-plan.md`](../diagnostics/integrated-live-validation-plan.md). The Treg API batch is finished ($0.004 used); do not spend Treg money on model tests.

## Done (committed, offline passed unless noted)

| Step | Commit | Evidence |
|---|---|---|
| P0 baseline, evidence gaps resolved | `c36d03e` | `docs/diagnostics/integrated-optimization-baseline-20261012.md` |
| P1 final-request prefix metrics | `73369d2` | `docs/diagnostics/integrated-request-metrics.md`, `tests/test_integrated_metrics.py` |
| P4a–c Treg contract, config, client, ledger, migration 0037, `.env.example`, README, configuration docs | `a48b91a` | `docs/diagnostics/treg-ab-contract.md`, `tests/test_treg.py` |
| P2a Ashby board response reuse (`JOB_AGENT_OPT_BOARD_RESPONSE_CACHE`) | `348800c` | `docs/diagnostics/integrated-board-discovery.md`, `tests/test_integrated_p2.py` |
| P3 candidate batches, API-first, LinkedIn source scope; P4d Treg wiring | `2627171` | `docs/diagnostics/integrated-search-flow.md`, `tests/test_integrated_p3.py` |
| P5 live AnyAPI vs Crawl4AI comparison (**real API**, 15 calls, $0.004, 0 unknown, 0 LLM); fix: trim "Similar jobs" from scraped pages | `e962519` | `docs/diagnostics/treg-provider-comparison.md`, `treg-ab-offline-validation.md` |
| P8 L0 cache-key probe (**real model**, 6 tiny calls, ~18.6K input) | `1ef8ab0` | `evals/cache_key_probe.py`, `.codex-runs/integrated-20261012/l0-cache-probe.json`: provider accepts `prompt_cache_key`; implicit prefix caching already **98.8%** from the 2nd identical request, with or without the key. **Decision: no cache key; prefix stability is what matters** |

## In progress: finish these first

1. **P7 material patches** (`agent_runtime/application_pack/patches.py`, `workflow.py::_patched_revision`, `SharedPackModel.revise_patch`, `JOB_AGENT_OPT_MATERIAL_PATCHES=0`).
   - Status: code written; the existing pack tests pass (48 passed / 2 skipped). **No dedicated tests yet.**
   - Write `tests/test_integrated_p7.py` with a fake model that has `revise_patch`, covering:
     - targeted patch applied, other paragraphs byte-identical;
     - stale hash, duplicate block, unknown block, evidence not in snapshot, `needs_full_revision`, length/schema failure → **fallback to the full `revise_blocks`**;
     - the merged letter still goes through verification (`VERIFYING` → verify);
     - revision count / `max_revisions` respected;
     - flag off → old path;
     - restart replay idempotent.
   - Then write `docs/diagnostics/material-patch-validation.md`.
2. **P8 L1 real router on frozen web: the lane is not usable as built.**
   - Run 1 (B0) stopped: the real model opened `https://www.linkedin.com/jobs/search/...` and 25 other URLs the frozen fixture never recorded. The replay's unexpected-IO guard (designed for scripted runs) failed the test. Log: `.codex-runs/integrated-20261012/l1/B0-run1.log`.
   - Fix the lane, not the model: for `test_b6_frozen_web_with_configured_model` only, make unrecorded URLs return a realistic **blocked / not found** outcome through the existing production errors (e.g. `SourceBlocked`, 404 → `tool_error`) instead of a test failure. Still forbid real network (the conftest guard stays). Keep the scripted replays strict.
   - Then run L1 as planned: B0, B4, alternating, 3 each, per-run caps ≤ 400K input, stop on any correctness regression. Results are recorded automatically via `OPT_LIVE_OUTPUT` (see the test). Report decisions, provider calls, input / cached / output, the wire-prefix share (P1) and acceptance.

## Remaining (master plan order)

- **P6 context experiments** (`SCOPED_CONTEXT`, `STATE_DELTAS`, `structured_checkpoint` history, stable common parts). Offline single-variable comparison first.
  - Use P1 wire metrics.
  - L0 shows the provider caches identical prefixes implicitly (98.8%). So the main lever is keeping the request prefix byte-stable: front trimming and the per-turn snapshot are the known breakers (stage-0 data: first group changes 17/19 in r1).
  - Do **not** add a cache key.
- **P8 L2/L3** after P6 and P7 offline gates. L4 (one full networked B6 with adopted defaults) last.
- **P9** final report `docs/diagnostics/integrated-optimization-final.md`, plus the per-switch adopt / off / defer table and the README / doc index entry.

## Recommendations already decided (keep unless new evidence)

- **Treg:** default search provider `crawl4ai` (same results as AnyAPI at 0.3× the price in the sample); scrape works (5/5 complete after trimming). Release defaults stay off.
- **Stage 2/4:** remain off until L1/L2 evidence.
- **Router reasoning:** no `low`. Writer `medium` stays a candidate (not adopted).

## Rules (unchanged)

- No change to qualification, `evaluate_search`, the raw input caps, or the B6 fixture.
- Don't touch `.env` values (reading through the product's config loader at runtime is fine), `tmp/`, `.codex-runs/b6-evidence/`, or other sessions' spec files.
- Every new behaviour behind a default-off switch.
- Commit locally in small units. If `.git` is read-only in your sandbox, produce a verified bundle. No push, no deploy, no real user DB migration.
- **Sandbox note:** `tmp/` evidence directories have owner-only ACLs; use copies if you need them.
- **Sandbox note:** named-pipe tests fail only inside the sandbox.
- The conftest isolation (`tests/conftest.py`) must stay; paid lanes switch it off only through their explicit `JOB_AGENT_LIVE_*` / `JOB_AGENT_B6_REPLAY_LIVE_MODEL` opt-ins.
- Regression gate: fixed commit and test set, no new failures, every skip with a reason. The reviewer reruns the full suite outside the sandbox.
- Live runs: one at a time; record every attempt; never re-run automatically after a mechanism failure.
