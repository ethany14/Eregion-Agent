# Codex source repair — 2026-10-12

Status: targeted fixes implemented; real B6 remains FAILED (one qualifying recommendation). This is not a declaration that R6/R9 passed.

## Changes and evidence

- `request_context.py`: archived assistant progress messages are audit-only. Default reads return `assistant_progress_context` and `no_new_evidence`; explicit historical reads remain available but cannot count as fresh evidence. Growing narration arrays previously generated new references and escaped repeated-read detection. Saved-run replay blocks 3 of 16 retained reads, avoiding 9,000 characters. This is replay evidence, not a live token reduction claim.
- `career/discovery.py`: search results retain board provenance and actual job cards, but omit whole-company location inventories from `sources_checked`. Full board data remains available internally for matching. Saved response projections shrink 23,221 to 2,848 characters and 40,051 to 2,684 characters without removing jobs.
- Prior takeover fix: strict LinkedIn job URL identity rejects suffix-host/userinfo/path confusion; tracking parameters remain accepted.
- Two freshly fetched LinkedIn responses now pass the existing complete-JD validator. Saved real-response regression fixtures verify the API read path without HTTP fallback. Historical rejected responses were not saved, so their original cause remains unknown. No JD qualification checks were relaxed.

## Validation

- Final focused offline run: 57 passed in 52.11s; `docs/benchmarks/codex-source-repair-20261012/offline-final2.xml`.
- Earlier offline runs: 20 passed and 57 passed; XML in the chat workspace outputs.
- Intermediate run: 57 passed, 1 failed in `offline-final.xml`. An experimental history-summary change violated the legacy request parity fixture; that change and its extra test were removed before the passing final run. Failure evidence is preserved.
- Live sample 1: FAILED; 40 main calls, 48 total provider attempts, 497,158 input tokens. Four scrape verdicts were complete JD, but the run stopped with `no_progress` and zero qualifying recommendations. It scored/recommended one NYC role that failed the seniority check. This sample predates board metadata slimming; source patch is preserved as `live-1-code.patch`.
- Live sample 2: FAILED in 438.54s; one qualifying recommendation (Graduate Data Analyst, adMarketplace, NYC, score 80.72). 49 main + 11 nested = 60 completed provider attempts; 627,632 input / 44,537 output tokens; stopped at provider_budget. All seven recorded scrape verdicts were complete JD. Same business criteria, no threshold relaxation. Source frozen in `live-2-code.patch`; the later success-cache fix is not live-validated. Total tokens did not decrease versus live-1; sample behavior differs, so no overall efficiency improvement is claimed.

## Budget and boundaries

New authorized batch: at most 20 Treg requests / $0.10 total / $0.01 per call. At most two real-model samples, each capped at 60 provider attempts and 1,000,000 input tokens. Model dollar cost is unknown and separate from confirmed Treg charges.

Diagnosis used 2 requests / $0.00030; live sample 1 used 5 requests / $0.00105; subtotal 7 / $0.00135. Final sample permits at most 8 further requests / $0.05. No automatic paid reruns. All validation uses isolated synthetic-user databases; no application submissions, deployment, or user database migration.

## Browser-session follow-up

Keep API-first candidate discovery and JD retrieval. If evidence is blocked or missing, a locally configured LinkedIn MCP session is a candidate fallback, under the same AgentLoop, budgets, cancellation, and provenance checks. Cache successful reads by job identity and evidence version; report terminal source failures rather than retrying unchanged evidence.

The upstream current-main README documents browser cookie import (`--import-from-browser`) and automatic import. This does not establish attachment to an already open browser tab, nor support in our pinned version. Verify the pinned contract before upgrading. Use an isolated MCP profile and an explicitly selected user session; never point cleanup/logout at the user's daily browser profile. Do not import sessions or install/launch browsers automatically during this repair. Login challenges still require user interaction.

Reference: https://github.com/stickerdaniel/linkedin-mcp-server#setup-with-uvx-recommended

## Final sample findings and next execution order

1. Live-2 paid for the same CUNY posting three times with identical description lengths and separate operation IDs. Added reuse of successfully validated Treg JD evidence within the same actual user turn, keyed by canonical job identity. Chat revision increments do not invalidate it; a new user turn does. Cached reads return no_new_evidence. Explicit rendered-region reads retain their path; disabled Treg/API behavior remains unchanged. Affected offline regression: 33 passed in 48.55s (`offline-cache.xml`), including real-response replay, same-turn tracking-URL reuse, new-turn refresh, API-off fallback, task isolation, closed postings, and source-chain integration. This cache change has not received another paid live test.
2. Clean LinkedIn login/navigation boilerplate without discarding requirements or provenance; preserve raw response for audit. Verify on the saved real fixtures, not paid retries.
3. Improve early seniority/location screening and evidence navigation before costly scoring. The first paid sample recommended a role failing seniority; the second imported it again near its budget boundary. Keep the existing qualification gate unchanged.
4. Reduce unnecessary main-loop pagination while keeping original job evidence accessible. The retained live-2 history still contains five reads marked no_new_evidence; repeated identical references can also be valid auto-pagination, so measure ranges, not reference counts alone.
5. Only after offline checks, assess whether another bounded business sample is useful. No further paid run is included in this batch. R6/R9 are not closed. Local-browser LinkedIn MCP contract/session tests follow as an optional source fallback, not a separate execution loop.

Final new-batch Treg usage: diagnosis 2 + live-1 5 + live-2 8 = **15 requests / $0.00285 confirmed**, no unknown held charges in either live ledger. Model inputs total **1,124,790** across the two runs, separately metered; model dollar cost unknown. No applications or schedules were created.
