# Optimization v3 closeout · validation and switch decisions (2026-10-12)

Task: [`docs/specs/opt-v3-closeout-decisions-validation.md`](../specs/opt-v3-closeout-decisions-validation.md) (C1–C4). Baseline and reproductions: [C0](opt-v3-closeout-baseline-20261012.md).

## Evidence types

| Type | Status in this task |
|---|---|
| Mechanism regressions | ✅ Run: `tests/test_opt_v3_closeout.py` (9 tests) plus the full offline suite, 2054 passed, 132 skipped, 0 failed under strict isolation |
| Scripted replays (frozen web, scripted model, offline scoring) | ✅ Run: four-config matrix below |
| Real decision model on frozen web | ⚪ **Not run**: no batch budget was set for this task (spec §1, §7). The entry point and plan are below |
| Full networked B6 | ⚪ **Not re-run** in this task. Last result (2026-10-11, P1b): FAILED, 1 of 2 qualifying |

Character counts are request characters, not tokens or dollars. A scripted model cannot show that a real model will follow the flow.

## C1/C2 changes (correctness, separate from optional optimizations)

| Commit | Change |
|---|---|
| `58c408e` | Offline test isolation: no repo `.env`, fake model endpoint, outside connections fail the test |
| `c9f1ff8` | Evicted reads are restored rather than returned empty; visible ranges are pointed to; partial reads still continue; an identical repeat still trips the host fingerprint. *Also in this commit:* `tool_result` keeps decision fields (`completed_steps`, `failed_step`, `opening_level`, `qualification_evidence`, `seniority_warning`, `score_range` …) inline when a large result is archived |
| `711f35b` | `decide_job` and per-job `decision_status` (pending / recommended / excluded / needs_evidence), bound to the user request and score version; `search_jobs` / `screen_jobs` wait while scored jobs are pending; the no-progress stop lists saved results without a model call |
| latest | Shorter `decide_job` definition and condensed scored-job instruction (same rules); matrix runner |

Requests changed on purpose (field allow-list): every request now includes the `decide_job` tool (493 chars) and, when scored jobs exist, `decision_status` / `reason` / `missing` on `known_results.scored_not_recommended`. Archived tool summaries carry the decision fields listed above. A repeated read can now return content where it used to return nothing.

## C3 · Four-config matrix (post-fix baseline)

All flags set explicitly per config, each in its own pytest process with its own temp/DB start. Runner: `docs/benchmarks/opt-v3-closeout-20261012/run_matrix.py`; raw data: `.codex-runs/opt-v3-closeout-20261012/matrix/`.

| Config | Stage 2 | Stage 4 |
|---|---|---|
| B0 | refs=0, trim=0, stable=0, history=current | verify_and_score=0 |
| B4 | as B0 | verify_and_score=1 |
| B2 | refs=1, trim=1, stable=0, history=checkpoint | verify_and_score=0 |
| B24 | as B2 | verify_and_score=1 |

| Case | Config | Qualified | Status | Decisions | Total chars | vs B0 | Max request | Protected overflow | Scoring inputs |
|---|---|---:|---|---:|---:|---:|---:|---:|---|
| r1 | B0 | 1 | completed | 20 | 967,497 | +0.0% | 57,929 | 12 | same |
| r1 | B4 | 1 | completed | 13 | 601,592 | −37.8% | 54,882 | 8 | same |
| r1 | B2 | 1 | completed | 20 | 870,121 | −10.1% | 48,279 | **1** | same |
| r1 | B24 | 1 | completed | 13 | 539,860 | −44.2% | 47,792 | 0 | same |
| r2 | B0 | 0 | needs_input | 11 | 468,207 | +0.0% | 47,070 | 0 | same |
| r2 | B4 | 0 | needs_input | 11 | 473,853 | +1.2% | 47,332 | 0 | same |
| r2 | B2 | 0 | needs_input | 11 | 429,476 | −8.3% | 45,643 | 0 | same |
| r2 | B24 | 0 | needs_input | 11 | 432,218 | −7.7% | 44,927 | 0 | same |
| r3 | B0 | 0 | completed | 2 | 58,720 | +0.0% | 30,825 | 0 | same |
| r3 | B4 | 0 | completed | 2 | 59,998 | +2.2% | 31,464 | 0 | same |
| r3 | B2 | 0 | completed | 2 | 46,325 | −21.1% | 24,805 | 0 | same |
| r3 | B24 | 0 | completed | 2 | 47,603 | −18.9% | 25,444 | 0 | same |
| correct | B0 | 2 | completed | 11 | 463,208 | +0.0% | 47,068 | 0 | same |
| correct | B4 | 2 | completed | 7 | 286,143 | −38.2% | 46,711 | 0 | same |
| correct | B2 | 2 | completed | 11 | 423,177 | −8.6% | 44,824 | 0 | same |
| correct | B24 | 2 | completed | 7 | 255,364 | −44.9% | 43,036 | 0 | same |
| directory-positive | B0 | 2 | completed | 12 | 503,310 | +0.0% | 46,481 | 0 | same |
| directory-positive | B4 | 2 | completed | 8 | 330,556 | −34.3% | 46,983 | 0 | same |
| directory-positive | B2 | 2 | completed | 12 | 467,080 | −7.2% | 45,606 | 0 | same |
| directory-positive | B24 | 2 | completed | 8 | 293,735 | −41.6% | 43,296 | 0 | same |
| directory-negative | B0 | 0 | completed | 3 | 103,329 | +0.0% | 39,789 | 0 | same |
| directory-negative | B4 | 0 | completed | 3 | 105,246 | +1.9% | 40,428 | 0 | same |
| directory-negative | B2 | 0 | completed | 3 | 85,424 | −17.3% | 34,123 | 0 | same |
| directory-negative | B24 | 0 | completed | 3 | 87,341 | −15.5% | 34,762 | 0 | same |

