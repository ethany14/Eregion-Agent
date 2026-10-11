# Optimization v3 · stage 1: trusted board directory, connection reuse, source health

Parent plan: `docs/specs/optimization-plan-v3.md` (Chinese; sections 1, 2.1, 3 "1 预算与来源推进", 4).
The budget half of stage 1 was delivered in v3 stage 0 (`1a0d09d`..`6583b3c`); this task is the
**source** half. B6 background: `docs/diagnostics/remaining-2026-10-11/b6-offline-replay.md`.
Offline tests only; no paid model calls.

## Why

Live B6 runs failed mostly because LinkedIn/Indeed/aggregators were blocked (Cloudflare/login). When
the agent fell back to company boards it guessed tokens (datadog/braze/ramp/plaid) and got noise.
r1 also showed the other half: of two recommendations only one qualified. So new sources must keep
**qualification evidence, de-duplication and no-progress governance** — more links are not the goal.

## 1. Trusted company board directory

- Data file `agent_runtime/career/board_directory.json` + loader module. Each entry:
  `platform` (greenhouse | lever | ashby | workday), `company` token, Workday `host`/`site` when
  applicable, `display_name`, `domains` (role families, e.g. data/analytics, backend, design, ML),
  `locations` (cities/regions/remote-US as observed on the board), `source_url` (the public board),
  `verified_at` (UTC date), `verified_by` (`public_api_get`), `job_count_at_verification`,
  `notes`.
- **No unverified entries.** An entry is added only after a successful GET of that board's public
  API (the endpoints already used in `JobDiscovery.search`), recording the date and job count. If
  the sandbox has no network, ship the mechanism, the schema, a validator, and an **empty** directory
  with a gap report — never invent tokens.
- Scope = real user search scope, not the test cities. Derive the target scope from what users
  actually ask for: saved search/alert configs and search goals in local data if present (read-only;
  report what you found, never copy personal data into the repo), plus the four documented
  personas (junior data analyst NYC, senior backend remote-US, ML internship California, junior UX
  Austin) as a minimum floor. Record coverage gaps explicitly (role family × location with < N
  verified boards) in `docs/diagnostics/board-directory-coverage-<date>.md`.
- A refresh script `scripts/verify_board_directory.py` (re-GETs each entry, updates
  `verified_at`/count, flags dead boards; dry-run by default; rate-limited, sequential per host).
- Directory entries older than a configurable age (`JOB_AGENT_BOARD_DIRECTORY_MAX_AGE_DAYS`,
  default 30) are reported as stale, not silently used as fresh.

## 2. Use the directory in search

- New harness capability (extend `search_jobs` or a sibling tool — choose the smaller, stable tool
  surface, and keep the tool array stable per v3 stage 2 intent): given role query + location,
  select matching directory boards (role family + location match) and search them through the
  existing board path, which already applies the role-term filter, location match and seniority
  warnings.
- Prompt: when requested sources are blocked, prefer directory boards over guessed tokens; guessed
  tokens remain allowed but are reported as unverified.
- Every result still goes through read → qualification (`posting_qualification`, seniority evidence
  `search_policy.opening_level`) → import → score → recommend; nothing is auto-recommended.
- De-duplication: board results share the existing candidate identity (`job_key`), so the same
  posting from board + aggregator is one candidate; repeated directory searches with no new
  identities are no-new-evidence (existing `task_host` rule).

## 3. Connection reuse and per-source limits

- `JobDiscovery.read` opens a new `httpx.Client` per call (`agent_runtime/career/discovery.py:115`).
  Reuse one client per discovery instance (thread-safe, closed on shutdown), keeping
  `follow_redirects=False`, `trust_env=False`, the manual redirect validation and public-URL checks.
- Per-host rate limit (min interval, configurable) and bounded concurrency (≤ 3) **only for API
  sources** (board APIs); never parallelise bot-protected HTML sites; no bypassing challenges.
- Cancellation: an in-flight board fan-out stops when the task is cancelled.

## 4. Source health

- Extend existing source health (`agent_runtime/career/source_health.py`) so directory boards record
  success/empty/HTTP-error per user turn and across turns with timestamps; a board that 404s or
  errors repeatedly is skipped for the turn and flagged for the refresh script.

## Gates (business results, not counts)

- B6 offline replay (`tests/test_b6_offline_replay.py`) unchanged and passing.
- New offline replay: the r2/r3-style blocked scenario where the agent uses the **directory** (via
  the frozen fixture's recorded board responses plus clearly-labelled synthetic directory entries
  for the test only) and reaches ≥ 2 qualifying recommendations under the unchanged
  `evaluate_search`, with disclosure of blocked sources; plus a scenario where directory boards
  return only non-qualifying roles and the agent finishes honestly with fewer than two.
- Regression: fixed base commit, **no new failures**, every skip with a reason. Sandbox-only
  named-pipe failures listed, not changed. Reviewer reruns the full suite outside the sandbox
  (base `3b8d062`: 1959 passed, 132 skipped, 0 failed).

## Rules

No paid/live model runs. Public board API GETs for directory verification are allowed (read-only,
sequential, rate-limited, ≤ ~200 requests total); no scraping of bot-protected sites, no login, no
form submission. Don't touch `.env`, `tmp/`, `.codex-runs/b6-evidence/`. Don't weaken tests,
thresholds, `scripts/remaining_search_acceptance.py` or the B6 replay. Specific `git add`, small
commits, no push; bundle if `.git` is read-only. Document new settings in `docs/configuration.md`.

## Report must answer

1. Directory size, role-family × location coverage, gaps, and how scope was derived.
2. How each entry was verified (counts, dates) or why the directory is empty.
3. Search integration, de-duplication and qualification path; the new replay results.
4. Connection reuse/rate-limit design and tests.
5. Base commit, test set, new failures (none), skips with reasons, commits or bundle.
