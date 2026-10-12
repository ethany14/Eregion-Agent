# Unified loop · R3 / M3 validation: deterministic analysis and material workflows (2026-10-12)

Plan: [`claude-unified-execution-plan-20261012.md`](../specs/claude-unified-execution-plan-20261012.md) §M3; migration plan §M3. Previous stage: [`unified-loop-m2-validation.md`](unified-loop-m2-validation.md). Executor: Claude.

## Result

| Commit | Content |
|---|---|
| `d1d3b13` | `custom_agent` → `job_agent/workflow` (git rename), `AnalysisWorkflow.advance`, aliases, callers moved, guard tests |
| `269427a` | Verifier: a restated job requirement in a cover-letter opening is employer context (strict span rule) |
| `53a3c86` | Review follow-up: heading qualifiers inherited, Unicode negation, positive requirement cue required |

The work was developed in a detached worktree from `917f35a` (`<scratchpad>/m3wt`, now removed) and cherry-picked.

### Analysis workflow

The old `custom_agent.loop.AgentLoop` was already deterministic: fixed steps chosen by `TransitionPolicy`, with no model routing. M3 makes that explicit:

- **Neutral package:** `custom_agent/{errors,events,handlers,models,policy,repository,state,steps}.py` moved with `git mv` to `job_agent/workflow/`. The loop became `job_agent/workflow/analysis.py::AnalysisWorkflow`.
- **One checkpoint per step:** `advance(state)` runs exactly one computation step and persists its transition. `run_until_pause` only repeats `advance` until human review, and `review` is unchanged. The old `run_until_pause` loop body became `advance()` with the same statements, in the same order and with the same error handling. Transitions, events, revision limits, exact-quote recovery (`_execute_step`), human review and result projection are unchanged.
- **One executor:** `custom_agent.loop.AgentLoop` is now a name for the same class, not a second executor. The old modules are `sys.modules` aliases of the new ones, so ORM tables (`custom_agent_states` / `custom_agent_events`, unchanged names), monkeypatches and module state are shared rather than copied.
- **Callers moved:** production and tooling (`api/runtime.py`, `api/services/run_service.py`, `api/db.py`, `api/session_dependencies.py`, `api/services/fit_analysis_service.py`, `agent_runtime/{analysis_cache,application_pack/workflow,job_workflow/workers}.py`, `main.py`, `migrations/env.py`, `evals/*`, `scripts/*`) import `job_agent.workflow`. A guard test forbids `custom_agent` imports there and in `main.py`. Tests keep the old import paths on purpose, to prove the aliases.
- **No new model calls:** no router or model call was added. Parsing, scoring, verification and state advancement are the same handler calls as before.

### Material workflow and the L3 open item

**Material workflow:** `ApplicationPackWorkflow` (writer, verifier, bounded revision) is unchanged. `JOB_AGENT_OPT_MATERIAL_PATCHES` stays `0`.

**L3 diagnosis (offline, from the frozen paid sample `L3-full-r1`):**

- **Paragraph 2:** `"I have built Python APIs."` cited the right evidence. It failed only because the old live fixture paired the real writer with a verifier that had no semantic judge. That wiring was fixed in R1 (`158e557`).
- **Paragraph 1, the "uncited experience opening":** `"I understand the Backend Engineer role requires Python API experience."` is exactly what `_COVER_SYSTEM` asks for: a separate second opening sentence stating the employer's need, *with no candidate fact*. The verifier's factual heuristic matched the word "experience" and demanded a candidate citation. The writer instruction and the verifier contradicted each other.
- **Fix (verifier, narrow):** a cover-letter sentence that only attributes a requirement to the role (`the … role/position/team requires/seeks/needs …`, optionally led by "I understand/see/note that") is treated as employer context only when all of the following hold:
  - it makes no first-person claim;
  - the requirement occurs as a **contiguous token span in one sentence of the verified job text** (`cleaned_job_description`, already passed by production). Numbers, `+` and word order are kept; only a leading article is ignored;
  - that job sentence has **no negation**;
  - for a hard verb (requires / needs / calls for / asks for), that job sentence has **no preferred / optional / nice-to-have qualifier**.

  - that job sentence **or the heading it sits under** (`Preferred qualifications:`, `Nice to have`, `Not required:` … apply to the lines below until the next heading) has no negation, including Unicode apostrophes (`isn’t`);
  - for a hard verb, there is **positive evidence**: a requirement cue (requires / required / must / need / minimum / mandatory / essential) in the sentence or its heading. A sentence that merely lacks a negation is not evidence of a requirement.

  Without job text, nothing is exempt. Uncertain attribution means no exemption.
