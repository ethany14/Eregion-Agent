# Workspace layout for the single AgentLoop

Superseded directory/compatibility status: see
[the final eregion namespace cleanup](eregion-namespace-cleanup-20261012.md).
The earlier validation below remains historical evidence for this intermediate layout.

Implemented 2026-10-12. This is a directory/import reorganization, not an additional
agent architecture or a business acceptance claim.

## Delivered

- Seven kernel/task modules moved into `agent_runtime/core/` and
  `agent_runtime/tasks/`. `core/engine.py` contains the only autonomous AgentLoop.
- `agent_runtime/multi_agent/` renamed to `agent_runtime/coordination/`, describing
  its existing deterministic child-task scheduling, leases and budget role.
- Production, API, migration bootstrap, evaluation and test imports/patch targets
  updated to canonical paths. No new legacy runtime aliases were introduced.
- Architecture tests retain their full production scan and exact Host/owner
  assertions. The runtime-to-API dependency scan still covers all of agent_runtime,
  not only the new core directory.
- Historical baseline source loading translates only relocated dependency imports.
  Original Git revisions, baseline file names, model behavior and acceptance
  assertions remain intact.
- Added `JobHunterAgent.code-workspace`, ordering runtime, domain services, API, UI,
  extension, tests, evaluations, documentation and root configuration. This editor
  view hides generated caches and local browser profiles; it does not delete them.
- Added runtime ownership/import migration documentation, a docs entry index and
  an explicit compatibility-only description for `custom_agent/`.

## Kept stable

Database tables, migration revision identifiers, API URLs, stored workflow-mode
values and existing public class names are unchanged. No user database was moved
or migrated. No backend restart, login, browser action or paid API test was run.
Existing unrelated working-tree changes remain in place.

Root-level dated E2E reports stay where existing audit scripts and evidence links
expect them. Historical reports retain old code paths as revision-specific
evidence. The new runtime guide maps these to current paths. `custom_agent/` remains
the existing import compatibility layer, not a second executor.

External scripts importing the relocated internal Python modules must update using
the [migration table](../../backend/eregion/runtime/README.md#module-relocation-2026-10-12).
Restart the backend after active tasks have finished to load the reorganized code.

## Verification

Evidence: `docs/benchmarks/workspace-layout-20261012/`.

- `regression.xml` / `.log`: 163 passed, one failed because an execution-owner
  source inspection still referenced the previous filename.
- `path-recheck.xml` / `.log`: 53 passed, two failed because historical harness
  source still imported the previous task module. The execution-owner path was fixed.
- `final-paths.xml` / `.log`: 12 passed after updating historical dependency import
  translation; includes both prior failing baseline cases, the owner check, Host
  contract and unique-kernel architecture checks.
- Across these runs, 207 distinct test cases have a passing latest result, with
  no outstanding failure among the executed cases. This is not a single full-suite run.
- `collection.log`: all 2,440 tests collected successfully; collection is not execution.
- `git diff --check`: no whitespace errors; existing line-ending conversion warnings remain.

Coverage includes shared loop, task/session Hosts, stale results, child coordination,
job workflows, execution shutdown, offline migration dry run, default LinkedIn MCP /
public-board routes and historical optimization comparisons. Offline network guards
remain enabled. The integrated real 10–15-qualified-job acceptance remains pending.
