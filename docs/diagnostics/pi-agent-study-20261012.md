# Pi agent study: what makes it cheap and fast, and what we can adopt (2026-10-12)

Source: <https://github.com/earendil-works/pi>, shallow clone at commit `4270522`, read only. Main files:
- `packages/agent/src/agent-loop.ts`
- `packages/coding-agent/src/core/system-prompt.ts`
- `core/compaction/compaction.ts`
- `core/cache-stats.ts`, `core/cache-warmer.ts`
- `core/tools/*`
- `packages/ai/src/api/openai-completions.ts`, `openai-prompt-cache.ts`
- `docs/how-pi-works.md`

## 1. How pi works

### Agent loop (`agent-loop.ts`, ~950 lines)

- **Append-only transcript.** Each turn sends `system → messages so far → (new user or tool results)`. The assistant reply and tool results are appended; earlier messages are never rewritten. No world-state snapshot is rebuilt per turn.
- **Tool changes as appended deltas.** If the available tools change, `declareToolChanges` appends a system message with `toolsAdded` / `toolsRemoved` instead of rewriting the tool list at the top of the request. System-prompt updates work the same way (`diffSystemPromptSections` sends only changed sections as a patch). The cached prefix never moves.
- **Steering and follow-up queues.** User messages typed mid-run are injected after the current turn without restarting.
- **Parallel tool execution by default**, sequential only for tools that declare it; results are re-ordered to the call order.
- **Safety:** if the reply was cut off by the output limit (`stopReason === "length"`), all its tool calls are failed rather than run with possibly truncated arguments.
- **Hooks:** `beforeToolCall` / `afterToolCall` (permissions, rewriting), `prepareRequest` (model / thinking per turn), `prepareNextTurn` (e.g. compaction), `transformContext`.
- **Streaming everywhere:** text, thinking and tool-call deltas are emitted as they arrive.

### Prompt engineering (`system-prompt.ts`)

- **Small system prompt** in named sections: a one-sentence identity, a one-line snippet per tool, a deduplicated bullet list of rules (each tool contributes its own guideline bullets, e.g. "Use read to examine files instead of cat"), "Be concise", cwd and project files. Roughly 2–3K characters for the default coding setup.
- **Few, generic tools:** `read`, `bash`, `edit`, `write` (plus optional grep/find/ls). Descriptions are one to three sentences and state their own limits ("output truncated to 2000 lines or 50KB … use offset/limit").
- **Skills on demand:** the prompt lists only name, description and file path. The model reads the full instructions with `read` when a task matches. Detailed procedures never sit in every request.
- **Bounded tool output:** output is truncated at 2000 lines / 50KB, never mid-line; the full output goes to a temp file whose path is returned, and the model pages with offset/limit.

### Caching (`openai-completions.ts`, `cache-stats.ts`, `cache-warmer.ts`)

- **Cache keys:** OpenAI-compatible requests send `prompt_cache_key = sessionId` plus session-affinity headers (`x-session-id`, `x-session-affinity`). Anthropic requests put `cache_control` on the last tool and the last user/system message.
- **Cache misses are a tracked defect:** every turn, everything in the previous prompt is expected to be read from cache, and misses above 1,024 tokens are counted with their dollar cost and likely cause (idle past the TTL, model change).
- **Cache warming:** while idle, pi re-sends a one-token request to keep the cache alive, but only when the expected saving is at least $0.05.

### Compaction (`compaction.ts`)

- **Only near the window limit:** it runs when context tokens exceed `contextWindow − 16,384`. It keeps the most recent ~20K tokens verbatim, cutting at a turn boundary.
- **Structured summary:** the rest is replaced by a summary in a fixed format (Goal / Constraints & Preferences / Progress: Done, In Progress, Blocked / Key Decisions / Next Steps / Critical Context, preserving exact paths and errors). Later compactions update the previous summary instead of re-summarizing.
- **Rare by design:** between compactions the prefix is stable, so it caches.

## 2. Why that is cheap and fast

| Lever | Pi | Effect |
|---|---|---|
| Prefix stability | Append-only; tool/system changes as appended deltas | Nearly the whole request is a cache read (about 10% of normal input price on most providers), and time to first token drops |
| Cache routing | `prompt_cache_key` = session + affinity headers | Requests land on the machine that holds the cache |
| Small fixed prompt | ~2–3K chars, 4 tools | Little to send, and it's cached anyway |
| On-demand knowledge | Skills by name/description/path | Detailed rules cost tokens only when used |
| Bounded outputs | Truncate + file path + offset | No huge tool results in the transcript |
| Compaction | Rare, structured, keeps 20K recent | Context stays useful without per-turn rewriting |
| Speed | Streaming, parallel tools, no planner/extra calls | Lower wall time |
| Measurement | Per-turn cache-miss accounting | Regressions are visible immediately |

