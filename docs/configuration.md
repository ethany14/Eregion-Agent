# Configuration

[Home](../README.md) · [User guide](usage.md) · [Development](development.md)

Run commands from the repository root with the project's virtual environment
active. Keep a single trusted local backend process.

## Model connection

The model and TypeSafe adapters read the repository-root `.env` file. Process
environment variables override values in that file. Restart the backend after
changing configuration so active services use the new settings consistently.

| Variable | Default | Purpose |
| --- | --- | --- |
| `LLM_MODEL_ID` | Required | Main model for chat, planning, writing, and verification. |
| `LLM_API_KEY` | Provider/client configuration | API credential; set it explicitly for your provider. |
| `LLM_BASE_URL` | Client default | Custom OpenAI-compatible endpoint, when needed. |
| `LLM_TIMEOUT` | `45` seconds | Positive timeout for a provider request. |
| `LLM_MAX_RETRIES` | `0` | Client retry setting. Budgeted calls can force zero client retries and manage recovery themselves. |
| `LLM_FAST_MODEL_ID` | Main model | Optional model for eligible routine actions. |
| `LLM_EXTRACTION_MODEL_ID` | Main model | Optional extraction/matching model. |
| `LLM_AGENT_REASONING` | Unset | Reasoning override for agent/fast-purpose clients that use this setting. |
| `LLM_EXTRACTION_REASONING` | Unset | Reasoning override for the extraction-purpose client. |

The reasoning settings accept `none`, `minimal`, `low`, `medium`, or `high`.
Only set them when the provider supports the corresponding request parameter.
Tool calling and structured output are required by agent workflows; optional
visual backup also needs image input. Compatibility varies between providers.

## Browser and worker settings

The following settings are read from the **process environment**. Putting them
only in `.env` does not export them to these components. Set them in the shell
before running both migrations and the server where applicable.

| Variable | Default | Purpose |
| --- | --- | --- |
| `JOB_AGENT_DATABASE_URL` | `sqlite:///./job_agent.db` | Database used by the API and Alembic. The default path is relative to the working directory. |
| `JOB_AGENT_APPLY_WORKERS` | `3` | Application worker count, clamped to 1–8. |
| `JOB_AGENT_MAX_OPEN_APPLICATIONS` | `6` | Limit on unfinished application attempts; minimum 1. |
| `JOB_AGENT_HIDDEN_BROWSER` | `offscreen` | `offscreen` uses a normal Chrome window outside the visible desktop; `headless` uses headless Chrome. |
| `JOB_AGENT_BROWSER_CHANNEL` | `chrome` | Playwright browser channel. The default uses installed Google Chrome. |
| `JOB_AGENT_ANALYSIS_WARMUP` | `1` | Precompute uploaded-resume analysis; `0`, `false`, or `off` disables it. Warmup can use model tokens. |
| `JOB_AGENT_ALLOWED_HOSTS` | Loopback hosts only | Comma-separated additional accepted Host names. This is not user authentication. |

For example, use headless Chrome with two application workers:

```powershell
# Windows PowerShell
$env:JOB_AGENT_HIDDEN_BROWSER = "headless"
$env:JOB_AGENT_APPLY_WORKERS = "2"
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

```sh
# macOS / Linux
export JOB_AGENT_HIDDEN_BROWSER=headless
export JOB_AGENT_APPLY_WORKERS=2
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

Lower concurrency if the provider rate-limits calls or the machine cannot support
the active browsers. A worker limit is not a promise that every task runs at once;
site coordination, waiting questions, and review boundaries still apply.

## Optional Jev acceleration

The main model handles conversation, planning and writing. The general Jev switch
also selects the fit-scoring engine; the career helper switch does not control
fit scoring.

```dotenv
TYPESAFE_API_KEY=your-typesafe-key
TYPESAFE_BASE_URL=https://api.typesafe.ai
TYPESAFE_DEFAULT_MODEL=jev-latest
TYPESAFE_ENABLED=false
TYPESAFE_CAREER_ENABLED=false
TYPESAFE_TIMEOUT=2.5
```

