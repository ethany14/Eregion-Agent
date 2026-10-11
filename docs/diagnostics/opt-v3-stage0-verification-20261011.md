# Optimization v3 stage 0 verification

Scope: `docs/specs/opt-v3-stage-0-calibration.md`; offline, no paid calls.
Base is the task-start HEAD `72e0da611d40c58a4583f7bf8760a50d68fcd03d`.
The reviewer's external full run at `ad4daba` (1913 passed, 132 skipped, zero
failed) is supporting evidence, not a substitute for the fixed-base comparison.

## Default-behaviour audit

| Change audited | Finding and final behaviour | Offline proof |
|---|---|---|
| Shared sync/async reasoning rejection | Fixed default drift: no retry unless `JOB_AGENT_REASONING_REJECTION_RETRY=1` and a reasoning value is configured. Opt-in fallback is separately metered and uncacheable. | `test_rejection_default_and_opt_in` (sync/async, enabled/disabled/absent value); existing plain-fallback and cache tests |
| FastDecisions and Jev reasoning rejection | Same drift fixed in both independent transports. Their failed HTTP response remains one attempt by default. | `test_typesafe_default_rejection_one_attempt`; `test_typesafe_plain_fallback_is_bounded`; escalation-plus-fallback attempt test |
| Mock interview exception | Existing default compatibility retry retained, including concrete shared client. No new interview default level. | `test_interview_retains_legacy_retry_without_flag`; full mock-interview suite |
| `batch_retry` | Identical by default: existing timeout/unavailable retry remains bounded; schema errors do not acquire an extra retry. | `test_default_structured_and_batch_retry`; existing batch/escalation tests |
| `invoke_structured` loop | Identical by default: one success/parser attempt, unchanged message layout and purpose legacy settings; opt-in escalation owns additional schema retries. | `test_default_structured_and_batch_retry`; `test_default_payload_bytes_and_override_precedence` across the purpose matrix |
| `analysis_cache` future tuple | Identical by default: tuple is internal; callers receive independent copies of the same value, concurrent computation is shared, durable reuse survives recreation. | `test_default_analysis_future_and_durable_cache`; existing uncacheable/in-flight cache tests |
| FastDecisions digest/namespace | Fixed additional drift: stage 0–1 unconditionally appended empty reasoning/false-policy fields. Restored the pre-`e5127b4` hash inputs when new configuration is absent. | `test_fast_default_identity` checks exact legacy namespace and payload digest and a subsequent cache hit |
| Both trimming layers | Identical by default: limits, removal decisions, messages and tools unchanged. Added persistent counters across slice restart and request/group hashes. | `test_two_layers_count_without_changing_messages`, `test_window_pending_counter_survives_slice_restart`; all four unchanged B6 replays and exact old/new composition averages |
| Task budget defaults | Limits unset retains provider dispatch, unknown-usage tolerance and existing router budget. Summary fields are additive. | `test_unset_budget_retains_unmetered_and_unknown_usage`; task-loop and usage tests; full fixed-set comparison |
| Configured SDK retries | Additional accounting gap fixed: SDK retries are now individually recorded/reserved, using the installed SDK's retry eligibility and delay rules; default factory retry count remains zero. | `test_sdk_transport_retries_are_individual_attempts` (sync/async, capped/uncapped); retry request bodies are identical; `test_transport_retry_does_not_reenable_reasoning_after_fallback` |

Existing compatibility tests were updated to explicitly opt in to the behaviour
they exercise; assertions were retained. No acceptance test or threshold was
weakened. No new reasoning value or trimming strategy was enabled.

## Metrics and budgets

Per-replay prefix attribution, tools/system hash changes, attempts and zero-token
counters are in [the benchmark report](../benchmarks/opt-v3-stage0-20261011/README.md).
Literal first-message hashes and complete first-group hashes are reported
separately: the repeated historical user wrapper hides later prefix movement.
Attribution checks group identity so persistent eviction of an already omitted
group is not mistaken for the cause of a new request prefix. Regression tests
cover independent task histories and this counterexample.

Provider limits derive from ledger rows, not a second in-memory counter.
SQLite `BEGIN IMMEDIATE` serializes check-and-reserve across connections/processes.
Pending and failed attempts consume capacity; completed known usage replaces
the conservative input reservation. Historical unknown input without reservation
cannot silently bypass an enabled input limit. Limits apply before dispatch,
including nested calls, with no interruption of a database write or tool effect.
The task retains saved work and an honest durable `needs_input/provider_budget`
status. Restart and `continue` do not reset the ledger.

