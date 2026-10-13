# Jev and performance

[Home](../README.md) · [Configuration](configuration.md) ·
[Architecture](agent-loop.md)

With `TYPESAFE_ENABLED=true`, chat and API fit analysis use a Jev-only scorer with
persistent decision caching and multi-job batching. With the switch off, those
entry points use the original analyzer. Jev also accelerates bounded decisions
in other tools. Planning, conversation, writing, interview evaluation and material
verification still use the main model.

## Jev-only fit scoring

Every semantic scoring question is a native yes/no decision: identify JD
requirements, distinguish personal conditions, test full/related evidence and
verify proposed citations. Arithmetic and exact source spans are local. The score is
the expected credit computed from Jev's probabilities, not thresholded categories,
so it is always a single number; personal conditions stay separate from skill
alignment. Categories (matched/partial/missing/unknown) remain for display.
The optional main-model resolver (`TYPESAFE_FIT_RESOLVE_UNKNOWNS=true`) is off by default.
There is no unbounded retry loop.

The persistent cache includes the exact resume, JD, supplied facts, owner,
model release and implementation identity. Single and batch entry points share
decisions, while compatible questions in a batch share resume context. The batch
tool accepts up to eight jobs. Unknowns have a shorter cache lifetime than decisive
answers. See [configuration](configuration.md#optional-jev-acceleration).

Production integration was exercised on 2026-10-10 with complete synthetic Avery
and Riley resumes, real `jev-1.13.0` requests, an isolated database, the saved-job
HTTP endpoints, production chat tools and provider usage accounting. Final measured three-job pair:

| Mode | Requests | Input tokens | Output tokens | Elapsed |
| --- | ---: | ---: | ---: | ---: |
| Three independent Jev scores, cold | 15 | 52,955 | 7,205 | 4.565 s |
| Three jobs sharing a Jev batch, cold | 7 | 27,499 | 4,250 | 1.986 s |
| Repeated batch, new service with persistent cache | 0 | 0 | 0 | 0.148 s |

That batch used 47.2% fewer total tokens and 56.5% less wall time than sequential
independent requests in this pair. It is not a percentile, a comparison with the
main-model analyzer, or a guarantee for unrelated jobs. One certification changed
from unresolved in an independent request to missing in the batch; other compared
requirement statuses agreed. Riley's incomplete bachelor's and future master's
remained partial; unresolved evidence kept a score interval. All scoring requests
used zero primary-model calls. This is limited integration evidence, not a new
accuracy benchmark or a universal resume-layout claim.

The [integration measurements](benchmarks/jev-only-fit-2026-10-10.json) include
unique task IDs, source-code hashes and per-phase token accounting.

Run the deterministic routing, source-boundary, cache, failure and accounting
checks without provider calls:

```sh
python -m unittest discover -s tests -p test_jev_fit_production.py -v
node --test tests/test_career_chat.mjs
```

## Expected-score consistency (2026-10-11)

Four synthetic applicants × real Greenhouse JDs (2 fits + 1 mismatch each, plus a
flattened copy of one fit), every input scored twice with fresh caches:

| Mode | Point scores | Cold repeat Δ mean / max | Flat vs structured Δ mean / max | Fit vs mismatch AUC | Median time | Main calls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Thresholded Jev (before) | 0 / 64 | ranges | ranges | — | ~2 s | 0 |
| Jev expected score | 32 / 32 | 0.53 / 3.16 | 3.49 / 6.47 | 1.00 | 1.85 s | 0 |
| Jev expected + main-model resolver | 32 / 32 | 3.16 / 9.34 | 11.65 / 23.37 | 0.81 | 54.7 s | 32 |

Jev's per-question probabilities moved by 0.003–0.01 on average between cold runs;
the former ranges came from thresholding, not provider randomness. Small sample,
synthetic resumes; not an accuracy benchmark against human labels.

## Where the fast path applies

| Capability | Eligible work | Boundary |
| --- | --- | --- |
| Form filling | Map confirmed source values to observed options | Only live option IDs can be adopted; freshness and actual field values are rechecked. |
| Job screening | Prioritize observed posting snippets | Screening is advisory and is not a verified fit score. |
| Memory retrieval | Rank already permitted confirmed memories | Uncertain selection returns the original candidate set; it creates no new facts. |
| Question classification | Choose an existing semantic category | Sensitive facts, consent, and ambiguous questions retain their normal checks. |
| Legacy workflow matching helper | Select evidence for eligible simple skills | Kept for older workflow workers; it is separate from Jev-only chat/API scoring. |

The adapter validates response IDs and distributions, uses a short timeout, and
falls back on invalid or uncertain output. It caches exact decisions briefly and
shares identical in-flight requests. Browser effects are never shared as cached
semantic decisions.

## Legacy matching helper cost gate

The legacy worker's matcher estimates remaining main-model batches before calling Jev. The
fast path requires both an opportunity to remove a main batch and enough request
size savings to justify the added request. A second evidence-verification batch
also requires a potential reduction in remaining main-model work.

Consequently, a mixed resume can use the same main-model batches with the Jev
switch on or off and make **zero Jev calls**. That is an intentional skip, not a
failed configuration. Check routing metadata and actual usage rather than
assuming that an enabled flag means the fast model was called.

The size estimate is not a provider price quote. It does not establish dollar
savings or eliminate latency variance.

## Recorded Jev measurements

The following measurements were recorded on **2026-10-09**, before later context
and cost-gate changes. Main model: `muse-spark-1.3-contributor`; returned Jev
version: `jev-1.13.0`. They used synthetic inputs and real configured services.
Times are per-mode medians including fallback work.

| Task | Samples per mode | Main only | Jev with fallback |
| --- | ---: | ---: | ---: |
| Simple skills with fixed extracted evidence | 2 | 20.44 s | 1.27 s |
| Mixed complex requirements with fixed evidence | 2 | 37.08 s | 17.03 s |
| Cross-language matching with fixed evidence | 2 | 14.21 s | 5.43 s |
| Application-question classification | 7 | 5.54 s | 0.68 s |
| Memory relevance | 6 | 6.38 s | 0.61 s |
| Full cold analysis, raw timing only | 2 | 48.59 s | 41.85 s |

The complete-analysis row is **not an equal-work speedup claim**. One extraction
produced eight requirements rather than six, changing the score from 83.3 to
70.0. Replaying the same extracted requirements through both matching paths
produced the same score and statuses. In six fixed-extraction pairs, all 28
requirement statuses and scores agreed, with original-source citations retained.

A comparable six-requirement cold pair took 53.616 s versus 45.885 s. Main-model
calls fell from three to two, with two additional Jev requests. Counting only
main calls would conceal part of the cost.

See the [recorded Jev results](benchmarks/jev-2026-10-09.json). These small samples
do not describe current production percentiles or establish an accuracy guarantee.

## Other historical measurements

The former latency audit and implementation plan are consolidated here. Their
raw records remain available; their timings are historical observations rather
than current product targets or service guarantees.

| Experiment recorded on 2026-10-09 | Observation | Interpretation |
| --- | --- | --- |
| Greeting through the task loop | 2.514 → 1.067 s median | Two samples per mode; provider latency can vary. |
| Browse, shortlist, and reply | 12.462 → 11.374 s median | Three planner calls remained in each run. |
| Controlled six-requirement cold fit | 35.481 → 31.909 s median | Same extracted work and match results in this fixture. |
| Two-page synthetic application | 26.27 → 19.07 s | One paired Chrome smoke; no employer submission. |
| Saved cold fit versus reused analysis | 217.482 → 0.032 s | Cache reuse, not faster cold inference. |

Sources: [latency measurements](benchmarks/latency-2026-10-09.json) and
[speed measurements](benchmarks/speed-2026-10-09.json). The saved-input speed trial
also had extraction and revision timeouts; it did not produce a fully verified
tailored pack in those attempted cases. Failed attempts must remain in any
comparison of completion rate and cost.

## Reproduce a comparison

Configure the main model and TypeSafe credentials using the
[configuration guide](configuration.md#optional-jev-acceleration). These commands
make billable requests with the scripts' synthetic inputs. Use a new output
directory for each run; the benchmark enables its Jev scope in its own process.

```sh
python tools/scripts/benchmark_jev.py --output artifacts/browser-eval/jev-run-001 --repeats 2 --suite all
python tools/scripts/check_jev_routing.py
python tools/scripts/quality_jev.py artifacts/browser-eval/jev-run-001/quality.json
python tools/scripts/compare_jev_extractions.py --input artifacts/browser-eval/jev-run-001/benchmark-all.json --output artifacts/browser-eval/jev-run-001/crosscheck.json
```

For a synthetic context-sharing comparison:

```sh
python tools/scripts/benchmark_context_sharing.py --live --jev --output artifacts/browser-eval/context-run-001
```

Record the code commit, model identity, source inputs, cache state, task IDs, and
call ledger for both modes. Compare output quality before reporting a speedup.
Use unique task IDs or ledger deltas so earlier rounds do not inflate the counts.

Report elapsed time, input/output tokens, main and Jev requests, fallback calls,
failed attempts, and unknown usage separately. Cached input and reasoning tokens
are detail categories within reported totals, not extra tokens to add again.
Claims about monetary savings require the applicable provider billing data.
