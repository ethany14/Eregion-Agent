# Development

[Home](../README.md) · [Architecture](agent-loop.md) ·
[Configuration](configuration.md)

## Repository map

| Path | Contents |
| --- | --- |
| `api/` | FastAPI routes, dependencies, persistence integration, and local web serving |
| `web_app/` | Browser UI, styles, and client-side state |
| `chrome_extension/` | Eregion Lens Chrome Side Panel |
| `agent_runtime/` | Shared loop, career tools, browser workers, context, evidence, materials, and interviews |
| `job_agent/` | Model adapters, schemas, extraction, matching, source checks, and rendering |
| `custom_agent/` | Persisted custom resume workflow |
| `migrations/` | Alembic database migrations |
| `skills/` | Runtime skill packages with their own metadata and permissions |
| `tests/` | Unit, integration, frontend, and opt-in Chrome tests |
| `evals/`, `scripts/` | Evaluation datasets, harnesses, and opt-in live benchmarks |
| `docs/benchmarks/` | Recorded historical measurements |

`design/` is an ignored local reference directory, not a runtime dependency.
The implemented frontend is the source of truth for a fresh checkout.

## Local development

Follow the [README setup](../README.md#get-started). CI uses Python 3.12 and
Node.js 22. The frontend is served as static assets; a Node build step is not
needed to run the app.

Run one server process. Automatic reload can interrupt active model requests or
browser sessions, so stop or finish those tasks before changing the server.
Apply migrations with the same database URL used by the application.

Use [web_app/AGENTS.md](../web_app/AGENTS.md) for frontend conventions. Keep the
web app and extension design tokens aligned, preserve question drafts, and check
changed states in both themes and at desktop/mobile widths.

## Automated checks

From the repository root, with dependencies installed:

```sh
python -m pytest -q
node --test "tests/*.mjs"
```

Include the opt-in real-Chrome fixture tests on Windows:

```powershell
$env:JOB_AGENT_BROWSER_TESTS = "1"
python -m pytest -q
```

These browser tests use intercepted fixture pages and scripted model behavior.
They exercise real browser mechanics but do not prove compatibility with every
live ATS, current employer page, or model provider. CI definitions live in
[.github/workflows/ci.yml](../.github/workflows/ci.yml).

Targeted shared-loop checks can also run through `unittest`:

```sh
python -m unittest discover -s tests -p test_shared_agent_loop.py -v
```

Choose checks appropriate to the change. Documentation-only changes need link,
command, and configuration verification rather than paid model runs.

## Live evaluation

Live scripts call configured model services and can incur usage charges. Inspect
the script's inputs and output location before running it. Use synthetic complete
candidate profiles, separate task IDs, an isolated database, and an output
directory outside committed source. Do not silently use a saved personal resume.

The shared application smoke uses synthetic intercepted pages with real Chrome
and the configured model, and asserts zero final-submit clicks:

```powershell
New-Item -ItemType Directory -Force artifacts/browser-eval/shared-loop
$env:NORTHSTAR_SMOKE_DIR = (Resolve-Path artifacts/browser-eval/shared-loop).Path
python scripts/smoke_shared_application_loop.py
```

`NORTHSTAR_SMOKE_DIR` is the existing script variable despite the current product
name. Additional controlled comparisons are documented in
[Jev and performance](jev-benchmark.md).

For a full application acceptance run, preserve source inputs, extracted facts,
tool history, model requests where appropriate, selected document versions, actual
field values, file hashes, and the final user-facing response. Inspect PDF pages,
not just API completion or text extraction. Keep failures and retries with their
original run IDs.

Distinguish public-page observations from locally intercepted application forms.
A listing link, login block, transport error, and successfully read full posting
are different outcomes. Count unexpected tool errors across the complete new
history, and restart only after meaningful progress if testing recovery.

## Data and contribution boundaries

Never commit `.env`, model credentials, personal resumes, local databases, or
browser login state. Keep raw evaluation captures local; they can contain source
material even when the test itself does not submit an application.

Shared-mechanism regressions should cover different source sizes, ownership,
education status, layouts, and recovery points. Do not hard-code one candidate's
answer or loosen factual verification to make a fixture pass. Preserve the source
text of extraction regressions, including meaningful layout boundaries.

The [human quality-review guide](../evals/human_quality_review/README.md) describes
the separate, consented real-material review process. Synthetic data must remain
labeled synthetic.

## Optional integrations and API work

The running server's `/docs` page is the endpoint reference. Keep legacy persisted
records readable when changing schemas, and add Alembic migrations for database
changes. Domain operations should execute external calls outside transactions.

MCP integration uses trusted local stdio server configuration. See
[`agent_runtime/mcp/config.py`](../agent_runtime/mcp/config.py) and the
[example configuration](../examples/mcp/local_test_config.json). Apply tool
allowlists, bounded results, timeouts, and approval policy; a tool's own metadata
does not grant it additional permissions.

Runtime `SKILL.md` files are executable configuration with approval/version
semantics. Treat changes to them as capability changes, not cosmetic documentation
edits.
