# Stage 4: optional verify-and-score workflow

Fixed no-new-failures base: `566f5642f921347df0446b7c40aa52d80ccbeaa9`
(the HEAD supplied for this task). The reviewer reference at `4785931` was
1996 passed, 132 skipped, zero failed; it is not substituted for this fixed base.
All runs here use frozen/offline IO and synthetic scoring, with external sockets
blocked and repository dotenv ignored. No paid or live runs were performed.

## Contract and unchanged business handlers

`JOB_AGENT_OPT_VERIFY_AND_SCORE=1` exposes `verify_and_score`; default is off.
It accepts **one** posting. Required: `url`. Optional: `region_ref`,
`observation_id`, `message_id`, `job_text`, `title`, `company`, `location`.
An observed candidate or saved retrieved body is addressed by its posting URL,
just as with `read_job` / `import_job`. The optional batch extension is not used.

- `CareerHarness.execute(read_job)` captures the original bounded browser body
  or existing discovery result, using the original identity/source preflights.
  A saved same-identity body can be reused, including on a blocked remote source.
- `CareerHarness.execute(import_job)` performs the original candidate preflight,
  `candidate_health.validate_and_record` / `posting_qualification.validate_posting`,
  literal-quote validation, captured metadata handling and workspace import.
  Original location and qualification evidence are preserved, with no new or
  relaxed qualification rule.
- `CareerHarness.execute(score_job)` uses the original resume/facts, catalogue,
  snapshot fingerprint, analysis service and caches. Nested usage scopes keep
  provider purposes and the task's shared ledger/budget.
- Success returns the original detailed score result, `completed_steps` and
  `opening_level`, computed by `search_policy.opening_level` from the exact saved
  description. `qualification_evidence`, location, description and match report
  remain available for judgement. It **never calls recommend_job**.

The tool joins the same deterministic search/recommendation tool groups.
The current execution mask still rejects it at completion, even if a stable
schema advertises it. Granular tools remain available. One 80-character prompt
rule prefers the composite and leaves recommendation separate. Flag-off arrays,
prompts and serialized requests are checked against the fixed base, both with
legacy settings and with stage-2 request optimization enabled.

## Replay results

| Replay | Decisions: granular / composite | Chars: granular / composite | Reduction | Qualified |
|---|---:|---:|---:|---:|
| r1 | 20 / 13 | 957,736 / 594,810 | 37.89% | 1 |
| r2 | 11 / 11 | 464,684 / 471,522 | -1.47% | 0 |
| r3 | 2 / 2 | 57,836 / 59,114 | -2.21% | 0 |
| correct | 11 / 7 | 458,002 / 284,879 | 37.8% | 2 |
| directory-positive | 12 / 8 | 506,161 / 333,744 | 34.06% | 2 |
| directory-negative | 3 / 3 | 101,850 / 103,767 | -1.88% | 0 |

With stage-2 refs, prompt trimming, stable tools and checkpoint history enabled:

| Replay | Chars: granular / composite | Composite maximum |
|---|---:|---:|
| r1 | 871,413 / 541,012 | 47,530 |
| r2 | 431,193 / 435,710 | 44,775 |
| r3 | 54,387 / 55,703 | 29,494 |
| correct | 424,146 / 257,526 | 42,769 |
| directory-positive | 461,554 / 296,663 | 43,035 |
| directory-negative | 88,960 / 90,934 | 34,457 |

All optimized requests remain within the unchanged **48,000-character** limit.

`evaluate_search` and its thresholds are unchanged. r1 still has one qualified
recommendation and the Associate result still says **Level unverified**. Correct
and directory-positive pass with two qualified recommendations. r2 stops with
no progress; r3 and directory-negative finish honestly without qualifying jobs.
All [scoring schema/system/content SHA-256 lists](scoring-inputs.json) match across granular and
composite runs, including stage-2 settings. Qualification checks also match.

Script adaptations replace reads with the composite, remove their import/score
calls and the now-redundant body/score context reads. Browser/search context reads,
source recovery, recommendation decisions and final reporting remain. Original
fixtures and replay acceptance tests are unmodified. Both modes run through the
production loop, not a hand-counted request estimate. Replays with no posting to
process retain the same decision count and pay the added tool/prompt overhead.
Character counts are not token prices, provider cache hits or live quality claims.

## Checkpoints, idempotency and crashes

The task's `verification_workflows` journal is keyed by the existing harness
request key with `job_key`-normalized posting identity. Each substep saves
`pending_step` before entering the original handler, then records completed
steps. The read body is retained for restart even after the bounded retrieved-body
map evicts it. Import/score re-enter their original handlers to revalidate current
inputs; workspace URL/content identity prevents duplicate applications/snapshots,
and persisted analysis fingerprints/caches prevent repeated scoring effects.
No separate business logic or provider cache is introduced.

Six crash tests interrupt after effects and after checkpoint persistence at each
of read/import/score. They reconstruct `TaskRepository` and `CareerHarness` over
real SQLite, resume, and assert one remote read, one actual analysis, one saved
application, unchanged version on repeat, and no recommendation. They simulate
process interruption with a `BaseException`; they do not kill an OS process.
Additional checks cover body eviction, tracking URL aliases, saved-body import
on blocked sources and changed-resume failure. A prior score is not reported as
completed when revalidation for changed inputs fails.

A composite that adds no evidence returns `no_new_evidence`; repeating it after
granular processing reaches the existing no-progress stop. Checkpoint writes are
not treated as evidence. Source/candidate rejections retain their original
no-progress semantics.

## Failure parity

