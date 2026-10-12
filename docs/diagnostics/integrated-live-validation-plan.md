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
