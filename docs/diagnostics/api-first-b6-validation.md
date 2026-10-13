# R6 · API-first B6 business gate (2026-10-12)

Plan: [`claude-unified-execution-plan-20261012.md`](../specs/claude-unified-execution-plan-20261012.md) §9; gate: [`r1-r2-api-first-gate-amendment-20261012.md`](../specs/r1-r2-api-first-gate-amendment-20261012.md). Executor: Claude. The old browser-first B6 (L4, failed) is kept as history and was not rerun.

## Gate and node

`tests/test_api_first_b6_live.py::test_api_first_b6` (`111218a`):
- **Same as the original browser-first node:** the synthetic analyst, "junior data analyst in New York", the harness (`settle_live`) and the `evaluate_search` assertions:
  - at least 2 qualifying recommendations;
  - full JD retrieved, seniority / location checked, formal score, explicit recommendation;
  - persisted, with URL and score in the final reply;
  - no application, no schedule;
  - usage complete with 0 unknown.
- **Only the source sentence of the task changes**, to the amendment's wording (offline test: `test_goal_drops_the_browser_first_instruction`).
- **Flags for the run:** `JOB_AGENT_JOB_API_FIRST=1`, `JOB_AGENT_TREG_ENABLED=1`, provider `crawl4ai` (chosen in the earlier provider comparison), Crawl4AI scrape on.
- **Model caps:** 60 main calls, 1M input, 60 total provider attempts.
- **Treg caps:** pinned below the remaining authorized Treg batch.

## Budget before each run

| Item | Authorized | Used before | Remaining |
|---|---|---|---|
| Treg batch | $0.10 / 20 requests | 15 calls, $0.004, 0 unknown (handoff record) | 5 requests before run-1 |
| Model, per B6 run | 60 main calls, 1M input, 60 provider attempts | — | Per run; under the user's standing approval of paid runs |

## R6 offline source chain

Existing coverage is reused (`test_treg.py`, `test_integrated_p3.py`, `test_board_directory.py`, search fallback / runtime suites): normal search, no results, page dedupe, missing JD, timeouts and network errors, unknown cost, idempotent retry, disabled API, caps.

Gaps added in `tests/test_r6_api_first_sources.py` (`b96d78b`, `ab81067`):
- Crawl4AI partial / blocked coverage is reported, not hidden;
- a blocked LinkedIn search counts as a blocked source;
- a scraped posting marked closed is reported and not re-read elsewhere;
- with no Treg key, API-first uses the free boards and never calls Treg;
- per-task evidence is isolated;
- plus the run-1 fixes below.

## Run-1 (`111218a`): FAILED

Evidence: [`run-1/`](../benchmarks/api-first-b6-20261012/run-1) (`invocation.json` with HEAD and flags, `summary.json`, `transcript.json`, `acceptance.json`, `treg-ledger.json`) plus [`run-1.xml`](../benchmarks/api-first-b6-20261012/run-1.xml) / [`run-1.log`](../benchmarks/api-first-b6-20261012/run-1.log).

| | |
|---|---|
| Result | `needs_input` / `no_progress` after 20 main calls, 191 s. Acceptance failures: `loop_not_completed_cleanly`, `fewer_than_two_verified_scored_qualifying_recommendations` (0 qualified) |
| The one scored job | DoorDash "Data Analyst, In-Store", score 37.14, **correctly excluded** (2+ years, no junior designation) |
| Model usage | 27 provider attempts, all completed, 0 retries, 0 unknown; 230,109 input / 15,026 output. Agent 20 calls 212,955 / 13,272; JEV fit 7 calls. Within caps |
| Treg | 2 operations (scrapes), both succeeded, $0.0003 confirmed, 0 unknown, ledger complete |

**Offline attribution** (stopped, not rerun automatically):

1. **Defect: an invalid board URL failed every later search.**
   - From the third directory page on, `JobDiscovery.search_directory` raised in `job_key` on a posting URL that is not public HTTPS ("Use a public HTTPS job page without embedded credentials."). Every later `search_jobs` returned that error, and the no-progress guard stopped the run.
   - Replayed with free public board GETs (no model, no Treg): pages 0–1 fine, **page 2 raised at `discovery.py:282`**.
   - Fixed in `ab81067`: invalid URLs are dropped and counted (page 2 now: 1 job, 1 dropped). Tests: `test_directory_dedupe_drops_an_invalid_board_url_instead_of_raising`, `test_one_invalid_board_url_does_not_fail_the_search`.
