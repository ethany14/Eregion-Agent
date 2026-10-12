# Treg AnyAPI vs Crawl4AI · live comparison (P5 / S4, 2026-10-12)

Status: **real API tested**. User-authorized batch, one persistent scope `treg-ab-live-20261012`, isolated ledger `.codex-runs/integrated-20261012/treg-live/ledger.db`.

| Budget | Limit | Used |
|---|---|---|
| Total | $0.10 | **$0.004000** (4,000 micro-USD, all confirmed via `X-Treg-Cost-Micro`) |
| Gateway requests | 20 | **15** (10 searches + 5 scrapes; no pre-checks, retries or status queries needed) |
| Per call | $0.01 (sent as `X-Treg-Route-Max-Cost`) | max $0.0005 |
| Unknown charges held | — | **0** |
| LLM calls | 0 | **0** |

No overflow relay (`X-Treg-Served-Via` absent on all calls), no idempotent replays, and no Treg archive hits (`X-Treg-Cache` absent). Runner: `evals/treg_compare.py` (explicit `JOB_AGENT_TREG_LIVE_API_TEST=1`). Raw evidence (public job data, no key): `.codex-runs/integrated-20261012/treg-live/evidence.json` and `scrape-*.md`.

## Frozen inputs (set before any call)

Same common inputs for both providers: query, location, posting window `week`. Filters without an equivalent in both are listed as **not applied**.

| Group | Query | Location | Not applied |
|---|---|---|---|
| G1 | junior data analyst | New York, NY | seniority (junior) |
| G2 | senior backend engineer | United States | remote, seniority |
| G3 | machine learning intern | California | internship type |
| G4 | junior UX designer | Austin, TX | seniority |
| G5 | entry level data scientist | United States | seniority |

Order alternated per group: AnyAPI first in G1, G3 and G5; Crawl4AI first in G2 and G4. First page only; no paging.

## Search results

Relevance is judged by a fixed rule: role words in the title, and a location token match. The location rule is strict; for "United States" (G2, G5) the rows list US cities, so the rule scores 0 on location for **both** providers. That is a limit of the rule, not of the sources.

| Group | Provider | Raw | Unique IDs | Relevant | Role match | Location match | Posted date | Seconds | Charge (µUSD) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| G1 | AnyAPI | 10 | 10 | 2/10 | 2/10 | 8/10 | 10/10 | 4.55 | 500 |
| G1 | Crawl4AI | 10 | 10 | 2/10 | 2/10 | 8/10 | 10/10 | 2.31 | 150 |
| G2 | AnyAPI | 10 | 10 | 0/10 | 9/10 | 0/10 | 10/10 | 7.07 | 500 |
| G2 | Crawl4AI | 10 | 10 | 0/10 | 9/10 | 0/10 | 10/10 | 4.22 | 150 |
| G3 | AnyAPI | 10 | 10 | 5/10 | 5/10 | 10/10 | 10/10 | 13.10 | 500 |
| G3 | Crawl4AI | 10 | 10 | 5/10 | 5/10 | 10/10 | 10/10 | 1.95 | 150 |
| G4 | AnyAPI | 10 | 10 | 7/10 | 7/10 | 10/10 | 10/10 | 6.22 | 500 |
| G4 | Crawl4AI | 10 | 10 | 7/10 | 7/10 | 10/10 | 10/10 | 8.64 | 150 |
| G5 | AnyAPI | 10 | 10 | 0/10 | 10/10 | 0/10 | 10/10 | 7.93 | 500 |
| G5 | Crawl4AI | 10 | 10 | 0/10 | 10/10 | 0/10 | 10/10 | 9.54 | 150 |
| **Total** | AnyAPI | 50 | 50 | 14/50 | 33/50 | 28/50 | 50/50 | 38.9 | 2,500 |
| **Total** | Crawl4AI | 50 | 50 | 14/50 | 33/50 | 28/50 | 50/50 | 26.7 | 750 |

Overlap of relevant results:

| Group | Both | AnyAPI only | Crawl4AI only |
|---|---:|---:|---:|
| G1 | 2 | 0 | 0 |
| G3 | 5 | 0 | 0 |
| G4 | 6 | 1 | 1 |

In this sample both providers returned near-identical LinkedIn results (same job IDs and counts). They most likely read the same public LinkedIn search. Every row had a stable LinkedIn job ID and a posting date. Neither returns a job description, which is expected and not counted against either. Job seniority was never filtered by either (e.g. "Senior UX Designer" for a junior query): qualification still decides.

## Page text extraction (`crawl4ai.web.scrape`)

Selection rule, fixed before scraping: relevant, de-duplicated by job ID; overlap first, then provider-only, round-robin across groups; at most 5.

| Job ID | Group | Tier | Title | Seconds | Raw chars | After trimming other jobs | Verdict |
|---|---|---|---|---:|---:|---:|---|
| 4474996157 | G1 | both | Data Analyst (Wilson Elser) | 8.1 | 27,050 | 9,026 | complete JD |
| 4474645212 | G3 | both | Machine Learning Engineer Intern (Atoms) | 9.4 | 29,865 | 10,543 | complete JD |
| 4476824786 | G4 | both | Product Designer (Rockstar) | 8.7 | 26,366 | 8,128 | complete JD |
| 4420697891 | G4 | AnyAPI only | Industrial Designer (Starlink, SpaceX) | 10.7 | 25,299 | 8,068 | complete JD |
| 4469284055 | G4 | Crawl4AI only | Senior UX Designer (Accruent) | 15.0 | 29,544 | 11,432 | complete JD |

**5/5 public LinkedIn job pages yielded the full description** (responsibilities and qualifications present, no login wall in the description, title bound, no closed signal), at $0.00015 each.

**Defect found and fixed:** the first assessment counted job links with a pattern that never matched LinkedIn's slugged URLs, so the "single job" check was vacuous. Each page appends "Similar jobs" / "People also viewed" with **37 other job links (about two-thirds of the text)**, which would have entered scoring. `posting_text()` now cuts at those sections, and the link count uses the real pattern (37 untrimmed → 0 trimmed). `read_job` uses only the trimmed description. All five saved pages were re-assessed offline (no new calls): still complete. Regression: `test_scrape_trims_other_jobs_and_counts_real_linkedin_links`.

Open status is not proven: LinkedIn shows age and applicant counts, but a page without a "no longer accepting" notice does not prove the posting is open. Recorded as unknown.

## Cost per complete JD (this sampled flow)

- Search per group: AnyAPI $0.0005, Crawl4AI $0.00015.
- Scrape: $0.00015 per page.
- One group's search plus one scrape: AnyAPI flow $0.00065; Crawl4AI flow $0.00030.
- Batch actual: $0.004 for 10 searches + 5 complete JDs.

## Decision

| Item | Decision | Basis |
|---|---|---|
| Default search provider (`JOB_AGENT_TREG_SEARCH_PROVIDER`) | **`crawl4ai`** recommended | Same results as AnyAPI in this sample at 0.3× the price and lower total latency. AnyAPI stays a configurable alternative; no dual calls, no failover |
| Page text extraction (`JOB_AGENT_TREG_CRAWL4AI_SCRAPE_ENABLED`) | **Works; candidate to enable per user** | 5/5 complete JDs after trimming other jobs; ATS URLs still use free company-board APIs |
| Release defaults | Unchanged: Treg off, provider empty, scrape off | Users opt in with their own key and cost |

Limits: 5 query groups and 5 scrapes are a small sample, not a recall or stability guarantee. The relevance rule is coarse (location strictness). Live results change over time.
