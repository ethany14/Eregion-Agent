# Optimization status — 2026-10-12

Plan: [`docs/specs/optimization-plan-v3.md`](docs/specs/optimization-plan-v3.md). Branch: `codex/remaining-e2e-fixes-20261011` (not pushed). Latest commit: `6af794b`.
Offline suite at `af0bf2a`: **2045 passed, 132 skipped (same set as before), 0 failed**.

## Bottom line

**The optimization plan is not finished.** Infrastructure and sources are done. The request and workflow optimizations are built but not validated; they are switched off, and one live sample suggests they may need rework. Reasoning tuning is partial, and scoring/fact-checker tuning is blocked on test data. **No overall cost saving has been demonstrated yet.**

## Status by stage

| Stage | Status | Evidence | Notes |
|---|---|---|---|
| Correctness gate (plan §2.1) | ✅ Done | `19a03b6`, `3b8d062` | Bare requirement lists, inline "preferred" levels, catalogue-aware cache signature, duplicate resume analysis, connection error misread as "reasoning unsupported" |
| 0 · Measurement and budgets | ✅ Done | `1a0d09d`..`6583b3c` | Per-attempt request composition, two-layer history trimming attribution, timing, cache/reasoning shares; per-task budgets cover every provider attempt |
| 1 · Sources | ✅ Done, on | `8b11a10`, `8517884`, `bc6aade` | 71 verified boards (58 Greenhouse, 9 Ashby, 4 Lever); per-family location coverage; ranking; directory paging on repeat; HTTP client reuse and rate limits; Ashby >2 MB read bug fixed |
| 2 · Smaller requests | 🟡 Built, off | `4a150e3`..`5594e27` | Offline: about −9–10% whole-task input. Live P2: about −20% input per call, but more `read_context` and 0 recommendations. Not validated |
| 3 · Reasoning per purpose | 🟡 Partial | P3, P5 | Router `low`: rejected (no outcome gain). Writer `medium`: candidate (−22% reasoning, 80→55 s, 1 sample). Scoring: blocked on A3 labels. Fact-checker: blocked on a positive/negative case set |
| 4 · Fewer round trips | 🟡 Built, off | `9cbe0b0`, `7d32b59` | Offline: decisions 20→13 (r1) and 11→7 (correct path), about −38% input, same outcomes. Live result inconclusive (only tested together with stage 2 in P2) |
| 5 · Retrieval (RAG) | ⚪ Not needed yet | — | Conditional; trigger not met |

## Business acceptance

| Check | Status | Latest result |
|---|---|---|
| B6: two junior data analyst jobs in NYC (live) | ❌ Failing | Best run P1b: 1 qualifying (Graduate Data Analyst, 80.34), clean completion |
| B6 offline replays (r1/r2/r3/correct, directory ±) | ✅ Passing | `tests/test_b6_offline_replay.py`, `tests/test_board_directory_replay.py` |
| E5: cover letter (live) | ✅ Passing | P4 and P5; human style review still pending |
| C16: interview feedback latency (live) | ✅ Passing | P6: p50 19.6 s, ordering check passes |

## Paid runs (2026-10-11, one each, no auto-retry)

| Run | Configuration | Outcome | Router calls / input / output (reasoning) |
|---|---|---|---|
| P1 | B6 default | Fail: 0 qualifying, no-progress stop; exposed directory paging and completion-check bugs | 36 / 460,535 / 28,229 (21,217) |
| P1b | B6 default, after fixes | Fail: 1 qualifying, task completed cleanly | 59 / 938,941 (cached 345,370) / 53,841 (37,696) |
| P2 | B6 + stage 2 recommended + stage 4 | Fail: 0 recommended (a qualifying job was scored but not recommended), no-progress | 34 / 431,044 / 20,708 (12,903) |
| P3 | B6 + router reasoning `low` | Fail: 0 qualifying, no-progress | 49 / 701,102 / 16,777 (9,048) |
| P4 | E5 default | Pass | 4 / 5,012 / 10,285 (9,740), 80.5 s |
| P5 | E5 + writer `medium` | Pass | 4 / 5,018 / 8,142 (7,563), 55.4 s |
| P6 | C16 | Pass, p50 19.6 s | 6 / 5,260 / 7,786 |

Evidence: `tmp/paid-p*/`; details in [`E2E_ACCEPTANCE_MATRIX_2026-10-11.md`](E2E_ACCEPTANCE_MATRIX_2026-10-11.md).

## Problems found and fixed during this phase

| Problem | Fix |
|---|---|
| Directory search only ever covered the top 5 boards; repeats returned the same ones | Paging per role/location per user turn (`bc6aade`) |
| Completion check rejected "a coverage gap, not proof no vacancies exist" | Negated disclaimers allowed; real absence claims still rejected (`bc6aade`) |
| "Graduate Data Analyst" flagged as a junior mismatch | Junior and new-grad treated as entry level (`af0bf2a`) |
| **Offline tests started background resume warmup that called the real model** (possible real spend; caused flaky errors) | `tests/conftest.py` disables warmup by default (`af0bf2a`) |
| Ashby board APIs over 2 MB were unreadable (e.g. OpenAI 13.5 MB) | 40 MB cap for board listing APIs only (`8517884`) |
| Board-search cancellation check read the full task state per downloaded chunk | Throttled to 4/s (`eac1c0a`) |

## Why B6 still fails

1. **Directory coverage:** the boards are mostly large tech companies with very few junior analyst roles in NYC. Austin UX has 0 boards.
2. **Agent decision efficiency** (now the largest cost driver):
   - repeated `read_context` of the same references;
   - qualifying jobs scored but not recommended;
   - runs ending on the no-progress stop.

## Known risks

- Stage 0 reimplemented SDK retries using private OpenAI SDK internals (`_should_retry`, `_calculate_retry_timeout`). Re-run `tests/test_opt_v3_calibration.py` on any `openai` upgrade.
- Stage 2 rewrote the career prompt (13.9K → 8.9K characters). It is checked mechanically only; real-model comprehension is unproven.
- B6 live results depend on site reachability. One run per configuration is observation, not proof.

## Next steps to finish

1. **Fix agent decision behaviour offline** (free): replays built from P1b/P2/P3 recorded web; stop redundant reads, recommend qualifying jobs promptly, finish honestly instead of no-progress.
2. **Re-run B6 several times per configuration** to decide stages 2 and 4 (keep, change or drop).
3. **Adopt writer `medium`** after more E5 samples and human style review.
4. **Unblock stage 3 for scoring and the fact-checker:** A3 human labels (user) and a fact-checker positive/negative case set (Codex task).
5. Grow directory coverage for thin cells (Austin; Workday needs a POST-verified path, a separate decision).

## Waiting on the user

- A3 human label review (96 items)
- E5 cover-letter style review
- #9 real employer login/application
- F1 push / PR
- F3 `tmp/` cleanup

## Not part of this plan

`docs/specs/opt-v3-stage-1b-treg-ab.md` and the uncommitted edit to `docs/specs/optimization-plan-v3.md` belong to another session and were left untouched.
