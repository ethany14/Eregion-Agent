# Search filter optimization and API / LinkedIn MCP comparison

## Current status

Production filtering and same-turn LinkedIn-only search reuse implemented. Offline regression: 35 + 50 passed. API source-only benchmark completed. LinkedIn MCP first business sample completed after user-performed isolated login; no claim that one source is more stable overall. B6/R9 remains unpassed; these measurements do not qualify 10–15 recommended jobs.

## Implementation

- Search tool exposes experience_level, work_type, employment_type and posted as validated enumerations. AnyAPI receives experienceLevel, workplaceType, employmentType and postedLimit; Crawl4AI receives only its supported posted field, and reports unsupported requested fields explicitly. Its limit can now follow a request up to 20, still bounded by configured max_results. AnyAPI first-page size remains provider-owned; do not pretend its ignored limit is honored.
- Unambiguous existing user-owned junior/new-grad/intern constraints map to entry/internship provider filters. Other levels remain unmapped unless supplied explicitly; no blind translation of ambiguous seniority categories.
- Local card screening removes only explicit title-level mismatches and records excluded URLs/reasons. Unknown titles remain candidates. This does not establish eligibility. Existing board location matching remains in use; no new blanket location string rejection, to avoid excluding metro/remote ambiguities.
- Filtering occurs before deciding whether board coverage is too thin and needs a Treg supplement. Search-cache keys include filters.
- LinkedIn-only searches now persist candidate evidence and reuse successful same-turn query/filter responses. This fixes a bypass of the ordinary directory-path storage and reuse. New user turns can refresh. Disabled sources remain disabled.
- Existing same-turn validated JD cache remains active. Single AgentLoop ownership is unchanged.

## Benchmark design and limits

Same three queries: junior data analyst / graduate data analyst / software engineer intern, all New York, NY. Provider order alternates. First pages only. AnyAPI gets its supported entry/internship filter; Crawl4AI has no equivalent: this compares deployable provider capability, not equal-filter retrieval quality. Raw responses are preserved in ignored `.codex-runs/filter-api-mcp-20261012`; measured summaries and charges are under `docs/benchmarks/filter-api-mcp-20261012`.

This is source-only, zero model calls. Response character/byte sizes and rough chars/4 token estimates are recorded separately; estimates are not billed tokens and cannot establish end-to-end agent token savings. Future model comparison must hold model, prompt, selected target jobs, evidence representation and scoring budget constant. Use the saved shared-targets.json for paired detail measurements.

New authorization: at most 30 Treg attempts / $0.10 total / $0.01 per call; isolated persistent ledger, unknown-charge and overflow stop, no applications/schedules. Actual API batch: 9 attempts, $0.00285 confirmed, zero unknown held charges. No model charges incurred by this source benchmark.

## API observations

| Source | HTTP success | Nonempty searches | Median search seconds | Range seconds | Returned candidates |
|---|---:|---:|---:|---:|---:|
| AnyAPI | 3/3 | 3/3 | 6.622 | 4.466–7.431 | 30 |
| Crawl4AI | 3/3 | 2/3 | 1.654 | 1.456–25.943 | 40 |

Crawl4AI internship search returned zero, so HTTP success must not be treated as useful coverage. No sample size here supports a population-level reliability claim. Candidates are not verified recommendations; these counts cannot be compared as eligible-job yield. Three shared candidate detail scrapes passed complete-JD checks in 0.481–0.638 seconds, but their body explicitly reports archive cache; these timings are not uncached scraping latency.

## LinkedIn MCP setup evidence

Installed PyPI mcp-server-linkedin==4.27.0 in isolated `.codex-runs/linkedin-comparison-venv`, leaving project dependencies unchanged. Current Chrome LinkedIn jobs UI confirmed authenticated. No account/profile/messages read for the benchmark beyond the login indication on that page.

The MCP-managed browser installer refused the Windows directory ancestry permissions. Using the upstream supported --chrome-path option avoids downloading another browser and preserves security settings. Official --import-from-browser chrome then returned no locally logged-in live session, despite Chrome UI authentication. Root cause is unproven; upstream v20 cookie encryption limitations are a possible explanation, not an observed diagnosis. No cookie values were printed or saved to reports.

The user subsequently explicitly authorized an independent window and completed login. Upstream confirmed the isolated profile was saved. First real MCP sample: 3/3 searches returned nonempty results (9 IDs each), 3/3 shared details passed complete-JD checks; 6 business calls, no auth/rate-limit error, 36.82 seconds including setup and shutdown. Search timings: 14.714, 6.788, 6.570 seconds (cold first search included); detail timings: 1.968, 1.842, 2.339 seconds. Session close was requested and the process exited cleanly. This is a small sample, not long-term reliability.

One fixed-text comparison uses the same three job identities and one accepted JD text per source, counted with cl100k_base. API: 2,202 / 2,619 / 2,711 tokens; MCP: 1,939 / 1,988 / 2,652. Totals 7,532 vs 6,579, about 12.7% lower for MCP. This is a tokenizer proxy, not actual production-model usage. Text content and cache freshness differ; a shorter document is not automatically more complete. Neither test called a model. Full-loop and scoring token comparison remains unmeasured.

The current MCP adapter strips search sections down to IDs and unknown title/company/location, while API cards include these fields. Thus smaller normalized MCP search payloads do not prove efficiency: they carry less screening information and may require more detail calls. Complete MCP details also include both description and evidence_text; avoid duplicating them in future agent projections, retaining raw evidence separately.

Recommendation: retain API-first routing for now; MCP is a demonstrated working local-session fallback worth integrating after preserving useful search-card fields and matching tool-result projections. Do not switch defaults based on this short run. Three archived API detail responses were faster, but they cannot be compared as fresh-fetch latency.

## Next gates

1. DONE: isolated session established by the user; no automated password/challenge entry.
2. DONE: three identical searches and three same-job details through the existing MCP adapter/read-only allowlist, 120s deadline; raw sizes and results saved. Login preserved, session closed. DONE: after closing/restarting MCP, all three repeated searches also succeeded without login, 12.777 / 6.774 / 6.840 seconds, returning 9 / 10 / 9 IDs. Total 9 business calls (6 searches + 3 details) across two processes, within the 12-call bound. No failures or auth/rate-limit challenges observed; first-call browser startup remains slower. Both processes exited cleanly.
3. Add repeat batches before making stability claims, with cache/clock/account differences disclosed.
4. Then run paired model evaluations with matching evidence and budget. Source-only zero tokens is not a promise of zero agent tokens.
5. Preserve the two-job smoke gate, then validate 10–15 qualifying recommendations and cost per qualifying result. Do not lower seniority/location requirements to fill a quota.
