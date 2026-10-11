# Fix plan for the problems that still exist

Current A-F acceptance status, original numbering 1-18, all six polish items and housekeeping: [2026-10-11 acceptance matrix](E2E_ACCEPTANCE_MATRIX_2026-10-11.md). The dated matrix takes precedence over the historical baseline below.

2026-10-11 priority update from the user: defer A5 eight-job cold ≤60s performance optimization; retain its 89.015s failure and original threshold, and do not repeatedly pay to retest it. Requirement classification/accuracy fixes remain in scope. Prioritize the original analyst search (two actual qualifying scored recommendations with consistent final evidence), then C16 real feedback latency, A1/A3 and the remaining A–F matrix. Backend already passed and must not be repeated for fees. The interval-completion production binding regression must pass before another analyst paid run.

## Phase 0: Lock in what is fixed (before more changes)

### 0.1 Commit the current repairs in reviewable pieces · S
* **Problem:** about 40 changed files sit uncommitted in one working tree, from three sessions.
* **Fix:** split into commits:
  1. loop / no-progress / context;
  2. resume layout + PDF + verifier;
  3. upload obligations;
  4. Jev splitter + boilerplate + resolver + cache;
  5. alerts / ownership / takeover;
  6. UI;
  7. tests + docs.

  Exclude `tmp/`, diagnostics databases and the E2E markdown reports unless you want them versioned.
* **Acceptance:** each commit passes `pytest -q` on its own (or at least the modules it touches); CI green on the final one.

### 0.2 Stabilise the flaky interview browser test · S
* **Problem:** `test_career_browser.py::test_default_chat_searches_scores_reviews_applies_and_interviews[saved_job]` fails about 1 in 8 runs; it also failed on `95cfda9`.
* **Evidence:** after `submit.click()` the test waits a fixed 15 s for `.career-interview` to contain the first question; when it fails, the card isn't rendered at all.
* **Cause (*hypothesis*):** after submit, the scripted agent must finish the application wait, call `start_interview`, and the page must poll a new view. Under a loaded machine this exceeds 15 s, or the UI misses one refresh cycle when the task flips `waiting → running → completed` quickly.
* **Fix:**
  1. Log the task's status transitions and the poll timestamps in the failing run to confirm which case it is.
  2. If it's polling: in `web_app/career-chat.js`, refresh the view immediately when a poll sees `interviews.length` change, instead of waiting for the next interval.
  3. If it's only time: wait on the API state (interview exists) before asserting the DOM.
* **Acceptance:** 30 consecutive targeted runs pass.

---

## Phase 1: Real-world verification of the fixed loop (highest value)

### 1.1 Re-run the long real conversations · M
* **Problem:** C1 (step-budget exhaustion in 7 of 11 long tasks) is fixed in scripted tests only. Nobody has re-run real LinkedIn/Indeed searches, materials, interview end and alerts with the real model since the fixes.
* **Fix:** re-run the original E2E scenarios with the harness in the session scratchpad (`run_conv.py`, `edge_cases.py`), offscreen browser, 4 synthetic applicants:
  * the 4 searches;
  * Daniel materials → approve → PDF;
  * interview with an explicit "end";
  * alert run-now;
  * mock ATS sign-up → review stop.
* **Acceptance (all must hold):**
  * no task ends with "Send continue" for normal work;
  * when the no-progress breaker fires, the reply states what was saved and what isn't done;
  * median search ≤ 60 model calls and ≤ 1 M input tokens (was ~105 calls / 1.8 M);
  * the interview "end" produces a report;
  * the alert produces either recommendations or an honest "no verified matches" digest;
  * the mock application reaches `awaiting_review` with 0 submit clicks.
* **If it fails:** keep the transcript and loop runtime JSON; that's the input for 1.2.

