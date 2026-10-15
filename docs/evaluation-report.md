# Eregion evaluation report

[Home](../README.md) · [Configuration](configuration.md) · [Architecture](agent-loop.md)

A summary of how Eregion has been tested from October 9 to October 14, 2026, and
what the tests showed. It condenses the maintainers' dated test reports, which
hold the commit hashes, raw measurements and usage ledgers and are kept locally
rather than published. Failures are reported as they happened, and no earlier
result has been re-scored under a later rule. Related published docs:
[architecture](agent-loop.md), [Jev and performance](jev-benchmark.md) and
[configuration](configuration.md).

## At a glance

| Area | Where it stands |
| :-- | :-- |
| Agent architecture | One autonomous loop for chat, applications and sessions. Migration accepted offline; full suite green when merged. |
| Job sources | Public company boards (118 verified) plus LinkedIn through a local MCP server, by default. Treg optional. Indeed refused third-party clients. |
| Job search and recommendations | Tiered results (priority / worth trying / needs confirmation). Latest scenario runs: 0 structural errors across 123 shown jobs. Tuning closed by the owner on 2026-10-14. |
| Fit scoring with Jev | Three jobs scored in 2.0 s cold and 0.15 s cached. The human-labelled accuracy set is still pending review. |
| Applications and browser | Mock-site flows pass in real Chrome, including review, remember and submit, and browser takeover. Real employer logins need the user. |
| Materials | Claims are checked against the resume, and the verifier was repaired. Human style review not done. |
| Interview practice | First answers were too slow (p50 110 s). Feedback now runs in the background, and a real-Chrome check passed. |

## How Eregion is tested

- **Synthetic applicants only.** Four made-up resumes cover different roles,
  levels and places: a junior data analyst in New York, a senior backend
  engineer for remote US, a machine-learning intern in California, and a junior
  UX designer in Austin. No real candidate data is used.
- **Offline suites first.** Every change runs against the Python test suite
  (about 2,400 tests) and frozen replays of earlier live runs before any paid
  run.
- **Live runs are capped and approved.** Each live run has fixed limits: 60
  model calls, 1M input tokens, 50 LinkedIn calls and 900 s, unless a larger
  profile is approved in advance. Runs never apply, generate materials or create
  schedules. Every model call is recorded in a usage ledger; unknown usage is
  kept as unknown, and dollar cost is not reported without billing data.
- **Independent checks.** A separate audit model reviews each shown job and the
  final reply. On 2026-10-14 a person reviewed one full scenario set by hand,
  and that review is the reference for result quality.
- **Fixed acceptance rules.** Pass/fail rules are versioned (v1 to v7) and
  written before testing. When a rule changes, earlier results keep their
  recorded verdict.

## 1 · Agent architecture

The runtime was moved to a single `AgentLoop` that every autonomous path shares
(career chat, auto-apply and assistant sessions), in seven stages (M1–M7).
`tests/test_unified_architecture.py` pins the structure by reading the code
itself: only the accounted layer may call a model provider, and no legacy loop
may be imported.

- All stages were accepted offline, and the full suite was green at `10a07ae`.
- Not done: a dry run against a real user database, and deployment.

## 2 · Job sources

| Source | Result |
| :-- | :-- |
| **Company boards** (Greenhouse, Lever, Ashby, Workday) | The directory grew from 4 to 118 boards, each verified through its public API. A matching fix on 2026-10-14 accepts every way boards write a remote-US location; before it, 22 of 23 boards returned nothing for a remote request. |
| **LinkedIn MCP** (local, user-signed-in) | Default source since 2026-10-12. In the first sample, 3 of 3 searches and 3 of 3 job reads succeeded. Calls are budgeted, and the source stops on sign-in or rate-limit problems. |
| **Treg** (optional, paid by the user) | 15 API calls cost $0.004, with zero unknown charges. Spend is capped per call, per task and per day. Off by default. |
| **Indeed MCP** | Sign-in worked, but the server returns 403 “Client not allowed”: only allow-listed clients are accepted. Not used. |

