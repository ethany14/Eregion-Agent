# Shared agent loop

The chat task driver and the application worker now run decisions through
`agent_runtime/loop_engine.py:AgentLoop`. The kernel does not choose job-search
stages or understand ATS fields. Existing domain services remain the tools it can
call, and the model chooses their order.

```mermaid
flowchart TD
  Chat[Career chat and scheduled research] --> Task[TaskLoop scheduling / TaskHost]
  Apply[ApplicationLoop browser worker] --> App[ApplicationHost]
  Task --> Core[AgentLoop]
  App --> Core
  Core --> Context[ConversationWindow: complete tool exchanges]
  Core --> Model[Interruptible model request]
  Core --> Tools[Advertised tool validation and execution]
  Tools --> Career[CareerHarness: search, score, materials, interview]
  Tools --> Browser[AgentTools: autofill, DOM, vision, questions]
  Core --> State[Host persistence: transcript, events, in-flight action]
```

## Responsibility boundaries

| Component | Responsibility |
| --- | --- |
| `loop_engine.py` | Observe/decide/execute cycle, advertised argument shape, complete tool-result groups, steering checks, lifecycle events, worker yields |
| `loop_context.py` | A bounded window of complete exchanges; excludes screenshots, typed reasoning and credential keys; never duplicates old full observations |
| `loop_model.py` | Cancellable waiting, provider deadlines and thread isolation; detaches obsolete requests so a new user message can proceed |
| `task_host.py` | Conversation persistence, chat messages, questions, plans, background-result waits and completion policy |
| `auto_apply/runner.py` | Application observations, browser-thread ownership, DOM/vision recovery, semantic answer verification and form completion checks |
| Existing repositories and domain tools | Candidate evidence, approved memory, documents, credentials, browser permissions and submission fencing |

The older `tools/loop.py`, resume workflow and persisted tool executor continue to
serve their existing document/session APIs. They are not extra planning loops in
the active career chat. This change does not migrate those APIs or replace their
approval and evidence contracts.

## Runtime behavior

- A normal text answer completes an ordinary chat turn. Only an explicit question
  creates a pending user request. An application progress message is delivered,
  while its host checks whether the form is actually ready before yielding review.
- User messages increment the existing revision. Decisions from a previous
  revision cannot execute. Provider calls already sent may still finish remotely;
  their results are ignored. This is not a provider-side billing cancellation.
- Explicitly declared independent read tools may run in one model turn. They run
  sequentially; browser mutations still require a fresh observation. Deferred
  calls receive results so provider message protocols remain well formed.
- Model retries do not replay completed tools. The application host keeps its
  existing failure recovery and submission checks.
- Each operation is journaled before execution. A restart with an in-flight
  operation exposes uncertainty and asks the model to inspect actual state;
  the kernel never blindly re-executes it. Domain idempotency and the existing
  final-submit fence remain necessary: this is not universal exactly-once delivery.
- A slice yields after twelve decisions; the existing schedulers continue it
  within their total budgets. Yielding does not invent a user question or erase
  successful field bindings.
- `loop_runtime` is a versioned JSON field in the existing state, so no database
  migration is needed. It retains up to eight complete exchanges / 24,000
  serialized characters, eighty metadata events and any in-flight operation.
  Domain history, messages, approved facts and artifacts remain the authoritative
  longer-lived task state. An oversized exchange is omitted whole, not cut into
  invalid tool JSON. This is bounded retention, not an LLM-generated summary.

## Host contract

A host supplies `active`, `revision`, `observe`, `invoke`, `progress`, `on_text`,
`execute`, `action_error`, `after_action`, and `persist`. `Turn` carries its prompt,
current snapshot, advertised tools, revision and optional ephemeral images.
`LoopStop` represents a deliberate stop or handoff, separate from unexpected errors.
Adding another domain requires a host and tools; it does not require editing the
kernel with new workflow stages.

## Design references