### 1.2 Make completion cheaper than re-reading (only if 1.1 still shows loops) · M
* **Cause (*hypothesis*):** with a live model, a breaker *stop* is still a poor outcome. The model re-reads because the current observation lacks a compact "what is already known" summary.
* **Fix:**
  1. `harness.observe()` adds a `known_results` block: jobs with score or interval, materials with status, interview state, and the user's original constraints. These are short and always inline.
  2. When `progress_guard.count == 2`, the next observation includes `must_decide: true` and only offers `finish_task`, `ask_user` and non-read tools for one turn.
* **Acceptance:** the real searches in 1.1 finish with a summary instead of a breaker stop in at least 4 of 5 runs.

### 1.3 Final review → memory → submission chain · M
* **Problem:** since C3 was fixed, no run has gone through `awaiting_review` → approve remembered answers → `confirm_submit` → confirmation / `submission_unknown`.
* **Fix:** extend the mock ATS (scratchpad `e2e_server.py`) with a confirmation page and a "slow / ambiguous submit" mode. Then script:
  1. apply → review;
  2. approve with `remember={...}`;
  3. confirm submit;
  4. apply to a second job on the same site and check that remembered answers (source, gender, certify) are reused or offered.
* **Acceptance:**
  * exactly 1 submit per confirmed review, and 0 without confirmation;
  * the ambiguous mode yields `submission_unknown`, with no resubmission;
  * the second application asks only for genuinely new questions.

### 1.4 Real employer sites (needs you) · S of your time
* **Problem:** real Workday / Greenhouse / Lever / Ashby filling and real sign-in were never exercised. The assistant may not put a synthetic identity into real employer systems or type passwords on third-party sites.
* **Fix:** run with **your own profile** on 2–3 postings you'd actually consider (one Workday, one Greenhouse, one Lever). When Eregion shows the secure account form, enter the credentials yourself, then let the agent fill to the review stop. Don't submit unless you mean to.
* **Acceptance:**
  * every field shown in review matches what's in the browser;
  * the resume is uploaded where a resume field exists;
  * nothing is submitted without your click.

---

## Phase 2: Application orchestration bugs (confirmed, still open)

### 2.1 Duplicate runs from URL variants (cause of the "restart opened a new application" report) · S
* **Evidence:** Maya's conversation `3ca60807` had task status `running` while its child waited, so restart recovery re-queued it (by design, `task_loop.py:99-102`). The model then opened `…/jobs/4021-data-analyst/apply`. Dedup for generic platforms hashes the full URL (`contracts.py:posting()`), so `/jobs/x` and `/jobs/x/apply` became two runs for one job.
* **Fix:**
  1. In `posting()`, for generic / Ashby / SmartRecruiters / iCIMS / Jobvite hosts, strip a trailing `/apply`, `/application` or `/apply/…` segment before computing the identity (keep the original URL for navigation).
  2. In `open_application_url`, if the conversation already links a run whose identity matches, reuse it instead of starting a new one.
* **Tests:** `/jobs/x` and `/jobs/x/apply` give one identity; a reopen in the same conversation returns the same run; a restart with a parent in `running` doesn't create a second run.

### 2.2 "Apply to both in parallel" opened one and claimed both · M
* **Cause:** the model called `open_application_url` once and then `wait_for_result`. No check compares the user's request with the runs actually started, and the reply text is unchecked.
* **Fix:**
  1. Accept `urls: [..] (max 4)` in `open_application_url` (and `application_ids` in `start_application`) so several runs start in one call, subject to `JOB_AGENT_MAX_OPEN_APPLICATIONS`.
  2. Add an `applications` summary (url → run status) to every observation while runs exist.
  3. In `validate_finish` / progress text, reject or annotate a claim of "both / all" when fewer runs exist than the job links mentioned in the current request (use the same URL extraction as `import_job`).
* **Tests:** a two-URL request creates two runs in one turn; a scripted reply claiming both with one run is blocked from completing.

