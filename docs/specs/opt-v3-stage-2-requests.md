# Optimization v3 · stage 2: low-risk request optimization

Parent plan: `docs/specs/optimization-plan-v3.md` (Chinese; sections 1, 2.1 correctness gate,
3 "2 低风险请求优化", 4). Offline only; no paid calls. Every change behind one flag; the
reviewer decides defaults from your evidence.

## Measured starting point (B6 offline replays, characters, not tokens)

Composition averages (`docs/benchmarks/opt-stage0-20261011/README.md`):

| Replay | System | Tools | History | Snapshot | Total |
|---|---:|---:|---:|---:|---:|
| r1 | 14,105 | 11,196 | 2,955 | 19,082 | 47,339 |
| r2 | 14,078 | 10,662 | 2,721 | 14,788 | 42,249 |
| correct | 13,965 | 11,017 | 2,922 | 13,141 | 41,046 |

Prefix stability (`docs/benchmarks/opt-v3-stage0-20261011/README.md`):
- The first replayed group changes on 17/19 (r1), 8/10 (r2), 8/10 (correct) consecutive requests.
- Almost all of that is **request-layer** trimming (16/19, 7/10, 6/10). The persistent window drops
  groups the request layer had already omitted.
- The tools array changes on 1–2 of 10–19 pairs; the system prompt changes on 0–1.

Two trimming layers:
- persistent `ConversationWindow._trim` (`agent_runtime/loop_context.py`, 8 groups / 24,000 chars);
- request copy in `request_context.prepare_request` (`replay.groups.pop(0)` until under `max_chars`).

## What to build

1. **Snapshot de-duplication and body references** (`JOB_AGENT_OPT_SNAPSHOT_REFS`).
   - Inventory what the live snapshot carries per request and what is duplicated with history,
     tool results or other snapshot keys (e.g. research pages vs `known_results` vs
     `search_candidates`, repeated job bodies, progress history).
   - Keep inline the facts the model must always see: user constraints and authority, current
     request, resume summary, candidate identities/health, blocked sources, scored/recommended
     summaries, `must_decide` / `completion_required`.
   - Large bodies (JD text, page text, old tool results, assistant progress history) become archive
     references readable through the existing `read_context`, with a one-line summary inline.
   - Prove necessary facts remain reachable: for each B6 replay, every fact the scripted decisions
     depend on is either inline or one `read_context` away, and qualification/scoring inputs are
     unchanged (they are read from storage, not from the snapshot).
2. **Stable, slimmer tool groups** (`JOB_AGENT_OPT_STABLE_TOOLS`).
   - Remove redundant text in tool descriptions and schemas (measure chars before/after; keep the
     behavioural constraints).
   - Make the tool array stable within a task: one deterministic group per task kind, with
     availability enforced at execution time. Restrictions (`must_decide`, `completion_required`,
     recommendation-run and search-only narrowing, browser tools without a page) stay hard: a
     disallowed call is rejected with the same guidance and no side effects, counts toward the
     no-progress breaker as today, and the live snapshot states the currently allowed set.
   - If a restriction cannot be safely moved to execution time, keep it in the array and say why.
3. **Fixed prompt de-redundancy** (`JOB_AGENT_OPT_PROMPT_TRIM`).
   - Remove duplicated or contradictory rules in the career system prompt
     (`agent_runtime/career/prompt.py`) and anything volatile in it. List every removed rule and the
     test or replay that still covers the behaviour.
4. **History trimming: compare strategies across both layers** (`JOB_AGENT_OPT_HISTORY_POLICY`
   = `current` | candidates you design). Evaluate at least:
   - `current`;
   - a checkpointed policy where the persistent window and the request copy agree on one eviction
     boundary that moves in large steps (so consecutive requests share the history prefix);
   - aligning the persistent window's budget with the request budget so the request layer rarely
     trims.

   For each: per-request total chars, first-group change rate, max request size vs `max_chars`,
   orphan-free tool groups, and protection of the latest user message and protected evidence.
   Pick one with evidence. Do not change `max_chars` limits to make numbers look better.

## Gates (business results)

- B6 offline replay (`tests/test_b6_offline_replay.py`) and directory replays
  (`tests/test_board_directory_replay.py`): the same business outcomes (qualified recommendations,
  acceptance results, honest stops). Identical tool traces are **not** required. If a scripted
  replay cannot express the new tool surface, adapt the script minimally and explain it.
- Whole-task input: total request chars per B6 replay go down with the chosen flags on (report
  the per-replay percentage); no single request exceeds `max_chars`.
- Correctness gate (plan 2.1) untouched: no change to scoring inputs, catalogue, qualification.
- With every new flag off, requests are byte-identical to the base commit (test).
- Regression: fixed base commit, **no new failures**, every skip with a reason; sandbox-only
  named-pipe failures listed, not changed. Reviewer reruns outside the sandbox
  (base `eac1c0a`: 1978 passed, 132 skipped, 0 failed).

## Rules

No paid/live runs or network. Don't weaken tests, thresholds,
`scripts/remaining_search_acceptance.py`, or the replays' acceptance. Don't touch `.env`, `tmp/`,
or existing files in `.codex-runs/b6-evidence/` (put your own artifacts under
`.codex-runs/opt-v3-stage2/`). Use public library APIs only. Specific `git add`, small commits, no
push; bundle if `.git` is read-only. Document flags in `docs/configuration.md`.

## Report must answer

1. Snapshot inventory: what was duplicated, what moved to references, what stays inline and why.
2. Tool and prompt chars before/after; each restriction moved to execution time and how it is
   enforced; removed prompt rules with their covering test.
3. History policy comparison table and the chosen policy.
4. Per-replay whole-task chars before/after with all chosen flags; business outcome of each replay.
5. Recommended default per flag; base commit, new failures (none), skips, commits or bundle.
