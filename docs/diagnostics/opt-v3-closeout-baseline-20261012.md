# Optimization v3 closeout · C0 baseline and reproductions (2026-10-12)

Task: [`docs/specs/opt-v3-closeout-decisions-validation.md`](../specs/opt-v3-closeout-decisions-validation.md). Done by Claude in this session; not handed to Codex.
Historical status snapshot (not overwritten): [`OPTIMIZATION_STATUS_2026-10-12.md`](../../OPTIMIZATION_STATUS_2026-10-12.md).

## Manifest

| Item | Value |
|---|---|
| Branch | `codex/remaining-e2e-fixes-20261011` (not pushed) |
| HEAD at task start | `f01196b3b70e20ad026290edf352d242bda2543b` |
| Uncommitted, other session (untouched) | `docs/specs/optimization-plan-v3.md` edit; untracked `docs/specs/opt-v3-stage-1b-treg-ab.md`, `docs/specs/opt-v3-closeout-decisions-validation.md` |
| Dependencies | openai 3.13.0, httpx 0.28.1, pydantic 2.13.5 |
| OPT defaults | `JOB_AGENT_OPT_SNAPSHOT_REFS=0`, `PROMPT_TRIM=0`, `STABLE_TOOLS=0`, `HISTORY_POLICY=current`, `VERIFY_AND_SCORE=0` |
| Model configuration | From the maintainer `.env`; not read or echoed. Offline tests use a fake unresolvable endpoint (`tests/conftest.py`) |
| Test set | `pytest.ini` `testpaths = tests`, full collection |
| New artifacts | `.codex-runs/opt-v3-closeout-20261012/` (matrix, skip reasons); tracked runner `docs/benchmarks/opt-v3-closeout-20261012/run_matrix.py` |

Original live evidence (read-only; first 16 hex chars of SHA-256):

| Run | Path | summary.json | transcript.json | acceptance.json |
|---|---|---|---|---|
| P1b | `tmp/paid-p1b-b6-default/` | `1d4acdddf42d91be` | `5d7a52e65ebe7fd1` | `f5aab1948089dfa4` |
| P2 | `tmp/paid-p2-b6-optimized/` | `c0a5db59b8470bfe` | `2795942a064cdf55` | `acbd71ba70854372` |
| P3 | `tmp/paid-p3-b6-router-low/` | `6f1737ec02ce3161` | `f3ada52214b0e985` | `c7edee7090367027` |

The B6 frozen fixture (`tests/fixtures/b6_offline_web.json`) was not rewritten.

## Full-run action counts (from `transcript.actions`, not the capped `history` tail)

| Run | Actions | read_context | search_jobs | read_job | score | recommend | Outcome |
|---|---:|---:|---:|---:|---:|---:|---|
| P1b | 60 | **36** | 2 | 4 | 1 (`score_jobs`) | 4 | 1 qualified, completed |
| P2 | 34 | **18** | 4 | 6 | 1 (`verify_and_score`) | 0 | 0 recommended, no_progress |
| P3 | 49 | 12 | **10** | 5 | 1 | 0 | 0 qualified, no_progress |

The earlier status report quoted read counts from the 24-entry `history` tail (P2: 15). The full action log shows 18 for P2 and 36 for P1b.

## Reproductions (failing first, then fixed)

| # | Live evidence | Minimal reproduction | Root cause |
|---|---|---|---|
| R1 | P2: GoodApple *Data Analyst* scored 44.03 with junior evidence ("0-2 years …") and passed role/level/location/qualification checks, but was never recommended or excluded; the agent kept searching and stopped on no_progress | `tests/test_opt_v3_closeout.py::test_scored_job_is_pending_and_discovery_waits_for_a_decision` | The scored job and its evidence **were** visible (`known_results.scored_not_recommended`, 445 chars). The missing piece was an outcome: there was no exclusion action and no requirement to decide before searching again. Information loss was **not** the cause here |
| R2 | P2: `read_context(ctx-e68c…)` / `(…, offset=0)` returned `offset=8516, content=""` six times | `test_fully_read_but_evicted_reference_is_restored_not_returned_empty` (fails before `c9f1ff8`, passes after) | `context_evidence` keeps about 9K characters of recent ranges. Later large reads evicted the fully read JD, so `read()` saw "already read" and moved its cursor to the end. The evidence became unreachable |
| R3 | P1 / P2 / P3: runs ended on the no-progress stop with a generic message; P1's honest summary was rejected by the absence-claim check | `test_no_progress_stop_delivers_saved_results_without_a_model_call`; absence check: `tests/test_e2e_followups.py::test_absence_claim_check_allows_the_disclaimer_that_denies_it` (`bc6aade`) | The stop message listed nothing saved; the absence regex matched the disclaimer that denies an absence |

Hypothesis from the task (§2): `verify_and_score` decision fields (`completed_steps`, `opening_level`, qualification evidence) are hard to use after archiving.
- **Confirmed in part:** `tool_result` archives results over 5.5K characters and its inline keys dropped those fields. This is now fixed.
- **Not shown to be the cause of R1:** the scored-job evidence reached every request through `known_results`.

## Test isolation (C0.5)

`tests/conftest.py` (`58c408e`) now:
- treats the repo `.env` as empty in every reader;
- sets a fake model config (`https://offline.invalid/v1`);
- disables background resume warmup;
- records any non-loopback socket connection and **fails the test at teardown, even when the code caught the error**.

Explicit live runs (`JOB_AGENT_LIVE_*=1`, `JOB_AGENT_B6_REPLAY_LIVE_MODEL=1`) disable it. Under this isolation the full suite gives 2054 passed, 132 skipped, 0 failed, and no outside connection attempts.

## Baselines for comparison

- **Pre-closeout** (`f01196b`) B0/B2 r1 measurements were taken in a temporary worktree (removed): B0 r1 total 957,736 chars, max 57,286, protected overflow 11; B2 r1 total 862,135, max 47,896, overflow 0.
- **Post-fix** four-config matrix: see [validation](opt-v3-closeout-validation-20261012.md). Correctness fixes and optional optimizations are compared separately.
