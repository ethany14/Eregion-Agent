# Execution roadmap · final status (R1–R9, 2026-10-12)

Plan: [`claude-unified-execution-plan-20261012.md`](../specs/claude-unified-execution-plan-20261012.md) §11. Executor: Claude, with review by Codex. **The full product chain is not complete: the API-first business gate (R6) has not passed.**

| Area | Status | Evidence |
|---|---|---|
| Architecture: one autonomous kernel, one execution owner (R2–R5, M1–M7) | **Done; accepted offline** (full suite green at `10a07ae`) | [`unified-loop-final.md`](unified-loop-final.md) |
| Source chain offline (boards, Treg, API-first) | **Done offline**: new tests for partial / blocked / closed, no key, isolation, invalid URLs, thin-directory supplement, scrape verdicts | [`api-first-b6-validation.md`](api-first-b6-validation.md) |
| **Business gate: API-first B6** (≥2 qualifying NYC junior DA recommendations within 60 calls / 1M input) | **FAILED**: 2 bounded samples, 0 qualified. Run-1 exposed 2 defects (fixed); run-2 completed cleanly with an honest no-match | same |
| LinkedIn MCP (R7) | **T0 passed offline** (adapter + contract). **T1 / T2 not run**: they need an explicitly chosen account and a login, which is not authorized. Not adopted; optional and off | [`linkedin-mcp-offline-validation.md`](linkedin-mcp-offline-validation.md) |
| Source configuration (R8) | **Not frozen as an accepted default**, because no configuration has passed the business gate. **Offline, precisely:** career routing for Treg off / on (free boards always; Treg only when configured; no crash without credentials), and runtime startup for none / Treg only / MCP only / both through the real MCP config file, loader and manager with a fake LinkedIn client. A real upstream process and account are not exercised. The first version of this test reused env rows without configuring MCP (review R8-EVIDENCE-001); it was corrected in `84ab70f` | `tests/test_r8_source_configurations.py` |
| Materials (L3) | One approved live full sample reached `awaiting_review`. **Human style review pending** (cannot be signed by Claude). Patch variant not compared; `MATERIAL_PATCHES=0` | [`unified-loop-m3-validation.md`](unified-loop-m3-validation.md) |
| Deployment / real user database | **Not done; not authorized.** Dry-run tool and steps prepared | [`unified-loop-m6-validation.md`](unified-loop-m6-validation.md) |

## Source policy as built (and what the evidence supports)

1. **Free public company boards (directory):** always used. They are free, but coverage for "junior data analyst, New York" proved thin in both R6 samples.
2. **Treg (user-supplied key; off by default):** LinkedIn candidate search when the directory returns fewer than 3 jobs, plus Crawl4AI page scrape for non-ATS postings. Every paid call carries a per-call cost cap, an idempotency key and a ledger entry; unknown cost is never zero. In run-2, two paid LinkedIn scrapes were rejected as incomplete and the reason was not recorded. That is now recorded (`a599ca3`), but it is unverified live.
3. **LinkedIn MCP:** adapter ready, not wired, off.
4. **Browser:** supplementary verification only. LinkedIn HTTP / browser reads were blocked in run-2, and the same account is never retried through another channel.

## Spend this session (model and Treg booked separately; dollar cost of the model unknown)

| Item | Attempts | Input / output tokens | Treg |
|---|---|---|---|
| L3 live full (M3, approved) | 2 | 2,413 / 6,855 | — |
| R6 B6 run-1 | 27 | 230,109 / 15,026 | 2 ops, $0.0003 |
| R6 B6 run-2 | 58 | 674,855 / 40,437 | 3 ops, $0.00075 |
| **Total** | **87** | **907,377 / 62,318**; 0 unknown | **5 ops, $0.00105**; batch now 20 / 20 requests, $0.00505 / $0.10 |

## What is needed to finish (decisions for the user)

1. **Treg budget for R6:** the authorized batch is exhausted. Another API-first B6 sample needs a new Treg allowance; about $0.0005–$0.002 per sample at observed prices, with the per-run model caps unchanged. The scrape-verdict recording added after run-2 lets the LinkedIn JD rejection be attributed on the next sample.
2. **LinkedIn account for R7 T1:** an explicitly chosen account and its login through the pinned upstream server. Otherwise MCP stays deferred.
3. **Materials:** a human style review of the `L3-full-r2` letter.
4. **Deployment:** a separate authorization for the backup → snapshot dry-run → deploy steps.

## Offline verification at the final HEAD

| Version | What ran | Result | Raw output |
|---|---|---|---|
| `0e2279f` (R6 / R7 / R8 code before the two review fixes) | Full offline suite, no edits during the run | **2269 passed / 135 skipped / 16 subtests, 0 failed** (827 s) | [`full-suite-0e2279f.xml`](../benchmarks/execution-roadmap-final-20261012/full-suite-0e2279f.xml) / [`.log`](../benchmarks/execution-roadmap-final-20261012/full-suite-0e2279f.log) |
| `84ab70f` (+ R7-CONTRACT-001 and R8-EVIDENCE-001 fixes) | Affected suites: LinkedIn T0, R8 configurations, MCP app, R6 sources, P3, Session API | **62 passed**, 0 failed | [`affected-84ab70f.xml`](../benchmarks/execution-roadmap-final-20261012/affected-84ab70f.xml) / [`.log`](../benchmarks/execution-roadmap-final-20261012/affected-84ab70f.log) |

The `0e2279f` full run is **not** attributed to `84ab70f`. The fixes after it change only `linkedin_source.py` (not wired into production routing) and two test files; their affected suites were rerun at `84ab70f`.
