# R1 live validation

Frozen version: `57c63ab4b9812ddcb0d9bc8e9f3760d1539f8a45`. Experimental release defaults remain unchanged. This report is updated after each attempt; no failed sample is replaced.

## L1 B0 continuation

Result: FAILED acceptance; `needs_input`, `no_progress`, zero qualified recommendations. Ten provider attempts completed successfully with no provider errors, retries or unknown usage in this attempt. Input 108,115, output 3,494, cached input 43,400; reasoning is included in output and must not be added again. Duration 46.31 seconds. Dollar pricing remains unknown.

Actions included LinkedIn and Indeed browsing, archived-context reads, an Indeed detail link, verified-board directory search and alternative public sites. Nine frozen requests were unavailable. The archive contains 12 HTTP responses, 14 browser captures and two exact public-search query keys; it is not a general web simulator. The requested directory route and several selected URLs lacked recordings. A returned Indeed page was available, but the chosen detail URL was not. Source blocking followed by three stalled actions ended the task honestly without importing/scoring invented jobs.

This is a failed live-router acceptance sample, not evidence of a provider connection failure and not proof that the corresponding real websites are unavailable. It also does not isolate a stage-4 regression because only B0 ran. No qualification threshold, fixture, no-progress guard or assertion was changed to turn the result into a pass.

Disposition: stop the L1 group, no automatic B0 retry or B4 sample. Keep VERIFY_AND_SCORE=0. Defer L2 PROMPT_TRIM/structured_checkpoint adoption because its selected live baseline is unresolved; both remain off/current. A future experiment needs an explicitly reviewed frozen-source coverage design, preserving original fixtures and acceptance standards. Independent L3 and the final real-web B0 L4 remain meaningful and may continue under existing authorization.

L1 cumulative accounting: historical 264,665 known input + 29,997 conservative unknown reservation + new 108,115 = 402,777 budget input. Remaining original L1 ceiling: 2,097,223. Historical unknown use is retained. New L1 evidence: `.r1-evidence/L1-B0-r1/{invocation.json,pytest.log,pytest.xml,result/result.json,trace.json}`. The SQLite test database retains the complete task and attempt records.

## L3

Full variant FAILED: `needs_revision`, one completed provider call, 1,948 input / 3,369 output, 27.14 seconds (33.74 seconds pytest). The opening contained an uncited experience-related claim; the cited paraphrase also failed verification. No retry/unknown usage. Evidence: `L3-full-r1/result/full.json` and `verification.json`.

Inspection found the live fixture replaced the writer with SharedPackModel but retained the verifier created for FakePackModel, which had no semantic judge. The sample therefore did not exercise production-equivalent verification. The test now pairs the injected writer with ArtifactVerifier(model.verify_claims), matching production construction. Two offline cases confirm a supported paraphrase passes and an unsupported one still fails. This fixes test wiring, not the actual generated opening or verifier policy. No qualification/grounding checks were relaxed.

The group stopped after the failed full sample: patch variant, further pairs and human style review are untested. MATERIAL_PATCHES remains 0. The full-revision live acceptance remains unresolved; offline wiring tests do not convert the failed sample into a pass. Per-variant cap remains 80K input / six attempts; original maximum three pairs (480K / 36 attempts) is a ceiling, not permission to rerun automatically. Only 1,948 input / one attempt was spent by this continuation. Existing material generation/revision evidence remains separate and is not reset.

## L4

FAILED on the original frozen default configuration. Runtime 464.64 seconds (471.65 seconds pytest). Sixty completed provider attempts, including 45 main-router provider calls; the task recorded 46 decisions because the last request stopped before transmission. Main input 587,860; total input 630,982; output 42,090; cached input 263,773. No retries, pending calls or unknown usage. Input limits were not exhausted; the runner's conservative 60-total-provider-attempt limit stopped the run before the nominal 60-main-call ceiling. That actual limit was preserved, not silently increased.

Two jobs were imported/scored. Good Apple's Data Analyst (NYC, junior evidence, score 43.46) was recommended. DoorDash's Data Analyst, In-Store (score 36.51) did not meet junior seniority and was not recommended. The saved single recommendation is insufficient for the required two. Additionally, the provider-budget final message omitted its URL/score, so the original acceptance result is **0 complete deliveries**, with `loop_not_completed_cleanly` and `fewer_than_two_verified_scored_qualifying_recommendations`.

The provider-budget stop now calls the existing local terminal_delivery formatter and appends saved results while preserving `needs_input`, `provider_budget`, non-retryable status and the explicit incomplete message. No model request or new tool work is added. Three offline cases cover saved, empty and unavailable delivery. This repair does not create a second recommendation; the recorded L4 result remains FAILED. No paid rerun was performed after the fix.

The run recorded zero materials, applications and schedules. API-first, candidate batches, Treg, material patches, stage-4 composition and context experiments were disabled; history was current. No LinkedIn MCP installation occurred. Published evidence is under `../benchmarks/r1-closeout-20261012/L4-B0-r1/`; raw SQLite remains in the isolated checkout.

## Continuation accounting

This execution spent 71 completed attempts, 741,045 input and 48,953 output tokens across L1, L3 and L4. No new unknown usage; this does not release the historical 29,997 reservation. Dollar cost remains unknown. Reasoning is already included in output and cached tokens in input; neither is added a second time. This total is for this continuation only, not all historical optimization work. Prior L0/Treg/material evidence and its charges remain in their original reports. L2 and L3-patch made no calls. Paid groups are now stopped; further samples need a revised, bounded run record and failure-specific readiness checks, not automatic repetition.
