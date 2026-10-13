# Default job sources: LinkedIn MCP + public company boards

Implemented 2026-10-12 after user approval. Treg is an optional user-key enhancement, not required for the default research route.

## Delivered

- JOB_AGENT_JOB_API_FIRST defaults to 1. Routing, prompt and snapshot consistently describe company-board APIs plus configured LinkedIn MCP. An explicit 0 retains the legacy route. Invalid optional Treg configuration no longer controls the free-source priority switch.
- Existing MCP manager remains the sole server lifecycle owner; existing career AgentLoop remains the sole decision owner. Sources run sequentially, not in a new parallel agent loop.
- Search cards recover titles through exact LinkedIn job reference IDs. Company/location are retained only from an unambiguous adjacent card layout; unknowns remain unknown. Saved real MCP response replay covers the parser. Cards do not establish eligibility.
- Directory and MCP candidates merge/dedupe by job identity. LinkedIn-only and no-LinkedIn restrictions are honored. No manager or login is not an implicit authorization to install/login. Board APIs work without MCP.
- Search reuse is per user request/filter set. Requests above 10 candidates permit at most two MCP pages; equivalent 15/20 limits share the expanded search. JD reads reuse successfully validated same-turn evidence. New user input can refresh, but the 26-call task budget does not reset.
- MCP calls are reserved before dispatch and stored in task state. Authentication, rate limit, uncertain timeout and pending calls left by restart stop that source. Cancellation/revision is checked before and after transport. A stopped source cannot silently fail over to paid Treg/browser merely because its manager disappears.
- MCP JD retrieval uses only the verified target job_posting section and keeps a single description in the career result, not a duplicate evidence envelope. Existing qualification validation/scoring remain required.
- MCP file configuration now supports max_result_bytes (example 2 MB) so realistic job details are not truncated at the prior 20 KB default. MCP_CONFIG_PATH supports process environment then project .env; an explicit empty process value disables file fallback.

## Local activation

The local .env now sets JOB_AGENT_JOB_API_FIRST=1 and JOB_AGENT_TREG_ENABLED=0, preserving the user's Treg key. MCP_CONFIG_PATH points to an ignored local config that uses the previously tested pinned 4.27.0 isolated installation and the user's independently logged-in profile. No credentials are copied into tracked files. Configuration-only verification found server linkedin, API-first true, Treg false. Backend restart is required to load the MCP manager configuration; no server restart or user database migration was performed here.

For other open-source users: see docs/configuration.md#default-job-sources and docs/examples/linkedin-mcp.json. The example uses pinned uvx installation; users choose an isolated profile and complete one interactive login. API keys are unnecessary for this combination, but setup/login remains necessary.

## Validation

- Main offline regression: 114 passed in 45.45s; docs/benchmarks/mcp-default-route-20261012/final.xml and final.log. Includes default-route scenarios, real card replay, previous Treg routes, MCP adapter/runtime, source-mode consistency, filters and cache regressions.
- Final edge regression: 10 passed in 11.57s; docs/benchmarks/mcp-default-route-20261012/edge.xml and edge.log. Verifies manager disappearance after auth stop, pagination expansion/cache reuse, persisted in-flight recovery, cancellation and source restrictions.
- Initial regression expectations referring to Treg-unavailable were corrected to LinkedIn-MCP-unavailable, preserving the no-board-traversal assertions.
- Two sandbox test runs were interrupted after hanging. A dedicated faulthandler capture in stall2.log showed Windows asyncio socketpair initialization blocked before scoring; the same offline suite passed outside the sandbox with external-network test guards retained. These interrupted runs are not counted as passes.
- No additional paid tests or real MCP business calls were made for this routing change. Prior source comparison (two search batches and three details) is recorded separately in filter-api-mcp-comparison-20261012.md and does not prove this integrated route's end-to-end performance.

## Remaining acceptance

The final integrated 10–15 qualifying recommendation scenario remains unrun. R6/R9/B6 are not declared passed. Before a default-release claim, run a bounded real integrated task and record qualified yield, actual nested-model attempts/tokens, first-result latency, total latency and per-qualified-result cost. Retain the two-job smoke gate. Do not relax seniority/location requirements or count unverified cards toward the target.
