# Eregion

**Your job search, in one conversation.**

Eregion helps you find relevant roles, understand your fit, prepare application
materials, work through application forms, and practice for interviews. Bring
your resume, describe what you want, and keep the whole search in one workspace.

Run it on your computer with your own model API credentials. Your saved resume,
conversations, documents, and application history stay in a local database;
model-assisted work sends relevant content to the providers you configure.

[Get started](#get-started) · [User guide](docs/usage.md) ·
[Configuration](docs/configuration.md) · [Architecture](docs/agent-loop.md)

## From a first search to an interview

| What you need | What Eregion does |
| --- | --- |
| Find your next role | Browse job boards and company careers pages, build a shortlist, or schedule recurring recommendations. |
| Decide where to apply | Compare a job with your resume and show the score, supporting evidence, gaps, and questions that need your input. |
| Prepare your materials | Draft a tailored resume, cover letter, and application answers using your source information. Review versions and download resume PDFs. |
| Get through the application | Navigate pages, fill known details, upload approved documents, and ask for missing answers in chat. |
| Keep the process moving | Reuse confirmed details and answers, follow multiple applications, and resume saved work. |
| Prepare for the conversation | Practice job-specific interview questions and receive feedback and a final report. |

The agent chooses its next actions and can continue independent work while it
waits for an answer. You can correct it, pause it, or take control of its browser.
Material approval and final application submission remain explicit review steps.

## Get started

You need **Python 3.12**, **Google Chrome** for browser tasks, and credentials for
an OpenAI-compatible model service. Choose a model that supports tool calling and
structured output; visual browser backup also requires image input. Node.js is
only needed for frontend tests.

### 1. Install

```sh
git clone https://github.com/ethany14/JobHunterAgent.git
cd JobHunterAgent
```

Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

macOS or Linux:

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

### 2. Connect your model

Create `.env` in the repository root:

```dotenv
LLM_MODEL_ID=your-model-id
LLM_API_KEY=your-api-key
# Set this when your provider uses a custom compatible endpoint.
LLM_BASE_URL=https://your-provider.example/v1
```

Replace the placeholders with your provider's settings. Leave `LLM_BASE_URL` out
if the client's default endpoint is appropriate. Keep `.env` private; it is
excluded from Git. Jev is optional and is not required to use Eregion.

### 3. Start Eregion

Run from the repository root, in the activated environment:

```sh
python -m alembic upgrade head
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

Open **[localhost:8000/apply](http://localhost:8000/apply)**.

The default browser channel uses your installed Google Chrome. Keep one backend
process running while the agent works or scheduled recommendations are due.

### 4. Start your first conversation

1. Upload a PDF resume with selectable text using the composer attachment button.
2. Open **Your details** and check the extracted contact information and education.
3. Describe the roles you want, paste a job description, or share a posting link.
4. Review the match, ask for tailored materials, and approve the versions you want.
5. Ask Eregion to prepare the application and review the completed form.

Try a request such as:

> Find data analyst roles in New York that fit my resume. Show me the best
> matches and explain any gaps.

> Tailor my resume and write a cover letter for this role. Keep every claim
> supported by my experience.

> Every day at 9 AM in America/New_York, recommend new roles matching
> these preferences.

## A workspace for the whole search

- **Council** holds your conversations with the agent.
- **The Road** tracks applications and their progress.
- **The Forge** keeps generated materials, versions, verification, and approvals.
- **Job alerts** manages recurring searches and recommendation digests.
- **The Lookout** shows browser activity and offers manual browser control.

Day and Night themes, conversation folders, and an archive help keep the workspace
organized as your search grows. See the [user guide](docs/usage.md) for account
sign-in, answer memory, browser takeover, and recovery.

## Bring a job from your browser

**Eregion Lens**, the optional Chrome extension, extracts the job on your current
tab, lets you edit the result, and compares it with your saved resume. Open the
saved job in Eregion to continue with materials, applications, or interview prep.

[Install Eregion Lens](chrome_extension/README.md).

## Deployment and compatibility

Eregion is a local, single-user application. The server binds to loopback by
default and is not a hosted multi-user service. The current workflow uses local
Chrome; a managed cloud browser is not required or included.

Browser automation combines form autofill, observed page controls, and optional
visual backup. Sites with login walls, custom widgets, MFA, or CAPTCHA can require
your help. Public-page checks and synthetic application tests do not establish
compatibility with every ATS or successful submission to every employer.

Generated materials are checked against their cited sources, but you should
review them before use. A match score describes the supplied evidence; it is not
a prediction of an employer's decision. PDF input currently requires selectable
text; scanned resumes need text extraction before upload.

## Documentation

| Guide | Covers |
| --- | --- |
| [Using Eregion](docs/usage.md) | Daily workflow, approvals, saved answers, alerts, and recovery |
| [Configuration](docs/configuration.md) | Model credentials, browser settings, optional Jev, and local data |
| [Agent architecture](docs/agent-loop.md) | Shared loop, evidence, context, persistence, and browser workers |
| [Jev and performance](docs/jev-benchmark.md) | Fast-path behavior, recorded measurements, and reproducible comparisons |
| [Development](docs/development.md) | Repository layout, local checks, live evaluation, and contributions |

The running service also exposes [API documentation](http://localhost:8000/docs)
and a [health endpoint](http://localhost:8000/health).