- **Review M3-GROUNDING-001** caught that the first draft used a whole-job-text word-set check, which let a changed number ("5 years" against "3 years") and a negated requirement ("not required") through. That draft was never committed to the branch. Both counterexamples, plus `3+` against `3`, `isn't`, `No … needed`, preferred against required, scattered and reordered words, and a negated opening, are now offline tests that **stay rejected**. A second review pass found two more holes, now fixed in `53a3c86` and tested: a `Preferred qualifications:` heading followed by the exact phrase on the next line, and negation written with a U+2019 apostrophe.
- **Grounding is not weakened:** candidate claims, mixed sentences, and requirements absent from the job text still require cited evidence (tested). The tailored-resume and application-answer checks are untouched.
- **Offline replay:** the frozen L3 artifact (embedded in the test, checked byte-equal against the evidence file when present) now has no paragraph-1/2 issues with production pairing.

**Real L3 re-check: NOT RUN (pending).** The planned batch is one node, `tests/test_integrated_p8_material_live.py::test_live_material_revision[full]`:
- `JOB_AGENT_LIVE_MATERIAL_PATCHES=1`;
- `OPT_LIVE_OUTPUT=docs/benchmarks/unified-loop-m3-20261012/L3-full-r2`, an unused directory;
- 80K input / 6 attempts cap, enforced by the test;
- run only after the full suite was green at `53a3c86`.

The tool permission layer blocked the command as a real-world paid action. I did not work around it, and the user's explicit confirmation is needed. **Until it runs, the material full path is not live-accepted.** The offline replay is not a substitute, and the old failed sample `L3-full-r1` is kept unchanged.

**Human style review:** not done. It cannot be signed off by Claude and stays pending.

## Verification

- **At `53a3c86` (current verifier):** verifier + workflow + all material suites: **103 passed / 4 paid skips** (33 verifier tests). Raw output: [`affected-53a3c86.xml`](../benchmarks/unified-loop-m3-20261012/affected-53a3c86.xml) (sha256 `ca4818dd…ef993`) and [`.log`](../benchmarks/unified-loop-m3-20261012/affected-53a3c86.log) (sha256 `9e5ce98f…be5a7`).
- **At `269427a` (superseded verifier):** 24 passed. Raw output: [`verifier-and-workflow-269427a.xml`](../benchmarks/unified-loop-m3-20261012/verifier-and-workflow-269427a.xml) and [`.log`](../benchmarks/unified-loop-m3-20261012/verifier-and-workflow-269427a.log).
- **Focused suites during development:**
  - analysis / API / main / fit / job workflow / pack / evals / prompt: 144 passed;
  - modules importing the moved code: 169 passed / 5 skipped;
  - materials (pack, p7, p8 runner, routes, r1 lane, cover style, verifier) after the review fix: 88 passed / 4 paid skips.
- **Full suite at `269427a`**, launched before `53a3c86`, so it ran the superseded verifier: **2327 passed / 134 skipped / 16 subtests, 0 failed** (742 s). Raw output: [`full-suite-269427a.xml`](../benchmarks/unified-loop-m3-20261012/full-suite-269427a.xml) (sha256 `4f924dbc…3675`) and [`.log`](../benchmarks/unified-loop-m3-20261012/full-suite-269427a.log) (sha256 `14b93fe2…d84e`).
- **Full suite at `53a3c86`:** **2339 passed / 134 skipped / 16 subtests, 0 failed** (690 s). Raw output: [`full-suite-53a3c86.xml`](../benchmarks/unified-loop-m3-20261012/full-suite-53a3c86.xml) (sha256 `8508dee7…e2c0f`) and [`.log`](../benchmarks/unified-loop-m3-20261012/full-suite-53a3c86.log) (sha256 `efd2c6c2…48150`).

## Still open

- Patch-variant comparison and human style review: not run.
- Migration step M4/M5 (scheduling) is next.
