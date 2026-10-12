# Integrated optimization · P8 live validation plan (2026-10-12)

**Authorization:** the user approved all paid tests in this session ("approve all the paid test"). Treg API budget ($0.10) is separate and was not used here.

**Model:** the configured main model (`LLM_MODEL_ID` from the user's `.env`, OpenAI-compatible endpoint `LLM_BASE_URL`). The ID and key are not recorded here.

**Pricing:** the per-token price of this account is **unknown** to the implementer, so dollar figures are not computed and caps are set in tokens and requests. Cached input is reported separately from uncached input (`cached_input_tokens`). Output includes reasoning tokens where the provider reports them inside output (`reasoning_tokens` shown separately, not added twice).

| Lane | Design | Samples | Hard caps | Stop rule |
|---|---|---|---|---|
| L0 cache-key probe | Same ~3K-token prompt, 1-token answer; group A without `prompt_cache_key`, group B with a task key; distinct prefixes per group so they cannot share cache; A and B interleaved, 3 each, back to back | 6 requests | ≤ 30K input tokens, ≤ 100 output | Any provider error that rejects the parameter: record "unsupported", stop group B |
| L1 real router, frozen web | `test_b6_frozen_web_with_configured_model` (`correct` scenario; offline scoring) for B0 vs B4 (stage 4 composite), alternating B0, B4, B0, B4, B0, B4 | 3 + 3 runs | ≤ 400K input per run, ≤ 2.5M input total for L1; the replay's own 600 s timeout | Any lost result, duplicate side effect, qualification violation or budget breach: stop L1 and fix offline. No automatic re-runs |
| L2 context single variables | P6 offline winners vs the selected baseline | 3 per variant | ≤ 400K input per run | As L1 |
| L3 material patches | Default full revision vs P7 patch on the same failure point | 1–3 | small | As L1 |
| L4 full networked B6 | One run with the adopted defaults | 1 | the evaluator's own 60 calls / 1M input | — |

What each lane can show:
- L0 shows only whether this provider accepts the key and reports caching for it, from a small sample.
- L1 shows real decision and tool-use behaviour with simulated scoring. It does not show real scoring quality.
- Small samples give candidate conclusions only; no statistical significance is claimed.

## Codex continuation: network stop and reviewer runbook

One additional L1 B0 attempt was made using the configured model, frozen web, 400K input
and 60 provider-attempt caps. It stopped at the first provider request with `ConnectError`.
One failed provider attempt, no completed calls, usage unknown, 29,997 reserved input
tokens, no retries and no tool actions were recorded. Dollar cost and cache reads are
unknown, **not zero**. Evidence: `../benchmarks/integrated-optimization-20261012/l1-blocked-attempt.json`.
No further paid attempt was started. L1 remaining samples and L2/L3/L4 are pending in a
networked reviewer environment under the user's existing authorization.

The repaired L1 lane returns production `SourceBlocked` for unrecorded HTTP/search/browser
sources, without falling through to a real website. Recorded-method/capture mismatches
remain strict, as do all scripted replays. Output destinations must be unused.

Run one process at a time from the repository root. Never run the entire suite with live
opt-ins. Remove live variables before any offline validation. Use a fresh `--basetemp` on
every invocation; `scripts/pytest_workspace.py` provides the sandbox Windows ACL workaround.

L1/L2 invocation (PowerShell; configure just the next selected variant):

```powershell
$env:JOB_AGENT_B6_REPLAY_LIVE_MODEL='1'
$env:JOB_AGENT_TASK_MAX_INPUT_TOKENS='400000'
$env:JOB_AGENT_TASK_MAX_PROVIDER_ATTEMPTS='60'
$env:JOB_AGENT_OPT_SNAPSHOT_REFS='0'
$env:JOB_AGENT_OPT_STABLE_TOOLS='0'
$env:JOB_AGENT_OPT_PROMPT_TRIM='0'
$env:JOB_AGENT_OPT_SCOPED_CONTEXT='0'
$env:JOB_AGENT_OPT_STATE_DELTAS='0'
$env:JOB_AGENT_OPT_HISTORY_POLICY='current'
$env:JOB_AGENT_OPT_VERIFY_AND_SCORE='0' # B4: 1; other switches remain fixed
$env:OPT_LIVE_OUTPUT='.codex-runs/integrated-review/L1-B0-next'
.venv/Scripts/python.exe scripts/pytest_workspace.py -q -p no:cacheprovider tests/test_b6_offline_replay.py::test_b6_frozen_web_with_configured_model --basetemp=.codex-runs/integrated-review/L1-B0-next-temp
```

L1 sequence remains B0/B4 alternating, three successful-or-failed planned samples each;
retain both historical mechanism attempts and the blocked continuation separately. The
2.5M aggregate input cap includes attempts with known use and conservative unknown
reservations. Inspect each result before selecting the next run; mechanism or correctness
failure stops the batch. Provider output is recorded, not assigned invented pricing.

L2: after selecting the L1 baseline, vary only PROMPT_TRIM for three samples, then only
structured_checkpoint for three. Each is capped at 400K input and 60 attempts; compare
against the unchanged baseline. Only after both live gates pass consider their combination.
No reason to spend on STATE_DELTAS from this offline sample. Keep scoring/verifier/router
reasoning unchanged; do not use low router reasoning.

L3: remove `JOB_AGENT_B6_REPLAY_LIVE_MODEL`, set `JOB_AGENT_LIVE_MATERIAL_PATCHES=1`
and a fresh `OPT_LIVE_OUTPUT`, then run exactly one selected node of
`tests/test_integrated_p8_material_live.py::test_live_material_revision[full]` or `[patch]`.
Use one pair first, at most three pairs after review. Each variant has a hard **80K input /
6 provider-attempt** cap and one revision; provider retries and full fallbacks count. Output
is bounded by the existing structured schemas and model configuration (no new dollar
price is assumed). Both variants use the same synthetic evidence and initial failure.
The JSON includes usage, wire metrics, artifacts, wall time and pending human style review.
Writer medium must be a separate future group, not mixed into this comparison.

L4: after reviewing adoption decisions, remove the other live flags; set
`JOB_AGENT_LIVE_REMAINING=1`, `JOB_AGENT_TASK_MAX_INPUT_TOKENS=1000000`, and
`JOB_AGENT_TASK_MAX_PROVIDER_ATTEMPTS=60`. Run only
`tests/test_remaining_live.py::test_long_real_search_conversations` with `-k analyst`
and a new permanent `--basetemp` evidence directory. This existing runner uses real
JobDiscovery, browser and fit service, synthetic candidate data and `evaluate_search`.
Its 60 main calls and 1M main/total raw-input acceptance caps remain unchanged; retain
summary, transcript and acceptance locally and redact before publication. No A5 batch,
real application, schedule, deployment or user-database migration is included.
