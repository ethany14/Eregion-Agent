# Eregion namespace cleanup — 2026-10-12

This report supersedes the directory/compatibility state described in
[the earlier workspace reorganization](workspace-layout-20261012.md).

## Final source layout

```text
backend/
  eregion/
    runtime/             # one autonomous kernel and its Hosts/capabilities
      core/engine.py     # the only AgentLoop definition
      tasks/
      coordination/
    domain/              # extraction, scoring, rendering, fixed analysis workflow
    api/                 # HTTP adapters and application composition
    paths.py             # checkout paths
  migrations/            # Alembic schema history
frontend/
  web_app/
  chrome_extension/
  site/
tools/
  scripts/
  evals/
tests/
docs/
skills/
examples/
```

Root configuration and the file-analysis CLI remain at the repository root.
Local databases, credentials, login profiles and historical raw evidence were not
moved or deleted. The editor workspace displays the new real directory paths.

## Removed and renamed

- Removed the entire `custom_agent` forwarding package. No `eregion.compat` package
  was created, and no old top-level Python module aliases are registered.
- `agent_runtime` → `eregion.runtime`; `job_agent` → `eregion.domain`;
  standalone `api` → `eregion.api`.
- Tests formerly using `custom_agent` now import `eregion.domain.workflow`
  directly. `test_custom_agent.py` became `test_analysis_workflow_state.py`.
- Removed `AgentLoop = AnalysisWorkflow`. `AnalysisWorkflow` remains an explicit,
  deterministic domain workflow. Only `eregion.runtime.core.engine` defines AgentLoop.
- Renamed the built-in business tool module to `domain_tools.py`, its registration
  function to `register_domain_tools`, and workflow ORM classes to
  `AnalysisStateRow` / `AnalysisEventRow`; no aliases retain their old Python names.
- Updated production imports, dynamic patch targets, test source inspections,
  scripts, migration bootstrap, package discovery, current docs and website commands.
- Shared checkout paths keep `.env`, browser sessions, static web assets, skill
  datasets and scoring cache signatures pointing at the intended files.

Database table names (including `custom_agent_states` / `custom_agent_events`),
Alembic revision IDs, environment variable names and the existing database filename
are persistence/configuration contracts, not additional agent implementations.
They remain stable; this source relocation requires no user database migration.

Historical reports retain revision-specific names. The offline baseline loader
translates imports only while evaluating saved Git source; it is not a production
compatibility layer. External scripts must adopt the new imports.

## Setup and startup

From the project root:

```sh
python -m pip install -r requirements.txt
python -m uvicorn eregion.api.main:app --host 127.0.0.1 --port 8000
```

`requirements.txt` includes the editable local project configured by
`pyproject.toml`. The current local virtual environment was updated with
`pip install --no-deps -e .`; existing business dependencies were not upgraded.
The old `uvicorn api.main:app` entry point is removed. Finish active tasks and
restart the backend with the new command. No running backend was restarted here.

`python main.py --help` continues to work. Alembic uses the root `alembic.ini`,
with its schema directory anchored at `backend/migrations`. Tests use temporary
databases. Previously unpacked Chrome extensions must be pointed at
`frontend/chrome_extension`; the public website workflow now publishes `frontend/site`.

## Verification and fixes

All evidence is under `docs/benchmarks/root-layout-20261012/`.

- Initial namespace regression: **173 passed** (`namespace-regression.xml`).
- Full offline suite: **2,264 passed, 46 failed, 135 skipped**; pytest's failure total
  includes failed subtests (`full-suite.xml` / `.log`). These failures represent
  42 distinct JUnit case identities.
- Failures were traced to external API host strings inadvertently rewritten as
  module names, the scoring signature's old domain file path, and an evaluation
  signature's old API file path. Each was corrected without weakening assertions.
  The full-suite process had already imported the affected code, so its original
  failures are retained rather than relabeled as passes.
- Final rerun of every failing file plus namespace/CLI/API/workflow/registration
  checks: **434 passed, 2 skipped**, plus four passing subtests
  (`final-recheck.xml` / `.log`; selection in `final-recheck-files.txt`).
- Reconciled by exact case identity: **2,306 passed, 135 skipped**, **zero unresolved
  failures**. All 42 original failed case identities were reexecuted.
  See `closure-summary.json`. This is a full run plus targeted fixes/rechecks,
  not a claim of a second clean full-suite run.
- Frontend: **24 passed**, zero failures (`namespace-frontend.log`).
- CLI help smoke passed (`cli-help.log`). `git diff --check` found no whitespace errors.

Architecture checks reject old package imports, verify old packages are not
importable, ensure exactly one AgentLoop definition with no assignment aliases,
and inspect the real production tree rather than passing on empty moved directories.
Host/API dependency checks, execution ownership, database upgrades and source
behavior retain their original assertions.

Live/browser integration tests were not enabled. No paid model/search calls,
actual user database upgrades, login actions, commits or pushes were performed.
The integrated real 10–15-qualified-job acceptance remains separate and pending.
Changes are local on `codex/remaining-e2e-fixes-20261011`, not committed to main.