The separation between a small loop, steering input, tool execution and lifecycle
events follows the useful structure visible in
[Pi's loop](https://github.com/badlogic/pi-mono/blob/main/packages/agent/src/agent-loop.ts).
Keeping session persistence and interruption concerns separate is also reflected
in [Hermes's runtime](https://github.com/NousResearch/hermes-agent/blob/main/run_agent.py).
The host/session distinction and bounded operational lifecycle are consistent with
[OpenClaw's documented agent loop](https://docs.openclaw.ai/concepts/agent-loop).
These are architectural references; no upstream runtime or new framework dependency
was imported.

## Verification

Run the deterministic scheduler/repository regression checks without pytest:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_shared_agent_loop.py -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_auto_apply_review_fixes.py -v
```

The opt-in live smoke uses the configured, billable model and actual Chrome. It
intercepts navigation to render a local synthetic two-page application; it uses no
saved candidate data, uploads or external ATS and asserts zero final-submit clicks:

```powershell
$env:NORTHSTAR_SMOKE_DIR = 'C:\path\to\existing\test-artifacts'
.\.venv\Scripts\python.exe scripts\smoke_shared_application_loop.py
```

The initial live run completed autofill, page navigation, semantic answer binding,
second-page filling and final review in five tool calls plus six model calls
(including answer verification), about 17 seconds. A separate isolated instance of
the real chat UI completed a greeting, saved-job lookup and public browser read.
This is targeted coverage of the new kernel and its integrations, not a claim that
every employer site, resume workflow or interview mode has been retested.

## Optional Jev fast decisions (first integration)

The main chat/application planner remains the configured `LLM_*` model. Jev is
an optional capability inside domain tools, not another planner or mandatory
router on every user message. It uses TypeSafe's `/v1/systemone` HTTP API through
the existing httpx dependency; no new framework or database migration is needed.

```dotenv
TYPESAFE_API_KEY="your-key"
TYPESAFE_BASE_URL="https://api.typesafe.ai"
TYPESAFE_DEFAULT_MODEL="jev-latest"
TYPESAFE_ENABLED=false
TYPESAFE_CAREER_ENABLED=false
TYPESAFE_TIMEOUT=2.5
```

`TYPESAFE_ENABLED`, `TYPESAFE_CAREER_ENABLED`, and `TYPESAFE_TIMEOUT` are project settings, not SDK environment
variables. Enabling the feature sends relevant field labels, options and their
confirmed answers to TypeSafe, and job snippets plus search preferences for
screening. The general form/screening scope does not send raw resumes, screenshots, passwords or account
forms. The additional career scope below sends extracted resume evidence and scoped memories. Leave it disabled until that data destination
is approved. Existing `LLM_*` settings are unchanged. Smoke scripts explicitly
enable Jev only in their own processes using synthetic data. They do not modify
`.env`, production profiles or running servers. Pin `TYPESAFE_DEFAULT_MODEL` to
`jev-1.13.0` if calibrating thresholds; `jev-latest` may change underneath them.

### Form choices

`auto_apply/fast_options.py` runs inside `autofill` after existing deterministic
filling (including resume upload). It batches unresolved exposed dropdown choices
against applicable confirmed sources. Matching by exact label or known aliases
remains deterministic. Dynamic menus are probed at most twice per invocation;
up to three bounded rounds allow an exposed category/leaf sequence. Only observed
option IDs can be selected. Labels, source values, revision, and the entire live
option list are checked again after the network call, and the browser value is
verified after clicking. Decisions remain run-local representations, not new
candidate facts. Existing source bindings and final-submit checks still apply.

The initial adoption gate requires confidence >= 0.90 and winning probability
>= 0.95. These are conservative starting values, not an empirically established
accuracy guarantee. Ambiguous/no-match answers and all provider failures return
control to the main LLM. Eligibility, consent, and yes/no interpretation keep
their existing path. Category exploration does not count as a completed answer.

### Job screening

`screen_jobs(urls, query)` accepts up to twenty actually observed browser/search
links or previously retrieved jobs. The host supplies captured titles, locations,
context and any retrieved descriptions; the model cannot invent posting text in
this tool. The query contains role/location/seniority preferences, not contact
details or resume text. Supplementary `search_jobs` also uses this screening.
Results are advisory `strong / possible / weak / unknown` priorities, never the
verified fit score. All candidates remain available, including uncertain ones.
Reading, evidence validation and recommendation gates remain required. Detailed scoring may use
the separately enabled career acceleration below; screening never substitutes for it.
The first gate is confidence >= 0.75 and winning probability >= 0.85. The task
allows at most twenty auxiliary screening evaluations per user revision.

### Failure behavior and observability

`fast_decisions.py` validates every response's IDs, distributions, numbers and
shape. Calls have a short per-operation HTTP timeout with no automatic retries
or redirects. An error opens a 30-second cooldown; results are cached in memory
for five minutes (128 hashed entries, keyed by exact model/input/questions).
Form requests also use the existing interruptible provider wait and model budget.
Unchanged failed mappings are not retried on every loop iteration. Diagnostics
record purpose, model, elapsed time, status, tokens and cache hits, without API
keys or raw provider requests. Application state records `fast_options` timings;
career tasks retain a bounded `fast_decisions` history.

Boolean grounding remains authoritative on the main model. The opt-in smoke
compares Jev against it, but does not change production answers or add a second
verification call to normal applications. Initial testing found a Chinese
negative answer that Jev abstained on while the main model accepted correctly.
The nested referral fixture also required the main model to explore Job Boards;
Jev's uncertain category choice was correctly declined. Fast decisions are an
optimization with a fallback, not a promise to solve all menus.

### Live verification (no pytest)

```powershell
$env:NORTHSTAR_SMOKE_DIR = 'C:\path\to\existing\artifacts'
.\.venv\Scripts\python.exe scripts\smoke_jev.py
.\.venv\Scripts\python.exe scripts\smoke_jev_runtime.py
.\.venv\Scripts\python.exe scripts\smoke_jev_nested.py
```

These use billable configured APIs and real headless Chrome with locally
intercepted pages and synthetic applicants/jobs. Runtime checks inject timeout,
401, 429, malformed responses, changed options, new user input and pause events.
The chat smoke exercises the actual task loop, browser and CareerHarness with
an isolated temporary database. The nested smoke validates uncertain Jev output
falling back to the main model and reaching LinkedIn through Job Boards. All
application checks assert zero final-submit clicks.

Initial measurements on 2026-10-09: ten option questions took about 0.6 seconds
in one Jev request; three synthetic jobs about 0.6 seconds. One Chrome application
comparison took 19.5 seconds / five main-model calls without Jev, versus 16.6
seconds / three main-model calls plus one Jev request after integration fixes.
This is a small smoke sample with variable provider latency, not a benchmark or
real-ATS reliability claim. The last option batch accepted five correct mappings
and deferred five cases (including one correct but low-confidence referral).

References: [TypeSafe API](https://docs.typesafe.ai/api),
[models and limits](https://docs.typesafe.ai/models),
[known limitations](https://docs.typesafe.ai/model-jaggedness/jev-1.13).


### Career decision acceleration (round 2)

The task loop still uses the configured main model for planning, tool selection,
communication, writing, extraction, interview evaluation, factual claim checking,
and nonliteral yes/no grounding. Jev is invoked inside existing capabilities,
not as a compulsory router before every chat message.

| Capability | Jev work | Main-model fallback |
| --- | --- | --- |
| Dropdown filling | Map confirmed answer to observed option | Unknown/ambiguous mapping or provider error |
| Job shortlist | Rank observed posting snippets | Main agent inspects uncertain candidates; all links retained |
| Memory retrieval | Relevance of already allowed, confirmed memories | Entire original candidate set if any decision is uncertain |
| Application question classification | Choose existing semantic category | Uncertain category, including ambiguous personal questions |
| Match assessment | Select exact evidence for simple skill requirements | Complex/partial requirements, years, education, uncertain evidence |

`TYPESAFE_CAREER_ENABLED=true` requires `TYPESAFE_ENABLED=true`. Both must be
explicitly enabled in configuration and the backend restarted to enable these
new career paths. They are disabled by default; benchmark scripts inject their
own enabled service and synthetic data without editing `.env`.

The career scope sends question text, a retrieval query and the already scoped
memory candidates, and validated resume evidence quotes plus job requirements
to `https://api.typesafe.ai`. These fragments can contain personal information.
This is broader than form-option mapping and job-snippet screening; enabling
the general switch alone does not enable it. Existing owner/sensitivity/expiry
filters run before memory selection. Neither benchmark nor fast decisions write
new user facts or consent choices. No resume file, browser image, password, or
verification code is uploaded by this code path.

`fast_semantics.py` batches at most 40 memory candidates. The relevance gate is
confidence >= 0.85 and winning probability >= 0.90, used only for retrieval.
It neither deletes stored memories nor changes their confirmed status. Initial
testing found that passing only uncertain memories to the main model changed
its context, so an uncertain batch now falls back with every original candidate.
Question categories require confidence >= 0.95 and probability >= 0.98. Existing
deterministic legal/logistics/demographic guards and manual-answer policy remain.

`job_agent/fast_match.py` handles at most 40 simple requirements against up to
80 evidence quotes, within the provider adapter's input bound. It picks only
existing quote IDs. Code maps them back to exact original text. Direct decisions
require confidence >= 0.90 and probability >= 0.95. Several valid quotes can split
selection probability; an additional bounded Jev batch can independently verify
the selected quote (confidence >= 0.95, probability >= 0.98). This is a second
decision, not permission to accept the first uncertain choice. Any unresolved
requirements are passed to the main model together in one request. No generated
quote is accepted and no truncated input is treated as proof of absence.

User-confirmation requirements remain unscored and unanswered. Years and degree
comparison use the main model. Existing exact-evidence, tool-name, education,
duration, grouping and required/preferred weighting rules still normalize the
final result. Jev's `Score` primitive never computes the public match score.
Fast assessments use a short evidence summary and per-gap suggestions, while
complex fallback requirements retain main-model suggestions. This is a change
in explanation style, not a replacement for full career coaching.

These confidence thresholds are provisional gates, not measured probabilities
of correctness. Model aliases and latency vary; pin the tested provider version
when using benchmark results to choose thresholds.

Fit analysis now reports `main_model_calls`, `fast_model_calls` and total
`model_calls`; workspace timing also retains per-purpose metadata and fallback
counts. Cache hits consume zero provider calls. Matching mode/model configuration
is included in fit cache identity. Jev HTTP requests participate in the existing
model usage budget and use provider token usage when returned. No prompt, resume,
memory content or API key is included in routing diagnostics.

Additional repeatable checks (billable APIs for the benchmark and quality script):

```powershell
.\.venv\Scripts\python.exe scripts\benchmark_jev.py --output <artifact-directory> --repeats 2 --suite all
.\.venv\Scripts\python.exe scripts\check_jev_routing.py
.\.venv\Scripts\python.exe scripts\quality_jev.py <artifact-directory>\quality.json
```

The benchmark alternates main/Jev order, disables fit caches and clears Jev result
caches before each trial. It measures isolated matching on identical extracted
evidence as well as the full extraction + matching service, and saves all scores,
statuses, quotes, fallbacks and timing. Full cold extraction is nondeterministic;
use the fixed-evidence trials to distinguish matching changes from extraction
variation. Quality holdouts cover negation, partial skills, compound requirements,
tool non-equivalence, translation, quoted instruction injection and consent.
Read `docs/jev-benchmark.md` for measured results and their limitations.


## Latency cleanup

The loop now elides exact duplicate tool results between current history and its
complete transcript, and repeats a user request only when it changes. Legacy and
changed results are retained. Provider waits check revisions at roughly 100 ms,
wake immediately on completion, and always recheck before accepting a response.
Timing records expose payload sizes and available provider token counters.

Resume/JD extraction uses compact provider-only schemas, expanding locally into
the same public evidence contracts. Source validation and score calculation stay
unchanged. See [the latency audit](latency-audit.md) for measurements, limits and
the remaining extraction, asynchronous scoring and streaming work.

## Speed plan implementation

See [the speed implementation report](speed-plan.md) for host-owned mechanical
steps, batching, durable analysis reuse, compact model contracts, optional model
tiers, configuration and measured results. Cold-provider performance targets are
not yet met; the report separates these from verified cache and call reductions.

## Provider usage and context reduction (first pass)

Migration `0036_provider_usage` adds an independent ledger. The shared provider
adapter records actual input/output usage before structured output parsing, plus
cached-input and reasoning counters when supplied. Jev is recorded at its HTTP
boundary; cache hits do not create paid-call records. Missing usage remains
unknown. Counts are application-level provider invocations; with nonzero
`LLM_MAX_RETRIES`, opaque internal SDK retry attempts are not individually visible.
The default remains zero SDK retries.

Task, browser-worker, analysis and material-generation thread contexts preserve
attribution. Application resumes establish their run ID again after restart.
Career API `usage_summary` combines the conversation with linked application
runs without double counting; the Lookout shows reported totals and a breakdown.
Standalone application GET responses also include their own usage. Old runs have
no retrospective billing data. Interrupted provider calls keep running when the
SDK cannot cancel them; late usage is recorded with `adopted=false`. A server
crash can leave a call pending/unknown, not falsely free. Prompts, credentials,
candidate data, URLs and provider error bodies are never written to this ledger.

The kernel now measures system text, tool schemas, transcript and observation
together against a default 64,000-character target (`AgentLoop.request_chars`).
This is a text-size target, not a tokenizer or image-token estimate. Large legacy
tool results and long source documents become `context_ref` references. The
read-only `read_context` tool retrieves 3,000-character JSON slices, with exact
offsets, from an archive persisted across worker slices and restarts. Current
references are pinned; older references can expire explicitly under the archive
size limit. The archive is excluded from public application responses.

Whole tool exchanges are trimmed from replay as needed. The latest user message,
candidate facts, pending question, live controls and observation IDs are retained
exactly. If those protected fields alone exceed the target, the kernel records
`protected_overflow` instead of silently removing instructions or permissions.
All capabilities remain available in this first pass; no lower decision-step
limit was introduced. Image usage is counted by provider counters when returned;
the separate visual-input policy is unchanged.

Semantic claim validation sends each distinct employer description once and
references it from each claim. Candidate evidence and complete decision-set
validation are unchanged. Adaptive matching batches, consolidation of overlapping
validators and selective screenshot capture are subsequent optimizations, not
claimed as part of this pass.

Validation on 2026-10-09: offline reconstruction of the same saved long career
conversation reduced the measured system/tools/base-observation text from 85,238
to 42,294 characters (50.4%). Rebuilding one saved four-claim cover-letter check
reduced its payload from 59,999 to 21,047 characters (64.9%). These are character
measurements, not billing totals.

A separate two-request live comparison used synthetic archived postings, the
same seven-current-jobs question and `muse-spark-1.3-contributor`. Both answers
were correct. Provider-reported input tokens changed from 20,681 to 7,323 (64.6%
lower); output tokens were 274 and 303, including 256 and 285 reasoning tokens.
Both reported zero cached input tokens. This one long-context case does not
establish an end-to-end job search/application savings percentage.

## Token reduction: second pass

Matching now sizes batches against the same compact JSON sent to the provider,
up to 24 requirements per call with a 40,000-character payload target. Every
batch retains all candidate evidence. If the evidence alone exceeds the target,
the batch still leaves 8,000 characters for requirements instead of multiplying
the oversized evidence once per requirement. Individual oversized requirements
remain intact. These are text/output-size heuristics, not strict token limits.
Large jobs still use at most three concurrent requests. Exact-skill and Jev
confidence gates, requirement completeness checks and score weights are unchanged.
The matching routing version changed to invalidate old match-cache entries.

Resume source ownership, header/entry metadata, citations and structure are
checked locally before factual model calls. The standard material-pack adapter
then uses the artifact verifier as its single semantic pass, including education
bullets (previously omitted by that artifact verifier's legacy section projection).
Only entire unchanged resume evidence quotes bypass semantic checking; removing
qualifiers such as "learning", "planned" or "in progress" must be judged.
The standalone resume handler retains its factual verifier after local checks;
injected pack models without `verify_resume_structure` retain their additional
verifier contract. This opt-in method must be deterministic and relies on the
artifact check for full claim semantics. Local checks do not reserve model usage.
Manual material edits and workflow workers use the same composition. Worker
reports have a verification version; old passing reports are not silently reused.
Citation, length and other deterministic artifact failures skip semantic calls;
revised content must pass every check again before approval.

Application screenshots are sent after explicit viewport/field viewing, visual
actions, or a DOM failure that requests visual recovery. A capture already returned
by a visual action is reused only after its fingerprint/token passes freshness
validation following host actions. A changed page is recaptured. Returning to DOM
or a text-only turn stops automatic images and invalidates old coordinate tokens.
Pixels are ephemeral; no screenshot or pending visual request survives a restart.
Login/verification barriers, secret masking and final-submission checks remain.

Live comparison on 2026-10-10 used synthetic evidence only and the same configured
`muse-spark-1.3-contributor`. Run
`python scripts/benchmark_token_efficiency.py --live --output <new-directory>`
to reproduce with the current configured model. The
benchmark records provider usage in its own SQLite DB, not the user's database.

| Scenario | Calls before → after | Input tokens | Output tokens (includes reasoning) | Total tokens | Seconds |
| --- | --- | --- | --- | --- | --- |
| Match 18 requirements | 3 → 1 | 3,121 → 1,893 | 2,141 → 763 | 5,262 → 2,656 (−49.5%) | 10.324 → 7.308 |
| Verify a paraphrased resume | 2 → 1 | 1,770 → 498 | 2,171 → 960 | 3,941 → 1,458 (−63.0%) | 13.499 → 9.100 |

All 18 match statuses agreed with expected results and cited only supplied quotes;
both resume checks passed. Matching reported zero cached input tokens. The final
resume check reported 497 cached input tokens, versus zero in its earlier pair.
These are single-sample measurements, not a universal speed/cost guarantee or an
end-to-end job-search total. Token totals include cached input and reasoning once;
they are not dollar-cost estimates. In real Chrome, a five-decision mixed visual/
DOM fixture sent only two image turns and captured each image once. Image token
savings were not estimated from that offline test.

A separate single-request live semantic check accepted a faithful paraphrase and
rejected three synthetic counterexamples: fabricated team/revenue metrics, an
in-progress degree presented as completed, and reversal of a negated skill.

Validation: the network-fenced full Python suite completed with 1,075 passed,
102 skipped and 12 passed subtests. Final qualifier/structure refinements passed
59 targeted material/workflow tests; the final visual batch-recovery change passed
30 application-loop/real-Chrome tests (including 11 visual tests). The broader
real-Chrome visual/general-browser run passed 25 tests. Employer pages were local
fixtures and no real application was submitted. The only warning was the existing
Starlette/AnyIO deprecation. Production backend processes were not restarted.

## Token reduction: third pass

Material and semantic provider inputs can now use a self-contained `shared-text-v1`
envelope. Long, exactly repeated prose is stored once in `shared_texts`; the
original fields in `content` refer to it with `{"$text":"tN"}`. All source text,
source ownership, evidence/version IDs, dates, preferences and revision feedback
remain available in the same request. No summarizer, evidence filtering or extra
retrieval/model call is involved. Public schemas and custom analyzer inputs are
unchanged. Existing reference-like domain data prevents this transformation.

The adapter applies this to resume generation/revision/verification, cover
letters, application answers, and small semantic decisions. It only enables
sharing when the encoded content plus its interpretation instruction saves at
least 30% of the original JSON text and more than 200 characters. This is a
conservative character heuristic, not a tokenizer or guaranteed latency saving.
Low-saving resume inputs retain the original prompt format. The threshold was
added after live testing found that a modest input reduction did not speed up
end-to-end resume writing. Revision instructions appended after JSON remain intact.

Identical concurrent Jev decisions now share one in-flight HTTP request per
configured service instance. The key includes the full frozen payload and
purpose; different page states, questions, models or purposes do not share it.
Waiters receive independent answer copies and report zero new requests/tokens.
Only the request owner is charged in the provider ledger. Waits are bounded by
the existing timeout; timeout/error results retain normal main-model fallback.
Budget exceptions release waiters without sharing exception bodies. This is
process-local deduplication of pure decisions, never reuse of browser actions.
The existing five-minute cache, decision confidence thresholds and outage cooldown
remain in effect.

Testing also exposed an older generator/validator mismatch: a summary could
combine undergraduate and graduate citations even though the existing structure
validator requires one source per claim and education in its own section. The
writing and revision prompts now state those existing requirements explicitly.
The validator was not weakened. Both complete education entries are still kept.

Reproduce the opt-in synthetic comparison with
`python scripts/benchmark_context_sharing.py --live --jev --output <new-directory>`.
`--only materials|semantics|jev` selects a subset. No private resumes, application
submissions, user memories or production DB changes are involved.

Live results on 2026-10-10 with `muse-spark-1.3-contributor` and `jev-latest`:

| Scenario | Requests before → after | Input tokens | Output tokens | Total tokens | Seconds |
| --- | --- | --- | --- | --- | --- |
| 12-claim semantic check | 1 → 1 | 1,515 → 881 | 1,053 → 985 | 2,568 → 1,866 (−27.3%) | 12.298 → 9.810 |
| Four identical concurrent Jev decisions | 4 → 1 | 1,336 → 334 | 152 → 38 | 1,488 → 372 (−75%) | 0.983 → 0.698 |

Both semantic variants accepted the same six supported claims and rejected all
six negative cases, including fabricated revenue/team size, degree completion,
an unsupported technology, and claims citing the wrong source even when the
correct fact appeared elsewhere in the shared table. All Jev callers received
the correct answer. Semantic calls reported zero cached input tokens. These are
single-sample provider measurements, not universal workflow/cost guarantees.

An initial resume pair was rejected after generation; those numbers are excluded
from successful-output claims. After aligning the source rules in both variants,
both drafts passed local and semantic checks and retained undergraduate/graduate
records. Generation input decreased 5,606 → 4,969 tokens, but output increased
3,660 → 4,193 and generation took 48.125 → 50.453 seconds. Including each draft's
verification, totals were 12,531 → 12,509 tokens and 60.352 → 63.711 seconds.
This does **not** establish a resume-writing speedup. Its net text reduction was
23.8%, so the final 30% gate now leaves that input in the original format; a
regression test checks exact equality with the previous prompt. Highly repeated
inputs still use lossless sharing. Reasoning/output variance remains material.

Validation: full network-fenced suite 1,090 passed, 102 skipped, 12 passed subtests.
Final gating/material changes passed 109 targeted tests; final wire-format and
concurrency checks passed 15 tests, including mutation of caller input during a
request, bounded waits, budget exceptions, source/citation preservation and
cover-letter/answer/revision adapters. Only the existing Starlette/AnyIO warning
was reported. Backend processes and `.env` were not changed or restarted.


## Current request and explicit completion

Task observations reconstruct `current_request` from the latest durable user
message and chat revision. The original creation goal remains `initial_goal`
for history and idempotency; it cannot override a later request. The current
request is protected during request compaction. Replayed exchanges are labeled
historical, including older stored transcripts; migration does not rewrite audit
evidence. A restart retains the same messages, revision, model count and budget.

Every task turn ends through an explicit control decision. `finish_task` delivers
the answer or observed result; it can directly answer a greeting or ordinary
question in one model call. Text without a control call is progress, including
before the first capability action and in a new chat revision. It cannot mark a
promise as completed. Questions, pauses, background waits and completion retain
their existing validation and persistence rules.

Repeated immutable reads ignore changing access counters when measuring progress.
If an unchanged read repeats while a linked application is running, the career
harness offers the same durable `wait_for_result` handoff used by the model.
Independent useful actions remain available. A capability that changed meanwhile
causes a fresh observation instead of sleeping on an obsolete result. Live domain
observations refresh archived-resource status; old source content stays readable
but is not authoritative for current approval or application status.
