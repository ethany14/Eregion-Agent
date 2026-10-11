# B6 offline replay test (junior data analyst, New York)

## Goal

B6 (`tests/test_remaining_live.py::test_long_real_search_conversations[analyst-...]`) needs a paid
model and live job sites. Three single live runs on 2026-10-11 went 2 recs → 0 → 0, mostly because
Indeed/LinkedIn/ZipRecruiter/Jooble/hiringcafe were blocked by Cloudflare or login walls. A live
run therefore cannot tell whether the agent logic is correct.

Build a **fully offline, deterministic** B6 replay: the real production `CareerService` / `TaskHost`
/ harness / `recommend_job` / completion validation / `scripts/remaining_search_acceptance.evaluate_search`,
with the **web frozen** (recorded pages, search results, board API responses, blocked pages) and the
**model scripted** (tool-call sequences). Zero network, zero provider calls.

## Source evidence (read-only, never delete or rewrite)

- `tmp/remaining-live-analyst-20261011-claude/test_long_real_search_conversa0/` (r1: 2 recommended,
  1 qualified; second job "Associate Data Analyst" rejected by the evaluator's seniority rule)
- `tmp/remaining-live-analyst-20261011-claude-r2/test_long_real_search_conversa0/` (r2: sources
  blocked, same public search six times, no-progress stop)
- `tmp/remaining-live-analyst-20261011-claude-r3/test_long_real_search_conversa0/` (r3: 1 scored,
  board search used, noisy board matches, no-progress stop)
- Each holds `summary.json`, `transcript.json`, `acceptance.json`, `career.db` (full bodies /
  context archive are likely in the db; tool results in history are compacted to context refs).
- Existing fixtures: `tests/fixtures/remaining_runtime_analyst.json`,
  `tests/fixtures/remaining_phase4_analyst_failure.json`; existing replay style in
  `tests/test_remaining_phase4_replay.py`, `tests/test_remaining_search_runtime.py`,
  `tests/test_remaining_search_acceptance.py`.
- Status/background: `E2E_ACCEPTANCE_MATRIX_2026-10-11.md` (Chinese; last three sections are the
  newest B6 records).

## What to build

1. **Frozen web fixture** `tests/fixtures/b6_offline_web.json` (keep it small, target < 300 KB):
   extracted from the r1–r3 evidence — search_jobs results, blocked/login/Cloudflare page outcomes,
   the real GoodApple "Data Analyst" (0-2 years) and "Associate Data Analyst" (preferred 1 year)
   posting bodies, the gainam talent-network page, aggregator listing pages, and the r3 board API
   responses (Datadog/Braze greenhouse, Ramp ashby, Plaid lever). Add **one** clearly-labelled
   synthetic public board posting with explicit junior evidence (e.g. "Junior Data Analyst",
   New York, "1-3 years of experience") so a correct agent path can reach two qualifying jobs.
   Record in the fixture which items are real-recorded vs synthetic. Public job text only; the
   applicant is the existing synthetic `APPLICANTS['analyst']`. No secrets, cookies or tokens.
2. **Fake web layer**: a `JobDiscovery` double (`read`/`search`) and browser double that serve the
   fixture and raise the same production errors for blocked sources (reuse existing test doubles
   where possible). Any unexpected URL must fail the test loudly, never touch the network.
3. **Scripted-model replays** (`tests/test_b6_offline_replay.py`), driving the real loop:
   - **r1 replay**: the r1 tool sequence. Expect: the Associate job's recommendation carries the
     "Level unverified" seniority warning/caveat (fix in `agent_runtime/career/search_policy.py`),
     GoodApple qualifies, evaluator reports qualified_count 1 — i.e. the agent cannot be graded as
     passing on the unverified-level job.
   - **r2 replay**: repeated identical/narrower public searches. Expect the second
     already-seen search to be `no_new_evidence` with board guidance (fix in
     `agent_runtime/task_host.py`), and the run to stop well before the 60-call budget.
   - **r3 replay**: board search for "junior data analyst". Expect only role-matching titles
     (no "Accounts Payable Analyst", no "AI Research Scientist - Data") (fix in
     `agent_runtime/career/discovery.py`).
   - **Correct-path replay**: blocked sources disclosed → board search → read/import/score
     GoodApple + the synthetic junior posting → recommend both → finish_task with URLs and exact
     scores. Expect `evaluate_search(summary,'analyst')['status']=='passed'`, completed status, no
     application runs, no schedules.
   - Assert zero provider usage and zero network in all replays.
4. **Optional real-model lane** in the same file, skipped unless `JOB_AGENT_B6_REPLAY_LIVE_MODEL=1`:
   the real configured model against the frozen web (isolates agent logic from site blocking).
   Implement it, but **do not run it** (it is paid).

Scores: if production scoring needs a model, use the existing offline scoring doubles/fixtures
used by other career tests; do not call providers. Do not hard-code scores into production code.

## Rules

- Production code changes only if a replay exposes a real bug. Then: separate commit, a focused
  regression, and explain it in the report. Never weaken `scripts/remaining_search_acceptance.py`,
  thresholds, budgets, or existing tests.
- Never delete or rewrite anything under `tmp/`. Never run paid/live tests
  (`JOB_AGENT_LIVE_*`, `JOB_AGENT_B6_REPLAY_LIVE_MODEL`). No network access in tests.
- Don't read or modify `.env`.
- Commit on the current branch `codex/remaining-e2e-fixes-20261011` with `git add` of specific
  files only. Do not push, do not open a PR.
- Use `.venv/Scripts/python.exe`. Run the new file, then the full suite
  (`.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`); baseline before this task:
  1770 passed, 131 skipped.
- Append a short section to `E2E_ACCEPTANCE_MATRIX_2026-10-11.md` (Chinese, same style as the
  last sections) recording the offline replay and its results; it does not replace the live B6
  criterion, which stays failed.

## Acceptance

- `tests/test_b6_offline_replay.py` passes offline, deterministic over 3 consecutive runs.
- Full suite passes with no new skips other than the opt-in live lane.
- Fixture provenance (recorded vs synthetic) documented in the fixture and the report.

## Report must answer

1. Which evidence files the fixture came from and its size.
2. For each replay: what it asserts and the result.
3. Any production bug found, the fix, and its regression.
4. Full-suite numbers and the commit hashes.
5. Anything you could not reproduce from the recorded evidence and how you handled it.
