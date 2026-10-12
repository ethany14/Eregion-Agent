# Optimization v3 stage 2: offline request optimization

Fixed base: `6691b0bb75651aa71d40b8287f086411623025a9` (HEAD at task start).
The reviewer's `eac1c0a: 1978 passed, 132 skipped, 0 failed` is an outside-sandbox
reference, not a substituted base. No paid/live runs. Frozen web, scripted router,
offline scoring and the original acceptance evaluator were used throughout.

## Snapshot inventory and reachability

| Content | Duplication and treatment with SNAPSHOT_REFS |
|---|---|
| goal, initial_goal, known_results.request | Only exact duplicates of the current user text become a pointer to current_request.message. That original remains inline. |
| research_pages | Already projected to URL/title/blocked, 400-character excerpts and at most six links. Long excerpts/bodies become per-body archive references plus one-line summaries. Identity, health and links remain. The archive stores the original supplied projection; it does not pretend an already-truncated excerpt is a complete webpage. Existing tool archives retain complete source results. |
| browser | Long text/preview fields become references; observation ID, controls, regions, URLs and block state stay inline. |
| jobs and recommendations | Only explicit long body fields move. IDs, scores, qualification evidence and recommendation summaries remain inline. |
| history / decision_history | Payloads repeat large results or archived summaries. Keep event identity, error/status/next-step summaries; reference the original payload. Existing context_ref is reused rather than archived again. |
| assistant progress | Archive older assistant updates; retain user messages, the latest two assistant messages and the assistant message preceding the latest user. |
| known_results / search_recovery | Keep candidate/scored/excluded identities and health. Shorten only the instruction duplicated by the system prompt. search_candidates is not copied directly into the snapshot: recovery projects it. Persistent registries are untouched. |
| protected facts | Current request/authority, constraints, candidate, existing resume summary policy, blocked sources, qualification/scored summaries, must_decide/completion_required remain. Already-read context_evidence is exact and unmodified. |

Existing `ContextArchive.reference/read` provides content-addressed originals.
A target field/range is directly readable with ref/path/offset. A read is capped
at 3000 characters: one-step access to a target fact does not mean an arbitrary
long document fits in one response. Tool archives and durable scoring storage
are not passed through this projection.

The unchanged B6 scripts consume observation IDs, imported URL/IDs, actual scores
and earlier read references. They still resolve those facts from the production
request at each step. `test_body_refs_and_protected_facts` checks moved originals
and actual read output. `test_history_protects_current_user_and_original_evidence`
checks the latest user and exact accessed evidence under all three policies.
`measurements.json` records equal per-replay scoring schema/system/content hashes
across every configuration. Acceptance outputs are equal after removing only
run-generated application IDs. Scoring, catalogue, qualification, acceptance and
original replay test files were not edited. No script adaptation was necessary.

## Tools, prompt and execution restrictions

For the same full tool set (controls + career/browser + read_context), serialized
characters fall **20,266 -> 18,669**. Fixed career prompt: **13,912 -> 8,913**.
Actual requests additionally contain the existing authority and accessed-evidence
instructions. The latter can still change the system prefix once; no cache-hit
claim is made. No time/budget/live-job values enter the fixed career prompt.

Schema changes remove display titles and normalize descriptions, preserving real
`title` parameters, defaults/enums/examples and all validation constraints. The
original schemas still validate execution. Tool groups are deterministic for
ordinary career, search-only and recommendation task kinds. A new user request
may change kind; browser/progress/budget changes do not change that kind's array.
All B6 arrays have zero changes when STABLE_TOOLS is enabled.

| Restriction | Enforcement |
|---|---|
| must_decide | Original read/control exclusions remain in the execution mask. |
| completion_required | Only finish_task and ask_user remain executable. |
| recommendation / search-only | Original narrowing is both retained in the static task group and enforced by the live mask. No application/material authority is added. |
| no browser page | Only browser_open is executable among browser tools. |
| visual/screening configuration | Definitions may exist; disabled capabilities remain excluded by the mask. |
| already-forwarded application reply | Original duplicate-forwarding restriction remains. |

TaskHost preserves the old filtered list as `allowed_tools`; AgentLoop exposes
its names in the live snapshot and validates against the original list **before**
progress, intent persistence, archive reads or host effects. Rejection retains
the same tool_arguments guidance, with no effects, and marks no new evidence for
the existing durable breaker. Parametrized mask tests cover each restriction;
real loop tests cover forbidden writes/reads and the breaker. No restriction
needed to be relaxed. Static task-kind narrowing is retained to avoid irrelevant
capabilities and request cost, not as a replacement for execution enforcement.

### Removed duplication and covering checks

No unique permission or business rule was intentionally removed. Other text was
compressed with the same constraints. These tests establish mechanisms/business
outcomes, not real-model comprehension quality of rewritten prose.

