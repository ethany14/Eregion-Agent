# Board directory coverage — 2026-10-11

## Scope and provenance

Read-only inspection of the default local SQLite database found **0 saved alerts**,
**0 alert runs**, and **5 career tasks**. Only goals were inspected for scope; no
candidate profile, resume, message body, tracking identifier or personal data is
copied here. The usable search goal requested business/data analyst or AI engineer
work, allowing on-site, hybrid or remote work, without an explicit location. Other
goals were greetings, saved-job reviews or a generic request to match preferences;
these do not justify inferred locations. National/unspecified-location analytics
and ML are therefore additional scope, not an invented city constraint. No alternate
user database was configured/read through `.env`.

Minimum documented personas remain: junior data analyst NYC, senior backend
remote-US, ML internship California, junior UX Austin. Directory selection does not
certify seniority or internships; those require actual posting evidence downstream.
Coverage target **N = 2 distinct verified boards** per role/location cell.

## GET verification

All entries were verified on **2026-10-11 UTC** by successful HTTP 200 public API
GET, then rechecked with the refresh script's default dry-run. Counts matched.
The directory contains **4 real boards** and **0 synthetic/unverified entries**.

| Company | Public API GET | Count |
| --- | --- | ---: |
| Datadog | `https://boards-api.greenhouse.io/v1/boards/datadog/jobs` | 435 |
| Braze | `https://boards-api.greenhouse.io/v1/boards/braze/jobs` | 334 |
| Figma | `https://boards-api.greenhouse.io/v1/boards/figma/jobs` | 151 |
| Stripe | `https://boards-api.greenhouse.io/v1/boards/stripe/jobs` | 727 |

Seed candidates came from recorded board context and known public company board
URLs; no candidate was admitted before a successful GET. Role families derive
from returned job titles; location strings are preserved from the response. These
are board-wide co-presence labels, **not a claim that each role exists in every
location**, or that any role is a qualifying vacancy. The unchanged search filters
and detail-level qualification still decide that. The broad title-based ML/data
labels may include adjacent roles; they are discovery hints only.

9 read-only public GETs total: 1 connectivity/Datadog probe, 4 initial verifications,
4 dry-run refreshes. Requests were sequential, with no scraping, login, forms or
paid/model calls. Local evidence: `.codex-runs/b6-evidence/verification.log` and
`refresh-dry-run.json`. Workday is intentionally absent: its existing listing path
uses POST and cannot honestly satisfy this task's `public_api_get` provenance.

## Coverage matrix

Values count fresh boards matching the role and observed location labels.

| Role family | New York, NY | remote-US | California | Austin, TX | Unspecified location |
| --- | ---: | ---: | ---: | ---: | ---: |
| data/analytics | 4 | 2 | 3 | 1 | 4 |
| backend | 4 | 2 | 3 | 1 | 4 |
| ML | 4 | 2 | 3 | 1 | 4 |
| design/UX | 4 | 2 | 3 | 1 | 4 |

**Gaps (<2 boards): all four Austin cells**, including the junior UX minimum
persona. Only Datadog's observed board location labels match Austin. No verified
Lever, Ashby or Workday entries were added; platform diversity remains a gap.
Nothing in these counts proves two suitable junior, senior or internship jobs.
Outside these observed locations coverage remains incomplete. There is no evidence
for expanding an unspecified user location into a particular city.

The default freshness window is 30 days. Matching stale entries are disclosed and
excluded from automatic directory selection; rerun the verifier before relying on
them. Empty/failed searches are source outcomes, never proof of no vacancies.

## Expansion (2026-10-11, user-approved additional public GETs)

The user approved more read-only public board API requests. All entries were re-verified the same
day by `public_api_get`; candidates that returned 404 or had no role family with ≥ 2 matching
titles were rejected (not added). About 370 sequential GETs in total across four passes
(two candidate passes, one Austin-focused pass, one full refresh after tightening labels),
0.5 s minimum interval per host.

**Directory: 71 boards** (58 Greenhouse, 9 Ashby, 4 Lever). Workday remains absent (POST listing).

Changes made while expanding:

- **Per-family location coverage** (`family_locations`): a board matches a role/location only where
  that role family was actually observed (data roles only in Paris no longer match "data analyst,
  NYC"). A family needs ≥ 2 matching titles; one incidental title is not coverage.
- **Tighter design family**: bare "design" no longer counts ("Design Engineer", "Design
  Verification" are engineering roles); UX/UI/user experience/product, visual, interaction or
  graphic design, or "designer" do.
- **Ranking**: directory search fans out to the first 5 boards; they are now ordered by matching
  family/location observations, not alphabetically.
- **Board API size cap** (real bug): Ashby's public listing API includes full descriptions, so large
  employers exceeded the 2 MB read cap and were unreadable (OpenAI 13.5 MB / 812 jobs; Notion
  2.3 MB). Board listing APIs now allow 40 MB; ordinary pages keep 2 MB.

Coverage after expansion (boards matching role family × location):

| Role family | New York, NY | remote-US | California | Austin, TX |
|---|---:|---:|---:|---:|
| data/analytics | 30 | 20 | 25 | 5 |
| backend | 38 | 19 | 34 | 8 |
| ML | 30 | 16 | 32 | 3 |
| design/UX | 24 | 11 | 20 | **0** |

**Remaining gap: UX/design in Austin (0)**, and Austin generally is thin. Austin-heavy employers tried
(WP Engine, BigCommerce, SailPoint, Khoros, Q2, Upland, Bumble, Everlywell, Workrise …) either are not
on Greenhouse/Lever/Ashby under those tokens or returned 404. Many Austin employers use Workday or
their own ATS; covering them needs a POST-verified Workday path (separate decision). Board coverage
is a discovery hint only — seniority (e.g. "junior") and qualification are still decided per
posting downstream, and big-tech boards often have few junior roles.
