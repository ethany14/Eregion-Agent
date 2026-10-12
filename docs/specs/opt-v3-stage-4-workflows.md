# Optimization v3 · stage 4: fewer mechanical round trips

Parent plan: `docs/specs/optimization-plan-v3.md` (Chinese; sections 2.1 correctness gate,
3 "4 减少机械往返", 4). Offline only; no paid calls. Behind one flag, default off.

**Do not touch** `docs/specs/optimization-plan-v3.md` (it has uncommitted edits from another
session) or `docs/specs/opt-v3-stage-1b-treg-ab.md` (another session's untracked spec). Do not
`git add` them.

## Why

In B6 every verified job costs several router decisions in sequence: `read_job` → `import_job` →
`score_job` (→ `recommend_job`). Each decision re-sends the system prompt, tools, history and
snapshot (≈ 41–47K chars per request in the B6 replays; see
`docs/benchmarks/opt-v3-stage2-20261011/README.md`). The read → qualify → import → score part is
mechanical once the model has chosen a posting; the recommendation is a judgement and stays with
the model.

## What to build (`JOB_AGENT_OPT_VERIFY_AND_SCORE`, default off)

1. A composite career tool, e.g. `verify_and_score`, taking one posting (URL or an observed
   candidate / saved retrieved body reference, the same inputs `read_job` / `import_job` accept),
   optionally a small batch (≤ 5) that reuses `score_jobs`' shared resume context.
2. Steps, each through the **existing** handler code paths (no duplicated business logic):
   read (or reuse a saved retrieved body) → posting qualification (`posting_qualification`,
   identity, current vacancy, location) → import → score.
   - Stop at the first failing step and return that step's exact outcome (same error codes,
     `next` guidance, `rejection_code`, blocked-source handling, `candidate_rejected`), plus which
     steps completed.
   - Never auto-recommend. The result includes the score, qualification evidence and the
     seniority/opening-level evidence (`search_policy.opening_level`) so the model can decide
     `recommend_job` in its next decision.
3. **Checkpoints and idempotency**: each step persists as today (intent before effect where the
   existing tools do so). Re-running the composite after a crash/restart resumes from the last
   completed step: no duplicate import, no duplicate scoring (reuse existing idempotency keys and
   analysis caches), no duplicate provider spend beyond what the single tools would do.
4. **Governance unchanged**: candidate identity (`job_key`), source health, blocked sources,
   no-progress breaker (a composite with no new evidence is no-new-evidence), provider budgets
   (v3 stage 0) and stable tool groups (v3 stage 2: add the tool to the deterministic groups where
   `read_job`/`import_job`/`score_job` are allowed; enforce the same execution masks).
5. Granular tools stay available. Promotion/demotion in the spirit of Progressive Crystallization:
   if the composite fails for an internal/validation reason (not a business rejection), return a
   clear fallback instruction to use the granular tools, and record it; no silent partial state.
6. Prompt: one short rule — prefer the composite for a chosen posting when the flag is on; decide
   recommendation separately. Keep the prompt within the stage-2 budget.

## Gates (business results)

- B6 offline replay and directory replays: add composite variants of the scripted runs (the model
  calls `verify_and_score` instead of the three tools). Same business outcomes under the
  unchanged `evaluate_search` (r1: qualified 1 with "Level unverified" on Associate; correct path:
  passed with 2; directory blocked recovery: 2 qualified; non-qualifying directory: honest stop).
  Report router decisions and total request chars per replay versus the granular scripts.
- Crash/restart tests at each step boundary: no duplicate import/score, correct resume.
- Failure-path tests: blocked source, not-current-vacancy, unreadable body, scoring failure,
  budget stop — each returns the same outcome the granular tool would.
- Correctness gate untouched: qualification, catalogue and scoring inputs identical
  (compare scoring input hashes between composite and granular runs).
- With the flag off: tool arrays and requests byte-identical to the base commit (test).
- Regression: fixed base commit, **no new failures**, every skip with a reason. Sandbox-only
  named-pipe failures listed, not changed. Reviewer reruns outside the sandbox
  (base `4785931`: 1996 passed, 132 skipped, 0 failed).

## Rules

No paid/live runs or network. Don't weaken tests, thresholds, `scripts/remaining_search_acceptance.py`
or replay acceptance. Don't touch `.env`, `tmp/`, existing files in `.codex-runs/b6-evidence/`
(your artifacts go under `.codex-runs/opt-v3-stage4/`). Public library APIs only. Specific
`git add`, small commits, no push; bundle if `.git` is read-only. Document the flag in
`docs/configuration.md`.

## Report must answer

1. Tool contract and how each step reuses existing handler code.
2. Router decisions and request chars per replay: granular vs composite.
3. Checkpoint/idempotency design and the crash tests.
4. Failure-path parity table.
5. Base commit, new failures (none), skips, commits or bundle path.
