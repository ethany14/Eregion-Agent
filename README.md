# eregion

eregion is a local-first career copilot for saving job postings, comparing
them with a resume, producing evidence-grounded application materials, and managing
the conversations and review steps around an application.

The web app has one conversational interface, with an optional Chrome extension:

| Surface | Purpose |
|---|---|
| **Career chat (`/apply`)** | One conversation for job discovery, match scores, tailored materials, applications and interview practice |
| **Chrome Side Panel** | Lightweight extraction and fit analysis for the job currently open in the browser |

The career chat runs at `http://localhost:8000/apply`. The home page and retired
`/app` workspace redirect to this chat; saved-job links preserve their job context.
The extension always talks to
the same local service at `http://localhost:8000`.

## What it does

- Saves jobs with title, company, location, original URL, and a cleaned job description.
- Accepts selectable-text PDF resumes and keeps one resume as the default.
- Splits compound job requirements into deterministic requirement groups.
- Distinguishes matched, partial, missing, and user-confirmation requirements.
- Grounds generated resume claims in quoted resume or user-confirmed evidence.
- Verifies drafts and uses a bounded revision loop before human review.
- Generates tailored resumes, cover letters, and application answers as versioned artifacts.
- Exports tailored resumes as searchable, ATS-friendly Letter-size PDFs.
- Persists Copilot conversations and lists them in a ChatGPT-style sidebar.
- Supports resumable tool calls, approvals, cancellation, deadlines, and recovery.
- Opens public job pages, navigates application steps, fills confirmed candidate
  details, and supports secure account input for login or registration. Greenhouse,
  Lever and Workday entry flows have focused coverage; other sites use the generic loop.
- Keeps Memory and Skills governed, versioned, reviewable, and separate from resume evidence.

### Chat and application agent loop

Career chat and application filling share one decision kernel with separate domain
hosts. It retains complete tool exchanges, fences stale decisions after user feedback,
and resumes from durable task state. See [the architecture and smoke checks](docs/agent-loop.md).

### Resume agent loop

The active custom backend persists state and an audit event after every completed
step. Human review is a durable pause rather than a long-running in-memory request.

```mermaid
flowchart TD
    A[Create run] --> B[Validate input]
    B --> C[Analyze resume]
    C --> D[Validate quoted evidence]
    D --> E[Analyze job]
    E --> F[Match requirement groups]
    F --> G[Write tailored resume]
    G --> H[Verify every generated claim]

    H -->|Passed| I[Review verified draft]
    H -->|Failed and revisions remain| J[Revise from verifier feedback]
    J -->|Persist new resume and clear old verification| H
    H -->|Revision limit reached| M[Review unverified draft]

    I -->|Approve| K[Approved]
    I -->|Reject with feedback| J
    M -->|Reject with feedback| J

    B -. Safe failure .-> L[Failed]
    C -. Safe failure .-> L
    D -. Safe failure .-> L
    E -. Safe failure .-> L
    F -. Safe failure .-> L
    G -. Safe failure .-> L
    H -. Safe failure .-> L
    J -. Safe failure .-> L
```

Only `awaiting_review` and `approved` states publish a stable public result. During
revision, the latest complete result may remain stored for audit purposes, while the
run status shows that it is no longer the current completed version.

## Quick start

### 1. Create an environment

Windows PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

macOS or Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

### 2. Configure the model

Create a `.env` file in the repository root:

```dotenv
LLM_MODEL_ID=your-model-id
LLM_API_KEY=your-api-key

# Optional for an OpenAI-compatible provider
LLM_BASE_URL=https://provider.example/v1

# Optional; defaults are provider timeout behavior and zero retries
LLM_TIMEOUT=60
LLM_MAX_RETRIES=0
```

`LLM_MAX_RETRIES=0` keeps one logical model invocation aligned with one provider
request during evaluations. Do not commit `.env`.

### 3. Initialize the database

```powershell
python -m alembic upgrade head
```

Production startup relies on Alembic. SQLAlchemy `create_all()` is used only by
isolated tests.

### 4. Start the local service

```powershell
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

Open:

- Career chat: <http://localhost:8000/apply>
- OpenAPI documentation: <http://localhost:8000/docs>
- Health check: <http://localhost:8000/health>

### 5. Complete the first-use setup

1. Open the career chat and use the **＋** button in the message box to upload a selectable-text PDF.
2. Check extracted information in **Your details** (your name at the bottom of the sidebar).
3. Describe your goal or share a job link in chat.
4. Review match scores and generated materials in the same conversation.
5. Continue through application review and interview practice in chat.

The chat retains the original PDF and candidate details locally for future
applications. Extension analysis also uses this saved resume and indexes its text
and metadata in the resume library. Use PDFs with selectable text.

## Chrome extension

The extension is intentionally smaller than the web application. It can:

- detect the title, company, location, URL, and job description on the active page;
- automatically extract the visible LinkedIn job when the Side Panel opens;
- keep the extracted fields editable before anything is submitted;
- save the job locally;
- compare it with the default resume and show a match score and suggestions;
- open the saved job in career chat, preserving its description and analysis.

**Analyze fit** uses the analysis-only pipeline: input validation, resume evidence
analysis, job analysis, and requirement matching. A cold analysis makes three
logical model calls: resume and job extraction run in parallel, then matching
uses both results after resume evidence validation. Within the same service,
an unchanged resume is reused for another job (two calls), and identical inputs
reuse the complete result (zero calls). Concurrent identical requests share work.
Scoring rules and evidence checks are unchanged.

This bounded in-memory cache clears when the backend restarts; saved job analyses
remain in the database. Changed inputs, model configuration, prompts, or schema
invalidate reuse. Analysis logs report stage durations, cache hits, and call counts
without resume or job content. Fit analysis does not write or verify a tailored
resume, create a reviewable run, or enter human review. Full `/runs` and Application
Pack workflows retain the complete write/verify/revise/review lifecycle.

Install it locally:

1. Start the FastAPI service.
2. Open `chrome://extensions`.
3. Enable **Developer mode**.
4. Select **Load unpacked**.
5. Choose the repository's `chrome_extension` directory.
6. Open a normal HTTP(S) job page and click the extension icon.

