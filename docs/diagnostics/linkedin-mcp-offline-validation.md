# R7 · LinkedIn MCP T0 offline validation (2026-10-12)

**T0: PASSED (offline).** No real model or account request was made; the upstream package was not installed. Contract: [`linkedin-mcp-contract.md`](linkedin-mcp-contract.md).

Tests: `tests/test_linkedin_mcp_t0.py` (11), run with the existing MCP suite `tests/test_mcp_app.py`: **18 passed** at `b2bd48b`. Raw output: [`t0-offline.xml`](../benchmarks/linkedin-mcp-20261012/t0-offline.xml) / [`t0-offline.log`](../benchmarks/linkedin-mcp-20261012/t0-offline.log).

| T0 requirement | Test |
|---|---|
| Real manager path; only business tools exposed (no messaging, profiles, saved jobs, employees) | `test_only_business_tools_are_exposed_through_the_real_manager` (fake client lists 11 upstream tools; the allowlist leaves 5) |
| Identity, dedupe, unknown fields stay unknown | same test: duplicate and non-numeric ids handled; cards have no invented title or company |
| Paging cap and deadline | same test: `max_pages` 5 → 2; timeout 120 s |
| No match vs partial | `test_no_match_is_empty_not_a_failure_and_partial_is_flagged` |
| Missing filter not treated as satisfied | `test_unsupported_filter_is_reported_as_not_applied` |
| Missing JD / closed never complete | `test_details_missing_description_and_closed_are_never_complete` |
| Apply entry only for external postings | `test_apply_url_only_for_external_postings` |
| Rate limit / login challenge stop the source, no channel switch | `test_rate_limit_or_login_challenge_stops_the_source` |
| Cancel / timeout: no next call until confirmed | `test_timeout_blocks_the_next_call_until_cancellation_is_confirmed` |
| Restart: budget not reset; failures counted | `test_budget_counts_failures_and_survives_restart` |
| Oversized response | `test_oversized_response_is_not_parsed` |
| Out-of-scope tool refused before any call | `test_out_of_scope_tools_are_refused_before_any_call` |

**Not covered by T0, belonging to T1:** that the installed release matches commit `5bdef1c9`; Windows install and first browser preparation timing; the real session / profile location; real `isError` texts from LinkedIn.

## T1 / T2 status: DEFERRED (authorization)

T1 requires a LinkedIn account **explicitly chosen by the user** and a login through the upstream server's own flow. The current authorization explicitly excludes logins, so T1 (≤ 26 business calls, zero model) and T2 (agent comparison) were **not run**. [`linkedin-mcp-live-validation.md`](linkedin-mcp-live-validation.md) and [`linkedin-mcp-comparison.md`](linkedin-mcp-comparison.md) record the deferral.

**Adoption decision: not adopted, MCP stays optional and off.** The board + Treg main path does not depend on it.
