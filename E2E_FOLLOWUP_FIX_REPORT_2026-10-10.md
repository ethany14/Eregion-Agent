# Follow-up fixes after repair verification

Fixes the defects listed in [E2E_REPAIR_VERIFICATION_2026-10-10.md](E2E_REPAIR_VERIFICATION_2026-10-10.md), in the recommended order, and finishes C4 with the decision made in chat: **unresolved Jev requirements go to the main model**. Applied on top of the uncommitted repair work (base `95cfda9`); nothing is committed.

## Result

| Check | Result |
|---|---|
| Full Python suite (real-Chrome tests included) | **1318 passed, 1 failed, 2 skipped** (10 m 39 s). The failure is `test_career_browser.py::…interviews[saved_job]`, which is **intermittent**: 7 of 8 targeted reruns passed, it passed in the previous full run, and it also failed on `95cfda9` in the original baseline. Not caused by these changes. |
| Node frontend tests | **23 / 23** |
| New regression tests (`tests/test_e2e_followups.py`) | **19 / 19** |
| Live: 4 synthetic applicants × real Greenhouse JDs, Jev + resolver | Before: **0 / 64** Jev point scores. After: **every completed analysis produced a point score** (15/15 run 1, 16/16 run 2). Repeat run: **0 main-model calls**, 0.1–3 s, 11/15 identical, 4 within ±5 points. |

## What changed, by defect

### C2: resume structure

| # | Cause | Fix | Verified |
|---|---|---|---|
| D2 | A wrapped date range (`…(Aug 2025 - May 2027` / `(expected)) - In progress`) matched as a header on its first line, and the tail was glued to the **next** degree | `entry_spans` keeps consuming lines while the header has an unclosed `(`; a line starting with `(`, `)` or a lowercase word can't start an entry | Priya: MS ends `May 2027 (expected)` and keeps "In progress, GPA 3.8"; the B.E. is clean |
| D1 | The school split needed the keyword after a capitalized word, so "University of …" failed | `SCHOOL` pattern accepts names that start or end with University / Institute / College / School / Academy / Polytechnic | Daniel: `B.S. in Computer Science / University of Illinois Urbana-Champaign / Aug 2013–May 2017`; also "University of California, Berkeley" and "University of Michigan" |
| D3 | Two-line, company-first and `Title at Company` headers weren't recognized | `two_line_metadata()` handles label line + dated line in either order, deciding title vs employer **only** from explicit company-suffix / title / degree / school words; adds the `Title at Company (dates)` inline form. Lines with no cues stay unowned (no guessing). | 7 layouts split correctly; an ambiguous pair stays unowned |
| — | The PDF repeated each degree line as a bullet | Education bullets containing only header fields are dropped; qualifiers stay | Rendered PDF: Daniel has no duplicate; Priya keeps "In progress" |

Files: `job_agent/resume_layout.py`, `job_agent/pdf_rendering.py`.

### C4: Jev scoring

| # | Cause | Fix | Verified |
|---|---|---|---|
| D4 | The sentence splitter broke on `B.S.`, `e.g.`, `U.S.`; numbered items split after "1."; in-phrase dashes (`$170,000 - $210,000`) were treated as bullets; unknown headings (`Benefits:`) inherited the previous section | Abbreviation/initialism and list-number guard; `-`, `*` and `1.` are bullets only at a line start (or right after a sentence end, colon or heading in flattened text); any `Label:` heading starts a new section; headings may be followed by a digit | Unit tests for all cases; the existing flattened-JD test still passes; the flat Stripe JD now has the same sections as the structured one |
| Boilerplate | EEO, benefits, salary and company text was scored as "unknown **required**", widening every range | `boilerplate()` marks it as context locally (no paid question): non-requirement sections (Benefits, Compensation, Salary range, About us, Equal opportunity, …) plus EEO/benefit phrases | Stripe JD: 13 company/team units marked context in both formats; no real requirement marked |
| Core gap | Jev leaves uncertain requirements unknown, so wide intervals and no score | **New `job_agent/jev_fit/resolve.py`**: after Jev's passes, only still-`unknown` requirements go to the main model in **one structured call per job** (see the rules below) | 4 resolver unit tests + an end-to-end service test; live results below |
| Drift | Jev's uncertain answers expire after 5 min, so the resolver would re-ask and drift (Maya × Lyft 67.9 → 50.0) | Resolver decisions are persisted 24 h (`resolver_decisions` table in the Jev cache file), keyed by resolver code + main-model settings + evidence + requirement | Run 2: 0 main calls, scores reproduce |
| Quote mismatch | The model echoed PDF bullet glyphs differently (`\x07` vs `\x7f`), so valid quotes were rejected | `locate()` normalizes only bullet/control glyphs, curly quotes and dashes with a 1:1 character map; every word must still match exactly | Maya × Stripe DA went from `[40.5–59.5]` to **54.76** (7/7 resolved); a changed number or a paraphrase is still rejected |
| D7 (★) | Browser contexts had no locale, so Chrome used the OS locale (zh-CN) and LinkedIn served Chinese text | `context_options()` sets `locale` + `Accept-Language` on both context-creation sites; default `en-US`, override with `JOB_AGENT_BROWSER_LOCALE` | Real Chrome: `navigator.language` was `zh-CN`, now `en-US` |
| Cache lock | Concurrent first analyses on a new cache file raised `database is locked` (2/2 live runs) | WAL is switched once per file per process under a lock; `busy_timeout` set on every connection | 16 concurrent live analyses on fresh caches: **0** lock errors |