LinkedIn changes its page structure regularly. **Extract page** remains available
as a manual fallback. The extension never sends extracted text until the user
selects **Analyze fit** or **Save job**.

The extension requests only:

- `activeTab`
- `scripting`
- `storage`
- `sidePanel`
- host access to `http://localhost:8000/*`

It does not request broad browsing history, cookies, downloads, `webRequest`, or
`<all_urls>` access.

## Capabilities in the conversation

Job cards, material reviews, and interview practice appear inside the chat.
The panel button in the chat header opens **Agent activity**: the live browser
view, plan, recent actions and answers. It opens on its own when an application
starts in a wide window, and remembers if you close it.

Next to the conversations, the sidebar links to three overviews:

- **Applications**: pipeline and weekly charts, a filterable table, and a board
  where cards can be dragged to any stage the application allows next.
- **Materials**: every tailored resume, cover letter and answer, with version
  history, verification status, PDF download and approval.
- **Archived** and **Trash**: conversations you have put away. Trash keeps them for
  30 days before deleting them; applications and materials are never deleted with
  a conversation.

The older Jobs, Copilot, Evidence, Learning and Settings pages are no longer served.
Their backend services and stored records remain available to the agent and API.

### Jobs

Saved jobs keep their source URL and immutable description snapshots. Reopening a
job shows its latest analysis and application materials without requiring the
original page to remain open.

### Conversations

Conversations can be renamed (F2), pinned, grouped into folders, archived or moved
to Trash from each row's **⋯** menu or by right-clicking. Conversations that need
your input are listed first under **Needs you**. Ctrl+K (⌘K) starts a new one.

Career conversations are durable and listed in a left sidebar. Messages appear
optimistically while a model turn is running, and failed sends remain visible for
editing and retry. The agent chooses tools, asks questions, and resumes work within
the same conversation; it does not require navigation between feature pages.

### Materials

Application Packs contain versioned tailored resumes, cover letters, application
answers, verification results, and review state. Generated claims remain subject to
the same evidence rules during revision. Tailored resumes can be downloaded as PDF
or copied as text.

New resume drafts must bind every claim to a real extracted source entry and may not
use `legacy:*` source IDs. Entry headings, organizations, locations, and dates are
checked against that source entry before a draft is persisted. The explicit v1
artifact upgrader retains `legacy:*` IDs only so historical artifacts remain
readable; it is not a generation fallback.

### Evidence and learning

Career Evidence records user-confirmed facts independently from generated artifacts.
Conversation learning may propose Memory candidates, but only confirmed Memory can
enter future context. Memory confirmation never turns a statement into resume
evidence automatically.

Skills use standards-compatible `SKILL.md` packages with validation, hashing,
approval, activation, and retirement. Skill tool declarations may narrow runtime
permissions but cannot expand them.

### Interviews

Evidence interviews clarify missing application evidence. Mock interviews provide
job-specific practice and coaching. Both are persisted and can resume after a
process restart; neither may silently confirm new career evidence.

## Architecture

```mermaid
flowchart TB
    WEB[Career chat] --> API[FastAPI]
    EXT[Chrome Side Panel] --> API

    API --> RUNS[Custom resume Agent Loop]
    API --> SESSIONS[Session Coordinator]
    API --> WORKSPACE[Job Workspace]
    API --> MULTI[Multi-Agent task runtime]

    SESSIONS --> CONTEXT[Context snapshots]
    SESSIONS --> TOOLS[Tool Runtime]
    MULTI --> SESSIONS
    MULTI --> WORKSPACE
    CONTEXT --> MEMORY[Confirmed Memory]
    CONTEXT --> SKILLS[Approved Skills]
    TOOLS --> BUILTIN[Built-in tools]
    TOOLS --> MCP[Governed MCP stdio tools]
    WORKSPACE --> EVIDENCE[Career Evidence]
    WORKSPACE --> PACKS[Application Packs]

    RUNS --> DB[(SQLite via Alembic)]
    SESSIONS --> DB
    MULTI --> DB
    WORKSPACE --> DB
    CONTEXT --> DB
    TOOLS --> DB
```

### Copilot and tool loop

Each model decision and each individual tool call has its own persistence boundary.
The coordinator never keeps a database transaction open while waiting for a provider
or tool.

```mermaid
flowchart TD
    A[Persist user message] --> B[Claim session execution]
    B --> C[Prepare and persist context snapshot]
    C --> D[Invoke model once]
    D --> E[Persist assistant response]
    E --> G[Mark snapshot used]
    G --> F{Tool calls requested?}

    F -->|No| H[Return response and release claim]

    F -->|Yes| I[Persist ordered pending calls]
    I --> J[Process first pending call]
    J --> K{Approval required?}
    K -->|Yes| L[Persist awaiting approval and release claim]
    L -->|Approved| M[Persist approval]
    L -->|Rejected| N[Persist safe rejection tool message]
    M --> O[Execute through persistent ToolExecutor]
    K -->|No| O
    O --> P[Persist tool result message]
    N --> Q{More pending calls?}
    P --> Q
    Q -->|Yes| J
    Q -->|No| C

    D -. Cancellation or deadline .-> R[Discard unpersisted response safely]
    O -. Uncertain external outcome .-> S[Await manual recovery]
```

The context snapshot fixes the exact policy, Skill versions, Memory versions,
conversation groups, evidence sources, and effective tools used for a model call.
Recovery reuses that snapshot instead of silently selecting newer context.

### Multi-Agent application workflow

The Multi-Agent runtime coordinates a server-defined application plan. It is an
opt-in orchestration path behind application preparation, not a separate chat persona
or a user-selectable execution-mode switch. The model cannot invent child agents,
dependencies, permissions, or budgets.

