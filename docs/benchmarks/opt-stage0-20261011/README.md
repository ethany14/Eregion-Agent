# Stage 0 offline baseline (2026-10-11)

B6 scripted production-loop runs; all provider tokens are zero. Frozen web/scoring,
unchanged acceptance evaluator and replay. These are character measurements, not
a paid-model latency/quality comparison. Timing values vary across machines.

| Replay | Calls | System avg | Tools avg | History avg | Snapshot avg | Total avg | Evicted requests | Evicted groups |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| r1 | 20 | 14105.40 | 11196.35 | 2955.25 | 19081.85 | 47338.85 | 16/20 (80.0%) | 69 |
| r2 | 11 | 14078.45 | 10661.64 | 2721.00 | 14788.18 | 42249.27 | 8/11 (72.7%) | 38 |
| r3 | 2 | 13965.00 | 7042.00 | 830.00 | 6131.50 | 27968.50 | 0/2 (0.0%) | 0 |
| correct | 11 | 13965.00 | 11017.45 | 2922.27 | 13141.36 | 41046.09 | 7/11 (63.6%) | 34 |

Repair chars are zero for these scripts. Character counting preserves the existing
`request_text_chars` definition: message content plus serialized tool definitions;
it excludes transport framing, image bytes and assistant tool-call metadata.
Evictions count complete replay groups removed by the request-budget loop, not
earlier persistent-window trimming. Repeated requests may omit the same old groups.

The baseline test captures each request scope into a separate offline SQLite
ledger and runs `evals.opt_report.report` on it. It does not invent provider rows
in the real replay DB; the original B6 tests still assert zero provider calls.

## Copied historical live evidence (read-only)

Full DB totals below include every purpose/run present, not just the career router.
They deliberately differ from narrower totals quoted in the parent plan.

| DB | Attempts | Input | Output | Known cache / all input | Known reasoning / all output | Missing cache/reasoning rows | Last request chars |
|---|---:|---:|---:|---:|---:|---:|---:|
| r1 | 38 | 305,354 | 20,642 | 33.11% | 47.05% | 16 / 16 | 55,370 |
| r2 | 26 | 284,519 | 13,056 | 48.50% | 77.38% | 0 / 0 | 49,431 |
| r3 | 47 | 554,656 | 29,269 | 36.73% | 70.04% | 8 / 8 | 53,575 |

All historical attempts lack per-attempt composition and the new split timings.
Eviction frequency is unknown. Saved last-request snapshots are included separately
in `live-r*.json`; they cannot recover an average or eviction frequency. Cache and
reasoning shares with missing counters are known-counter lower bounds, not complete
measurements. The reports retain per-purpose groups and missing counts.

Reproduce (no paid lane):

```powershell
$env:OPT_BASELINE_DIR='docs/benchmarks/opt-stage0-20261011'
.venv/Scripts/python.exe -m pytest -q tests/test_b6_offline_replay.py tests/test_opt_metrics_reasoning.py
.venv/Scripts/python.exe evals/opt_report.py .codex-runs/b6-evidence/r1/career.db --json report-r1.json
```

Do not enable `JOB_AGENT_B6_REPLAY_LIVE_MODEL` or `JOB_AGENT_LIVE_*`.
The sandbox validation wrapper additionally blocks external connections, ignores
the repository `.env`, and creates temporary directories with inherited ACLs.
It is an environment-only bootstrap, not a modification to the tests or fixtures.

Tool execution timing includes synchronous child work (including nested model
calls), so do not add it to provider duration as if the spans were disjoint.
Provider persistence excludes the final telemetry timing update; tool persistence
covers the pre-effect intent checkpoint. Unknown historical timings stay null.
See the reasoning audit and verification report for the quality gates and test totals.
