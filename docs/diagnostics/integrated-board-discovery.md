# Integrated optimization · P2 board response reuse (2026-10-12)

| Part | Status |
|---|---|
| **P2a** Ashby whole-board reuse (`JOB_AGENT_OPT_BOARD_RESPONSE_CACHE`, default `0`) | **offline passed** |
| **P2b** parallel discovery across independent sources (`JOB_AGENT_OPT_DISCOVERY_PARALLEL`) | **deferred, not implemented**. The plan adds it only after P2a's benefit is confirmed; there is no live measurement yet. Existing per-host limiter / bounded API concurrency are unchanged |

## Finding

Of the supported ATS detail paths, only **Ashby** downloads the whole board again for every detail read (`JobDiscovery.job` → `api.ashbyhq.com/posting-api/job-board/<tenant>`, which lists every posting with full descriptions; e.g. OpenAI's board is 13.5 MB). Greenhouse and Lever detail reads use small per-job endpoints, and Workday uses a per-posting endpoint, so none of them needs reuse.

## Design (`agent_runtime/career/discovery.py::BoardResponseCache`)

- **Scope:** GET on `api.ashbyhq.com/posting-api/job-board/*` only, keyed by the exact API URL (tenant included). It applies to search and detail reads alike.
- **Limits:** in-process only. 5-minute TTL; at most 8 boards and 64 MiB in total; a single response over 32 MiB is used but not stored. The existing 40 MB read cap is unchanged.
- **Concurrency:** readers of the same key share one in-flight download, so concurrent search and detail reads do not duplicate traffic.
- **Failures:** never stored. Waiters receive the same error, and the next read fetches again.
- **What is unchanged:** job identity (posting ID inside the board), the public-URL / DNS checks and redirect validation (in `_read`), and durable job evidence, which stays in the workspace. Nothing in this cache survives a restart. An expired entry or a different URL triggers a new download.
- **Switch off:** the old path is unchanged (tested: two downloads for search + detail).

## Tests

`tests/test_integrated_p2.py` (6):
- search + 3 detail reads → **1 board download**, 3 cache hits;
- switch off → 2 downloads;
- TTL expiry re-fetches; failures are not cached;
- 4 concurrent readers → 1 download;
- an oversized response is returned but not stored;
- only the Ashby board API qualifies.

No live speed-up is claimed; the gain depends on how many Ashby postings a task reads from one board.
