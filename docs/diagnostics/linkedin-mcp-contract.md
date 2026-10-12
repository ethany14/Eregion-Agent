# R7 · LinkedIn MCP contract (2026-10-12)

Plan: [`claude-unified-execution-plan-20261012.md`](../specs/claude-unified-execution-plan-20261012.md) §10; roadmap §4–7 ([`execution-roadmap-linkedin-mcp-20261012.md`](../specs/execution-roadmap-linkedin-mcp-20261012.md)).

## Pinned upstream

- `stickerdaniel/linkedin-mcp-server` at commit **`5bdef1c93ff394386430faf81aed404a9e205fc7`** (pyproject version 4.27.0). This is the reviewed snapshot; never use `@latest`.
- **Source only.** The schemas below were read from that commit's `linkedin_mcp_server/tools/job.py` and `tools/company.py`. The package and its browser (Patchright) were **not installed**. That installed release matches this commit is **not yet verified**; it must be checked before T1.

## Business tools in scope (allowlist = read-only set)

| Tool | Parameters | Returns (relevant fields) |
|---|---|---|
| `search_jobs` | `keywords` (req.), `location`, `max_pages` 1–10 (default 3; **we cap at 2**), `date_posted`, `job_type`, `experience_level` (internship / entry / associate / mid_senior / director / executive), `work_type`, `easy_apply`, `sort_by` | `url`, `sections`, `job_ids`, `references`, `total {count, exact}`, `promoted_job_ids` (only when all pages read); no match = empty `job_ids` + `section_errors[...].type = no_matching_jobs` |
| `get_job_details` | `job_id` | `url`, `sections` (raw text), `references`, `section_errors.job_posting.type = description_missing` (text kept, possibly incomplete), `apply {type: applied \| closed}` (absent = unknown) |
| `get_job_apply_url` | `job_id` | `url`, `apply {type: easy_apply \| external \| applied \| closed \| unknown, url?}` (external URL as LinkedIn gives it; short links not expanded; nothing clicked) |
| `search_companies` | `keywords` | `url`, `sections.search_results`, `references` (company slugs) |
| `get_company_profile` | `company_name`, `sections` (optional `posts`, `jobs`) | `url`, `sections`, `references`, `unknown_sections` |

- **Lifecycle only:** `close_session`.
- **Out of scope, filtered out by the allowlist:** `get_saved_jobs`, `get_company_posts`, `get_company_employees`, profile tools, messaging, connections, inbox, profile edits, applying.

## Project integration

- **Transport:** the existing `agent_runtime/mcp` stack (`McpStdioServerConfig`, `McpToolManager`, `StdioMcpClient`, allowlist, `read_only_tools`, timeouts, diagnostics), unchanged.
- **Adapter:** `agent_runtime/career/linkedin_source.py::LinkedInMcpSource` (`b2bd48b`), the domain adapter over `McpToolManager.call_tool`:
  - **Identity:** numeric `job_id` becomes `https://www.linkedin.com/jobs/view/<id>/`. Anything else is dropped and counted, never invented. Search cards carry `title` / `company` / `location = None` (unknown stays unknown) and `completeness = card`.
  - **Results:** no match → `status: no_match` (not a source failure); `section_errors` → `partial`. `apply.type = closed` → `closed`. An unsupported `experience_level` → `unapplied_filters`, never assumed satisfied.
  - **Complete JD rule** (tightened after review R7-CONTRACT-001, in `c31e0fe`): a detail is `complete_jd` only when **this job's own `job_posting` section** is present and at least 400 characters long, `section_errors` has no entry for `job_posting` (any type), and the returned `url` is `/jobs/view/<this job id>`. Otherwise the result is `incomplete` with `incomplete_reasons` (e.g. `job_posting_missing`, `job_posting_timeout`, `job_posting_too_short`, `identity_unverified`), and every section stays available as `evidence_text`. Other sections are never used as the description.
  - **Guards:**
    - a per-batch call budget (default 26), counted before sending, so retries and failures use it, and kept in a persisted store, so a restart does not reset it;
    - a per-call deadline (120 s) and a 2-page cap;
    - a response-size limit (2 MB, not parsed beyond it).
  - **Stop conditions:** a rate limit or a login / checkpoint / challenge stops the source for the batch, with no switch to another channel on the same account. An outer timeout stops further calls until cancellation / recycling is confirmed (`confirm_cancelled`).
  - **Not wired** into source selection or JD reading: adoption needs T1 / T2.

## Example server configuration (matches the project loader; disabled by default)

```json
{"server_id": "linkedin", "command": "<path to the pinned server's launcher in its own environment>", "args": ["..."],
 "required": false, "startup_timeout_seconds": 60, "call_timeout_seconds": 120,
 "tool_allowlist": ["search_jobs", "get_job_details", "get_job_apply_url", "search_companies", "get_company_profile"],
 "read_only_tools": ["search_jobs", "get_job_details", "get_job_apply_url", "search_companies", "get_company_profile"]}
```

The command comes from trusted local configuration only; page content can never change it. The session / profile store is the upstream's own directory, per user, and is never the application browser's profile. Automatic import of a browser login is not used.