Resolver rules:
* Every *matched/partial* verdict must quote the resume verbatim, or the requirement stays unknown.
* Non-requirements are dropped; personal conditions become *needs confirmation*.
* A failed main-model call keeps Jev's honest interval.
* The score is recomputed with Jev's existing formula.
* Decisions are tagged `resolved_by: main_model`, and usage appears as a `jev_fit_resolver` routing entry.
* `TYPESAFE_FIT_RESOLVE_UNKNOWNS=false` restores Jev-only behaviour.

Files: `job_agent/jev_fit/core.py`, `resolve.py` (new), `service.py`, `settings.py`, `projection.py`, `cache.py`, `api/services/fit_analysis_service.py`, `agent_runtime/auto_apply/browser.py`. Docs: `docs/configuration.md`, `docs/jev-benchmark.md`.

### Loop, ownership and uploads

| # | Cause | Fix | Verified |
|---|---|---|---|
| D6 | The repeat warning was hashed into the archive ref, so identical data looked unread | `ContextArchive.tool_result` builds the ref from the result without `progress_feedback`; the warning is still shown to the model | Maya-pattern repro: 1 ref (was 2); stops after 8 calls (was 11; 30/30 on `95cfda9`) |
| D5 | A run owned by a **deleted** conversation blocked its job forever | `owner_active()` treats deleted, cancelled or trashed owners as gone. Reopening the job (`open_application_url` / `start_application`) adopts the run, but not while it's still executing. Every other cross-conversation write is still refused. | Unit tests: live owner blocks; deleted / cancelled / trashed owner adoptable; executing run refused |
| D8 | A required generic upload ("Attachments") wasn't recognized as the document slot | `document_kind` treats a **required** generic file field as the resume slot; optional extra-document fields don't create an obligation | Unit test |

Files: `agent_runtime/request_context.py`, `agent_runtime/career/harness.py`, `agent_runtime/auto_apply/autofill.py`.

## Live scoring after the fix

Synthetic applicants from the original test × the same real Greenhouse JDs. Run 1 used a fresh cache; run 2 is a new process on the same cache.

| Applicant | Pair | JD form | Run 1 | Run 2 | Main calls (run 1 / run 2) |
|---|---|---|---:|---:|---|
| Maya | Stripe Data Analyst | structured | lock error* | 52.38 | – / 1 |
| Maya | Stripe Data Analyst | flat | 50.00 | 50.00 | 1 / 0 |
| Maya | Lyft Data Analyst GTM | structured | 53.57 | 57.14 | 1 / 0 |
| Maya | *mismatch:* Stripe Backend/API Eng | structured | 21.43 | 25.00 | 1 / 0 |
| Daniel | Stripe Backend/API Eng | structured | 71.88 | 75.00 | 1 / 0 |
| Daniel | Stripe Backend/API Eng | flat | 66.67 | 66.67 | 1 / 0 |
| Daniel | Databricks Sr SWE Web Platform | structured | 44.44 | 44.44 | 1 / 0 |
| Daniel | *mismatch:* Discord Product Designer | structured | 11.54 | 11.54 | 1 / 0 |
| Priya | Stripe MLE | structured | 25.00 | 25.00 | 1 / 0 |
| Priya | Stripe MLE | flat | 35.71 | 35.71 | 1 / 0 |
| Priya | Databricks Sr Applied MLE | structured | 43.33 | 43.33 | 1 / 0 |
| Priya | *mismatch:* Reddit Sr Business Analyst | structured | 35.00 | 35.00 | 1 / 0 |
| Lucas | Databricks Sr Product Designer | structured | 34.09 | 34.09 | 1 / 0 |
| Lucas | Stripe Product Designer | structured | 26.19 | 30.95 | 1 / 0 |
| Lucas | Stripe Product Designer | flat | 50.00 | 50.00 | 1 / 0 |
| Lucas | *mismatch:* Stripe MLE | structured | 25.00 | 25.00 | 1 / 0 |

\* Before the cache-lock fix. After it, two further fresh-cache runs of 8 pairs each had 0 lock errors.

Cold latency is 15–90 s per job (the resolver call dominates). Cached reruns take 0.1–3 s. The 4 small run-to-run changes come from Jev itself answering one previously uncertain question differently after its 5-minute uncertainty expiry, not from the resolver.

## Known limits (not hidden)

* **Format sensitivity remains.** A flat JD still yields fewer requirements than the structured one (Lucas × Stripe Designer: 50.0 flat vs 26–31 structured; Daniel × Stripe: 66.7 vs 72–75), because flattened text without punctuation forms longer compound units.
* **Mismatch separation is weaker than the pure main-model scorer.** Mismatches score 11–35 here vs 3–15 with the main-model pipeline. Priya × a Senior Business Analyst role scores 35: her SQL and Python count as partial.
* **Resolver quality isn't validated against human labels.** Quotes guarantee grounding, not correct judgment.
* **Cost:** each cold job adds one main-model call (typically 2–13 requirements). Cached for 24 h per resume + requirement.
* **Interview browser test:** intermittent (1 in 8 locally); pre-existing.
* **Long real-site conversations** (LinkedIn/Indeed searches, materials, interview end) were not re-run with the real model after these fixes.
