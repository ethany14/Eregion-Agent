# Verification of the E2E repairs

Checks [E2E_REPAIR_REPORT_2026-10-10.md](E2E_REPAIR_REPORT_2026-10-10.md) against the root causes in §7 of [E2E_TEST_REPORT_2026-10-10.md](E2E_TEST_REPORT_2026-10-10.md). Uncommitted working tree on top of `95cfda9`, checked 2026-10-10.

## Summary

The repairs address the right causes and the suite is green: **1300 passed / 0 failed / 2 skipped** (10 m 48 s, real-Chrome tests included) and **node 23/23**, matching the repair report.

* **Correct as reported:** C3, the C1 circuit breaker, alert weekdays, digest text, run ownership, takeover auto-resume, Forge overflow, logo SVG.
* **Fixed but with new defects:**
  * C2: education parsing. "University of …" school names aren't parsed, and wrapped headers move "in progress" to the wrong degree.
  * C4: the new sentence splitter breaks on abbreviations.
* **Not fixed:** the browser locale (and the warning-before-archive ordering, now only mitigated).

| Root cause I identified | Repaired? | Verified how | Verdict |
|---|---|---|---|
| C1-a: repeat guard only warns; no stop outside running applications | ✅ Per-request breaker after 3 stalled steps → `needs_input` / `no_progress` | My scripted repro: HEAD runs 30/30 calls to the budget; repaired tree stops at **4** (identical reads) and **11** (Maya's inspect → read_context ×2 pattern) | **Correct** |
| C1-b: warning written into the outcome *before* archiving → new content-hash ref → re-read looks unread | ⚠️ Not changed (`task_host.py:185` still runs before `:200`, and `loop_engine.py:226`) | Repro still shows the same data under **2 alternating refs**; the breaker only fires because exhausted ranges now return `no_new_evidence` | **Mitigated, not fixed** |
| C1-c: actionable IDs hidden by compaction (interview never ended) | ✅ `live_resources` and per-object compaction keep `mock_interview_id` / `current_question`; resource identity prefers the interview ID | Code review; covered by the passing browser interview tests | Correct |
| C2-a: Jev projection only splits `Title \| Co \| YYYY` | ✅ New `resume_layout.py` | All 4 test resumes now split jobs with correct title, employer and dates (9/9 jobs). Pipe year-only, pipe month-year range, pipe year range and `Title - Co, City (dates)` all split. | **Largely correct**; see defects D1–D3 |
| C2-b: PDF hid education text | ✅ Education bullets rendered | Rendered output includes the degree text | Correct (each degree line now also repeats as a bullet; cosmetic) |
| C2-c: verifier compares with the degraded source | ✅ `unresolved_source_structure` when dated sources collapse | Code review | Correct for collapse; doesn't catch wrong metadata (D2) |
| C3: `pending_documents()` ignores whether an upload field exists | ✅ Requires an observed resume / cover-letter file control (current page or earlier review fields) | 6 cases: no field → `[]`; field now → `['resume']`; field on an earlier page → kept; refresh off → `[]`; Greenhouse resume + cover letter → both | **Correct** |
| C4: line-only JD units, double-confident extraction gate, uncertainty keeps full weight, raw text as cache key | ✅ Sentence/list units with section context, heading-based Required/Preferred, bounded clarification passes, normalized cache keys, interval-aware recommend and alerts (lower bound) | Code review; thresholds unchanged (.85/.15); no silent main-model fallback | Correct direction; see D4. The report itself says complex JDs are still unresolved, which is honest. |
| C4 (★): browser context sets no `locale`, so LinkedIn serves zh-CN pages | ❌ `browser.py` unchanged; no `locale=` on `new_context()` | grep | **Not fixed** |
| Weekdays saved as daily | ✅ `weekdays` field; tool schema derives from `AlertConfig` | Weekday alert checked on Sat 19:00 NY → next run **Mon 13:00 UTC** | Correct |
| Digest "Send continue" | ✅ Digest built from saved count and real stop reason | Code review | Correct |
| Cross-conversation run sharing / cancel | ✅ `origin_task_id`; cancel, reply, continue and duplicate open check ownership | Code review | Correct; see D5 |
| Takeover dropped by auto-resume | ✅ No auto-resume while `pause_requested` / `paused_for_control` | Diff `auto_apply/loop.py:143` | Correct |
| Forge 375 px overflow, logo SVG | ✅ | SVG path now has complete cubic groups | Correct |

## New or remaining defects

| # | Severity | Defect | Reproduction |
|---|---|---|---|
| **D1** | High | **Education with "University of …" names gets no metadata.** The school-split regex in `resume_layout.py:51` needs the keyword *after* a capitalized word, so `University of Illinois Urbana-Champaign` and `University of Michigan` fail, while `Stanford University` works. Daniel's education still has no degree, school or dates. | `B.S. in Computer Science, University of Illinois Urbana-Champaign (Aug 2013 - May 2017)` → heading / org / dates all `None` |
| **D2** | **High (factual)** | **A wrapped education header moves "in progress" to the next degree.** When the date range wraps (`…(Aug 2025 - May 2027` / `(expected)) - In progress, GPA 3.8`), the first line already matches as a header, so the continuation line is prepended to the *next* header (`entry_spans`, lines 66–76). Priya's completed B.E. renders as **"Anna University \| (expected)) - In progress, GPA 3.8 B.E. in Computer Science…"**, and the MS evidence quote loses its in-progress qualifier. This is exactly the in-progress vs completed distinction the product promises to protect. | Priya's real resume PDF; minimal repro in the verification session |
| D3 | Medium | Still unparsed: two-line headers (`Acme Corp, Chicago` / `Senior Engineer, 2021 - Present`), company-first with tab dates, `Title at Company (dates)`. These stay one unowned entry, which the new structure check should now block. The report's claim that line-break headers (换行表头) are covered holds only for wrapped single headers. | `resume_projection()` on those layouts → 1 entry, no metadata |
| **D4** | Medium | **The sentence splitter breaks on abbreviations** (`(?<=[.!?])\s+(?=[A-Z])`): `B.S. Computer Science or equivalent` → `"B.S."` + `"Computer Science or equivalent. 3+ years of Python and SQL."` (two requirements merged, because no split happens before a digit); `Experience with e.g. Kafka` → `"Experience with e.g."` + `"Kafka or Pulsar."`; `U.S.` also splits. An unknown heading such as `Benefits:` inherits the previous section (`Nice to have`). This contradicts the report's claim that splitting won't change a requirement's meaning. | `job_units()` on short sample JDs |
| D5 | Medium | **Ownership never expires.** `require_application_owner()` refuses any run whose `origin_task_id` is a different conversation, even if that conversation was **deleted**. After deleting a conversation, no conversation can apply to that job again. | Code: `harness.py:916-922`, `service.delete()` keeps runs |
| D6 | Low | C1-b ordering (the warning changes the archived ref) is still present; the loop now depends on `no_new_evidence` from range exhaustion to stop | Repro: 2 distinct refs for identical data |
| D7 | Low | Browser `locale` unset → LinkedIn zh-CN on this PC; Chinese UI text still reaches JDs and scoring | `new_context()` in `auto_apply/browser.py:289` and `:373` |
| D8 | Low | A file field with a generic label ("Attachments") isn't recognized as a resume slot (pre-existing) | `pending_documents` case |

## What was not re-verified here

* Long real-site conversations (LinkedIn/Indeed searches, materials, interview end) were not re-run on the real model. As the repair report itself says, the breaker prevents waste but doesn't prove these tasks now finish successfully.
* The repair report's 12-pair live scoring matrix uses its own short synthetic resumes and JDs, not the real Greenhouse JDs from the original test. Its cold Stripe probe still shows `[20–100]`, so Jev point scores on real JDs remain unproven.

## Recommended follow-ups

1. **D2 first:** when a header matched on line *i* is followed by a non-bullet continuation line before the next date range, attach that line to header *i*. Add Priya's wrapped layout as a regression.
2. **D1:** accept school names that begin with the keyword (`University of …`, `Institute of …`, `College of …`).
3. **D4:** protect common abbreviations (`B.S.`, `M.S.`, `Ph.D.`, `e.g.`, `i.e.`, `U.S.`, `etc.`) before sentence splitting; split before digits too; treat unknown `Word:` lines as a section reset.
4. **D5:** treat a run whose owner conversation no longer exists, or is cancelled, as unowned or resumable.
5. **D6 / D7:** add the warning *after* archiving (or exclude it from the hash); set `locale='en-US'` on browser contexts, or make it configurable.