`TYPESAFE_ENABLED=true` selects **Jev-only fit scoring**, including JD requirement
classification, evidence decisions and citation checks. This applies to chat's
`score_job` / `score_jobs`, quick analysis and saved-job analysis. There is no
main-model fallback in these scoring requests. Provider failures remain failures;
uncertain decisions produce unresolved requirements and a score interval rather
than an invented exact score. Setting it to `false` selects the original analyze
pipeline. Resume upload warmup skips main-model extraction while Jev is enabled.

The switch also enables general option mapping and job screening.
`TYPESAFE_CAREER_ENABLED=true` additionally enables eligible memory, question,
and legacy workflow evidence-matching helpers; it also requires the general switch.

Fit-specific settings:

| Variable | Default | Purpose |
| --- | --- | --- |
| `TYPESAFE_FIT_MODEL` | `jev-1.13.0` | Exact Jev release. When unset, an exact `TYPESAFE_DEFAULT_MODEL` is used; its `jev-latest` / `jev-preview` aliases resolve to the tested `jev-1.13.0` for fit scoring. |
| `TYPESAFE_FIT_TIMEOUT` | `12` seconds | Timeout for each fit request, from 0.1 to 60 seconds. No automatic paid retries. |
| `TYPESAFE_FIT_CACHE_PATH` | Database sibling ending in `.jev-fit.sqlite3`; otherwise `.cache/jev-fit.sqlite3` | Persistent local decision cache. Relative overrides resolve from the server's working directory. |

The cache uses exact resume, JD, supplied facts, owner, model release and scoring
code/prompt identities. Decisive answers expire after 24 hours; uncertain answers
after 5 minutes. Changes invalidate reuse. Only hashes, answers and provenance
are stored in the decision cache; application artifacts retain the actual sources.
Chat can batch up to eight imported jobs for the same candidate. Compatible
questions share a request while each job retains its own result and citations.
Paid requests and tokens are accounted once, including shared requests.

Fit requests send extracted resume text, the supplied JD and scoped candidate
facts to Typesafe. A combined input above 60,000 UTF-8 bytes is rejected without
truncation. General helper requests can include observed choices, confirmed source answers, job
snippets, and search preferences. Career requests can include extracted resume
evidence and scoped confirmed memories. These may contain personal information.
The Jev adapter does not upload resume files, screenshots, passwords, or codes.

The general helper timeout accepts 0.1–10 seconds. Those helpers can fall back
or skip Jev under their existing cost gate. **Fit scoring uses the separate
timeout above and never falls back to the main model while enabled.**
See [Jev and performance](jev-benchmark.md) for measurements and limitations.

## Data and credentials

The local database stores candidate information, conversations, evidence,
application state, and provider-usage records. Treat it and any exported artifacts
as personal data. Stop the backend before making a filesystem backup of the
database and associated files; keep any SQLite sidecar files together.

Supported Windows login persistence uses DPAPI encryption under
`.browser-sessions/`, scoped to the candidate and job-site host. It does not store
the supplied password as a reusable agent credential. Other operating systems do
not use a plaintext persistent fallback for this store.

Provider requests can contain the relevant resume, job, answer, or document
content. Requested screenshots are an additional data flow when visual backup
is enabled. Local storage does not mean offline inference.

## Updating an installation

Stop the backend, back up local data, and update from the repository root:

```sh
git pull --ff-only
python -m pip install -r requirements.txt
python -m alembic upgrade head
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

Use the same `JOB_AGENT_DATABASE_URL` for migrations and the server. Refresh the
web page after updating frontend files, and reload the unpacked Chrome extension
after changing its files. Do not delete the database to resolve a migration error.

The default server address is `127.0.0.1:8000`; the extension uses
`http://localhost:8000`. Changing the server port requires corresponding extension
configuration changes. The health endpoint reports service/MCP state, not proof
that a model request or employer application will succeed.
