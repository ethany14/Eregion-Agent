# Optimization stages 0–1: per-attempt metrics and per-purpose reasoning

Parent plan: `docs/specs/optimization-plan-v2.md` (Chinese; sections 2, 4·阶段0, 4·阶段1, 6). Read it first.
This task implements **mechanisms and an audit only**. It changes no default model behaviour and runs
no paid calls; a later paid comparison (approved separately by the user) will choose new values.

## Background facts (verified 2026-10-11)

- Usage ledger: `agent_runtime/provider_usage.py` (`UsageLedger`, `usage_scope`, `adapter_attempt`)
  already records input/output/cached/reasoning tokens, retries, unknown usage per attempt.
- Request assembly: `agent_runtime/request_context.py::prepare_request` returns `context_metrics`
  (`loop_engine.py:140-142` stores it in `self.runtime['context_metrics']`, not in the ledger).
  Message order is `System(prompt) → history → Human(live snapshot)`.
- B6 measured request composition: System 13,368 chars, tools 739, replay 3,494, snapshot 42,732.
- Reasoning: `job_agent/model.py:124-129` applies `LLM_EXTRACTION_REASONING` for `extraction` and
  `LLM_AGENT_REASONING` for `agent`/`fast` only. All other purposes (e.g. scoring, pack writer
  `CoverLetter`, `ClaimDecisions` verifier, `job_screening`, `skill_evidence(_verify)`,
  `question_category`, `memory_relevance`, `form_options`, `browse`, `application`, `api`, `None`)
  send no reasoning setting, so the provider default applies. Interview calls use
  `LLM_INTERVIEW_REASONING` (default `low`) in `agent_runtime/mock_interview/model.py`.
- Live evidence: E5 cover letter ~8.2K output of which ~7.9K reasoning; A1 main-model sample
  238,553 input vs 517,877 output; C16 p50 110 s → 15.7 s after interview reasoning `low`.

## Stage 0 — per-attempt metrics (small)

1. Persist request composition per model attempt into the usage ledger: chars for system, tools,
   history/replay, live snapshot, repair; total; and whether history eviction happened this request
   (and how many replay groups were evicted). Attribute to the same attempt row as the tokens.
2. Timing split per attempt / per tool action: queue wait, provider duration, tool execution,
   persistence. Use monotonic clocks; do not use model-supplied timestamps.
3. Ledger summary gains: cache hit ratio (`cached_input_tokens / input_tokens`), reasoning share
   of output, per-purpose groups (already grouped by purpose — extend, don't duplicate).
4. A reporting script `evals/opt_report.py` that, given a task/run DB (career.db / usage sqlite),
   prints per-purpose tokens, cache ratio, reasoning share, composition averages and timing
   percentiles, and writes JSON. Make it work on the copied live evidence in
   `.codex-runs/b6-evidence/r1|r2|r3/career.db` (read-only) where the data exists; report what
   is missing for older runs instead of inventing it.
5. Run the B6 offline replay (`tests/test_b6_offline_replay.py`) and record composition metrics
   for its scripted runs (token counts are zero offline; chars are real) as the offline baseline,
   in `docs/benchmarks/opt-stage0-20261011/` (small JSON + short README).

## Stage 1 — per-purpose reasoning (mechanism + audit; defaults unchanged)

1. **Audit**: enumerate every model construction path and purpose (`create_model`, `shared_model`,
   interview model, pack/verifier models, fast decisions, scoring/Jev service, extraction). Produce
   `docs/diagnostics/opt-reasoning-audit-20261011.md`: purpose → call sites → model id setting →
   reasoning setting actually sent today (including "none sent / provider default") → output
   schema → quality gate that covers it.
2. **Config**: support `LLM_REASONING_<PURPOSE>` (upper-snake purpose, e.g.
   `LLM_REASONING_CLAIM_VERIFIER`) for every purpose found. Precedence: purpose-specific > existing
   variables (`LLM_AGENT_REASONING`, `LLM_EXTRACTION_REASONING`, `LLM_INTERVIEW_REASONING`) >
   nothing sent. With no new variables set, the request payload must be byte-identical to today
   (add a test proving it for each purpose). Reuse the existing allowed values and the existing
   "provider rejects reasoning → retry once without it" behaviour (see interview model).
3. **Escalation on validation failure** (opt-in, `JOB_AGENT_REASONING_ESCALATION=1`, default off):
   when a structured call fails schema validation, grounding verification, or the existing batch
   retry triggers, the single retry of that step uses one level higher reasoning (`low→medium`,
   `medium→high`; none-sent → unchanged). Never more than one escalation per step; record the
   escalation on the ledger attempt.
4. **Cache identity**: the effective reasoning level per purpose must enter every result-cache
   signature that already includes model identity (fit/analysis cache, Jev cache, extraction
   signature where relevant), so results from different levels never mix.
5. Document new variables in `docs/configuration.md`.

## Rules

- No paid/live runs (`JOB_AGENT_LIVE_*`, `JOB_AGENT_B6_REPLAY_LIVE_MODEL`, real providers). No network in tests.
- No default behaviour change: with no new env vars, every provider request is identical to before.
- Don't weaken tests, thresholds, `scripts/remaining_search_acceptance.py`, or the B6 replay.
- Don't read or modify `.env`. Don't delete or rewrite anything under `tmp/` or `.codex-runs/b6-evidence/`.
- Commit on the current branch with specific `git add` paths; small logical commits; don't push.
  If `.git` is read-only in your sandbox, produce a verified bundle as last time and say so.
- Full suite: known sandbox-only failures are the Windows named-pipe ones
  (`test_browser_runtime_recovery`, `test_mcp_app`, `test_mcp_runtime`,
  `test_auto_apply_review_fixes` ChromeChecks). Everything else must pass; the reviewer reruns the
  full suite outside the sandbox (baseline 1776 passed incl. B6 replay).
- Use `.venv/Scripts/python.exe`.

## Acceptance

- Ledger rows carry composition + timing for every career-loop attempt; offline tests prove it.
- `evals/opt_report.py` runs on the copied B6 evidence and on a replay DB.
- Audit document lists every purpose with the setting actually sent today.
- Byte-identical-payload tests per purpose with no new env; precedence and escalation tests.
- Cache-signature tests show different reasoning levels never share a cached result.

## Report must answer

1. The audit table (short form) and any purpose whose reasoning behaviour surprised you.
2. Offline baseline numbers (composition, eviction frequency) from the B6 replay and copied evidence.
3. Proposed starting values per purpose for the later paid comparison, with the quality gate for each.
4. Test and full-suite numbers, commit hashes (or bundle path).