### 2.3 Sibling run keeps a stale account request after another run signs in · S
* **Evidence:** the 4021 run kept `account_request` after the 4022 run registered and verified on the same host.
* **Fix:** when `save_login_state(force=True)` succeeds for `(owner, host)`, mark other unfinished runs for the same owner and host `needs_recheck`. Their worker reloads the stored state into its context (or re-navigates) and re-observes before keeping an account request.
* **Tests:** two runs on one host, sign in on one, and the other leaves `needs_input / account` without new credentials.

### 2.4 Profile facts re-asked on every application (Country asked 3×) · M
* **Cause:** answers given inside an application only become reusable after an approved final review. Profile-type facts (country, city, state, postal code, phone) are never written to the saved candidate profile.
* **Fix:** when a pending field maps to a `CandidateDetails` key (country, city, phone, linkedin, website) and the user answers it in chat, have the parent call `remember_profile` automatically for that key only, and say so ("Saved Country = United States to your details").
  * Sensitive or legal fields (authorization, sponsorship, EEO, consent) stay excluded, as today.
  * The UI "Your details" panel shows the change.
* **Tests:** answer Country once; the next application pre-fills it and doesn't ask; consent and sponsorship answers aren't auto-saved.

### 2.5 Stale parent banner after the account step · S
* **Evidence:** after registration succeeded, the parent `message` still said "sign in or register" while the child asked for verification, then Country.
* **Cause:** the parent's own `input_request` (written during the account wait) isn't cleared when the child's `account_request` changes or disappears; `CareerService.view()` prefers it.
* **Fix:** in `harness.wake()` / `sync`, clear the parent `input_request` if it was created for an account wait and the child's account digest (`wait_token`) changed. In `view()`, prefer the child's current message when the child is in `needs_input`.
* **Tests:** a register → verify → field-question sequence shows the right banner at each step.

### 2.6 Takeover panel error after the page navigates · S
* **Evidence:** typing the code, then Enter, navigated; the panel showed "Browser control could not complete", and `frame` / `end` returned 409.
* **Status:** the auto-resume race was fixed (`paused_for_control` blocks auto-resume). Not re-verified in the UI.
* **Fix:** re-test in the UI. If the error persists, make `browser_control` treat a navigation during `key` / `click` as success (return a fresh frame from the new page) rather than raising.
* **Acceptance:** the verification-code flow completes and "Done · Resume agent" works without an error message.

### 2.7 Interview answers: routing under rapid input, slow feedback · M
* **Evidence:** three quick messages led to the 3rd being filed against Q1 and the 1st dropped. Feedback took 75–256 s per answer.
* **Cause:** routing is left entirely to the model (`answer_interview` needs `message_id` + `question_id`). Slow feedback comes from full main-model evaluation on every answer, plus agent-loop overhead.
* **Fix:**
  1. **Deterministic routing:** while an interview is `awaiting_answer`, the harness binds each new user message, in arrival order, to the current question directly. The model is only consulted when a message is clearly a command ("skip", "end", a question to the coach), detected by a small classifier or the existing control phrases.
  2. **Queue:** messages that arrive while an evaluation runs are held and applied to the next question in order; none are dropped.
  3. **Latency:** evaluate with `LLM_FAST_MODEL_ID` when configured, and show the next question before the full feedback finishes (feedback streams in after).
* **Tests:** three rapid answers map to Q1, Q2 and Q3 in order; "end" mid-queue ends after the queued answers are recorded. Acceptance: p50 feedback ≤ 30 s with the main model, ≤ 10 s with a fast model.

---

## Phase 3: Scoring quality

### 3.1 Build a labelled evaluation set first · M
* **Problem:** resolver and Jev quality are unvalidated; "quotes guarantee grounding, not judgment".
* **Fix:** create `evals/fit_labels_v1.json`:
  * 6 synthetic applicants (the current 4 plus a senior data scientist and a new-grad SWE);
  * 12 real public JDs (3 per field), each in structured and flat form.
  * For each pair, a human labels the requirement list (what counts as a requirement, and its level) and a status per requirement.
  * Add `evals/run_fit_labels.py` to report requirement-extraction precision/recall, status accuracy, score MAE vs labelled score, mismatch-vs-fit separation (AUC), and flat-vs-structured delta.