Business outcomes match across all four configs: r1 has 1 qualifying (Associate still "Level unverified"); correct and directory-positive pass with 2; r2/r3/directory-negative stop honestly. Scoring-input hashes match B0 in every cell.

**B2 r1 protected overflow:**
- One request reached 48,279 characters against the 48,000 soft budget. Its history was already fully trimmed, so the excess is protected content: system 9,697 + tools 12,020 + snapshot 26,562.
- Before closeout, B2 r1 peaked at 47,896 with no overflow. The closeout added 463 characters for `decide_job`, +124 in `history` and +28 in `known_results`.
- B0 r1 already overflowed 11 times before closeout.
- The stage-4 gate in `test_replay_measurements` asserts no overflow when refs are on, so the B2 r1 cell fails that gate; it was measured with the assertion disabled locally (not committed).
- Not trimmed further to pass: stage 2 is at the budget edge on r1, which counts as evidence against enabling it.

## Switch decisions

| Switch | Decision | Basis | Default | Rollback | Remaining risk |
|---|---|---|---|---|---|
| Stage 4 `VERIFY_AND_SCORE` | **Kept off; candidate for real-model check** | Scripted: −34% to −45% chars and 20→13 / 11→7 decisions where jobs are processed; +1–2% where none are; outcomes and scoring inputs identical. Not validated with a real model (P2 mixed it with stage 2) | `0` | Leave unset | A real model may ignore the composite tool or decide worse |
| Stage 2 `SNAPSHOT_REFS` + `PROMPT_TRIM` + `HISTORY_POLICY=checkpoint` | **Kept off; deferred** | Scripted −7% to −21% chars, but protected overflow on r1 at the budget edge. Live P2 showed more `read_context` and 0 recommendations (single sample, mixed with stage 4). The read-restore fix may reduce the read churn, which is unproven | `0` / `current` | Leave unset | Prompt rewrite comprehension unproven; budget-edge overflow |
| Stage 2 `STABLE_TOOLS` | Kept off | Existing offline coverage only; no cache benefit measured | `0` | — | — |
| Router reasoning `low` | Not adopted | P3: no outcome gain | unset | — | — |
| Writer `medium` | Not adopted in this task (spec §7.5) | P5 candidate (−22% reasoning) | unset | — | Needs more samples and style review |
| Scoring / verifier reasoning | Not changed | Needs A3 labels and a positive/negative verifier set | unset | — | — |

## C4 · Real-model entry point (prepared, not run)

**Lane:** the existing opt-in test `tests/test_b6_offline_replay.py::test_b6_frozen_web_with_configured_model` runs the real configured decision model against the frozen web on the `correct` scenario. Scoring stays offline (simulated) and must be reported as such.

```bash
JOB_AGENT_B6_REPLAY_LIVE_MODEL=1 JOB_AGENT_OPT_SNAPSHOT_REFS=0 JOB_AGENT_OPT_PROMPT_TRIM=0 JOB_AGENT_OPT_STABLE_TOOLS=0 JOB_AGENT_OPT_HISTORY_POLICY=current JOB_AGENT_OPT_VERIFY_AND_SCORE=0 .venv/Scripts/python.exe -m pytest -q -s -p no:cacheprovider "tests/test_b6_offline_replay.py::test_b6_frozen_web_with_configured_model"
```

Set the five `JOB_AGENT_OPT_*` variables per group (B0 / B4 / B2 / B24), as in the matrix table.

**Proposed batch** (requires an explicit budget before running):

| Order | Group | Samples | Est. input tokens/run | Est. output/run |
|---|---|---:|---:|---:|
| 1 | B0 | 3 | 120K–250K | 15K–40K |
| 2 | B4 | 3 | 80K–170K | 10K–30K |
| 3 | B2 | 3 (only if 1–2 are clean) | 110K–230K | 15K–40K |
| 4 | B24 | 3 (last) | 70K–160K | 10K–30K |

- **Estimate basis:** decisions 7–20 per run at about 11–12K tokens per request (scripted matrix chars ÷ ~4), plus output from paid P1–P3. Estimates only.
- **Hard caps:**
  - at most 12 runs;
  - at most 3.0M input tokens in total;
  - at most 400K input tokens per run;
  - retries count toward the caps.
- **Stop rule:** stop at once on any mechanism failure (lost result, duplicate side effect, qualification violation, budget breach); fix it offline before continuing. No automatic paid retries.
- **Pricing:** the provider's model is configured in `.env`. The dollar cost needs the account's real price per token and is **unknown** here, so it must come from the bill or locked pricing.
- **Adoption rule:** a group is adopted only if business delivery and qualification accuracy are at least B0's, and whole-task tokens (including retries and failures) go down. With 3 samples per group the result is a candidate judgement, not proof.