```mermaid
flowchart TD
    A[Source preparation] --> B[Candidate analysis]
    A --> C[Job analysis]
    B --> D[Requirement matching]
    C --> D
    C --> E[Analysis projection]
    D --> E
    D --> F[Evidence-gap classification]
    E --> F

    F --> G{Clarification requested?}
    G -->|Yes| H[Evidence interview]
    G -->|No| I[Freeze generation evidence]
    H --> I

    I --> J[Artifact writers run independently]
    C --> J
    D --> J
    J --> K[Verify each artifact]
    K -->|Unsupported claims and revisions remain| L[Revise that artifact]
    L --> K
    K -->|Verified or bounded final result| M[Assemble Application Pack]
    M --> N[Human review]
```

The runtime provides:

- **Deterministic planning.** Python builds and validates the DAG before any worker
  runs. Unknown task types, cycles, invalid dependencies, excessive depth, or budgets
  outside server limits are rejected.
- **Isolated child sessions.** Each task receives declared input artifacts and a
  scoped context. It does not inherit sibling conversations, arbitrary tools, or new
  permissions.
- **Dependency-aware scheduling.** `requires_success` blocks downstream work after a
  failed prerequisite; `requires_completion` lets pack assembly account for optional
  artifacts that ended without succeeding.
- **Bounded parallelism.** Ready tasks are claimed with leases and heartbeats, while
  the plan limits total tasks, depth, concurrent work, model calls, tool calls,
  tokens, cost, and deadlines.
  Model workers reserve call and token capacity before contacting the provider.
  Failed attempts retain their reservation when actual usage is unavailable;
  retries share the same persisted plan budget. Provider usage replaces token
  estimates when returned. Monetary cost caps are not supported yet: setting one
  blocks model calls instead of silently ignoring the cap.
- **Durable artifacts.** Analyses, evidence snapshots, drafts, verification reports,
  revisions, and the final pack are versioned outputs rather than hidden agent-to-agent
  messages.
- **Safe recovery.** Expired task claims can be recovered within attempt limits;
  cancellation, timeout, approval, and required user input remain explicit states.

The main application DAG currently prepares a tailored resume, cover letter, and up
to three application answers. Restricted questions remain manual. A failed required
artifact blocks final assembly, while optional artifacts are recorded according to
their terminal outcome. The resulting pack still requires human review.

Important boundaries:

- **Custom Agent is the active backend** for newly created runs.
- **The custom Agent Loop is the only execution backend** for the API, CLI, and
  workflow evaluations. The retired graph runtime and its dependencies are removed.
- Schemas, prompts, model configuration, domain rules, rendering, and evaluation
  datasets are shared where behavior must remain comparable.
- Saved results from historical runs remain readable. Runs whose stored backend
  is retired or unknown cannot be reviewed or resumed; create a new custom run.
  Historical backend labels remain in the database for provenance.
- Model and tool calls execute outside database transactions.

## Persistence and recovery

The default database is `job_agent.db`; custom state and audit events live in the
same database. Old checkpoint files are no longer opened or required. Existing
database files and archived evaluation reports are not deleted by this cleanup.
Override the active database with:

```dotenv
JOB_AGENT_DATABASE_URL=sqlite:///./job_agent.db
```

SQLite foreign keys are enabled on every connection. Business state, events, and
public projections are committed transactionally with optimistic version checks.
Session execution uses time-bounded claims so one active attempt owns a running
session.

Recovery guarantees are deliberately conservative:

- completed tool results can be replayed into a missing session message without
  executing the tool again;
- expired read-only, side-effect-free, idempotent calls may retry within limits;
- uncertain write calls become `outcome_unknown` and require manual recovery;
- provider model calls are at-least-once if a process stops before the response is
  durably persisted;
- no exactly-once claim is made for external side effects.

## Optional MCP tools

MCP support is limited to governed local `stdio` servers. Configuration is loaded
from `MCP_CONFIG_PATH`; see `examples/mcp/local_test_config.json` for the local test
server format.

MCP tools enter the same registry, policy, approval, timeout, idempotency, provenance,
and persistence path as built-in tools. Current support does not include Streamable
HTTP, OAuth, resources, prompts, sampling, or elicitation.

## API overview

The complete contract is available from `/docs`. Main endpoint groups are:

| Prefix | Purpose |
|---|---|
| `/runs` | Resume workflow runs and human review |
| `/sessions` | Persistent Copilot conversations, messages, approvals, cancellation, and recovery |
| `/api/workspaces`, `/api/applications` | Saved jobs and application workspaces; `/api/applications/overview` adds pipeline and weekly figures |
| `/api/resumes` | PDF resume upload and default resume selection |
| `/api/packs` | Application Pack generation and review |
| `/api/materials` | Materials library across applications, with rendered versions |
| `/api/evidence` | Governed Career Evidence |
| `/memories`, `/skills` | Memory and Skill lifecycle management |
| `/api/interviews`, `/api/mock-interviews` | Evidence discovery and interview practice |
| `/api/applications/{id}/multi-agent-runs`, `/api/multi-agent-runs` | Governed application task plans, progress, cancellation, and resumption |
| `/api/assistant-sessions` | Safe conversation timeline and registered actions |

Client-facing errors are normalized. API responses do not expose API keys, complete
tracebacks, SQL, local paths, raw system prompts, or private tool results.

## Testing

Run the complete Python suite:

```powershell
python -m pytest -q
```

Run the browser-side unit tests:

```powershell
node --test tests/test_copilot_ui.mjs tests/test_learning_ui.mjs tests/test_mock_interview_ui.mjs tests/test_web_ui.mjs
```

Run the suite including the real-Chrome tests. They drive local fixture pages in
Google Chrome and intercept every employer request, so they make no network or model calls:

```powershell
$env:JOB_AGENT_BROWSER_TESTS = "1"; python -m pytest -q
```

The historical release baseline before removal of the graph backend was:

```text
638 passed, 1 skipped
18 JavaScript tests passed
```