| Removed duplicate expression | Remaining rule and coverage |
|---|---|
| Current versus historical request authority | prepare_request authority + observed outcomes; fixed-base byte comparison and task-loop authority regression |
| Change source when blocked, repeated in several paragraphs | Search/source-health rule; B6, directory replays, test_remaining_phase4.py |
| Do not invent eligibility or fill quota with invalid jobs, repeated | Qualification rule; test_remaining_posting_qualification.py and r1/correct acceptance |
| Mechanical tool arguments, path/pagination and browser region instructions | Schemas/descriptions; slim-schema constraints test, shared-agent-loop tests, B6 read_context |
| Screening is advisory, not eligibility | screen_jobs description + qualification rule; existing screening/qualification tests and B6 |
| Batch scoring shares resume; use actual results | Tool descriptions + score uncertainty rule; identical scoring-input hashes and acceptance |
| Public browsing needs no resume; ordinary recovery needs no approval | Authorization paragraph + browser_open/recovery rules; career/browser regression |
| Context reread/trust/fresh-observation instructions repeated | Context paragraph + read_context description; context evidence/progress tests |
| Mechanical material/interview field instructions | Schemas; prompt retains approval, grounded facts, exact question ID and real user-answer constraints; application-pack/interview/career regression |

## Both history layers: comparison

The next table enables all three boolean flags and varies only history policy.
Denominator is consecutive requests in the same task (N-1). Both first-group
identity and complete group hash were checked; their change counts agree here.
Full per-request characters, composition, eviction counts and hashes are in
`measurements.json`; no max_chars limit was increased.

| Policy | r1 chars / first-group changes | r2 chars / changes | correct chars / changes | Maximum request |
|---|---:|---:|---:|---:|
| current | 873,777 / 6/19 | 444,694 / 6/10 | 428,783 / 5/10 | 47,956 |
| checkpoint | 871,413 / 6/19 | 431,193 / 4/10 | 424,146 / 4/10 | 47,956 |
| aligned | 873,777 / 6/19 | 438,417 / 6/10 | 427,683 / 6/10 | 47,956 |

r3 is identical for all policies: 54,387 chars, 1/1 change, maximum 28,836.
Checkpoint evicts half the persistent window on pressure and commits the request
boundary, reserving additional half-window headroom when possible. Aligned derives
the persistent budget from remaining request space and saves it for restart.
Request-layer evictions for r1/r2/correct: current **79/19/23**, checkpoint **19/9/9**,
aligned **2/0/1**. Thus alignment actually makes second-layer trimming rare.
Checkpoint counts synchronized eviction once rather than repeatedly trimming the
same persistent prefix on subsequent requests.

Choose **checkpoint** for lowest whole-task input and fewer prefix changes on
r2/correct. Every policy preserves whole exchanges, the latest user and accessed
original evidence. However, optimized r1 has **13/20 requests with no replay
history**, including the first. Some apparent prefix stability is empty history,
not demonstrated provider caching. Evidence remains in live state/archives.

## Whole-task business gate

All-boolean-flags-on plus checkpoint, with the unchanged 48,000-character limit:

| Replay | All off | All on + checkpoint | Reduction | New maximum | Unchanged business outcome |
|---|---:|---:|---:|---:|---|
| r1 | 957,736 | 871,413 | 9.01% | 47,956 | Two recommendations but only one qualified; Associate caveat retained, expected acceptance failure |
| r2 | 464,684 | 431,193 | 7.21% | 45,472 | Zero qualified; no-progress needs_input, honest stop |
| r3 | 57,836 | 54,387 | 5.96% | 28,836 | Zero qualified; honest no-match completion |
| correct | 458,002 | 424,146 | 7.39% | 44,384 | Two qualified, acceptance passes |

Directory positive remains two qualified; directory negative remains zero with
coverage disclosure. Current-base source-health fields differ from old stage-0
measurements, so those older averages are not reused as this base. Base r1 has
**11 requests over limit, maximum 57,286**; the optimized replay has none.

Stable tools cost 11,433 per B6 request versus base averages of
11,338 / 10,804 / 7,184 / 11,159 for r1/r2/r3/correct. A slimmer equivalent set
is not necessarily fewer characters than a dynamically narrowed set. Some live
snapshot averages increase as evicted replay results return to live history or
more summaries fit; the gate measures the whole task, not one chosen component.

## Recommended defaults (not automatically enabled)

| Flag | Recommendation | Reason |
|---|---|---|
| SNAPSHOT_REFS | 1, with the validated combination below | Direct source access and protected facts pass; duplicates move out of repeated input. |
| PROMPT_TRIM | 1 | Removes 4,999 fixed characters while preserving covered boundaries. Real-model quality is not asserted. |
| HISTORY_POLICY | checkpoint | Best measured total/prefix tradeoff across both layers. |
| STABLE_TOOLS | 0 | Implemented and fully tested, but larger arrays can outweigh slimming; no actual cache benefit was measured. Keep opt-in for cache experiments. |

The separately validated recommended combination (refs=1, trim=1,
policy=checkpoint, stable=0) improves further:

| Replay | Whole-task chars | Reduction vs base | Maximum request |
|---|---:|---:|---:|
| r1 | 862,135 | 9.98% | 47,896 |
| r2 | 424,383 | 8.67% | 45,180 |
| r3 | 45,399 | 21.50% | 24,342 |
| correct | 416,732 | 9.01% | 44,092 |