## 3 · Job search and recommendations

This area had the most testing. The target changed once along the way.

### 3.1 Strict target: 10–15 fully qualified jobs (October 12–13)

The first target was 10 to 15 jobs, each confirmed on role, location, seniority
and every personal requirement.

- **16 full live runs, all failed.** The best runs delivered 11–12 jobs that an
  independent reviewer confirmed. One run passed the automatic check but was not
  counted: four of its jobs had hard requirements the candidate did not meet.
- **The cause was supply, not code.** With strict evidence, only about 1 in 7
  New York LinkedIn postings qualified, and the fixed call limits could not read
  enough of them.
- **Usage across the 16 runs:** 889 provider calls and 10.5M input / 1.4M output
  tokens. Three calls had unknown usage, so these totals are a lower bound.
- Fixes from those runs carried forward: batched decisions, a call reserve kept
  for the final reply, location binding on cards, and score parsing.

### 3.2 Changed target: tiered recommendations (October 13 onward)

The owner changed the product goal: show relevant jobs even when not every
requirement is confirmed, and say plainly what is missing. Each result is now
one of three tiers:

| Tier | Meaning |
| :-- | :-- |
| **Priority match** | Role, location and level match, and the resume shows the core requirements. |
| **Worth trying** | Relevant, but a core skill or experience is clearly missing. Each gap is listed. |
| **Needs your confirmation** | A personal fact (GPA, work authorization, start date and so on) or the job's exact level or location still needs confirming. |

The model chooses the tier; the code checks the structure. Each job must have
quoted evidence from the posting, a stretch job must list its gaps, and an
unconfirmed level or location can never be a priority match. There is no
minimum count. The model decides when to stop searching, and the reply must say
what is left unsearched and offer to continue.

### 3.3 Human review (live-set-01)

A person reviewed all 32 items of the first four-scenario set:

- **0 of 23 shown jobs were wrong.**
- **0 of the audit model's 8 “substantive error” flags were upheld.** As a
  result, audit judgments became advice only (acceptance v6).
- **Tiers agreed on 17 of 23.** The disagreements leaned conservative, for
  example senior backend roles placed as "worth trying".
- **Too strict on what to show.** The reviewer wanted near misses shown, such as
  slightly more experience than asked or hybrid instead of remote. Only clear
  mismatches, such as Staff for a senior request, should be filtered out.

### 3.4 Consistency of the job check

The model checking a posting against the request can give different answers on
different calls, even at temperature 0. A borderline verdict now gets a second
opinion, and the more inclusive verdict is kept.

| Measure on the 32 labelled postings | One check | With second opinion |
| :-- | --: | --: |
| Postings whose verdict flipped between repeats | 9 | 3 |
| Agreement with the human labels | 89% | 95% |

### 3.5 Scenario runs after the changes

| Set | Rule | Code change tested | Passed | Shown | Structural errors | Notes |
| :-- | :-- | :-- | :-- | --: | --: | :-- |
| live-set-02 | v6 | Near misses, second opinion | 3 / 4 | 25 | 0 | Designer stopped by the no-progress guard. Backend all from one employer. |
| live-set-03 | v6 | Show by default, looser tiers | 4 / 4 | 32 | 0 | Tiers matched the human labels on 7 of 11. Backend still one employer. |
| live-set-04 | v6 | Posting conditions checked, role judged by main work | 4 / 4 | 36 | 0 | Internship "priority" picks dropped from 4 to 1. |
| live-set-05 | v6 | Remote-location fix | 3 / 4 | 50 | 0 | Backend from 10 employers. Marked failed only because the 6-call audit cap ran out at 20 jobs. |
| live-set-06 | v7 | Audit cap grows with jobs shown; Staff excluded | 1 / 1 | 5 | 0 | Backend only. Staff roles excluded, but the model read 8 of 40 results and stopped. |

