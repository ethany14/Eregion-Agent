# R1 offline revalidation

Status: PASS for S2 on frozen checkout `57c63ab4b9812ddcb0d9bc8e9f3760d1539f8a45`. This is not a live business acceptance or R2 release decision.

## Results

| Run | Result | Duration |
|---|---|---|
| Exact 13 historical failure/error nodes | 13 passed, 12 passing subtests, 0 failed/error | 41.28 s |
| Final-version complete offline suite | 2136 passed, 134 skipped, 16 passing subtests, 0 failed/error | 664.09 s |

Both runs used ordinary pytest with the existing virtual environment, outside the restricted subprocess/named-pipe sandbox, in an isolated review checkout. No test assertions, production implementation or conftest isolation were changed. One Starlette/AnyIO deprecation warning remains; it does not indicate failed behavior.

The previously reported Chrome setup, browser recovery and MCP subprocess nodes now pass. This independently supports the prior environment-cause diagnosis. The new full run includes the final checkpoint-integrity, patch-commit crash and combination tests that were not all present at the old full-suite collection.

## Reproduction

Use the frozen checkout and the recorded dependency environment in `r1-baseline-freeze-20261012.md`. Clear JOB_AGENT_LIVE_*, JOB_AGENT_OPT_* and JOB_AGENT_B6_REPLAY_LIVE_MODEL in the child test environment. The checkout has no copied maintainer .env; conftest supplies fake model configuration and blocks outside connections.

Boundary command: `python -m pytest -q -p no:cacheprovider <13 exact nodes from prior validation.json> --basetemp=<fresh boundary temp> --junitxml=<boundary XML>`.

Full command: `python -m pytest -q -p no:cacheprovider --basetemp=<fresh full temp> --junitxml=<full XML>`.

All output paths were new. No real-user database, application, schedule, Treg call or paid model was used by these offline runs.

## Scope and evidence

Raw evidence in the isolated checkout: `.r1-evidence/boundaries.log`, `boundaries.xml`, `full.log`, `full.xml`, and `skip-reasons.json`. The XML independently reports zero failures and errors and 134 skips. Skip messages are grouped with exact multiplicities; browser/live opt-ins remain unexecuted rather than passed. Existing historical classification was 118 browser opt-ins, 15 live/paid opt-ins and one unavailable symlink; retain the new XML as the authority for this run.

Critical browser ownership, stale observation, recovery, confirmation/receipt and MCP timeout/concurrent-session nodes were executed in the dedicated 13-node run as well as the full suite. This does not claim every optional browser test was run.

## Post-live minimal fixes

Repair commit `158e55781c0467fb97d70710471d3444090af596` adds provider-budget saved-result delivery and corrects the live material fixture's verifier binding. The full-suite result above predates those changes. Afterward the affected suite passed **53 tests, 2 paid skips, 0 failures/errors in 35.04 seconds**, with the same dependency warning. Files: `.r1-evidence/fixes.log` and `fixes.xml`.

Command: `python -m pytest -q tests/test_r1_budget_delivery.py tests/test_task_loop.py tests/test_opt_v3_closeout.py tests/test_r1_material_lane.py tests/test_integrated_p7.py tests/test_integrated_p8_material_live.py -p no:cacheprovider --basetemp=<fresh fixes temp> --junitxml=<fixes XML>`.

Coverage includes budget-stop incomplete status and local delivery without extra calls, ordinary task-loop behavior, existing decision/delivery closeout tests, supported/unsupported material paraphrases and patch integrity. Existing network isolation remains unchanged; two live variants were skipped. A full second sweep was not repeated because the changed behavior has passed its affected-area regression, as required by G7. No live post-repair pass is claimed. R2 remains unreleased by the failed business gate.