Business outcomes and scoring-input hashes are identical here too. Production
defaults remain **0/0/0/current**, as required for reviewer choice. Flags are
independent; arbitrary protected inputs may still overflow, which remains visible.
Turning a flag off restores legacy construction, not already-evicted history.

## Verification and reproduction

Each of off/current/checkpoint/aligned/recommended: **25 passed, 1 skipped**.
The skip explicitly disables the paid B6 model lane. Seven final focused checks
also pass (base bytes, restriction masks, schema preservation).
After retaining explicit plan/history-reading guidance, each enabled configuration
was remeasured: 5 passed per configuration. All 44 flag-off B6 requests also
passed byte-for-byte comparison against the fixed base request/window code
(plus the fixed-input prompt/window regression).
Full regression details and delivery hashes are recorded in the accompanying
regression/delivery evidence. Raw XML/logs are under `.codex-runs/opt-v3-stage2/`.

```powershell
.venv/Scripts/python.exe docs/benchmarks/opt-v3-stage2-20261011/run_matrix.py
.venv/Scripts/python.exe docs/benchmarks/opt-v3-stage2-20261011/summarize.py
.venv/Scripts/python.exe docs/benchmarks/opt-v3-stage2-20261011/run_offline.py -q -ra -p no:cacheprovider --basetemp=.codex-runs/opt-v3-stage2/reproduce-full
```

The wrapper ignores repository dotenv configuration, supplies constructor-only
fake credentials, disables paid opt-ins and blocks external socket connections.
The fixed base was extracted with git archive under the new artifact directory.
`.codex-runs/b6-evidence/` was never written: all three source DB SHA-256 hashes
match the pre-existing stage-0 manifest. `tmp/` and `.env` were not modified.
The three untracked main-stability-LIVE-sample-20261011 directories remain untracked.

Character reductions are not token/cost measurements. Scripted decisions and
frozen sources do not establish live reasoning quality, latency or cache hit rate.


### Full regression: raw results and final reconciliation

| Run | Passed | Skipped | Failed | Setup errors |
|---|---:|---:|---:|---:|
| Fixed base, full suite | 1965 | 132 | 9 | 4 |
| Implementation, initial full suite | 1975 | 132 | 10 | 4 |
| Final combined coverage (full + final focused/isolated reruns) | 1982 | 132 | 9 | 4 |

The combined line is explicitly **not** a second full-suite run. Six additional
boundary/schema cases were added after full-suite collection and passed in final
focused runs. The original eleven added cases were included in the full run.
No base tests were removed. Every one of the 132 skips and its exact reason is
listed in `regression.json`; there are no new skips or changed skip reasons.

The one initial new failure was
`test_mcp_app::test_sync_session_execution_does_not_block_fastapi_event_loop`:
0.9121532 seconds against the unchanged 0.5-second threshold. Base and head suites
had overlapped, so load contention is a plausible cause, not a proven assertion.
After all large runs settled, isolated fixed-base and implementation reruns both
passed. No implementation, assertion, timeout or threshold was changed for it.
The original failure and both reruns remain in `regression.json` and raw XML.
There are **no unresolved new failures** after this paired check.

Unchanged sandbox failures, never patched or skipped:

- Four `test_auto_apply_review_fixes.ChromeChecks` setup errors: confirmation
  negative/positive, one-submit confirmation, standard-answer edits, and URL
  without receipt. All fail with WinError 5 while establishing browser pipes.
- Four `test_browser_runtime_recovery` failures: parallel owner/last close,
  changed URL/control refresh, closed Chrome recovery, repeated transport failure.
  Pipe creation is denied; the last consequently observes PermissionError rather
  than the injected TargetClosedError.
- `test_mcp_app::test_fastapi_lifecycle_health_effective_tools_and_snapshot`:
  required local stdio server cannot start in the sandbox.
- Four `test_mcp_runtime` failures: local stdio end-to-end, timed-out connection,
  owned-thread execution, and concurrent sessions. Denied pipe/server startup.

These thirteen base failures/errors account for the gap from the reviewer's
outside-sandbox reference. Outside-sandbox rerun remains necessary to turn that
reference into a claim about this implementation's complete green suite.

### Delivery

The workspace's original `.git` is read-only. Changes are committed in an
independent Git directory under `.codex-runs/opt-v3-stage2/submission.git`, using
read-only alternate access to base objects. The original branch/HEAD did not move;
no push occurred. A local clone attempt also hit the sandbox's shell mapping
restriction, so the independent repository was initialized without a clone helper.
The final `stage-2-requests.bundle` and `delivery.json` are in
`.codex-runs/opt-v3-stage2/`; the latter records commit IDs and bundle SHA-256.

In a clean checkout of the fixed base, review/import with:

```text
git bundle verify /path/to/stage-2-requests.bundle
git fetch /path/to/stage-2-requests.bundle opt-v3-stage2
git merge --ff-only FETCH_HEAD
```

Do not run that merge over the already-edited working tree from this sandbox.
