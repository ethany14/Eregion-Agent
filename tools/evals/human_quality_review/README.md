# Human material-quality review

This workflow complements automated regressions with human review of **10–20
anonymized real resume/job-description pairs**. The repository's synthetic
fixtures must not be counted as real-material evaluations.

## Prepare the cases

Use material owned by the contributor or supplied with permission for this
evaluation. Remove names, contact details, profile URLs, confidential employers
or clients, and other identifying information before creating the review packet.
Retain the facts needed to judge grounding: technologies, responsibilities,
durations, qualifications, and public job requirements.

Keep original PDFs and private source material outside Git. Do not extract a
review dataset from the production database. Use opaque case IDs such as
`real-backend-01`.

Copy [cases.template.json](cases.template.json) to `cases.local.json` in this
directory. Each case must contain the anonymized source and generated artifact,
declare `source_kind: "anonymized_real"`, and set `consent_confirmed: true`.
The local packet is ignored by Git.

[cohort_plan.json](cohort_plan.json) defines a 12-case target across Backend, Data
Analyst, Business Analyst, and AI Engineer roles. It is a collection plan, not
evidence that those real cases have been collected or passed review.

From the repository root:

```sh
python -m evals.human_quality_review.validate evals/human_quality_review/cases.local.json
```

## Review the output

Use at least two reviewers when possible. Score each dimension from 1 to 5 and
record concrete examples:

| Dimension | What to assess |
| --- | --- |
| Factual accuracy | Every substantive claim has source support. Invented employers, dates, metrics, responsibilities, or technologies fail review. |
| Non-duplication | Repeated content within an entry is removed without losing distinct experience from another employer or project. |
| Application readiness | The document needs ordinary personal editing rather than factual reconstruction or a rewrite. |

Inspect rendered PDFs page by page as well as the text. Check headings, links,
skills, education, date/status fidelity, repeated entries, clipping, and excessive
blank space. A passed semantic check alone does not establish layout quality.

## Record failures and regressions

Copy [reviews.template.json](reviews.template.json) to `reviews.local.json`.
For every score below 4, provide `failure_reasons` using the supported codes:
`unsupported_claim`, `invented_metadata`, `within_entry_duplicate`,
`cross_entry_fact_removed`, `poor_targeting`, `not_application_ready`, or `other`.

Every failed case also needs a `regression_test` entry describing the smallest
general regression that would prevent recurrence. After implementing it, record
the repository path. Validate the completed packet:

```sh
python -m evals.human_quality_review.validate evals/human_quality_review/cases.local.json --reviews evals/human_quality_review/reviews.local.json
```

The validator checks the packet structure without calling a model. It does not
replace human judgment or turn a failed artifact into a passing one. Keep the
original failure and its revision trail. Only a separately minimized, reviewed
synthetic regression fixture should enter committed tests.
