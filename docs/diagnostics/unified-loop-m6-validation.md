# Unified loop · R5 / M6 validation: migration dry-run on database copies (2026-10-12)

Plan: [`claude-unified-execution-plan-20261012.md`](../specs/claude-unified-execution-plan-20261012.md) §8; migration plan §4, §M6. Previous: [`unified-loop-m4-m5-validation.md`](unified-loop-m4-m5-validation.md). Executor: Claude. **The real user database (`./job_agent.db`) was not opened, copied or migrated. Nothing was deployed.**

## What "migration" means for this design

M1–M5 changed **no schema and no identifier**:
- Sessions, career tasks, application runs, agent tasks, interviews and analysis runs keep their tables and ids.
- The unified owners (AgentLoop hosts, ExecutionService kinds) read the same records.
- The `legacy → execution` mapping is therefore the **identity**: there is nothing to convert, no new table (migration plan §4: "extend existing storage first"), and no possibility of cross-type id collisions.
- Review and answer bindings, provenance, tool-call ids and spend records are untouched by construction.
- The Alembic head stays `0037_external_tool_operations`.

The dry-run must therefore prove ownership and recovery, not a data conversion:
- every in-flight object is picked up by exactly one new owner, exactly once;
- terminal history is unchanged;
- unknown external effects stay unknown;
- repeating the run gives the same result.

## Tool

`scripts/unified_loop_dry_run.py --source COPY.db --work DIR [--report OUT.json]`. Introduced in `75c5e6d`; the coverage method was corrected in `fc5dc79` after review M6-COVERAGE-001.

1. **Snapshot.** A consistent snapshot is taken with SQLite's backup API from a read-only connection. A plain file copy missed committed pages still in the `-wal` file; that is exactly how the first interview sample came out empty. The source hash is checked unchanged. `./job_agent.db` is refused unless `--allow-user-database` is given, and even then only a snapshot is read.
2. **Independent expectation.** In-flight objects are enumerated per kind from stored rows, without the owner code:
   - career tasks: running / queued, not paused;
   - interview inputs: tasks with pending or running queue entries;
   - interview feedback: pending feedback jobs of open interviews;
   - Sessions: running / awaiting approval;
   - agent tasks: all non-terminal;
   - applications: hybrid running / queued expected to resume; `submitting` expected to become manual.
3. **Owner evidence, with recording stand-ins** (no model, browser or network call is possible):
   - career: the real `TaskLoop._recover`, with drives recorded;
   - interviews: the real `InterviewQueue.recover`, with input runs and feedback submissions recorded;
   - applications: `ApplyRepository.recover` through the `ExecutionService` owner, with no browser.
   - **Sessions and multi-agent tasks are classification only.** No SessionHost turn or scheduler dispatch runs, so the report does not claim they were recovered. Their real recovery is covered by the M2 recovery tests and the M4 scheduler tests, not by this dry-run.
4. **Coverage per kind:** `expected`, `covered`, `missing`, `duplicate`, `unexpected`. Agent listings use a limit above all rows; an injected smaller limit reports `listing_truncated` and fails. `coverage_complete` is required for exit code 0.

## Results (tests: [`dry-run-tests-coverage.xml`](../benchmarks/unified-loop-m6-20261012/dry-run-tests-coverage.xml), 6 passed at `fc5dc79`; report: [`dry-run-report.json`](../benchmarks/unified-loop-m6-20261012/dry-run-report.json))

| Sample | Result |
|---|---|
| Mixed synthetic database built with the real migrations: career tasks queued / running / waiting / needs_input / completed / paused; applications hybrid running / submitting / submitted / autofill awaiting_review; Sessions; 1 agent plan | `coverage_complete`. Career 2 / 2 covered, application resume 1 / 1, manual `submission_unknown` 1 / 1, Session 1 classified with pending `c1`, agent task 1 classified. History unchanged, source unchanged, repeatable on fresh snapshots |
| Second restart on the already-restarted snapshot | No further transitions; unknown submissions stay unknown |
| An application owner that "forgets" its run (injected) | `missing` reported, `coverage_complete: false` |
| 505 ready agent tasks | 505 / 505 covered; with an injected listing limit of 500, `listing_truncated` and `coverage_complete: false` |
| Real career + mock-interview fixture with a queued interview input and a pending feedback job | Inputs 1 / 1 and feedback 1 / 1 covered by the real `InterviewQueue.recover` |

**Cannot be converted automatically:** an application whose submission receipt is unknown (`submitting` at the stop). It becomes `submission_unknown` and needs the user to check the employer's confirmation. It is never retried automatically.

## Deployment to-dos (not authorized here)

1. Back up `job_agent.db`, the file `-wal` / `-shm` if present, and `.browser-sessions/`. Restoring means stopping the process and putting those files back; there is no schema change to roll back.
2. Run `scripts/unified_loop_dry_run.py --source job_agent.db --work <new dir> --allow-user-database --report <file>` (it reads a snapshot) and review `coverage_complete`, `application_run.manual_submission_unknown` and `history_unchanged`.
3. Deploy the new version. In-flight work resumes under the unified owners, and old owners no longer exist in the code (M7).

Steps 1–3 need the user's deployment authorization and were not done.
