# Unified loop · R2 / M1 validation: public contracts and protections (2026-10-12)

Plan: [`claude-unified-execution-plan-20261012.md`](../specs/claude-unified-execution-plan-20261012.md) R2, [`unified-loop-migration-plan-20261012.md`](../specs/unified-loop-migration-plan-20261012.md) §M1. Baseline: [`unified-loop-m0-baseline.md`](unified-loop-m0-baseline.md) (HEAD `158e557`, then M0 doc `fe139e9`). Executor: Claude. No paid calls, no `.env` change, no flag defaults changed.

## Result

**M1 passes offline.** The table maps each acceptance item in the migration plan to the commit and the tests that check it.

| M1 acceptance item | Change | Commit | Tests |
|---|---|---|---|
| Existing Career / Application Hosts pass the contract | New `agent_runtime/host_protocol.py`: `Host` protocol, `REQUIRED` / `OPTIONAL` / `ATTRIBUTES`, `missing_methods()`. A test checks that the engine uses only declared members and guards optional ones with `hasattr` | `1ff796f` | `test_host_protocol.py` |
| Truncated responses and invalid arguments never run a tool: **Session path** | `tools/model_adapter.py`: malformed JSON, non-object args, missing name, LangChain `invalid_tool_calls`, and every call of a `length` / `max_tokens` response become `invalid_reason` calls. `tools/loop.py` answers them with a failed `invalid_tool_arguments` result **without reaching the executor**. An empty string or no args is still a valid no-argument call. Responses now carry `finish_reason` and non-secret `provider_metadata` | `c195de1` | `test_tool_model_adapter.py` (+7), `test_tool_loop.py` (+1) |
| Same, **AgentLoop path** | It already rejected `finish_reason` truncation and `invalid_tool_calls` (repair once, then `invalid_model_response`). It now also honours the Anthropic-style `stop_reason` | `0dac765` | `test_task_loop.py` (+4) |
| Nested calls settle once; unknown ≠ zero | No production nesting of `provider_call` exists. The real wrapper case, `adapter_attempt`, counts itself only when it has no metered child; this is now locked in by tests. Overlapping `provider_call`s remain **separate budgeted attempts** (see "Rejected change") | `f819ab2` | `test_usage_accounting.py` |
| Cancellation never accepts a stale result | Engine behaviour is verified directly: a result arriving after cancel stops with `cancelled` and executes nothing; a result for an older revision is `decision_discarded` and re-decided | `c2625d3` | `test_loop_stale_results.py` |
| Treg / browser / model resources closed by their owner | `CareerHarness.close()` now closes the Treg client too. It is idempotent and keeps closing the rest when one resource fails. The browser manager already closes pages on its own worker thread | `849c095` | `test_treg.py::test_career_harness_close_…` |
| API-first: prompt / snapshot / tool descriptions / slim tools from one config | New `career/source_mode.py`, keyed on `CareerHarness.api_first()` (`JOB_AGENT_JOB_API_FIRST` via `treg_config`). On: the prompt (full and trimmed) loses its browser-first wording, `search_jobs` / `read_job` descriptions say API-first, and the snapshot carries `source_policy`. Off: byte-for-byte unchanged. `Turn.tool_descriptions` is applied **after** `slim_tools`, so `STABLE_TOOLS` cannot restore the old text | `931d232` | `test_source_mode.py` (on/off, both prompts, slimmed tools, a real `TaskHost.observe`) |
| Runtime-used API business functions are neutral | `extract_pdf_text` → `agent_runtime/resumes/pdf_text.py`; `public()` → `agent_runtime/auto_apply/public.py`. Routes re-export them. A guard test forbids `api.*_routes` imports in `agent_runtime` | `37d7455` | `test_host_protocol.py::test_runtime_does_not_import_api_route_modules` |
| New contracts trigger no extra model request | None of these changes adds a model call. Invalid Session calls produce a tool result, not a re-request; the engine repair path is unchanged | — | covered by the call counts asserted in the tests above |

## Rejected change (recorded on purpose)

I first added a context-variable guard that folded any `provider_call` opened inside another into the outer row. The existing test `test_opt_v3_calibration.py::test_input_reservation_pending_failed_and_actual` failed, correctly: overlapping calls stand in for a concurrent second request, which must still reserve budget. A worker thread with a copied context would also have bypassed the budget and the ledger. I reverted the guard (it was never committed) and replaced it with a test that overlapping calls stay separate budgeted attempts.

## Compatibility

- **Persisted Session messages:** `NormalizedToolCall` omits `invalid_reason` when it is None, so valid calls keep their previous JSON shape and message content hash. In-flight Session rows written before this change replay without `MessageConflictError`. A test pins the shape.
- **Flags:** every default is unchanged. `source_mode` acts only when `JOB_AGENT_JOB_API_FIRST=1`.
- **Out of scope here** (per plan): Session → AgentLoop is M2; the analysis workflow and material full re-check are M3; scheduling is M4/M5.

## Offline verification

Full suite (no live opt-ins; `tests/conftest.py` offline isolation):

```
2176 passed, 134 skipped, 16 subtests passed, 0 failed in 775 s (at 37d7455)
(R1 report at 57c63ab: 2136 passed / 134 skipped. The +40 includes this stage's new tests and tests added by 158e557; no test was removed or skipped to get here)
```

Focused runs during the work:
- Session / tool loop: 122 passed;
- career / loop / integrated / opt suites: 380 passed / 7 skipped;
- usage: 237 total with 1 expected failure, which led to the revert above, then 40 passed;
- route-neutral move: 138 passed / 2 skipped.

## Next

R3 / M2: a SessionHost on `loop_engine.AgentLoop` behind a compatibility switch. The Session coordinator keeps its claim, version and approval semantics; `ToolCallingLoop` stays only as a fallback until M7.
