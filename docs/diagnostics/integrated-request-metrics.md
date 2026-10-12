# Integrated optimization · P1 request measurement (2026-10-12)

Status: **offline passed**. The request path is unchanged (no message, tool or parameter changes; measurement failures are swallowed and recorded as `wire_metrics_error`).

## What is recorded per provider attempt

Recorded at the final request boundary (`ProviderCompatibleChatOpenAI._generate` / `_agenerate_attempt`, `job_agent/model.py`), on the exact body that `_get_request_payload` would send, into the existing usage ledger row (`details_json`):

| Field | Meaning |
|---|---|
| `wire_chars`, `wire_tools_chars`, `wire_messages`, `wire_last_message_chars` | Size of the serialized request: tools first, then messages, in order |
| `wire_tools_hash`, `wire_system_hash` | 16-hex SHA-256 of the tool definitions and the system message |
| `wire_common_prefix_chars` | Length of identical leading text versus the previous request for the same `task_id | run_id | purpose | model`. `None` when there is no previous request (first call, other model, process restart) |
| `wire_first_change` | `identical`, `tools`, `message:N` (first message that differs), or `unknown_no_previous` |

Existing fields stay as they were:
- provider `input_tokens` / `cached_input_tokens` / `output_tokens` / `reasoning_tokens` (absent means unknown, not zero);
- per-part composition and history-trimming attribution (`context_metrics`);
- timing split (`queue_wait_seconds`, `provider_duration_seconds`, `persistence_seconds`).

Privacy:
- Full request text exists only in an in-memory LRU of 64 keys (`agent_runtime/wire_metrics.py`) for the comparison. It is never logged or persisted.
- Ledger rows hold lengths and short hashes only.
- After a restart the prefix is `unknown`, never inferred from hashes.

## Report

`evals/opt_report.py` now adds a `wire` section:
- the measured prefix share (identical leading characters ÷ request characters);
- where requests first change (tools / message / identical);
- the provider-reported cached share, kept separate because it counts tokens, not characters;
- the number of attempts whose provider cache counters are unknown.

The two shares are compared, never substituted for each other. A Pi-style "missed reuse" is not reported as a measured loss.

## Tests

`tests/test_integrated_metrics.py` (5): first request unknown; identical retry; appended tail (`message:2`); tool change located at `tools`; front trim located right after the system prompt; model switch and restart do not compare unrelated requests; the adapter records the metrics while the sent payload is byte-identical.

Related suites (`test_opt_metrics_reasoning`, `test_opt_v3_calibration`, `test_token_usage`, `test_task_loop`) plus P1: 211 passed.

## Limits

- Offline B6 replays use a scripted model that does not go through the provider adapter, so they produce no wire metrics.
- Live numbers come from the P8 paid runs.
- Characters are not tokens. The provider's tokenizer is not known locally, so no token-level prefix is claimed.
