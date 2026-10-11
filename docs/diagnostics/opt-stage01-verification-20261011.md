# Stage 0–1 verification and delivery (2026-10-11)

Implementation commits in the delivery bundle:

- `104c5ae`: per-attempt composition/timing, read-only reporting and B6 baselines.
- `e5127b4d2369f1a886396a0055c377eba2337d51`: purpose configuration, validation escalation,
  effective-level cache isolation and regression tests.

The final full suite ran against this exact implementation, with no production edits
while it ran. Result: **9 failed, 1900 passed, 132 skipped, 1 warning, 4 errors, 4 subtests passed in 674.65s (0:11:14)**. Four subtests, when listed, are not added to
pytest's passed total. All failures/errors are in the user-approved sandbox exception
set; `verification.json` lists every case. The known local-stdio registration assertion
can surface as a denied tool because optional server startup swallows the named-pipe
failure. A reviewer must rerun the full suite outside this Windows sandbox.

Targeted final suite: **194 passed, 1 skipped, 4 subtests passed in 27.45s**.
The separate fit-cache regression suite also passed all 10 tests.
After the full run, a reporting-only addition exposes the existing historical
`duration_seconds` percentiles alongside (not as substitutes for) the new split
timings. Its older-run regression test and all four B6 baseline report tests passed
again; all three read-only evidence reports and both replay report commands were
rerun. No runtime/model/cache code changed after the full suite.
Includes the unchanged B6 offline replay, wire-byte compatibility, configuration
precedence, sync/async unsupported-parameter fallback, bounded schema/grounding/batch
repair, durable/fit/Jev/fast cache isolation, and request attribution/timing tests.
The one targeted skip is the existing opt-in paid B6 lane.

Validation used `.venv/Scripts/python.exe`. Local bootstrap:
`.codex-runs/opt-stage01/run_offline.py`. It removes live opt-ins, ignores only the
repository `.env`, supplies a fake model/key/endpoint for constructor-only tests,
blocks external socket connections, and creates test temp directories with mode 0777
inside its own root to inherit sandbox ACLs. It does not relax assertions, modify
existing directories/ACLs, or touch the copied evidence. Test-owned temporary env files
remain supported. The first bootstrap run exposed three constructor-only tests needing
fake configuration; those now pass without reading private settings.

```powershell
.venv/Scripts/python.exe .codex-runs/opt-stage01/run_offline.py -q -p no:cacheprovider --basetemp=.codex-runs/opt-stage01/full-open6 --junitxml=.codex-runs/opt-stage01/full-final-verified.xml
```

Logs/JUnit: `.codex-runs/opt-stage01/full-final-verified.log|xml` and
`.codex-runs/opt-stage01/targeted-complete.log|xml`.

`evals/opt_report.py` was run on all three `.codex-runs/b6-evidence/r*/career.db`
files and both replay databases (production `career.db` and the separate scripted
usage DB). The production replay report contains 20 tool timing records and zero
provider calls; the scripted usage report contains 20 measured compositions and zero
tokens. Input DB SHA-256 values are in `evidence-manifest.json` and were rechecked
unchanged. The benchmark README gives exact composition/eviction numbers and explains
why historical last-request metrics cannot stand in for per-attempt averages.

No new default reasoning values were set. No paid/live calls were made. `.env`,
`tmp/`, copied evidence and user-owned untracked LIVE benchmark directories were not
modified. `tests/test_b6_offline_replay.py` and `scripts/remaining_search_acceptance.py`
were not changed. The proposed later paid comparison and quality gates are in
`docs/diagnostics/opt-reasoning-audit-20261011.md`.

Direct `git add` on the current branch failed with `.git/index.lock: Permission denied`.
The sandbox explicitly grants read-only access to `.git`. No permission bypass was
attempted. A separate writable bare repository retains the same branch name and parent
`63f77aaff6847a67c0f96223239ab20703f26c66`; only explicit task paths were staged.
The final deliverable is `.codex-runs/opt-stage01/submission.bundle`, verified with
`git bundle verify` and imported into a separate verification repository. The original
branch remains at `63f77aa`; delivering a bundle is not a claim that it was advanced.
No push was performed. The final documentation commit and bundle SHA-256 are recorded
in `.codex-runs/opt-stage01/delivery.json`.
