# R1 evidence package — 2026-10-12

R1 FAIL; R2 is not released. See ../../diagnostics/r1-closeout-and-r2-gate-20261012.md.

Full offline and paid runs use 57c63ab4b9812ddcb0d9bc8e9f3760d1539f8a45.
The six-file repair is 158e55781c0467fb97d70710471d3444090af596; fixes.xml/log
cover its affected-area offline regression (53 passed, 2 paid skips).
full.xml/log refer to the parent (2136 passed, 134 skips).
L1/L3/L4 folders preserve failed samples, invocation settings and recorded usage.
No paid sample was repeated after the repair; no failure is replaced with a pass.

r1-closeout.bundle was verified. It requires original commit
92b60550c0aeda7f3d4a67911f026b17769292af and contains the earlier optimization
continuation plus the repair. In a NEW clean clone containing that prerequisite:

```powershell
git fetch <absolute-path-to-r1-closeout.bundle> HEAD
git checkout --detach FETCH_HEAD
```

Do not reset/clean the existing dirty checkout. r1-repair.patch contains only
the six-file repair relative to 57c63ab4; implementation-manifest.json records
delivery hashes. Reports/evidence are separate from the implementation commit.
checksums.json hashes packaged files (excluding itself and the later sync receipt).

Logs/JSON are sanitized publishing copies. Raw SQLite and full unredacted evidence
remain in the isolated review checkout's .r1-evidence directory; no .env or database
is published. Raw failures remain unchanged. Existing historical reports, including
the L1 unknown reservation of 29,997 input, remain authoritative for prior spend.
The continuation total is 71 completed attempts, 741,045 input and 48,953 output;
dollar cost is unknown. No Treg calls, applications or schedules were created.
