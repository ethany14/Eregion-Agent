# Optimization v3 closeout · handoff (2026-10-12)

Task: [`docs/specs/opt-v3-closeout-decisions-validation.md`](../specs/opt-v3-closeout-decisions-validation.md). Reports: [C0 baseline](opt-v3-closeout-baseline-20261012.md) · [C1–C4 validation](opt-v3-closeout-validation-20261012.md). Historical snapshot (unchanged): [`OPTIMIZATION_STATUS_2026-10-12.md`](../../OPTIMIZATION_STATUS_2026-10-12.md).

## Result

```
ready_for_treg: true
```

This means the executable baseline is settled: defects reproduced and fixed offline, each switch decided, honest delivery in every stop path. It does **not** mean the optimizations work or that live B6 passes. Treg proceeds on the defaults below, with stages 2 and 4 **off**.

## Gate checklist

| Gate (spec §8) | Met | Reason |
|---|---|---|
| Decision, repeated-read and delivery defects reproduced, fixed and regressed offline | ✅ | R1–R3 in the C0 report; fixes `c9f1ff8`, `711f35b`, `bc6aade`; `tests/test_opt_v3_closeout.py` (fails before, passes after) |
| No known unresolved defect that loses results, duplicates side effects, exceeds budget or violates qualification | ✅ | None known. Stage-4 checkpoint/idempotency and budget tests still pass; the decision gate adds no side effects (it only blocks discovery) |
| Stage 2/4 four-config matrix complete, each switch decided | ✅ | B0/B4/B2/B24 on 6 replays; stage 4 **off** (candidate), stage 2 **off** (deferred), stable tools off |
| Frozen sufficient candidates pass the unchanged two-qualified standard; insufficient/blocked/stop cases are honest | ✅ | `correct` and `directory-positive` pass with 2 in all configs; r1 = 1 with Associate "Level unverified"; r2/r3/directory-negative stop honestly |
| Full networked B6 recorded truthfully | ✅ | Still **FAILED** (last P1b: 1 of 2). Remaining causes: directory coverage (mostly big tech, few junior NYC roles) and live decision behaviour. The decision/read fixes are **unverified on a real model**; not everything is assigned to Treg |
| Deferrals listed, user-paused items not reopened | ✅ | See below; A5 not reopened |
| Handoff identity, defaults, commands, cost basis, open items | ✅ | Below |

## Identity

| Item | Value |
|---|---|
| Branch | `codex/remaining-e2e-fixes-20261011` (not pushed, no PR) |
| Closeout commits | `58c408e` isolation · `c9f1ff8` read restore + inline decision fields · `711f35b` scored-job outcomes / decision gate / stop delivery · `37a83df` shorter tool and instruction + matrix runner · docs commit containing this file |
| Key file hashes (SHA-256, first 16 hex) | `decisions.py d34d0c94cd92ebac` · `harness.py be4f05150ddb6bcf` · `request_context.py 91ff556e730ab797` · `loop_engine.py 376f00068eb1d28d` · `task_host.py 64742092b1fc39c5` · `tests/conftest.py 8ac7e42147d07b32` · `tests/test_opt_v3_closeout.py 5b1989b4f9bfe9f4` |

## Defaults to carry into Treg

All unset, or set as below. Do not enable deferred switches for Treg.

| Setting | Default |
|---|---|
| `JOB_AGENT_OPT_SNAPSHOT_REFS` / `PROMPT_TRIM` / `STABLE_TOOLS` | `0` |
| `JOB_AGENT_OPT_HISTORY_POLICY` | `current` |
| `JOB_AGENT_OPT_VERIFY_AND_SCORE` | `0` (use the granular tools) |
| `LLM_REASONING_*` | unset (no change to router, writer, scoring or verifier) |
| Board directory | 71 verified boards, on |
| Decision gate (`decide_job`, pending-before-search) | on. Correctness fix, not an optional optimization |

Rollback: each optional switch reverts by leaving it unset. The correctness fixes have no flag. Revert the listed commits if ever needed. Turning switches off deletes no evidence, decisions or usage ledger.

## Tests

- **Command:** `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`
- **Result at `37a83df`:** 2054 passed, 132 skipped, 0 failed, no outside connections.
- **Skips, all with reasons:** offline Chrome / real-browser opt-in (~100), paid live opt-ins (`JOB_AGENT_LIVE_*`, B6 frozen-web model lane, Jev, batch performance), and one platform limit (symlinks). List: `.codex-runs/opt-v3-closeout-20261012/skip-reasons.txt`.
- **Matrix:** `.venv/Scripts/python.exe docs/benchmarks/opt-v3-closeout-20261012/run_matrix.py`. It exits nonzero because of the documented B2 r1 protected-overflow gate.

## Cost basis

- This task made **no paid calls** and no Treg, AnyAPI or Crawl4AI calls.
- Character counts are not tokens or dollars.
- The real-model batch plan (C4) has token caps. Its dollar cost is unknown without the account's real pricing.

## Open items

| Item | Status |
|---|---|
| Real decision model on frozen web, B0/B4 then B2/B24 | Prepared, not run; needs an explicit batch budget (C4 plan: ≤ 12 runs, ≤ 3.0M input tokens) |
| Live B6 after the decision/read fixes | Not re-run; FAILED is the last recorded state |
| Stage 2 budget-edge overflow on r1 (48,279 / 48,000) | Recorded; stage 2 stays off |
| Writer `medium`; scoring / verifier reasoning; A3 labels; verifier positive/negative set; RAG | Deferred |
| Directory coverage for thin cells (Austin; Workday via POST verification) | Deferred |
| Private OpenAI SDK internals in the transport-retry loop (stage 0) | Risk recorded; re-run `tests/test_opt_v3_calibration.py` on any `openai` upgrade |

## Next

Start [`opt-v3-stage-1b-treg-ab.md`](../specs/opt-v3-stage-1b-treg-ab.md) with the defaults above. The API batch is capped at $0.10, at most 20 requests at $0.01 each, and that budget is not available for model tests.