The key insight is that **a large prompt that is mostly cached is cheaper and faster than a small prompt that is rebuilt every turn.**

## 3. How our loop differs (measured)

| Aspect | Eregion today | Evidence |
|---|---|---|
| Request shape | `System (~9–14K chars) + tools (~11–12K) + trimmed history (~1–3K) + **live snapshot rebuilt every turn (13–27K)** at the end` | Stage-0/closeout metrics; closeout B2 r1 req 18: system 9,697 + tools 12,020 + snapshot 26,562 |
| Prefix stability | History trimmed from the front on most requests (r1: first group changed 17/19); tool array changes with state | `docs/benchmarks/opt-v3-stage0-20261011/README.md` |
| Cache share (live) | P1b: 345,370 cached of 938,941 input (**37%**); P2 37%; P3 39% | `tmp/paid-p1b-…`, `p2`, `p3` usage |
| Request size policy | Hard cap ~48–64K chars per request; aggressive trimming to stay under it | `prepare_request(max_chars=…)` |
| System prompt | 13.9K chars of domain rules (8.9K trimmed version, off) | Stage-2 report |
| Tools | ~30 career tools, ~11K chars of schema per request | Stage-0 metrics |
| Cache key | None sent | `job_agent/model.py` |
| Tool execution | Mostly sequential; only read-type tools batchable | `harness.batchable_tools` |

So we rebuild and resend about 13–27K characters of world state every turn, and keep trimming the front of history. That defeats prefix caching. P1b paid full price for ~63% of 939K input tokens.

## 4. What we can learn (ranked by expected value and risk)

1. **Append-only state updates instead of a per-turn snapshot** (largest lever).
   - Send the stable parts once (system, tools, initial task state).
   - After each tool, append only what changed: tool results already carry most of it, plus a short `state_update` message when durable state changes (new recommendation, decision status, blocked source, user constraint change).
   - Keep authority rules in the fixed system prompt, so they don't depend on the snapshot.
   - Risk: stale beliefs. Mitigate with explicit appended updates and the existing validators, which already enforce correctness at tool time.
2. **Stop per-turn trimming; compact rarely and structurally.**
   - Raise the request budget to something closer to the model window and keep history verbatim.
   - When near the limit, replace older turns with a pi-style structured summary (Goal / Constraints / Progress / Decisions / Next / Critical context, exact URLs/IDs/scores) and keep recent turns verbatim.
   - This replaces two independent trimming layers with one rare, explicit cut.
3. **Prompt-cache routing:** send `prompt_cache_key = task_id` (and affinity headers if the provider supports them). Already planned as `JOB_AGENT_OPT_PROMPT_CACHE_KEY`. It needs one paid check that our OpenAI-compatible provider honours it (watch `cached_input_tokens`).
4. **Tool and prompt diet the pi way:**
   - one-line tool descriptions with limits stated inline;
   - each tool contributes its own rule bullets (deduplicated);
   - move long procedures (application flow, interview flow, material rules) into on-demand "skills": the name and one line in the prompt, full text read only when the task needs it;
   - declare tool-set changes as appended deltas, never by rewriting the array.
5. **Cache-miss accounting per turn:** extend the stage-0 ledger with "expected cached = previous prompt; actual cached = provider counter". Flag misses over 1K tokens with a reason (prefix change / idle TTL / model change). This makes cache regressions visible like pi does.
6. **Parallel independent tools:** allow parallel execution for independent read/score calls (we already have batchable reads and `score_jobs`). Keep sequential where order matters.
7. **Small safety items:**
   - fail tool calls from a length-truncated reply instead of executing them;
   - stream the final reply to the UI.

Things **not** to copy blindly:
- Pi is a single-user coding agent with a permissive tool set and no business validators. Our correctness gates (qualification, decision gate, completion checks, budgets) stay; they operate at tool/finish time and are independent of how context is assembled.
- Cache warming only pays at high volume with known pricing; skip it for now.

## 5. Suggested next step (not started)

Prototype item 1 + 2 + 3 behind one flag (`JOB_AGENT_OPT_APPEND_ONLY`):

