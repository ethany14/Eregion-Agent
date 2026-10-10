# Response latency audit — 2026-10-09

The largest delays are model round trips and structured extraction, not Python
observation construction. The first optimization keeps the autonomous planner,
full tool catalog, evidence validation, interruption and final-submit boundaries.

## Observed bottlenecks

Read-only inspection of the current local database found 36 recorded career
decisions: median model time 3.758 s versus observation time 0.016 s. Three recorded
score actions had median 69.118 s. An application trace reached 121,131 text
characters in one model request. These are historical records, not measurements
of the new code or a controlled benchmark.

Code inspection found:

- The current observation repeated tool results already sent in the complete
  tool transcript, and each exchange repeated the same user request.
- The career system prompt was 14,790 characters before any tool schemas, live
  state or resume. The catalog has 44 tools with visual tools included.
- Model waiting checked task state every 10 ms; each chat check decoded the
  entire database record twice. This wastes local work while the provider runs.
- Structured extraction generated temporary IDs, repeated reference lists and
  duplicate requirement text which the application can construct itself.
- The UI rebuilt every saved conversation's full documents/interviews every two
  seconds. It also waited for the browser preview before scheduling its next poll;
  a stalled screenshot could add five seconds to that cycle.

## Changes

1. `ConversationWindow.snapshot` replaces only exact duplicate history entries
   with a reference to their retained tool message. Call ID, tool name, arguments
   and result must agree. Legacy, changed and trimmed-out results stay visible;
   persisted history is untouched. Repeated user requests within the same revision
   are emitted once. JSON transport whitespace is reduced.
2. The career prompt is 9,345 characters (36.8% smaller), consolidating repeated
   directions and discouraging unnecessary plan/progress/read calls. The model
   still chooses tools and workflow; no greeting classifier or mandatory router
   was added.
3. Provider waits check active revision about every 100 ms, using one repository
   read. Futures wake immediately when complete; a fresh revision check still
   gates acceptance. Playwright event pumping stays on its owner thread.
4. Compact provider-only resume/JD schemas group evidence under its source and
   atomic requirements under their verbatim statement. Python restores IDs,
   ownership references and `original_text`. Public schemas, normalizers,
   scoring and quote/metadata validation remain in place. Cache fingerprints
   include both compact prompts and schemas. Custom injected analyzers retain
   their existing public schema contract.
5. Active-chat polls use the single-conversation endpoint every 750 ms after a
   response. Full history refreshes every ten seconds or on explicit UI actions;
   idle refresh cadence remains two seconds. Screenshot requests are independent
   and limited to one in flight. Layout, answer drafts and approval controls remain.
6. Existing timing records now include text size, tool schema size/count and
   provider input/output token counts when supplied, without logging raw prompts.

## Live comparison

Configured main model: `muse-spark-1.3-contributor`; Jev was enabled in both modes.
Synthetic data only, temporary databases, real headless Chrome and real model
requests. Two runs per mode, alternating before/after order. Complete fit caches
were disabled and Jev's cache cleared for each scoring trial. Provider prompt
caching was not disabled. These are exploratory samples subject to provider load
and generated-output variance, not production percentile or accuracy guarantees.

| Flow | Before median | After median | Reduction |
| --- | ---: | ---: | ---: |
| Greeting through actual task loop | 2.514 s | 1.067 s | 57.5% |
| Browser open → Jev shortlist → reply | 12.462 s | 11.374 s | 8.7% |
| Cold resume/JD extraction → match | 35.481 s | 31.909 s | 10.1% |

The two browsing runs still used three planner calls each. Median total input
tokens fell from 27,249 to 22,250 (18.3%). Repository reads fell from median
1,045.5 to 151.5; some of that count reduction also reflects different run times.

The controlled fit fixture contains the same six explicit skill requirements in
all four runs. All scored 83.3 with identical match statuses and valid source
quotes. Median resume extraction was 34.160 → 30.085 s, JD extraction
29.261 → 25.432 s, and matching 1.313 → 1.256 s. Extraction runs in parallel, so
these stage times must not be summed.

An earlier exploratory fixture included a responsibilities sentence. The old
extractor omitted it; the compact extractor retained two responsibility items.
That changed six requirements to eight and added a main-model matching fallback.
Its end-to-end times are **not** an equal-work speed comparison. The controlled
table does not use those results. More complete extraction may change existing
scores, and open-ended extraction consistency remains a quality concern.

## Verification

- All 14 existing shared-loop checks passed with `unittest`, including steering,
  retries, worker recovery, complete tool exchanges, waits and visual revocation.
  No pytest was run.
- Targeted checks retained changed/legacy history, preserved complete tool results,
  rejected ungrounded resume evidence and retained two distinct education owners.
  Interruption was observed at 0.113 s in the injected slow-call check. An already
  inactive request was never sent.
- Real-model extraction holdout preserved bachelor's and master's entries,
  disciplines and dates, explicit three-year experience, work-authorization
  confirmation and both responsibilities; verbatim quotes/metadata validated.
- The existing real-model + Chrome two-page application completed five tool actions
  and six model calls, reaching review in 28.27 s with zero submissions. This was
  a functional regression, not an application speed A/B or an external ATS test.
- Current UI in real Chrome showed a new reply in 0.828 s while a deliberately
  four-second preview was still pending. Four single-task polls and zero full-list
  polls occurred in that sample; the composer draft survived with no page errors.
  Desktop/mobile and light/dark screenshots were inspected.
- Changed Python files compiled and scoped `git diff --check` passed.

Results: [machine-readable measurements](benchmarks/latency-2026-10-09.json).

## Highest-value next work

1. **Reuse validated extraction across restarts and prepare it at resume upload.**
   Existing fit caches are process-local. A bounded durable cache must key exact
   source content, owner, schema/prompt and model identity, invalidate on corrections,
   and preserve the same quote checks. Keep source extraction identity separate
   from downstream matching configuration so changing Jev doesn't redo extraction.
2. **Overlap independent job work.** Scoring currently blocks that conversation's
   tool execution. A durable score worker would allow browsing the next job while
   the current one scores. Use bounded concurrency, distinct operation identities,
   cancellation and existing result-wait semantics; never parallelize dependent
   browser mutations simply to reduce latency.
3. **Stream user-facing text and serve lightweight updates.** Current replies
   appear only after a complete model response. Streaming can improve first-visible
   response latency; it does not shorten extraction. Preserve rejection of internal
   reasoning/malformed outputs and only execute complete, validated tool calls.
   Single-task polling still renders that task's full materials; event/version
   updates and a lightweight sidebar would remove the remaining repeated work.
4. **Measure cold/warm and long-conversation p50/p95.** The new counters make it
   possible to separate provider latency, context growth, fallbacks and UI delay.
   A broader extraction-quality set should accompany any further schema changes.

Existing backend processes were not restarted, so backend improvements take effect
after restart. Refresh the page to load the updated frontend. No `.env`, user
profile, application answers, saved documents, Git commit or remote branch changed.