2. **Coverage gap: LinkedIn was never consulted.**
   - With API-first on, the Treg LinkedIn search ran only when the directory returned *nothing*. Here it returned 1–2 jobs per page (none junior), so the only broad source was never used.
   - Fixed in `ab81067`: fewer than 3 directory jobs triggers one Treg supplement per query / location per user turn, merged and deduped. Tests: `test_thin_directory_gets_one_merged_treg_supplement_per_query`, `test_enough_directory_results_do_not_spend_on_treg`.
3. **Not a defect:** the qualification check excluded the non-junior role correctly. No threshold was changed.

Offline after the fixes: source suites 212 passed / 1 skipped; directory / P3 / career 75 passed / 1 skipped.

## Run-2 (`afa9b1f`, Treg attempts capped at the remaining 3): FAILED

Evidence: [`run-2/`](../benchmarks/api-first-b6-20261012/run-2), [`run-2.xml`](../benchmarks/api-first-b6-20261012/run-2.xml), [`run-2.log`](../benchmarks/api-first-b6-20261012/run-2.log).

| | |
|---|---|
| Result | `completed` cleanly in 58 main calls / 600 s with an honest no-match report. Acceptance failure: `fewer_than_two_verified_scored_qualifying_recommendations` (0 qualified, 0 imported). Loop, budget, usage, no-application and no-schedule checks passed |
| Model usage | 58 provider attempts, all completed, 0 retries, 0 unknown; 674,855 input / 40,437 output (within 1M input / 60 attempts) |
| Treg | 3 operations: 1 Crawl4AI LinkedIn search ($0.00045) + 2 scrapes ($0.00015 each). All succeeded, $0.00075 confirmed, 0 unknown. **The authorized Treg batch is now used up: 20 / 20 requests, $0.00505 of $0.10** |
| Agent's report | Directory: 31 boards checked, 3 postings read. None was a junior NYC role (CX Data Analyst; NYT Senior Analyst; Stripe Data Analyst, NYC with no junior evidence). LinkedIn leads (e.g. Associate Data Analyst at Research Foundation CUNY) were found but not verified: `browser:www.linkedin.com` was blocked (HTTP error) |

**Offline attribution:**

1. **The fixes work.** The thin directory now triggers the Treg LinkedIn supplement (10 LinkedIn ids in state), and no search failed on invalid URLs.
2. **The LinkedIn JDs could not be read.**
   - Three LinkedIn postings were attempted. The 2 paid scrapes returned HTTP 200 but were not accepted as a complete matching JD, so the read fell back to plain HTTP. The third exceeded the Treg attempt cap and fell back to plain HTTP too, which LinkedIn blocks.
   - **Why the scrapes were rejected cannot be determined from the saved evidence:** the verdict was not stored. A Treg idempotent replay would return it at $0 but is a request beyond the authorized batch, so it was not made.
   - Fixed for the future in `a599ca3`: every paid scrape now records `status`, `failed_checks`, length and `operation_id` in task state (`treg_scrape_verdicts`). Test: `test_every_paid_scrape_records_its_verdict`.
3. **Free-board coverage is thin** for "junior data analyst, New York": in both runs the directory surfaced no junior NYC posting. Qualification rules were not relaxed.
4. **Efficiency note:** 13 of the last 24 actions were `read_context`. It is within caps but expensive (675K input). To review in R8 / R9, without changing evaluator thresholds.

## Status: R6 business gate FAILED (2 bounded samples); group stopped

- The gate needs at least 2 qualifying recommendations; both samples produced 0. This is **not** reported as passed, and the old browser-first failure is unchanged.
- **Blocking on budget:** another live sample needs Treg budget beyond the exhausted batch, at least about 1 search plus N scrapes, roughly $0.0005–$0.002 per sample at observed prices. Without new Treg budget, a run could only use the free boards, which surfaced no qualifying NYC junior role in two runs. That needs the user's decision.
- **Possible next levers,** none of them threshold changes:
  - a Treg scrape verdict replay or re-scrape once budget exists, to fix whatever rejected the LinkedIn JDs;
  - LinkedIn MCP for JD reading (R7, which needs an explicit account / login authorization);
  - widening the board directory for NYC data roles (free public GETs).

Total R6 live spend: model 85 attempts, 904,964 input / 55,463 output (dollar cost unknown); Treg 5 operations, $0.00105 confirmed, 0 unknown.
