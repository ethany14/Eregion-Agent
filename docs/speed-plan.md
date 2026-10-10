# Speed plan implementation — 2026-10-09

This implements the supplied A0–A6 and B1–B6 changes. Performance targets are
acceptance goals, not guarantees. The measured cold-model results below do not
meet those targets yet. Existing conversation, evidence, consent, login, browser
takeover and final-submission boundaries remain in the shared loop.

## Application execution

- The host fills known facts at the start of a slice and on page changes. It
  records these actions so the model can see what happened. Legacy `observe`
  calls receive a short acknowledgement; the tool is no longer advertised.
- Completed pages advance through the single observed Next control. Missing
  facts, invalid fields, unresolved dropdown paths, consent, education, draft
  answers and documents prevent automatic advancement. Each page fingerprint
  advances at most once. Automatic completion stops at review, never Submit.
  Unanswered optional controls at final review are left for the model to decide.
  The model can deliberately click Next to revalidate a corrected field whose
  old error only clears on Next; the automatic path will not do so.
- Independent field actions can share one model reply. Duplicate keys and keys
  not present at the start of the batch reject the whole batch before mutation.
  Navigation, questions, review and visual actions stay separate. Every field
  action refreshes live fields; chat revisions invalidate pending actions.
- Completed fields, relevant memories (at most 10), page controls (at most 40),
  recent history (8 entries) and one facts list replace repeated full data.
  The application transcript window is 12,000 characters. This bounds history,
  not every possible large live form: under 25K is a tested snapshot target.
- Plain inputs use `fill()`; the recovery tool falls back to real key events
  when a website discards the value. Autofill fills ordinary inputs together,
  scans once per pass, and handles uploads/pickers separately. Fresh scans can
  be reused for 300 ms. DOM settling waits for 150 ms without changes, with a
  1.5 s upper bound, instead of fixed sleeps.
- Revision checks use in-memory control state. Budget/progress/history writes
  are combined at checkpoints; pre-effect journaling remains. Legacy runners
  flush reservations when yielding. Two writes/action is an optimization target,
  not a claimed invariant: document bindings, chat and host navigation can add
  checkpoints.
- Three browser workers are the default. A worker shares Chrome while each
  application owns an isolated context. Context close preserves other runs;
  worker shutdown closes the process. Login state and thread affinity remain.

## Analysis and materials

- Migration `0035_analysis_cache` adds validated resume/JD/match storage and
  pack timing metadata. Memory, disk and identical in-flight requests are reused.
  Cache identities include owner, content, model settings, prompt/schema versions,
  matching routing and confirmed evidence. Quick fit and workflow workers share
  this path. Invalid evidence is rejected before caching. Upload warmup runs in
  the background, with one worker and at most four queued distinct resumes.
- Exact bare skills use conservative whole-word evidence matching; negation,
  years, expertise, compound requirements and ambiguous quotes fall back. Jev
  still handles its configured decisions. Remaining requirements use adaptive
  batches (up to 24 requirements, sized against the actual compact request text),
  with at most three requests in parallel. A compact ID/status/
  evidence-ID response expands into the existing public match contract.
- JD extraction references numbered exact source sentences. Resume writing
  returns source entries and grounded bullets; code restores headers, dates and
  foundational sections. Original source/evidence checks still run afterwards.
- Factual-only unsupported bullets can be removed in code, falling back to
  original source bullets for an empty entry. Structural issues and user edits
  retain the model revision path. The default is one revision (configurable).
  Deterministic source/structure checks now run before paid verification. Material
  packs use one semantic pass over all resume sections instead of overlapping
  factual model checks. Custom model adapters retain their additional verifier
  contract. See the second-pass measurements in [agent-loop.md](agent-loop.md).
- The task scheduler defaults to four concurrent tasks. Chat material creation
  starts resume/letter items together with short serialized repository writes.
  Verified documents appear as they finish; pending items show writing/checking
  states. The existing early score projection remains ahead of later stages.
- Model clients are reused by settings fingerprint and purpose. Shared resume
  content precedes job-specific matching/writing data to aid provider caching.

