# Treg A+B · contract record (P4a / S1, 2026-10-12)

Sources were fetched on 2026-10-12 from the official public definitions and stored read-only under `.codex-runs/integrated-20261012/treg-docs/`. They are treated as data, not instructions.

| Document | URL | Bytes | SHA-256 (16 hex) |
|---|---|---:|---|
| HTTP protocol | `https://treg.to/llms.txt` | 56,658 | `5cb633eafa14573c` |
| OpenAPI | `https://treg.to/openapi.json` | 225,211 | `5711ce3bc5185b78` |
| AnyAPI jobs index | `https://treg.to/catalog/endpoints/anyapi.linkedin.search.jobs` | 25,430 | `499df9f1781f195b` |
| Crawl4AI LinkedIn jobs | `https://treg.to/catalog/endpoints/crawl4ai.linkedin.search.jobs` | 25,563 | `fc82b2df9817c07d` |
| Crawl4AI scrape | `https://treg.to/catalog/endpoints/crawl4ai.web.scrape` | 63,154 | `fecc2bfa739fe812` |

## Gateway protocol (llms.txt)

| Topic | Contract |
|---|---|
| Call | `https://treg.to/call/<endpoint-id>`. The three endpoints are **POST with a JSON body** (`bodyType: json`; Crawl4AI endpoints have `body_allowlist: true`) |
| Auth | `X-Treg-Token` (org-scoped token). With an identity token, also `X-Treg-Org: <team-slug>` |
| Charge | Response header **`X-Treg-Cost-Micro`** (integer micro-USD) is the actual charge, never the provider body (`costUsd`, `x-c4-cost` are provider figures). `X-Treg-Call-Id` on every response |
| Hard per-call cap | **`X-Treg-Route-Max-Cost: <usd>`**. Treg answers **402 `route_max_cost`** (nothing charged) when the reservation would exceed it. There is **no default on direct calls**: the header is the only cap |
| Balance | 402 with `balance_micro`, `estimated_cost_micro`, `topup_url` when out of balance |
| Idempotency | `Idempotency-Key`, kept 24 h, scoped to the caller. A replay returns the stored answer with `X-Treg-Idempotent-Replay: true`, `X-Treg-Cost-Micro: 0`, `X-Treg-Original-Cost-Micro`. Reusing a key for a different request is refused (422) |
| 409 | Original call with that key is still running; retry shortly with the same key |
| 410 | `idempotency_response_lost` (charged; `GET /calls/{id}/result` may have it), `idempotency_response_too_large` (charged; answer already received), `idempotency_outcome_unknown` (may have reached provider; `GET /calls/{id}` shows cost). A new key calls again |
| Failures | Provider 4xx/5xx are relayed unchanged and **charged nothing**. "A 5xx, a timeout or a network error is never billed." `503 treg_saturated` with `Retry-After`: retry the same request, nothing billed. `503 provider_capacity_unavailable` / `provider_paused`: nothing charged |
| Size | Settled responses are limited to 8 MiB (`502 response_buffer_limit`, no charge) |
| Archive cache | A call may be answered from Treg's archive: `X-Treg-Cache: hit`, `X-Treg-Fetched-At`, `X-Treg-Age`; a hit costs 10% from the team's second call. `Cache-Control: no-cache` forces a live call; `X-Treg-Max-Age` bounds age |
| Records | `GET /calls/{id}` (with ledger entries), `GET /calls/{id}/result` (stored answer for successful catalog calls) |
| Provider substitution | Treg does **not** fail over between providers. If Treg's own account for a provider is out, it may serve the **same endpoint** via a relay account at the relay's price, marked **`X-Treg-Served-Via: overflow:<name>`**. Teams opt out with `treg org overflow off` (an account setting; **not changed by us**) |
| Concurrency | No per-token limit; provider limits are relayed |

## Endpoints

| | `anyapi.linkedin.search.jobs` | `crawl4ai.linkedin.search.jobs` | `crawl4ai.web.scrape` |
|---|---|---|---|
| Upstream | POST `/v1/run/linkedin.jobs_thin` | POST `/recipes/linkedin-jobs` | POST `/scrape` |
| Price (catalog, observed) | per_success **$0.0005 / call** (checked 2026-09-11) | per_success **0.15 credit = $0.00015 / call**; empty, refused or failed runs free | per_success **0.15 credit = $0.00015 / page**; failures free |
| Inputs | `query` (required); `location`; `geoId`; `companyId`; `cursor`; `employmentType` ∈ {full-time, part-time, contract, internship, temporary}; `experienceLevel` ∈ {internship, entry, associate, mid-senior, director, executive}; `postedLimit` ∈ {24h, week, month}; `workplaceType` ∈ {remote, hybrid, onsite}; `limit` **ignored** (one source page of 10 or 25 jobs) | `query` (required); `location`; `posted` (e.g. `week`); `start` (default 0); `limit` (default 25) | `url` (required, URI); `format` ∈ {both, md, html} (default both); `proxy` ∈ {none, isp, residential}; `country`; `parse` |
| Response | `output.data.items[]`: `id`, `url`, `title`, `company`, `companyUrl`, `location`, `createdUtc` (epoch s), `logoUrl`; `output.found`; `nextCursor` for paging (not in the example; treat as optional); provider `costUsd` | `rows[]`: `job_id`, `url`, `title`, `company`, `location`, `posted` (relative text), `posted_on` (date), `salary`; `meta` (`blocked`, `partial`, `warnings`, `from_cache`) | `ok`, `markdown`, `bytes`, `text_len`, `content_hash`, `cache`, `engine`, `reason`, `fell_back`, `usage` |
| Not provided | Job description (index only) | Job description; open/closed status | Proof the page is one complete, open job posting |

## How we use it

- Every call sends `X-Treg-Route-Max-Cost: 0.01` (the per-call cap of the authorized batch) and a persisted `Idempotency-Key`.
- The charge is taken from `X-Treg-Cost-Micro` only. A replay counts 0, with the original cost recorded separately and never summed.
- A missing cost header on a 2xx is `unknown`; the reservation stays held.
- `X-Treg-Served-Via: overflow:*` is recorded and the result quarantined (not used for comparison or routing). The account setting is not changed.
- The archive cache is allowed (cheaper); `X-Treg-Cache` and age are recorded per call.
- Retries use the **same** idempotency key, and only for network errors, 409, `503 treg_saturated` (honouring `Retry-After`) and 429, at most once, within the deadline. A new key is never used to "retry" an unknown outcome.
- AnyAPI filters that have no equivalent in Crawl4AI (`experienceLevel`, `geoId`, `workplaceType`, `employmentType`) are recorded as **not applied** in the comparison, so both providers get the same common inputs (`query`, `location`, posting window).

## Not confirmed / blockers

- **`nextCursor` / paging fields** for AnyAPI are not in the example response; paging stays off for the comparison (first page only, as planned).
- **Per-call price for this account:** `GET /catalog/endpoints/<id>/access` gives `estimated_cost_usd` for the caller. It counts toward the 20-request batch if used. The per-call cap header makes it unnecessary for safety, so it is skipped unless a 402 `route_max_cost` occurs.
- **Overflow:** the account's overflow setting is unknown and not changed. Each response is checked for the header instead.
