# Treg A+B · offline validation and status (S0–S5, 2026-10-12)

Plan: [`integrated-optimization-execution-plan-20261012.md`](../specs/integrated-optimization-execution-plan-20261012.md) §9–§10. Handoff spec: [`treg-ab-execution-handoff-20261012.md`](../specs/treg-ab-execution-handoff-20261012.md). Baseline: [P0](integrated-optimization-baseline-20261012.md).

| Step | Status | Evidence |
|---|---|---|
| S0 baseline and evidence gaps | done | P0 report: skip count 132 explained, B2/r1 record located |
| S1 contract | done | [`treg-ab-contract.md`](treg-ab-contract.md) (official docs hashed) |
| S2 A: config, client, ledger, recovery | **offline passed** | `agent_runtime/career/treg_config.py`, `treg_client.py`, `external_tool_usage.py`, migration `0037`; `tests/test_treg.py` |
| S3 B: wiring into `search_jobs` / `read_job` | **offline passed** | `harness.py` (`_treg_search`, `_treg_scrape`), `candidate_queue.py`, `search_policy.source_scope`; `tests/test_integrated_p3.py`; [`integrated-search-flow.md`](integrated-search-flow.md) |
| S4 live comparison | **real API tested** | [`treg-provider-comparison.md`](treg-provider-comparison.md): 15 calls, $0.004, 0 unknown, 0 LLM |
| S5 delivery | done (defaults off) | `.env.example`, README "Optional: LinkedIn search through your own Treg account", `docs/configuration.md` |

## Mechanisms covered by offline tests

`tests/test_treg.py` (23) and `tests/test_integrated_p3.py` (10), mock transport and temp DBs. The test isolation fails any outside connection.

- **Configuration:**
  - environment > `.env` > defaults; an explicit empty variable does not fall back; placeholder tokens count as missing;
  - invalid budgets block Treg only; the token never appears in `repr`, the ledger or errors.
- **Requests:** the fixed allowlist of 3 endpoints; `X-Treg-Route-Max-Cost` and a persisted `Idempotency-Key` on every call.
- **Charges and outcomes:**
  - charges come only from `X-Treg-Cost-Micro`;
  - a replay counts 0 and keeps the original cost separately;
  - a missing cost header on success → unknown, reservation held;
  - network error → one retry with the **same** key, then unknown;
  - saturated 503 / 409 → one same-key retry; 402 `route_max_cost` → a free failure; 410 → unknown;
  - overflow relay → recorded and quarantined.
- **Budgets:**
  - task cap, attempt cap, and the UTC-day cap across tasks and a new client on the same DB (restart);
  - 4 concurrent reservations for the last budget → exactly 1 admitted;
  - cancel before send → free; a second worker cannot claim an operation in flight.
- **Adapter:**
  - de-duplication by LinkedIn job ID; rows without identity are dropped, never invented;
  - common inputs only;
  - scrape assessment rejects login walls, short text, the wrong job and closed postings, and trims other jobs.
- **Wiring:** the four switch combinations, LinkedIn-only scope, the directory supplement, no forced browser read, scrape only for a complete bound JD, ATS URLs never paid.

Migration `0037` upgrade → downgrade → upgrade verified on a temporary database only. The real user database was not migrated.

## Not covered / limits

- Recovery of an `unknown` operation through `GET /calls/{id}` is not implemented as an automatic background job, by design (the switch off never reconciles). Unknown operations keep their reservation and are reported.
- Multi-process concurrency is covered by SQLite `BEGIN IMMEDIATE` reservation tests in threads, not separate OS processes.
- Live behaviour beyond the 15-call sample is unmeasured.
- Live B6 with Treg on has not been run.
