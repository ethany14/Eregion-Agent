# Optimization v3 · stage 0: calibration fixes

Parent plan: `docs/specs/optimization-plan-v3.md` (Chinese; sections 1–4). Read it first, and the
stage 0–1 audit/verification docs: `docs/diagnostics/opt-reasoning-audit-20261011.md`,
`docs/diagnostics/opt-stage01-verification-20261011.md`, `docs/benchmarks/opt-stage0-20261011/`.
Offline only; no paid calls; default behaviour must be byte-identical with new flags off.

## 1. Restore default behaviour of the reasoning-rejection retry

Stage 0–1 (`e5127b4`) extended "provider rejects the reasoning parameter → retry once without
it" from the interview model to every client: `ProviderCompatibleChatOpenAI._generate/_agenerate`
in `job_agent/model.py` and `FastDecisions._request` in `agent_runtime/fast_decisions.py`.
That changes default behaviour (an extra provider call on some errors).

- Keep it only where it existed before (interview model, `agent_runtime/mock_interview/model.py`).
- Elsewhere make it opt-in (`JOB_AGENT_REASONING_REJECTION_RETRY=1`, default off), and apply it
  only when a reasoning value was explicitly configured for that purpose.
- Tests: default off → a reasoning rejection raises exactly as before `e5127b4` (one provider
  attempt); opt-in → one retry without reasoning, recorded on the ledger and uncacheable.
- Check the other stage 0–1 runtime changes for any further default-behaviour drift
  (`batch_retry`, `invoke_structured` loop, `analysis_cache` future tuple, fast_decisions cache
  digest/namespace) and list each in the report as "identical by default" with the test proving
  it, or fix it.

## 2. Metrics cover both history trimming layers

There are two trimming layers:
- persistent `ConversationWindow._trim` (`agent_runtime/loop_context.py:56`, max 8 groups /
  24,000 chars, pops the oldest group on append);
- per-request copy trimming in `request_context.prepare_request` (~line 519, `replay.groups.pop(0)`).

Stage 0 metrics count only the request layer.

- Record per attempt: groups dropped by the persistent window since the previous request,
  groups dropped by the request layer, and a hash of the first replayed history message (so
  prefix changes are directly measurable).
- Extend `evals/opt_report.py`: per run, the share of consecutive requests whose history prefix
  changed, attributed to persistent vs request-layer trimming; also tools-array hash changes and
  system-prompt hash changes between consecutive requests.
- Re-run on the B6 offline replays and update `docs/benchmarks/opt-stage0-20261011/` (or a new
  `opt-v3-stage0-20261011/`) with these numbers. Do not change trimming behaviour in this task.

## 3. Budget covers every provider attempt

Today the loop budget (`agent_runtime/task_loop.py`, `model_calls` vs `_budget`) counts router
decisions only; nested provider attempts (scoring, extraction, Jev, writer/verifier, retries)
are not budgeted.

- Add attempt-level accounting per task: provider attempts, input tokens, retries, including
  nested and failed attempts (the ledger already has them — derive, don't duplicate).
- Add optional limits (`JOB_AGENT_TASK_MAX_PROVIDER_ATTEMPTS`, `JOB_AGENT_TASK_MAX_INPUT_TOKENS`;
  default unset = current behaviour). When a limit would be exceeded, stop before the next
  provider attempt with a durable, honest status (like the existing budget stop: saved work
  preserved, request not claimed complete), never mid-write.
- Expose the counters in the task view/summary used by the live B6 test (`settle_live` reads
  `UsageLedger.summary`) without changing its acceptance logic.
- Tests: nested scoring attempts count; retries count; failed attempts count; limit stops
  cleanly; default unset leaves behaviour unchanged; restart keeps the counters.

## Rules

- No paid/live runs or network. Don't weaken tests, thresholds,
  `scripts/remaining_search_acceptance.py` or `tests/test_b6_offline_replay.py`.
- Don't touch `.env`, `tmp/`, `.codex-runs/b6-evidence/`.
- Specific `git add`, small logical commits, no push; bundle if `.git` is read-only.
- Regression gate: fixed commit and test set; **no new failures** relative to the base commit; every
  skip has a stated reason. Known sandbox-only failures: Windows named-pipe tests
  (`test_browser_runtime_recovery`, `test_mcp_app`, `test_mcp_runtime`,
  `test_auto_apply_review_fixes` ChromeChecks) — list them, don't change them. The reviewer reruns
  the full suite outside the sandbox.
- Document new flags in `docs/configuration.md`. Use `.venv/Scripts/python.exe`.

## Report must answer

1. Each default-behaviour drift found and how it is now proven identical or fixed.
2. Prefix-change attribution numbers per B6 replay (persistent vs request layer, tools, system).
3. Budget counters for the B6 replays (scripted, so token counts are zero; attempts are real).
4. Base commit, test set, new failures (must be none), skips with reasons, commit hashes or bundle.