- **Offline:** run the B6 replays and directory replays and require the same business outcomes as B0. Measure prefix stability: the first N messages are byte-identical across consecutive requests in ≥ 95% of turns.
- **Paid** (needs a budget): 3 runs each of B0 vs append-only on the frozen-web real-model lane. Compare total input, **cached share** (target ≥ 80%), uncached input, output, wall time and outcomes.

Expected effect, an estimate to be verified: a similar or larger raw input, but a much larger cached share. For example, at 85% cached and a 0.1× cache price, the paid-input equivalent drops by roughly 4×.

Keep the study's limits in mind: this is a reading of source code, not a benchmark of pi. Savings for our workload must be measured.

## 6. Corrections after source review by Codex (2026-10-12)

Codex re-read the same commit (`4270522473e677ddba7b093caa0064a3df51d459`). Claude verified each point below against the source. These corrections take precedence over §1–§5 where they conflict.

| Original claim | Correction (verified) |
|---|---|
| Tool/system changes are appended as deltas, so "the cached prefix never moves" | Pi **stores** replayable deltas. Whether the **sent** request keeps its prefix depends on the provider adapter: `resolveTranscriptTools()` (`packages/ai/src/utils/transcript.ts`) sends the full current tool set when the provider does not support mid-conversation tool additions or when a tool is removed or redefined. Without mid-conversation system messages, the system state is merged back into the opening system prompt. **Check the final request, not the internal message list.** |
| Send `prompt_cache_key = task_id` | In `openai-completions.ts`, `prompt_cache_key` is sent only for `api.openai.com` or for long retention with declared support; affinity headers only when `compat.sendSessionAffinityHeaders` is set. Pi would **not** send the key to an OpenAI-compatible endpoint like ours by default. Choose parameters by provider capability. Note: our provider already caches implicitly (P1b: 345,370 cached tokens with no key sent), so prefix stability alone may raise the cached share; whether a key helps needs a small paid probe. |
| Cache-miss accounting "locates" cache problems | `cache-stats.ts` **estimates** misses: `min(previous prompt, current prompt) − cacheRead`, counted above 1,024 tokens, reset after compaction. It never compares actual request prefixes. For us, record the actual common-prefix length of consecutive requests, which parts changed (system / tools / history / state), the provider's cache read, and the estimated cost with unknowns. |
| Add protection against executing tool calls from a length-truncated reply | **Already present:** `agent_runtime/model_output.py::output_problem()` rejects `length` / `max_tokens` / `max_output_tokens` replies before tools run. Not a new task. Context archive, complete tool-exchange protection, score caching and batch scoring also exist; improve them, don't rebuild. |
| Pi's prompt is ~2–3K characters | That is the bare default. Project context files and the skills list are appended in full, so real requests are larger. Not a like-for-like comparison with our full prompt. |
| Stop per-turn trimming; compact rarely | Pi's compaction also: cuts mid-turn with a separate prefix summary, never splits a tool call from its result, stores current system state with the compaction entry, rejects summaries truncated by the output limit, supports manual and overflow-recovery compaction, and spends model calls on summaries. **For us:** job identity, user constraints, score version, pending decisions and budgets stay program-owned and restorable; a model summary may describe exploration but is never the sole source of business state. |
| One switch for append-only + larger window + cache key | Test separately so gains and failures can be attributed. |
| "Parallel tools" | Pi runs a batch in parallel unless any tool declares sequential mode, keeps results in call order, and queues file mutations per file. For us: bounded concurrency for independent reads across sources/jobs; same-browser-session actions stay ordered; score / decision / material updates on one application keep version order; concurrent calls share the task budget. No sub-agents. |

### Revised plan (replaces §5)

1. **Measure the final request:** actual common-prefix length between consecutive requests, which part changed, provider cache read, and cost attribution with unknowns. Stage 0 already hashes system / tools / history prefix; add prefix length and the comparison with provider counters.
2. **Stabilize per-task common parts:** prompt sections, tool definitions and serialization order. Validate cache parameters per provider capability (small paid probe: identical requests with and without a key).
3. **Experiment: a small current state, versioned changes and stable history**, first for job search. The database stays authoritative, and restart recovery is preserved.
4. **Experiment with compaction separately:** count summary cost; cover changed user conditions, job updates, cancellation and recovery.
5. **Compare whole tasks against the baseline:** recommendation quality, calls, total cost and time. Cached share is a supporting metric only.