What the runs show:

- **Showing:** among the labelled postings, 28 of 29 are now handled the way the
  reviewer wanted. The cost is that two postings the reviewer would hide now
  appear as "needs your confirmation".
- **Tiers:** about two in three match the reviewer, and most misses are one tier
  apart.
- **Replies:** every audited reply was honest about failures and stated
  correctly what remained unsearched.

### 3.6 Known limits (accepted; tuning closed)

- **The model often stops early.** In a dedicated measurement it stopped after a
  single query in 20 of 20 runs. On identical input, the stop audit itself gave
  different verdicts. The same backend scenario has produced 20 jobs in one run
  and 5 in another.
- **Verdicts still vary** a little between calls, even with the second opinion.
- **Some senior roles land one tier low,** for example two Reddit backend roles
  the reviewer called priority matches.
- **The audit model is not a reliable gate** and is used for advice only.

## 4 · Fit scoring and Jev

| Recorded run (synthetic resumes) | Requests | Time |
| :-- | --: | --: |
| Main model only, cold (2026-10-09) | — | 32–49 s |
| Three jobs scored separately with Jev, cold | 15 | 4.6 s |
| Three jobs in one Jev batch, cold | 7 | **2.0 s** |
| Same batch again from the local cache | 0 | **0.15 s** |

- The batch used 47% fewer tokens than separate requests. The batch size limit
  was later raised from 8 to 16, which cut Jev calls for 4 jobs from 18 to 11.
- **Not yet measured:** scoring accuracy. A labelled set (6 applicants × 12 real
  postings) is built, but its 96 human reviews are pending, so no accuracy
  figure is claimed.
- A cross-job resolver batch took 89 s against a 60 s target. Performance work
  was paused at the owner's request.

## 5 · Applications, browser, materials and interviews

From the A–F acceptance matrix (2026-10-11) and later reports:

- **Pass, in real Chrome on local mock sites:**
  - review, remember and submit, in both checkbox states;
  - URL de-duplication across restarts and sessions;
  - one sign-in shared across applications on the same site;
  - remembering profile fields such as Country;
  - the expired-login banner;
  - taking over the browser after a page change;
  - titles that are never cut mid-word;
  - cancel states;
  - city and state kept together (New York, NY).
- **Needs the user:** applying at real employers through their own logins
  (Workday, Greenhouse, Lever), which Eregion never does on their behalf.
- **Materials:** generated resumes and cover letters are checked claim by claim
  against the source resume.
  - A verifier bug, where an employer requirement was read as a candidate claim,
    was fixed.
  - A live re-check ended at `awaiting_review`.
  - Paragraph-level patches stay off by default.
  - Human style review has not been done.
- **Interview practice:** the first measurement had a p50 of 110 s before
  feedback, against a 30 s target. Feedback is now processed in the background
  in order, and a real-Chrome run passed (15.3 s, with no JavaScript errors).

## 6 · Efficiency experiments (off by default)

Six context-saving variants were compared on a frozen replay of one search,
using the production request format. Every variant kept the same two qualifying
recommendations and identical scoring inputs.

| Variant | Total request characters | Shared-prefix share |
| :-- | --: | --: |
| Baseline | 463,208 | 56.9% |
| Stable tool list | 466,284 | 61.2% |
| Trimmed prompt | 434,319 | 53.2% |
| Structured checkpoint | 458,120 | 58.1% |
| Trimmed prompt + checkpoint | 434,528 | 52.8% |

None is switched on by default; each needs live evidence first.

## 7 · Open items

1. Human review of the fit-label set, which would give the first accuracy figure
   for scoring.
2. Human style review of generated materials.
3. A real-database dry run and deployment of the unified loop.
4. The early-stop habit in search. It is accepted as a known limit; the reply
   always offers to continue.
5. Applying with a real account at real employers, which only the user can do.
