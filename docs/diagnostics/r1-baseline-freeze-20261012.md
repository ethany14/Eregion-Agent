# R1 baseline freeze

Status: S1 complete; S2 completed. R1 live acceptance failed; R2 is not released. Prepared under the user's instruction to execute R1. No migration implementation or original-workspace reset was performed.

## Version

- Original repository: `C:/Users/zhiyu/Documents/JobHunterAgent`, HEAD `92b60550c0aeda7f3d4a67911f026b17769292af`.
- Isolated review checkout: `C:/Users/zhiyu/Documents/Codex/2026-10-11/docs-specs-optimization-plan-v2/work/r1-review`.
- Bundle branch head / frozen checkout: `57c63ab4b9812ddcb0d9bc8e9f3760d1539f8a45`.
- Implementation regression commit recorded by prior evidence: `428ac9645b417b743bea5af8b69fb0c28a71f126`.
- Bundle verified and fetched only into the isolated checkout. Original modified/untracked files remain in place; no commits were applied to the original branch.

The five continuation commits are ff0bb6e, eb504fb, b042ee7, 428ac96 and 57c63ab. The frozen checkout contains the final implementations and evidence. The external optimization master specification was intentionally not included in the bundle and remains available in the original project's docs/specs.

## Correspondence and environment

The 12 implementation hashes and four protected-file hashes were checked against the original workspace. Three checkout byte differences (patches.py, test_integrated_p7.py, tests/conftest.py) are exclusively LF/CRLF conversion; normalized contents match. The master specification is external to the bundle. No runtime content mismatch was found in this manifest. This check does not claim all unrelated workspace files were reviewed.

Evidence: `.r1-evidence/source-hashes.json` in the review checkout. Tests run against the checked-out files, not a mixture with original Python source. The existing original virtual environment supplies dependencies only.

Environment: Windows 11 build 26300, Python 3.13.7, pytest 9.1.1, Playwright 1.63.0, MCP 2.2.0, langchain-openai 1.6.2. Browser launch usability is verified by the boundary suite rather than inferred from package presence.

Offline processes remove inherited JOB_AGENT_LIVE_*, JOB_AGENT_OPT_* and JOB_AGENT_B6_REPLAY_LIVE_MODEL variables. The checkout has no copied .env. Existing conftest isolation, fake model settings and outside-network blocking remain unchanged. Effective opt-in settings within individual tests remain those deliberately set by the tests.

## Initial validation and budget preparation

The exact 13 previously failing/error nodes passed in ordinary pytest outside the restricted sandbox: 13 passed, 12 subtests passed, one dependency deprecation warning, 41.28 seconds. The complete offline suite subsequently passed: 2136 passed, 134 skipped, 16 passing subtests, 664.09 seconds. Evidence: `.r1-evidence/{boundaries,full}.{log,xml}`.

Non-inference preflight used the configured original endpoint without displaying its host, model identifier or credentials. TCP and TLS succeeded. This proves transport availability only, not successful authentication or model inference. The original config reports timeout 120 and no explicit max_retries override; actual live caps will be imposed by the approved lane.

Historical L1 B0-run1 database was read with SQLite mode=ro: 22 provider attempts, 264,665 known input tokens and 8,617 output tokens. The later network-blocked attempt retains 29,997 input reservation. Initial L1 accounting is therefore 294,662 budget input, leaving 2,205,338 of the original 2,500,000 input cap. New attempts must also be charged to that same total; per-run maximum remains 400,000 or remaining allowance, whichever is smaller. No new inference or Treg call has occurred during this preparation.

## Post-validation repair snapshot

Repair commit: `158e55781c0467fb97d70710471d3444090af596`, parent `57c63ab4b9812ddcb0d9bc8e9f3760d1539f8a45`. It changes provider-budget saved-result delivery, the material live-test verifier binding, adds five regression cases, and links README/configuration to the R1 status. The complete suite and all paid results refer to the parent; the repair has a separate 53-pass / 2-paid-skip affected-area run. Neither result is mislabeled as a full post-repair or live post-repair pass.

Reports and a sanitized evidence manifest are delivered separately from the implementation commit. The reconstruction bundle includes the original optimization continuation and this repair; restore it into a clean review checkout, never reset a dirty user checkout. Only six explicitly checked files plus new reports/evidence are eligible for synchronization to the original project. Existing files must match parent content before replacement; unrelated changes, .env, user databases and original Git HEAD are preserved.

Known API-first description conflicts, Treg client close and old Session response metadata protection retain the ownership in the R1 specification. All experiment defaults remain disabled. See the gate report for the remaining R1 tasks; do not start R2.
