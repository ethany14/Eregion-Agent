# Material patch validation — 2026-10-12

Status: offline passed; real writer comparison pending networked review. Release default remains `JOB_AGENT_OPT_MATERIAL_PATCHES=0`.

The inherited implementation only bound paragraph text. This continuation additionally binds the returned patch to the exact artifact ID and item version, rejects noncanonical paragraph aliases, and includes the target in the structured writer context. The repository's optimistic version check remains the final concurrency boundary.

`tests/test_integrated_p7.py` uses the real repository, temporary migrated SQLite database and existing verifier. Fifteen cases cover targeted replacement and byte-identical unmodified text/metadata; stale hash/version/artifact; duplicate/unknown/aliased blocks; unsupported evidence IDs and evidence versions; full-rewrite request; schema/length rejection; flag off; exhausted revisions; injected unsupported facts; reopened repository and repeated continuation. Rejection makes one full-revision fallback, while a successfully merged but ungrounded patch goes through VERIFYING and remains NEEDS_REVISION at the revision cap. No approval or application submission is automated.

Validation: P7 + application pack + frozen B6: **52 passed, 1 skipped** (paid router opt-in), 63.28 s. Initial test execution was blocked by Python 3.13 owner-only temporary-directory ACLs; `scripts/pytest_workspace.py` uses inherited Windows ACLs for scratch directory creation only, leaving conftest isolation and assertions intact. A first executable run exposed a test comparison of JSON key ordering; comparison now canonicalizes metadata while preserving every text byte.

L3 runner: `tests/test_integrated_p8_material_live.py`, 80K input / 6 provider attempts per variant; complete provider accounting including fallback, same synthetic evidence and repair target, human style review explicitly pending. Writer reasoning unchanged. Live network was unavailable at L1, so L3 was not attempted. Rollback: set the switch to 0; retain artifacts, versions and usage records. Application-answer patches are deferred; this first experiment covers cover letters only.