* **Acceptance:** the script runs offline against cached results and live with `--live`; numbers are recorded in `docs/benchmarks/`.

### 3.2 Format sensitivity (flat vs structured JD) · M
* **Evidence:** Lucas × Stripe Designer scores 50 flat vs 26–31 structured; flat text yields 3–4 requirements vs 7–12.
* **Cause:** flattened text loses line breaks, so `job_units()` forms longer compound units, and the extraction question then classifies whole paragraphs.
* **Fix:**
  1. Add `restore_structure(text)`, run before `job_units()` when the text has few newlines relative to its length. It inserts line breaks before recognised headings, before `•`, and between sentences inside requirement sections, with an offset map back to the original so citations stay exact.
  2. Cap a unit at about 220 characters: split an over-long unit at `;` or sentence boundaries, and at commas only between two clauses that each contain a verb.
  3. Keep conjunctions ("Python and SQL") together, as now.
* **Acceptance (on 3.1's set):** |score_flat − score_structured| ≤ 10 points for ≥ 90% of pairs; requirement-count ratio flat/structured between 0.8 and 1.25.

### 3.3 Mismatch separation / resolver leniency · M
* **Evidence:** mismatches score 11–35 with Jev + resolver vs 3–15 with the main-model pipeline (Priya × Sr Business Analyst = 35).
* **Cause (*hypothesis*, confirm with 3.1):** the resolver awards *partial* for adjacent generic skills (SQL / Python for a business-analyst role), and partial earns half weight.
* **Fix:**
  1. Tighten the resolver prompt: *partial* requires the **same skill or domain** with a concrete shortfall (years, level, scope); generic adjacent skills are *missing*. Require the quote to mention the requirement's key term or a listed synonym.
  2. Add a deterministic check: a *partial* whose quote shares no content word with the requirement text (after a small synonym map) is downgraded to *missing*.
  3. Leave the 0.5 partial weight unchanged until 3.1 says otherwise.
* **Acceptance:** mismatch-vs-fit AUC ≥ 0.9 and mismatch median ≤ 15 on 3.1's set, with fit scores dropping by no more than 5 points on average.

### 3.4 Resolver cost and latency · S
* **Evidence:** each cold job adds one main-model call (15–90 s).
* **Fix:**
  1. In `score_jobs` (up to 8 jobs), send all jobs' unknowns for the same resume in **one** resolver call, keyed per job.
  2. Use `LLM_FAST_MODEL_ID` for the resolver when configured (new `TYPESAFE_FIT_RESOLVER_MODEL=fast|main`, default main).
  3. Skip the resolver for requirements with weight 1 (preferred) when the score interval is already narrower than 10 points.
* **Acceptance:** 8-job batch = 1 resolver call; cold batch wall time ≤ 60 s.

### 3.5 Main-model pipeline (when `TYPESAFE_ENABLED=false`): variance and timeouts · M
* **Evidence:** ±20-point spread across equivalent cold runs; 31–93 requirements per JD (90 for one internship); one 502 at the 120 s request timeout.
* **Cause:** extraction includes duties, benefits, EEO and surrounding page text; per-request timeout under concurrency.
* **Fix:**
  1. Reuse `job_units()` + `boilerplate()` to drop non-qualification text before `job_extraction.py` builds its numbered sentences.
  2. Deduplicate near-identical requirements (normalised text + same source sentence).
  3. On a provider timeout during analysis, retry once with the remaining batches only (not the whole analysis).
  4. Document `LLM_TIMEOUT` ≥ 180 for analysis-heavy use.
* **Acceptance:** spread across 4 equivalent cold runs ≤ 8 points on 3.1's set; ≤ 30 requirements for a typical JD; 0 timeouts in 32 runs at 6× concurrency.

---

## Phase 4: Search coverage

### 4.1 Headless blocked, Indeed Cloudflare, LinkedIn login walls · M
* **Evidence:** headless runs were blocked on LinkedIn and Indeed; offscreen worked for LinkedIn listings, but detail pages were often login-walled; Indeed returned Cloudflare blocks.
* **Fix (no bot-detection evasion):**
  1. **Docs:** mark `JOB_AGENT_HIDDEN_BROWSER=headless` as "may be blocked by major job boards; prefer offscreen".
  2. **Detection:** classify Cloudflare / "verify you are human" / LinkedIn auth walls as `site_blocked` in `browser_evidence`, so the agent switches source immediately instead of retrying. It should tell the user once that they can open Control browser and sign in to LinkedIn themselves; their session is then reused (the persistent login store already supports this).
  3. **Coverage:** extend `search_jobs` beyond Greenhouse / Lever to the public Ashby and Workday CXS JSON endpoints (as used in the test harness) so remote / role searches have a non-browser path.
* **Acceptance:** a blocked board costs ≤ 3 tool calls before switching; a search request with Indeed blocked still returns verified postings from other sources, with an honest coverage note.

### 4.2 Seniority drift (Senior requested → Staff recommended) · S
* **Fix:**
  1. Store requested seniority from the request (junior / mid / senior / staff / principal / intern / new grad) in the task plan.
  2. `recommend_job` adds a caveat (or refuses, if the user said "only") when the posting title's level differs by more than one step.
* **Test:** a "Senior only" request with a Staff posting produces a caveat or refusal.

---

## Phase 5: Copy and small UX

| # | Problem | Fix | Effort |
|---|---|---|---|
| 5.1 | Internal enums leak (`autonomous_driving_software_development`, `needs_review`) | `match_overview` / `job_summary` return `display_name` for gaps and a human label for status; add a post-check that rejects `snake_case` tokens of 3 or more parts in final replies, unless the user asked for IDs | S |
| 5.2 | Chronicle titles truncated mid-word ("…original re is waiting on you") | Truncate on a word boundary with an ellipsis in `web_app` title formatting; don't append "is waiting on you" to a truncated request | S |
| 5.3 | A cancelled *search* labelled "Application cancelled" (`web_app/apply.js:17`) | Use "Cancelled" for conversations without an application run; keep "Application cancelled" for application runs | S |
| 5.4 | Extracted city drops the state ("New York" vs "New York, NY") | In `resume_profile.extract_profile`, keep the full city/region token from the header line when it matches `City, ST` | S |
| 5.5 | Cover letter style stiff and generic | Add 2 style rules to the cover-letter writer prompt (open with the specific role and company problem; avoid "This letter addresses…"); keep the grounding verifier unchanged | S |
| 5.6 | "U.S. Sponsorship is not available." kept as one unit | Treat `U.S.` / `U.K.` followed by a capitalised word as a sentence end when the next word starts a new clause; both are eligibility conditions, so this is low risk | S |

---

## Order and effort summary

| Phase | Items | Effort |
|---|---|---|
| 0 | Commit, flaky test | ~1 day |
| 1 | Real re-run, completion summary (if needed), review → submit chain, your real-site run | 3–5 days + your time |
| 2 | URL dedupe, multi-apply, sibling login, profile facts, banner, takeover, interview routing | 5–7 days |
| 3 | Labelled set, format sensitivity, mismatch separation, resolver cost, main-pipeline variance | 6–9 days |
| 4 | Blocked boards, seniority | 2–3 days |
| 5 | Copy / UX | ~2 days |

Recommended path: **0 → 1.1 → 2.1 → 1.3 → 2.4 / 2.5 → 3.1 → 3.2 / 3.3 → the rest.** Do 1.1 early: its result decides whether 1.2 is needed and re-baselines cost. Do 3.1 before any further scoring changes, so they're measured rather than guessed.

## Explicitly out of scope

* Bypassing CAPTCHA / Cloudflare or other bot detection.
* Submitting applications to real employers with synthetic identities.
* The assistant entering real credentials. The secure account form stays user-operated.
