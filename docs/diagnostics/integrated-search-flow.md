# Integrated optimization · P3 candidate batches + API-first, P4d Treg wiring (2026-10-12)

Status: **offline passed**, all switches default off.

| Switch | Default | Effect when on |
|---|---|---|
| `JOB_AGENT_OPT_CANDIDATE_BATCHES` | `0` | Snapshot `candidate_queue` (query view over existing state: read-not-imported, imported-not-scored, scored-pending-decision, unread candidates). At most 5 actionable unread candidates are shown per view, out of a batch of 10; the rest are `deferred_unread`, never dropped. `search_jobs` / `screen_jobs` wait while read or imported work is unfinished (`candidates_in_progress`); decisions keep their own gate. `target_reached` once qualifying recommendations (no level warning) meet the requested count |
| `JOB_AGENT_JOB_API_FIRST` | `0` | `search_jobs` without explicit boards uses the verified directory first (no browser attempt needed). If the directory returns nothing and the user did not exclude LinkedIn, one Treg LinkedIn supplement runs (when Treg is enabled and a provider is selected). A **LinkedIn-only** request goes straight to the configured LinkedIn source and never traverses other boards. A URL already open in the browser no longer forces a browser read; an explicit `region_ref` still does. The snapshot carries a short `source_policy` (end of request) |
| `JOB_AGENT_TREG_ENABLED` + `JOB_AGENT_TREG_SEARCH_PROVIDER` | `0` / empty | Allows the Treg search above. Without a provider, paid search is refused (`treg_unavailable`) |
| `JOB_AGENT_TREG_CRAWL4AI_SCRAPE_ENABLED` | `0` | `read_job` on a public **non-ATS** URL (e.g. LinkedIn) under API-first tries `crawl4ai.web.scrape`. It is used only when `assess_scrape` judges the text a complete, open JD bound to the candidate's title (length, ≥ 2 requirement/responsibility sections, no login/captcha, title overlap ≥ 70%, single job). Otherwise the existing read path runs. Greenhouse, Lever, Ashby and Workday URLs never use a paid scrape |

Source restriction comes from the current user message (`search_policy.source_scope`):
- English and Chinese "only LinkedIn" give `linkedin`;
- "no LinkedIn" / 不要 / 排除 give `no_linkedin`;
- "not only LinkedIn" / 不只 is **not** a restriction.

A model plan or tool query is never the authority.

Unchanged:
- `read → qualify → import → score → recommend / decide`;
- the qualification and seniority rules;
- the decision gate and `evaluate_search`.

Search cards are candidates only (`completeness: card`).

## Tests

`tests/test_integrated_p3.py` (10, real `CareerHarness` + temp DB, mock Treg transport):
- flags off keep the old route; API-first uses the directory;
- LinkedIn-only never traverses other boards (Treg off → explicit `treg_unavailable`; Treg on → candidate cards and spend recorded);
- empty directory → one supplement, none when LinkedIn is excluded;
- no forced browser read for an open page;
- scrape used only for a complete, bound JD; a login wall falls back; ATS URLs skip Treg;
- the candidate gate sequence import → score → decide → search allowed;
- the batch view bounds detail and reports deferred.

Replays with the switches on:

| Combination | B6 + directory replays |
|---|---|
| `CANDIDATE_BATCHES=1` | 8 passed, 1 skipped (paid lane) |
| `JOB_AGENT_JOB_API_FIRST=1` (± batches) | `correct`, `r3`, `directory-positive` (2 qualifying), `directory-negative` (honest 0), unknown-IO pass. **r1 and r2 are not applicable**: they replay a recorded public-search (Bing) route, and API-first sends the same call to the board directory, whose URLs the frozen web has no recordings for, so the replay correctly refuses unrecorded HTTP. They stay valid for the B0 route |

Scripted replays show mechanism and business rules, not real-model behaviour or live savings.
