# Model-owned search closeout evidence

Execution entry: [Claude handoff](../../diagnostics/model-owned-search-handoff-20261013.md).

- `evidence-summary.json`: sanitized historical run6/run7 metrics and all three semantic probes. No credentials, session data, raw JD, resume or SQLite is included.
- `validation-files.json`: the 38-file offline regression selection; see the handoff for its exact result and command.
- `offline-validation.txt`: final offline test log, with the local checkout path replaced by `<repo>`.

The latest semantic probe has 10/10 hand-labelled synthetic cases and 47 saved-posting assessments. It made zero new source requests. Nine postings received a positive search-qualification label; they were not rescored or independently accepted as recommendations.

No complete live search was run after the model-owned classification changes. Historical run7 failed with seven recommendations at the provider budget. Probe 1 has two calls with unknown token usage, so its totals and aggregate spend are incomplete. Dollar cost is unavailable, not zero.

The probes used evolving policies/batch settings and different workloads; their total times are not an apples-to-apples performance comparison. The latest broad regression checks code contracts and scripted model IO, not production semantic accuracy.