Budget stop is control flow that semantic fallback handlers cannot swallow. The
async provider adapter translates this signal only across LangChain's gather
boundary, then restores it for the task host. Tests cover the async SDK retry
boundary as well as a real TaskLoop stopping inside nested scoring after saving
work. No completion statement is published for the unfinished task.

Input-token reservation is deliberately conservative (serialized text UTF-8 bytes
plus framing allowance). It can stop early; it is not an exact prediction of an
arbitrary remote tokenizer. Unsupported image/audio estimation stops closed under
an input cap. Provider-reported `input_tokens`, reservation-inclusive
`budget_input_tokens`, retries and `provider_attempts` are separate public summary
fields. See [configuration](../configuration.md).

## Fixed-version regression and delivery

Runtime/tests fixed at `f56bf337693e7bde025248d8a37c3f44b87d45b1`.
The final full command uses the same test collection and offline bootstrap as the
base archive. It does not exclude named-pipe tests. Detailed node IDs, all skip
reasons, collection hashes, missing/added tests and failure differences are stored
in [verification.json](../benchmarks/opt-v3-stage0-20261011/verification.json).

Base sandbox full run: **1900 passed, 132 skipped, 9 failed, 4 errors**,
plus 4 passing subtests (not added to the pytest passed count), in 1021.48 seconds.
The 13 failing/error cases are the documented sandbox exception set:

- `test_auto_apply_review_fixes.ChromeChecks`: four named-pipe setup errors.
- `test_browser_runtime_recovery`: four browser/named-pipe failures.
- `test_mcp_app`: one tool-registration assertion after sandbox-denied server startup.
- `test_mcp_runtime`: four stdio/named-pipe failures.

The tests are retained and unchanged. The reviewer must rerun outside the sandbox.

Final sandbox full run: **1927 passed, 132 skipped, 9 failed, 4 errors**,
plus 4 passing subtests, in 1347.73 seconds. **No new failures**: all 13 failing/error
node IDs exactly match the base. All 2045 base test cases remain present; 27 new
calibration cases pass. There are no new skips. A dependency deprecation warning
(`starlette` / `anyio.BlockingPortal`) is present in both runs.

All 132 skips have individual node IDs and reasons in `verification.json`:
118 browser opt-ins, 12 explicit live/configured-model/evidence opt-ins,
one unavailable-platform symlink case, and one deliberately unexecuted original
revision lane. Neither thresholds nor opt-in/skip policies were changed.
The final documentation-only commit does not change the tested runtime or tests.

Targeted verification: 203 passed, 1 skipped, followed by the additional concrete
interview-default test (1 passed). The targeted skip is the unchanged explicit
paid B6 lane. Logs/JUnit are `.codex-runs/opt-v3-stage0/calibration-final.log|xml`.
The full suite includes that extra test. Base logs/JUnit are `base.log|xml` and
the final fixed-version run is `full-verified.log|xml` in the same directory.
An earlier full-run launch was cancelled while refining prefix attribution and
is not used for the regression gate.

The offline wrapper removes paid opt-ins, ignores only the repository `.env`,
provides fake constructor credentials, blocks external socket connections and
uses sandbox-compatible new temporary directories. It never reads `tmp/`, alters
existing ACLs, or weakens assertions. The base is an archive of the exact starting
commit, run through the same wrapper with `OPT_TEST_ROOT` selecting that archive.
The equivalent bootstrap is included at
`docs/benchmarks/opt-v3-stage0-20261011/run_offline.py`; only its repository-root
path offset differs from the local wrapper used in these runs.

Direct `git add` was denied (`.git/index.lock: Permission denied`). A writable
bare repository at `.codex-runs/opt-v3-stage0/delivery.git` holds the task commits;
existing Git objects were copied read-only, with the original base as parent.
Only explicit task paths were staged. No push was performed and the original
branch was not advanced. The final bundle and delivery manifest are
`.codex-runs/opt-v3-stage0/submission.bundle` and `delivery.json`.

Implementation commits:

- `1a0d09d`: default retry repair, both-layer metrics, durable provider budget.
- `d988042`: configuration and offline default/budget regression coverage.
- `f56bf33`: accurate prefix attribution by retained group identity and additional tests.

Final documentation/evidence commit is recorded in `delivery.json`, avoiding a
self-referential commit hash. `.env`, `tmp/`, the three untracked
`docs/benchmarks/main-stability-LIVE-sample-20261011*` directories and copied
evidence were left unchanged. Historical evidence DB SHA-256 values were rechecked.