| Path | Unchanged granular outcome | Composite addition / preserved state |
|---|---|---|
| Blocked source | `source_blocked`, original `source`, `next`, `no_new_evidence` | `failed_step=read_job`, no import/score; existing source health applies |
| Not-current vacancy | `candidate_rejected`, `rejection_code=not_current_vacancy`, candidate/body evidence and `next` | Reject recorded through original handler; no import/score |
| Unreadable rendered body | Exact original error and `tool_error` / `next` | `failed_step=read_job`, granular fallback recorded |
| Scoring failure / missing resume | Exact original error mapping and `next` | Read/import preserved, `failed_step=score_job`, fallback recorded |
| Provider budget stop | Original `TaskProviderBudgetExceeded` control flow and reason | Propagates without conversion/retry; original task error adds completed read/import and failed score; zero provider attempts at exhausted budget |

Ordinary exceptions receive `completed_steps` and `failed_step` without replacing
error codes or guidance. Only internal/validation failures add `fallback` with an
instruction to use the granular tools and inspect saved work. Returned error
outcomes are also recorded and stop the sequence. Provider-budget control flow
continues to the existing task-loop budget handler rather than becoming a
retryable tool error; the task error gains the same completed/failed step metadata.

## Validation and reproduction

| Run | Passed | Skipped | Failed | Setup errors |
|---|---:|---:|---:|---:|
| Fixed base, complete suite | 1983 | 132 | 9 | 4 |
| Implementation, complete suite | 2026 | 132 | 9 | 4 |

**Zero new failures, zero added/removed skips, zero changed skip reasons.**
All 13 shared failure/error messages are identical. The 43 added stage-4 cases
all pass in the complete run. Both suites additionally report four passing subtests.
Base duration: 738.75 seconds; implementation: 784.21 seconds; these sequential
offline test-suite durations are not production latency measurements.

The request matrix passed **41 cases under each of default and stage-2 settings**.
Two end-to-end budget cases were then added; final budget checks passed **5 cases
in each setting** (three overlap with the initial matrix). The complete final suite
includes all 43 unique stage-4 cases. No stage-4 tests are skipped.
An initial budget fixture attempt left its unrelated seed task queued, allowing
service recovery to consume the script. The fixture now cancels that seed before
starting its own replay, as the existing B6 fixture does; all assertions remain.
The initial and corrected logs are retained as `budget.log` and `budget-final.log`.

Unchanged sandbox failures (each exact test name/message is in regression.json):

- Four `test_auto_apply_review_fixes.ChromeChecks` setup errors: confirmation
  negative/positive, one-submit confirmation, standard-answer edits, and URL
  without receipt. Windows pipe creation fails with `WinError 5`.
- Four `test_browser_runtime_recovery` failures: parallel owner/last close,
  changed URL/control refresh, closed Chrome recovery, and repeated transport
  failure. The last observes `PermissionError` instead of its injected
  `TargetClosedError` because pipe creation fails first.
- `test_mcp_app::test_fastapi_lifecycle_health_effective_tools_and_snapshot`:
  required local stdio server cannot start.
- Four `test_mcp_runtime` failures: local stdio end-to-end, timed-out connection,
  owned-thread execution, and concurrent session calls. Local pipe/server startup
  is denied.

These tests were neither patched nor skipped. A reviewer run outside the sandbox
is still needed to establish an entirely green full suite for this implementation.

Every skip and its reason, plus named sandbox failures, is listed in
[regression.json](regression.json). Full logs, JUnit XML, per-request metrics,
scoring hashes and source protection hashes are under
`.codex-runs/opt-v3-stage4/`. No base tests, skip conditions, timeouts, correctness
thresholds or acceptance scripts were weakened.

```powershell
.venv/Scripts/python.exe docs/benchmarks/opt-v3-stage4-20261011/run_matrix.py
.venv/Scripts/python.exe docs/benchmarks/opt-v3-stage4-20261011/run_offline.py -q -ra -p no:cacheprovider --basetemp=.codex-runs/opt-v3-stage4/reproduce-full --junitxml=.codex-runs/opt-v3-stage4/head.xml
.venv/Scripts/python.exe docs/benchmarks/opt-v3-stage4-20261011/regression.py
```

`regression.py` expects `base.xml` from the archived fixed base using the same
wrapper (`OPT_TEST_ROOT` set to the base checkout and cwd inside it). Full suites
are run sequentially to avoid timing-test contention. Existing `.codex-runs/b6-evidence/`
files and `tmp/` are not modified. `.env`, the three untracked LIVE sample
directories remain unchanged by this task. SHA-256 checks found that the protected
stage-1b spec and optimization-plan edit were updated externally at 21:52:04 local
time during this run. This task did not write, stage, restore or commit them;
their current versions are preserved. The three LIVE sample directories still
match the initial hashes. Details: `protected-observation.json` in the evidence directory.

## Delivery

The original `.git` is read-only. Commits are made in an independent Git directory
under `.codex-runs/opt-v3-stage4/submission.git`, with read-only alternates for base
objects. The original HEAD/index is unchanged; no push occurred.

Feature/test commit: `9cbe0b0310d11681988a56014188e38a2e830f19`.
The report/reproduction commit, both commit IDs, bundle SHA-256 and verification
result are recorded in `.codex-runs/opt-v3-stage4/delivery.json`.
Bundle: `.codex-runs/opt-v3-stage4/stage-4-workflows.bundle`.
Only the six implementation/test/configuration files and this stage-4 benchmark
directory are included; protected user files are excluded.

In a clean checkout at the fixed base:

```text
git bundle verify /path/to/stage-4-workflows.bundle
git fetch /path/to/stage-4-workflows.bundle opt-v3-stage4
git merge --ff-only FETCH_HEAD
```

Do not merge the bundle over the already-edited sandbox working tree.
