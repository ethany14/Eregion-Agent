# Pi context experiments — 2026-10-12

Status: offline prototypes passed; release defaults unchanged. No cache key, LLM compaction, larger window, new runtime or scoring model was added.

`context_experiments.py` adds independently gated search-only resume references (`SCOPED_CONTEXT`) and disposable request-side state deltas (`STATE_DELTAS`). The original resume remains losslessly available through `read_context`; omitted facts are explicitly unknown. Scoring still obtains its complete inputs from the existing evidence path. Deltas carry contiguous sequence numbers and before/after hashes. Every request includes the complete checkpoint and sequence, so a model never depends on having consumed a previous request. Current user authority, constraints, qualification, budget and decisions remain inline. Invalid sequences/hashes, changed authority, phase changes, eviction and restart rebuild from the current authoritative observation. There is no second persistent event store and no database write/event atomicity gap.

`HISTORY_POLICY=structured_checkpoint` keeps whole tool exchanges, aligns the persistent and request trim boundary, persists the available history budget through the existing runtime, and labels the authoritative observation as a deterministic checkpoint. It differs from the older `checkpoint` policy by retaining the aligned budget. The 48,000-character request cap is unchanged. Turning all switches off reconstructs the original full request from current observations without deleting evidence or costs.

Single-variable frozen `correct` B6, production request serializer and P1 prefix measurement, scripted router, simulated scoring:

| Variant | Router calls | Total request chars | Serialized UTF-8 bytes | Common prefix share |
|---|---:|---:|---:|---:|
| B0 | 11 | 463208 | 482312 | 56.90% |
| STABLE_TOOLS | 11 | 466284 | 485732 | 61.19% |
| PROMPT_TRIM | 11 | 434319 | 458061 | 53.21% |
| SCOPED_CONTEXT | 11 | 463208 | 482312 | 56.90% |
| STATE_DELTAS | 11 | 466857 | 486572 | 57.89% |
| structured_checkpoint | 11 | 458120 | 475894 | 58.14% |
| PROMPT_TRIM + structured_checkpoint (after single gates) | 11 | 434528 | 456964 | 52.75% |

All seven have two qualifying persisted recommendations, identical formal scoring input hashes, no orphan tool results and no protected overflow. Raw records: `docs/benchmarks/integrated-optimization-20261012/p6/`. Read-back counts are recorded per request. These are serialized request sizes, **not provider tokens or paid-cache results**. No tokenizer estimate is presented because its provider-specific accuracy is unknown. The synthetic resume is below the scoped threshold, explaining its unchanged size; dedicated long-resume tests verify exact retrieval and projection behavior.

Decision: PROMPT_TRIM is the leading size candidate (6.24% fewer characters); structured_checkpoint is secondary (1.10%). State deltas slightly increase total size; no adoption. Stable tools improve prefix share but increase raw size; no adoption. The subsequently tested combination also passes with identical scoring input hashes, but has no clear character-count benefit over PROMPT_TRIM alone. No combination is promoted because live single-variable evidence is unavailable. L0's inherited 98.8% implicit-cache observation supports investigating stable prefixes, not adopting a new cache field.

Dedicated gates cover restart, missing/corrupt sequence, evidence changes, deletion, repeated projection idempotence, current constraints, cancellation/phase reset, switch rollback, exact originals, whole exchanges and unchanged request budget. Scope: scripted behavior cannot prove router comprehension or real performance. L2 must compare PROMPT_TRIM first against the selected L1 baseline, then independently structured_checkpoint before any combined candidate.
