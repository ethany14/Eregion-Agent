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