Current test totals change as retired-backend tests are replaced by custom-loop
coverage. Tests use fake models or scripted adapters by default and do not make paid model
calls. Live evaluations are opt-in. Reproducible datasets, runners, raw outputs, and
version metadata live under `evals/`.

GitHub Actions runs both commands on every push and pull request through
`.github/workflows/ci.yml`, and runs the real-Chrome tests on a Windows runner. It never runs a real-model evaluation. Live evaluations
remain explicit, paid, manual commands.

Human material-quality review uses 10–20 anonymized real resume/JD pairs and scores
factual accuracy, non-duplication, and application readiness. The governed local
packet format and privacy rules are in `evals/human_quality_review/README.md`.
Synthetic stability cases do not count as real-material review, and every failed
human review must identify a regression test before the packet validates.

Common evaluation commands:

```powershell
python -m evals.run_evals
python -m evals.run_stability_evals
python -m evals.run_requirement_intelligence_v3
```

These runners use the configured model and may make billable provider requests.
Unit tests remain offline by default.

Review the saved artifacts in `evals/results/` instead of combining results from
different prompt or dataset versions.

## Project layout

```text
JobHunterAgent/
|-- agent_runtime/       # Tool, session, context, memory, skill, MCP, and agent runtimes
|-- api/                 # FastAPI routes, schemas, dependencies, and services
|-- chrome_extension/    # Manifest V3 Side Panel extension
|-- custom_agent/        # Active persisted resume workflow loop
|-- job_agent/           # Shared schemas, prompts, model config, domain rules, rendering
|-- web_app/             # Unified career chat and retained UI modules
|-- migrations/          # Alembic schema history
|-- evals/               # Synthetic datasets, runners, and versioned results
|-- skills/              # Built-in, project, and generated Skill packages
|-- tests/               # Python and JavaScript tests
|-- examples/mcp/        # Local MCP example configuration and server
`-- scripts/             # Development smoke-test utilities
```

## Security and current limitations

This is a trusted, local, single-user application. It is not an authentication or
multi-tenant authorization boundary.

- Do not expose the service directly to an untrusted network.
- Resume text, job descriptions, feedback, generated artifacts, messages, and audit
  state are stored locally in SQLite.
- The browser extension treats webpage content as untrusted data and renders returned
  content with safe DOM APIs.
- Prompt instructions and structured output reduce risk, but deterministic evidence
  validation is the primary claim-safety boundary.
- SQLite is suitable for this local deployment, not high-throughput multi-worker use.
- Dynamic provider timeouts depend on provider support; Python cannot forcibly stop an
  in-flight remote request.
- LinkedIn extraction may require selector updates when its DOM changes.
- OCR, hosted authentication, cloud synchronization, automatic job submission, and
  login bypass are outside the current scope.

## Development policy

All executable workflows use the custom runtime. Archived evaluation reports
retain their original backend metadata and are historical evidence only. Database
changes require Alembic migrations, and tests should use isolated temporary SQLite
files rather than production `create_all()`.

### Command-line workflow

`python main.py resume.txt job.txt --thread-id application-001 --output result.json`
runs the same persisted custom Agent Loop as the API. Use a unique run ID for each
application; the CLI never overwrites an existing run. `--database-url` optionally
selects a separate database. A run paused for review can be reviewed through `/runs`
using the same database. A retired backend cannot be selected by environment settings.

## On-demand discovery and optional daily recommendations

Job discovery is available directly in the existing `/apply` conversation. For
example, say “Find five data analyst jobs in New York that fit my resume.” eregion
chooses sources and search terms, searches in the actual browser, reads postings, scores promising roles against
the saved resume, and adds its reasons and uncertainties to the job cards. Continue
with “Only show remote roles” or ask it to prepare materials for a selected job.
A one-time search creates no schedule and requires no notification setup.

Browser search is the default for both chat and scheduled research. For example,
“Search LinkedIn for data analyst roles in New York” opens LinkedIn Jobs and uses
its search fields, filters and visible results. The agent can read or scroll a
specific result/detail panel, expand descriptions and capture the selected posting
for analysis without mixing in neighboring results. Public HTTP search and
Greenhouse/Lever APIs remain supplementary tools for blocked access or broader
coverage; a requested LinkedIn search should not silently become an API search of
unrelated company boards.

Research and application browsers run locally in the background, including
scheduled searches, reopened tasks and server recovery. Click **Control browser**
in **Agent activity** to pause the agent and interact with its current page inside
the chat interface. The browser is not restarted, so unsaved form fields and file
inputs are preserved. Click, drag, scroll, switch tabs, type text or send keys;
use Actual size on a small screen. Input goes directly to the local browser, not
to chat or answer memory. Passwords and one-time codes are masked in previews;
other page content can be observed by the agent after resuming. Closing the view keeps the agent paused; **Done · Resume agent**
returns control. Resuming or new feedback invalidates the old control session.
Submission review is invalidated before handoff; a submission in progress cannot
be taken over. **Open Chrome window** is an explicit fallback: it restarts the
browser with storage state, so unsaved DOM edits and file inputs may be lost.
This local viewer does not bypass site verification or keep a browser alive
through a backend restart. No cloud browser subscription is required.

The research browser is isolated from the user's usual Chrome profile. Public
LinkedIn search can work without an account; access varies by page and session.
Observed public links and dismiss buttons remain usable on an account overlay,
while account text, credentials and screenshots stay hidden from the model. When
an account or verification is required, use **Control browser**, sign in there,
and reply in chat to continue. This research path does not yet expose the
application worker's secure credential form or persist its login across research
sessions. Scheduled runs try other accessible sources and report coverage limits.

For recurring research, explicitly ask in chat, for example: “Every day at 9 AM
New York time, find up to five new remote Python roles with a match score of at
least 75.” The agent can create, edit, pause and resume daily searches. The optional
**Job alerts** view provides the same settings, manual **Search now**, digest history
and **Find jobs now** to return to an ordinary chat. Daily searches call the same
career tools and task loop as one-time searches; they are not a separate search bot.

Each recommendation must have a retrieved posting and a saved score for the current
resume and job description. Scheduled digests enforce the selected score threshold,
result count and deduplication across prior digests, including common tracking URL
variants. A digest can contain fewer results or no matches. Blocked sources and
uncertainties should be explained instead of replaced with invented jobs. Scheduled
research does not apply, register accounts or contact employers. Opening its
conversation lets the user continue with the normal interactive capabilities.

Run one local backend worker and keep the computer awake. Searches **start** at the
chosen local time; recommendations arrive after retrieval and model scoring finish.
Schedules and results persist in the database. After downtime, one catch-up search
replaces missed daily runs. IANA timezones handle daylight saving: repeated local
times fire once and nonexistent times shift forward. Windows installs `tzdata`
from `requirements.txt`. Startup applies migration `0034_career_job_alerts`.

In-app digests are saved even when the web page is closed. Optional browser popups
require the eregion page to stay open and **Enable browser notifications** to be
clicked; permission is never requested just because the user searched. Popups are
deduplicated in this browser and read digests are not notified again. This version
does not provide browser-closed Web Push or an OS/cloud scheduler. See
[MDN's notification permission documentation](https://developer.mozilla.org/en-US/docs/Web/API/Notification/requestPermission_static).

The API is `/api/career/alerts`: GET lists schedules and digests, POST creates a
schedule, PUT `/{alert_id}` updates it with an expected version, POST
`/{alert_id}/run` starts an idempotent manual run, and POST
`/digests/{run_id}/read` acknowledges a digest. Settings remain opt-in; installation
does not create an enabled search schedule.

Verification uses isolated databases and synthetic candidate data:

```powershell
python -m pytest tests/test_job_alerts.py -q
$env:JOB_AGENT_BROWSER_TESTS='1'
python -m pytest tests/test_job_alerts_browser.py -q
python -m pytest tests/test_general_browser.py tests/test_browser_job_search.py -q
# Optional: real configured model and real public boards; incurs model usage.
python scripts/job_discovery_eval.py --live --seconds 360
python scripts/job_discovery_eval.py --live --source linkedin --seconds 420
python scripts/browser_eval.py --case linkedin --seconds 240
```

The live evaluation searches Greenhouse/Lever or LinkedIn, checks recommendation scores
against saved analyses and verifies that a one-time request creates no schedules.
It uses a synthetic resume and does not apply or create accounts. Reports are saved
under `artifacts/browser-eval/`; they establish the tested path, not universal
coverage across all employers.

## Unified career conversation

Open `/apply` and describe the goal in ordinary language, for example:
“Find Python backend roles in New York, compare them with my resume, prepare
materials for the best fit, and help me apply and practice the interview.” Attach
a selectable-text PDF once; the saved source resume and profile persist across
conversations. Existing browser attempts still appear in the sidebar.

The model owns planning and tool selection through `agent_runtime/task_loop.py`.
`agent_runtime/career/harness.py` provides career capabilities: public job discovery,
saved jobs, actual fit analysis, verified writing, browser applications, confirmed
career evidence, and mock interviews. There is no required stage ordering. A user
can start with an interview, compare several roles, revise documents, or change the
goal while work is running. Questions can wait while independent work continues;
browser waits resume on state changes without spending repeated model calls.

- Search prioritizes browsing job websites such as LinkedIn, with public web results
  and Greenhouse/Lever APIs available as supplemental sources. Rendered job text
  from the selected posting is captured before scoring. Search can be blocked;
  login-only descriptions can need user sign-in in the agent's browser. This is not
  a guarantee of every job board's coverage.
  Applying with the saved resume can open the browser directly without prior
  description extraction or scoring; no fabricated workspace/score is created.
- Scores, document previews, PDF downloads, document approval, application review,
  interview questions and feedback appear in the same chat. Versions remain linked
  to their job. Original resumes are preserved; approved tailored materials are
  the default when that job has a pack. Updated documents invalidate the old
  application review and reopen the browser to upload the replacement files.
- Extra career facts supplied in chat can be saved as exact user-attested quotes
  for future writing. The existing evidence verifier remains responsible for
  rejecting unsupported claims.
- The browser capability retains autofill, model-controlled DOM operations, optional
  visual computer use, secure login/registration, remembered answers, multiple
  education records, batched questions and explicit final submission confirmation.
  Credentials go directly to its secure account endpoint, outside model context.
- The main task loop also has a general browser: public home pages, search, links,
  editable controls, dropdowns, dynamic loading, back navigation, tabs, frames,
  open shadow roots, and paginated/filterable page observations. Browsing needs no
  resume or application record. The same navigation tools are available to the
  application worker, where applicant answers still use its grounded field tools.
  Every action returns the observed page; stale targets and navigation races can
  be recovered by reading/waiting rather than restarting the task. Rendered job
  text can feed `read_job` and `import_job` when an HTTP fetch misses JavaScript.
  Previews use `/api/career/tasks/{task_id}/browser/preview` in the existing chat.
  The existing **Visual browser backup** option also enables main-task screenshots
  and coordinate clicks. The agent can choose visual recovery when DOM controls
  are incomplete. Non-login viewport images are sent to the configured model for
  one decision, with password/OTP controls masked, and are not stored in task
  history. Turning the option off removes retained model image inputs. Login and
  verification pages stay in the secure workflow. Browsing tabs are ephemeral and
  isolated from the user's signed-in Chrome. After restart, reopen the last URL.
- Only a confirmed employer receipt marks a workspace job as applied. Practice
  interviews do not imply a real interview invitation or a scheduled meeting.
- Conversations, plans, linked results and question IDs persist in migration
  `0032_career_tasks`. Startup applies migrations and restores unfinished work.
  Use one backend worker. Pause persists until an explicit resume; user feedback
  invalidates model decisions computed before that feedback.

The API is `/api/career/tasks` (create/list/read/chat, material reviews and browser
review actions). `PATCH /api/career/tasks/{id}` renames, pins, groups, archives or
trashes a conversation; `?view=archived|trash` lists those views; `DELETE` removes a
trashed conversation permanently and `DELETE /api/career/tasks/trash` empties Trash.
Groups live at `/api/career/groups`. Existing workspace, Pack, interview and browser APIs remain usable.
The standalone browser chat is available at `/apply?mode=application`.

Live browser evaluations are opt-in: run
`.venv/Scripts/python.exe scripts/browser_eval.py --case wikipedia --case todo`.
They use the configured model and the real task loop/career harness, a fresh test
database, and isolated Chrome with no saved candidate details, resumes or cookies.
The model chooses actions; separate DOM assertions verify outcomes. Public-site
interaction tests do not submit applications or create accounts. Reports, timings,
tool histories and final screenshots are saved under `artifacts/browser-eval/`.
`--driver` checks reachability only and does not count as an autonomous pass.
`--case visual` explicitly enables screenshot-to-model input and verifies a real
coordinate click on the W3C combobox demo; other cases use DOM tools only.

The conversation loop retries temporary model connection errors, timeouts, HTTP 429,
and server failures up to twice, counting each attempt against its model-call budget.
It reports retry progress and safe error details in chat, without recording provider
response bodies. New feedback or a pause cancels pending retries; completed tools are
never replayed by a model retry. Greetings can receive a direct conversational reply
without inspecting saved jobs or starting a workflow.

Text accompanying a tool call appears in chat before the tool executes. The API
exposes active tool progress and recent observation/model/tool timings for latency
diagnosis. Each decision includes the current context once, with document status
summaries; full documents and verification results remain available through
`inspect_materials` and the review cards. Model responses are currently displayed
after each response completes, rather than streamed token by token.

Chat replies render Markdown as semantic headings, lists, emphasis, links, code,
and responsive tables. Historical replies use the same typography without a data
migration; Copy copies the visible plain text. The pinned local Marked lexer lives
in `web_app/vendor` with its MIT license. The renderer creates DOM nodes directly:
embedded HTML stays inert, and Markdown images do not trigger external requests.

Verification with synthetic profiles and intercepted employer requests:

```powershell
python -m pytest tests/test_task_loop.py tests/test_career_flow.py -q
$env:JOB_AGENT_BROWSER_TESTS='1'
python -m pytest tests/test_career_browser.py tests/test_auto_apply_browser.py -q
node --test tests/test_career_chat.mjs tests/test_apply_answers.mjs
```

`JOB_AGENT_LIVE_CAREER_TEST=1` additionally enables the configured-model orchestration
check in `test_career_flow.py`. It uses a fictional candidate and local job/browser
fixtures; no real application is submitted.

## Standalone browser application assistant

Open `/apply?mode=application` to work directly with the browser capability.
It uses a persisted custom observe/act/verify
loop under `agent_runtime/auto_apply`; it has no LangGraph dependency. The existing
resume-generation loop remains focused on producing and reviewing materials.

1. Install the updated `requirements.txt` and run `python -m alembic upgrade head`.
2. Start the local service with one worker. Chrome must be installed on this machine.
   Set `JOB_AGENT_BROWSER_CHANNEL=msedge` to use an installed Edge instead.
3. Attach the final resume PDF in the chat. Selectable text is sent to the configured
   model to extract evidenced contact and education details. Missing required details
   are asked in chat; **Your details** (bottom of the sidebar) opens an optional profile editor.
4. Send a direct public HTTPS job link (for example Greenhouse, Lever or Workday).
   The chat starts Agent + autofill automatically.
   New chat applications always show a review card before submission. The API retains
   its existing explicit automation/submission settings for other clients.
5. Reply in the conversation; no question-selection dropdown or Continue click is
   needed. Short choices appear next to questions; three or more questions are asked
   one at a time. **Agent activity** (the panel button in the header) opens the
   browser preview, plan, activity, completed answers and answer memory. **Pause agent
   & use Chrome** stops automation for manual interaction; send `continue` to resume.
   Review approval remains bound to the observed form and is invalidated by changes.
6. Answers the agent interpreted from your chat are listed on the review card with a
   **Remember** checkbox. Checked answers are saved when you submit and are filled in
   automatically on later applications, so each answer is approved once. **Standard
   answers** in **Your details** (salary, start date, relocation, work authorization,
   demographics and similar) are approved the same way and match common wordings.

Application automation settings (environment variables):

| Variable | Default | Effect |
| --- | --- | --- |
| `JOB_AGENT_APPLY_WORKERS` | `2` | Applications filled at the same time (1–8). Jobs on one employer site always take turns. |
| `JOB_AGENT_MAX_OPEN_APPLICATIONS` | `6` | Unfinished attempts allowed at once; each can keep a Chrome window open. |
| `JOB_AGENT_HIDDEN_BROWSER` | `offscreen` | How Chrome runs while hidden. `offscreen` is a normal window placed off-screen, which sites challenge far less often than headless Chrome and which can be shown without reloading. `headless` restores the previous mode. |
| `JOB_AGENT_ALLOWED_HOSTS` | (none) | Extra hostnames accepted by the local server besides `localhost` and `127.0.0.1`. |

If a site shows a verification challenge, use **Control browser**, complete it, and the
agent continues by itself once the challenge is gone.

If the browser never opens, confirm that Playwright is installed in the **same
Python environment as the server**. Installing Chrome alone is not enough. After
pulling updated code, rerun `python -m pip install -r requirements.txt` in that
environment and restart the server. Missing Python browser dependencies pause the
attempt with setup instructions rather than automatically retrying.

For macOS, run these commands from the repository root (with Google Chrome installed):

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

The default `chrome` channel uses the installed Google Chrome on Windows, macOS,
and Linux; it does not require a separate `playwright install` browser download.
After repairing the environment, choose **Try again** on the existing attempt.

Hybrid mode uses the existing `LLM_MODEL_ID`, `LLM_BASE_URL`, and `LLM_API_KEY`
configuration. The model must support native tool calls and image input for visual
backup. It chooses how to combine
deterministic `autofill`, individual field actions, and page navigation. Playwright
performs real browser input using DOM/ARIA locators or screenshot coordinates.
The visual backup uses the same model and browser session, rather than requiring
a provider-specific computer-use model or controlling the user's desktop.

Field observations include nearby groups, help, constraints and validation errors.
The agent also reads selectable text from the attempt's saved resume, including
work and project history. For open-ended questions it can compose a draft with
literal resume/chat evidence. Drafts appear in editable multiline answer boxes
with source excerpts; missing details such as an unreported measurable effect are
called out separately, without inventing results. Review or edit the draft and use
the existing **Submit answers & continue** button. Until then, the draft is kept
separate from confirmed answers, browser input and cross-application answer memory.
Existing attempts reuse their stored PDF; they do not require a new upload.

`resolve_field` lets the model adapt a sourced value to the site's representation
(including splitting an international phone), match an observed semantic option,
or choose an incidental default such as a handset classification. These run-local
decisions have provenance and are kept separate from confirmed answers/memory;
source corrections invalidate them. The review panel labels incidental defaults.
Material answers and consent still require explicit facts. This does not prevent
`equivalent` mappings of a supplied fact (for example an M.Eng. to an observed
Masters category); those cite this question's confirmed source, respect explicit
corrections, and never become default qualifications or new remembered facts.
`explore_option` opens
an observed category without requiring it to equal the user's intended leaf, then
reads its children or newly revealed dependent controls. Search text is distinct
from a committed selection. A rejected unchanged value is handed to the model for
repair instead of repeatedly being written by autofill.

It observes retained values after every action. **Visual browser backup** is an
explicit option in application details, disabled by default. When enabled, after
a failed DOM action (or when the model requests `view_browser`), the model sees
the current viewport and can click, double-click, hover, scroll, drag, type a known
source or press editing/navigation keys. Each action returns a fresh screenshot.
The model uses an explicit 0..1000 coordinate grid, mapped to the screenshot's CSS
pixel dimensions (also on high-DPI displays); old images are rejected
after page changes. The model can explore menus without DOM option roles. Actual
form values and errors still determine completion, not a successful mouse click.
Screenshots stay in memory, password/verification controls are masked, and account
pages use the secure account workflow. Candidate facts, fields and requested
screenshots are sent to the configured model. Changing the visual option applies
to the active attempt with the next chat message, including `continue`.
The model cannot navigate arbitrarily, execute page JavaScript, or submit directly.
Final validation and the submission boundary remain in the custom host loop.

The agent executes up to 12 decisions per worker slice and schedules the next slice
automatically while making progress. The task plan, recent actions and last tool
result survive slices. A user instruction/resume has a budget of 40 model calls and
120 tool calls; cumulative usage is retained. Transient failures have at most two
automatic recovery attempts with backoff. Waiting does not block other browser work,
and pause/cancel invalidates scheduled retries. Persistent failures surface a retry
action rather than asking for already supplied answers. Autofill failures are isolated
per field. Existing API clients can still select deterministic autofill mode.

Country aliases (for example US/USA/United States), phone-country suffixes, and
common school names/abbreviations are matched against observed options. School
acronyms with multiple matches pause rather than select an arbitrary campus.
Autocomplete searches can expand known aliases before retrieving options.

**Remember my answers** stores user-provided answers under the candidate email.
Equivalent questions on another application can reuse them, with their original
question shown beside the field. Work authorization preserves country context;
sponsorship and present/future scope are separate. Consent is asked on first use,
including optional consent controls, then reused for an equivalent question.
Generic "I agree" labels without scope are not reused. Candidate details in the
current resume/form take priority over older remembered contact/education answers.
Open **Remembered answers** to inspect or forget entries. Previously saved explicit
answers are indexed once on upgrade; forgetting an entry survives a restart.
Migration `0030_application_memory` adds the answer store.

Optional fields explicitly requested by the agent appear in the same question
list and answer controls as required fields. Voluntary demographic dropdowns use
confirmed answers or ask for the site's actual choices, including decline options;
they are never inferred from the resume. Newly revealed dependent questions are
handled after the preceding selection.

The original resume PDF and editable candidate details now persist locally across
new applications, page reloads and server restarts. **Your details** includes an
editable education history. Migration `0031_saved_candidate` adds this store;
the latest legacy application's resume is restored once and re-extracted to obtain
all education records. Removing the saved resume prevents legacy backfill from
restoring it again. Resume extraction uses the agent's ordinary tool-call transport
and validates each extracted fact against a literal quote from the PDF.

The agent sees confirmed answer memories with their original questions and can
reuse paraphrased questions through `use_remembered_answer`; consent, immigration
and employer-specific facts retain their scope. Education rows are associated with
individual saved records using `bind_education`. Autofill then fills each record's
school, degree, major and stated dates, including optional fields. Completion checks
prevent moving past an offered repeatable education section with missing records
or known details. Date components absent from the resume are not invented.

Inline questions keep selections as drafts. Choose all answers, then use
**Submit answers & continue** to save them in one request and resume the agent once.
Polling retains unsent choices; changing the question schema invalidates its draft.

The application agent now owns its questions through `ask_user`, including general
questions that are not attached to a form field. Its wording is preserved in chat.
It can set `wait_for_reply=false`, keep working on independent controls, and use
`wait_for_user` when the reply becomes necessary. Pending answer batches remain
available while the browser runs. Replies use the question ID (`POST
/{run_id}/reply`) instead of a changing application version; duplicate replies are
idempotent, stale questions are rejected, and new feedback invalidates a pending
model action. Replying to an explicitly paused task saves answers without resuming it.

`agent_runtime/auto_apply/runner.py` runs decisions separately from the tool
implementations. A bounded history of the last 24 tool arguments and outcomes is
persisted with the task and included in subsequent observations, including after a
worker yield or restart. Repeated unchanged actions receive strategy feedback before
being stopped. Worker slices continue within the configurable per-interaction budget
(120 model calls and 360 tool calls by default); a slice ending is not itself a request
for user input. Screenshots and credentials are excluded from this durable trace.
Ordinary observed page buttons such as Edit or Show details are available without an
ATS-specific label whitelist. Final submission, unknown form-submit controls, consent
and source-sensitive field changes retain their dedicated checks.

The application chat persists user feedback and agent replies. Sending feedback
invalidates an outstanding model decision; the next decision sees the new message.
**Pause** stops subsequent actions and submission until you continue. The browser
panel shows local snapshots and named tool actions. The browser preview stays local;
the separate visual-backup option also sends requested viewport images to the model. This is a preview,
a periodic screenshot preview; click **Control browser** for direct local interaction.

Each attempt stores its selected PDF, candidate details, explicit answers, observed
form state, and bounded event history in the local application database. Cookies and
passwords are not stored in that database; encrypted browser login state is described
below. The reusable candidate store keeps the original PDF separately from the
resume library's extracted text, so subsequent applications can reuse the upload.

The runtime limits open active attempts to three and runs browser actions serially.
It re-observes after every fill, bounds execution time and action count, and detects
an unchanged unsuccessful action instead of clicking indefinitely. A unique posting
identity prevents duplicate attempts, including across tracking URLs and restarts.
Before a submit click it durably enters `submitting`. Missing confirmation, crashes,
or timeouts after that point become `submission_unknown`; there is no automatic
resubmission. Only an observed employer confirmation marks a run `submitted`.

Running/queued hybrid attempts resume on server startup from saved facts and answers.
Paused tasks remain paused; previously approved review screens require fresh review
after reopening the browser. The local backend and computer must stay running for
background execution. Unstarted chat drafts are held in the current page; the reusable
candidate profile/PDF, started applications and their chat are stored in the database.
Cancelling before submission preserves progress and offers **Resume application**.
Resuming reopens the same attempt, restores saved answers and drafts, and requires
a fresh final review. Sending an existing job link in a new chat opens its original
application instead of leaving the user at a duplicate error. An application that
has reached submission (including an uncertain result) cannot be restarted this way.
The browser now accepts public HTTPS job links beyond Greenhouse and Lever. The
LLM observes page text, application controls and the current form, and chooses when
to open Apply, import a resume, add a repeated section, or continue to the next
step. Final submission remains host-controlled, and a Next button does not count
as a completed application. Earlier-page answers stay available for review.

Candidate account pages open a dedicated credential dialog. The agent can sign in
or register using the supplied email or username and password; the password is kept out of model
inputs, chat, application records and previews. Account agreements are shown with
the page's instructions and require explicit choices. Verification emails, MFA,
CAPTCHA still pause for browser interaction. The secure worker observes each step
and supports email-first, password-only, confirmation fields, unfamiliar submit
labels, and account forms inside already allowed site frames. Ambiguous controls
can be selected by the model from a value-free catalog of control types and locally
classified purposes. Login-page prose, labels, screenshots and credential values
are not sent by this selector. New agreements and origin/mode changes require a
fresh secure request; rejected credentials are never submitted repeatedly.
Structurally ambiguous layouts, third-party embedded sign-in and SSO can still need
browser interaction. This is not a claim that every employer login is supported.
Account requests take priority over parent chat questions, and the parent observes
only their summary. Truncated responses and detected internal protocol narration
are withheld and given one repair attempt before a clear model error is displayed.
Successful login cookies/local storage are encrypted with Windows DPAPI under
`.browser-sessions/`, isolated by candidate email and the initial job-site host.
Passwords themselves are not retained by the agent. Other operating systems retain
the current browser session but do not persist an unencrypted fallback. This is a
local Windows implementation, not a credential service for cloud deployment.

Hosted Greenhouse/Lever controls have regression coverage. Workday's public
application, email sign-in, and registration entry screens have been inspected;
account execution, multiple pages, and final review are tested using offline
fixtures. Other ATS links (including Ashby, SmartRecruiters, iCIMS, Taleo,
SuccessFactors and Jobvite) enter the same generic loop; URL acceptance is not a
claim of verified compatibility. Custom widgets, SSO redirects, unknown questions
and employer-specific steps can still require browser interaction. Job discovery
is available in the career conversation described above; cloud browser hosting is
not included.
Attempts have their own history; they do not automatically change the saved
job's pipeline status. Use a single trusted local server process, not a public or
multi-tenant deployment.

Application tests (scripted model responses, no live model calls):

```powershell
python -m pytest tests/test_auto_apply.py tests/test_auto_apply_agent.py tests/test_auto_apply_personalization.py tests/test_auto_apply_conversation.py tests/test_auto_apply_autonomy.py -q
$env:JOB_AGENT_BROWSER_TESTS = "1"
python -m pytest tests/test_auto_apply_navigation.py tests/test_auto_apply_workday.py tests/test_auto_apply_browser.py -q
```

The Chrome tests intercept every employer request and use local fixture pages. They
cover actual browser filling, PDF upload, questions, review, confirmation, and the
web UI through the real API without submitting to an employer. Hybrid tests also
cover keyboard fallback, readonly portal dropdowns, replaced DOM nodes, background
requests during pauses, cancellation, stale observations, answer grounding, resume
extraction, cross-application memory, chat corrections, previews and forgetting.
These tests do not establish compatibility with every live model provider. Production selectors
were also checked against public read-only Greenhouse and Lever pages; this does not
establish success across every employer customization.

Implementation references: [Playwright input actions](https://playwright.dev/python/docs/input),
[Playwright locators](https://playwright.dev/python/docs/locators),
[Greenhouse job board documentation](https://docs.greenhouse.io/job-board.html),
and [Lever hosted application URLs](https://github.com/lever/postings-api).
