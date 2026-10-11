# Optimization v3 stage 0 calibration

Offline only. The acceptance evaluator and `tests/test_b6_offline_replay.py` are
unchanged. The four replays use frozen web/scoring and real invocations of their
scripted router, not a paid provider. Token counts are zero by construction.
Their measurement ledger is separate from the production replay database, whose
provider count remains zero as required by the unchanged acceptance test.

## Prefix changes

Denominator: consecutive assembled requests in the same run (N − 1). Retries
sharing a request ID are not new requests; separate task/run IDs are never paired.
Hashes contain no source text. Missing historical metrics remain unknown.

The literal first history message is a repeated historical user-request wrapper.
It changes once in each replay, when empty history becomes nonempty:

| Replay | Request pairs | First-message changes | Persistent attribution | Request-layer attribution | Tools changes | System changes |
|---|---:|---:|---:|---:|---:|---:|
| r1 | 19 | 1/19 (5.26%) | 0 | 0 | 1/19 (5.26%) | 1/19 (5.26%) |
| r2 | 10 | 1/10 (10%) | 0 | 0 | 2/10 (20%) | 1/10 (10%) |
| r3 | 1 | 1/1 (100%) | 0 | 0 | 0 | 0 |
| correct | 10 | 1/10 (10%) | 0 | 0 | 1/10 (10%) | 0 |

This literal hash alone does **not** demonstrate a stable history prefix. A
supplementary hash measures the complete first replayed exchange. Stable group
identities distinguish eviction from archive compaction. A persistent eviction
is attributed only if it removes the previously replayed first group; deleting
an older group already omitted by request trimming is not blamed for that change.
The attribution columns may overlap when both layers move the prefix (`both` in
JSON); there is no overlap in these replays. `other` includes initial history and
changed content within the same first group.

| Replay | First-group changes | Persistent | Request layer | Other | Persistent groups dropped | Request-copy groups dropped |
|---|---:|---:|---:|---:|---:|---:|
| r1 | 17/19 (89.47%) | 0/19 | 16/19 (84.21%) | 1/19 | 12 | 69 |
| r2 | 8/10 (80%) | 0/10 | 7/10 (70%) | 1/10 | 3 | 38 |
| r3 | 1/1 (100%) | 0/1 | 0/1 | 1/1 | 0 | 0 |
| correct | 8/10 (80%) | 0/10 | 6/10 (60%) | 2/10 | 3 | 34 |

Persistent trimming does occur. In these short scripts it removes groups that
the request layer has already omitted; zero attribution is not zero trimming.
Request-copy drops can count the same persistent group again on later requests.
No trimming policy, limit, message content, or tool definition was changed.
Composition averages match `../opt-stage0-20261011/{r1,r2,r3,correct}.json` exactly.

## Attempt accounting

| Replay | Scripted attempts | Failed | Retries | Input tokens | Budget input units |
|---|---:|---:|---:|---:|---:|
| r1 | 20 | 0 | 0 | 0 | 0 |
| r2 | 11 | 0 | 0 | 0 | 0 |
| r3 | 2 | 0 | 0 | 0 | 0 |
| correct | 11 | 0 | 0 | 0 | 0 |

These are actual scripted boundary invocations, not HTTP attempts. Nested paid
attempts, failures, transport/reasoning retries, atomic reservations, and restart
are tested separately with offline transports and durable SQLite ledgers in
`tests/test_opt_v3_calibration.py` and `tests/test_token_usage.py`.

`live-r*.json` is a **read-only** report of the historical databases under
`.codex-runs/b6-evidence/`. They have no new per-attempt prefix hashes; no prefix
change rates can be recovered from their last-request snapshots. Their provider
attempt/input totals remain r1: 38/305354; r2: 26/284519; r3: 47/554656.
`evidence-manifest.json` contains their unchanged SHA-256 hashes. No new live run
or provider compatibility/quality claim is made.

## Reproduction

Use `.venv/Scripts/python.exe`; keep all paid opt-ins off. The local verification
wrapper ignores only the repository `.env`, supplies constructor-only fake
credentials, blocks external socket connections, and creates ACL-compatible
temporary directories without changing existing permissions.

```powershell
$env:OPT_BASELINE_DIR='docs/benchmarks/opt-v3-stage0-20261011'
.venv/Scripts/python.exe docs/benchmarks/opt-v3-stage0-20261011/run_offline.py -q -ra -p no:cacheprovider tests/test_opt_v3_calibration.py tests/test_opt_metrics_reasoning.py tests/test_token_usage.py tests/test_task_loop.py tests/test_b6_offline_replay.py --basetemp=.codex-runs/opt-v3-stage0/reproduce
.venv/Scripts/python.exe evals/opt_report.py .codex-runs/b6-evidence/r1/career.db --json .codex-runs/opt-v3-stage0/report-r1.json
```

See `../../diagnostics/opt-v3-stage0-verification-20261011.md` and
`verification.json` for the fixed base, final test set, every skip reason, sandbox
failure comparison, and bundle delivery.