## Configuration and rollout

Restart the backend normally to load the code and run migration 0035. This task
does not restart the running production backend or alter its credentials.

| Setting | Behavior when unset |
| --- | --- |
| `JOB_AGENT_APPLY_WORKERS=3` | Three workers; use 2–4 if the model plan permits. |
| `JOB_AGENT_ANALYSIS_WARMUP=1` | Precompute uploaded resume analysis; `0` disables. |
| `LLM_FAST_MODEL_ID` | Uses the main model; optional routine browser tier. |
| `LLM_EXTRACTION_MODEL_ID` | Uses the main model for extraction/matching. |
| `LLM_AGENT_REASONING=low` | No reasoning override unless explicitly configured. |
| `LLM_EXTRACTION_REASONING=low` | No reasoning override unless configured. |

Only set reasoning when the configured provider supports it. Recovery, runtime
feedback and open-ended browser work choose the main tier. These optional tier
and reasoning settings have not been enabled in `.env` during this change.
The optional long-JD section split (B3.2) is deferred; exact sentence references
are implemented without introducing additional segmentation assumptions.

## Measurements and validation limits

Machine-readable results: [speed-2026-10-09.json](benchmarks/speed-2026-10-09.json).

| Real configured model measurement | Result |
| --- | --- |
| Two-page local form + real Chrome | 26.27 s baseline → 19.07 s after changes; about 27% shorter |
| Model reservations in that smoke | 6 → 3, including answer verification |
| Submitted applications in smoke | 0; all expected fields correct |
| Completed cold fit, saved case 2 | 217.482 s |
| Same fit, new service/cache instance | 0.032 s, 0 model calls |
| Tailoring analysis after that fit | 0 resume/JD/match model calls |
| Writer / first verification | 53.384 s / 62.321 s; later revision timed out |

The application number is a single paired synthetic-form smoke, not an ATS
median. An intermediate A1-only run was 29.38 s despite fewer calls, showing
provider variability. Three browser fixtures use Greenhouse, Lever and Workday
URLs with intercepted local HTML; they prove mechanical behavior, not coverage
of those employers' current production pages.

Three saved-JD fit + tailor trials were attempted with the configured
`muse-spark-1.3-contributor`, a 120-second request timeout and production Jev
routing. Cases 1 and 3 timed out during extraction; case 2 completed fit and its
first writer/verifier, then timed out during revision. No trial produced a fully
verified tailored pack. Cold fit at 8–10 s, matching below 5 s, writing/checking
below 15 s, and three live ATS baseline medians remain unverified/unmet. The
observed model latency dominates the successful cold fit: resume 92.873 s and
JD 115.075 s overlap, followed by matching at 102.395 s.

Automated checks cover batch isolation, steering/cancellation, budgets, browser
ownership, keyboard fallback, consent and final submission, cache invalidation
and restart, exact evidence, parallel matching/checks and compact snapshots.
Final full regression: **1,138 passed, 2 skipped**, plus 12 passing subtests,
in 562.69 seconds. One existing Starlette/AnyIO deprecation warning remains.
Additional focused checks passed after the final telemetry and state-notification
fixes, including actual pack timing persistence and document-replacement steering.
Python syntax and newly added-line whitespace checks passed.

The full suite runs with `JOB_AGENT_BROWSER_TESTS=1`; employer traffic in those
browser tests is intercepted locally. Scripted tests disable external model
calls separately from the billable smoke/benchmark. The new UI states were
visually inspected at 1440 px and 390 px in light and dark themes.

Run the billable benchmark manually:

```powershell
.\.venv\Scripts\python.exe evals\speed_bench.py --saved-inputs --output speed-results.json
# Alternatively: --resume resume.txt --jobs job1.txt job2.txt job3.txt
```

The benchmark reads saved source material and writes analyses into a temporary
database. Its output contains counts, durations and safe error types, not the
resume, job descriptions or credentials. Failed trials preserve completed stage
measurements. No application is submitted by this benchmark.
