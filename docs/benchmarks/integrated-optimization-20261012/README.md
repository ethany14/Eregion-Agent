# Integrated optimization evidence

Base: `92b60550c0aeda7f3d4a67911f026b17769292af`.
Final implementation regression: `428ac9645b417b743bea5af8b69fb0c28a71f126`.

Implementation commits in order:

1. `ff0bb6e` — version-bound material patches and dedicated gates.
2. `eb504fb` — gated context experiments and frozen comparisons.
3. `b042ee7` — L1 blocked-source repair and bounded L3 runner.
4. `428ac96` — checkpoint integrity and crash-after-patch-commit recovery.
5. Final documentation/evidence commit — inspect the bundle's branch head.

`validation.json` names the fixed tests, source/protected-file hashes, complete skip
reasons and baseline failure reproductions. UTF-8 logs have local workspace/home paths
redacted. `p6/` contains production-serializer measurements of scripted frozen runs,
not live provider usage. `l1-blocked-attempt.json` contains the single new paid attempt,
including conservative unknown-use reservation and separate attempt/test timing.

The original repository's `.git` denied writes. The verified deliverable lives at
`.codex-runs/integrated-20261012/integrated-optimization.bundle`; it contains only the
continuation commits and requires the base commit above. The working-tree edits are
also left in the original workspace for inspection. No unrelated specification or
benchmark was included.

Review in a clean checkout containing the base commit:

```text
git bundle verify /path/to/integrated-optimization.bundle
git fetch /path/to/integrated-optimization.bundle master
git log --oneline 92b6055..FETCH_HEAD
git diff --stat 92b6055 FETCH_HEAD
```

Do not replace the current workspace's other-session files when applying the commits.
Rerun the full suite outside the sandbox, then follow the sequential paid-lane runbook
in `docs/diagnostics/integrated-live-validation-plan.md`. Keep experimental defaults off
until the live adoption gates pass.
