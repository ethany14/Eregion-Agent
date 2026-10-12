# Integrated optimization · P0 baseline (2026-10-12)

Plan: [`docs/specs/integrated-optimization-execution-plan-20261012.md`](../specs/integrated-optimization-execution-plan-20261012.md). Implemented by Claude in this session (user instruction: do it directly, hand over to Codex only near the usage limit).

## Code and workspace identity

| Item | Value |
|---|---|
| Branch | `codex/remaining-e2e-fixes-20261011` (not pushed) |
| HEAD at start | `dd065eb6714893a9c45dbe53649f2142f2e3d149` |
| Other-session files (untouched, not committed by me) | `docs/specs/optimization-plan-v3.md` (modified); untracked `integrated-optimization-execution-plan-20261012.md`, `treg-ab-execution-handoff-20261012.md`, `opt-v3-stage-1b-treg-ab.md`, `opt-v3-closeout-decisions-validation.md` |
| Commits | Local commits per completed step (the user allowed commits in this session); no push, no deploy, no real user DB migration |

Key file hashes (SHA-256, first 16 hex):

| File | Hash |
|---|---|
| `agent_runtime/career/decisions.py` | `d34d0c94cd92ebac` (= closeout handoff) |
| `agent_runtime/career/harness.py` | `be4f05150ddb6bcf` (= handoff) |
| `agent_runtime/request_context.py` | `91ff556e730ab797` (= handoff) |
| `agent_runtime/loop_engine.py` | `376f00068eb1d28d` (= handoff) |
| `agent_runtime/task_host.py` | `64742092b1fc39c5` (= handoff) |
| `tests/conftest.py` | `8ac7e42147d07b32` (= handoff) |
| `agent_runtime/career/discovery.py` | `8c9767a7a17de585` |
| `job_agent/model.py` | `240c5cfcb7953746` |
| `agent_runtime/provider_usage.py` | `27a5e124af9e71ec` |

The closeout fixes are unchanged since the handoff (identical hashes), so the closeout's targeted re-check still applies.

## Configuration (names only, no values)

- **`.env` contains:** `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL_ID`, `LLM_TIMEOUT`, `TREG_TOKEN`, `TYPESAFE_API_KEY`, `TYPESAFE_BASE_URL`, `TYPESAFE_CAREER_ENABLED`, `TYPESAFE_DEFAULT_MODEL`, `TYPESAFE_ENABLED`.
- **Not in `.env`:** no `JOB_AGENT_OPT_*` and no `JOB_AGENT_TREG_*`, so all optional switches are at their code defaults.
- **Effective B0:** `SNAPSHOT_REFS=0`, `PROMPT_TRIM=0`, `STABLE_TOOLS=0`, `HISTORY_POLICY=current`, `VERIFY_AND_SCORE=0`. Model and reasoning configuration unchanged.
- **`.gitignore`** ignores `.env`; there is no `.env.example` yet (P4 delivers it).

## Known state carried forward

| Item | State |
|---|---|
| Live B6 | **FAILED** (last P1b: 1 of 2 qualifying). Not changed by offline work |
| C16 | Passed live (P6, p50 19.6 s); fast lane not configured |
| E5 | Live samples passed (P4/P5); human style review pending |
| A5 | User-paused; not reopened |
| Stage 2 / Stage 4 | Off (closeout decisions) |
| Correctness baseline | Decision gate, read restore, stop delivery, offline isolation (closeout) |

## Evidence gaps from the Treg handoff (§1.2), resolved

1. **Skip count 108 vs 132.** The 108 was my counting error: the script dropped pytest's `SKIPPED [N]` multiplicity. Recounted from the same log (`tmp/closeout-full-skips.log`, run at `37a83df` with `-rs`): **132**, all with reasons.
   - 114 Chrome / real-browser opt-ins (`JOB_AGENT_BROWSER_TESTS` and similar);
   - 17 paid / live opt-ins (research, interview latency, cover letter, Jev, provider batch, saved-page replay, frozen-web model lane, configured-model lane, revision lane);
   - 1 platform limit (symlinks unavailable).

   Corrected list: `.codex-runs/opt-v3-closeout-20261012/skip-reasons-corrected.txt`.
2. **B2/r1 matrix record.** It exists at `.codex-runs/opt-v3-closeout-20261012/debug-B2/r1-granular.json`. It was produced with the overflow assertion disabled locally (not committed), so it is a measurement, not a passing standard-runner artifact. The standard runner's B2 result for r1 remains **failed** (protected overflow 48,279 / 48,000). The assertion and threshold are unchanged.

No new correctness defect was found while closing these gaps.
