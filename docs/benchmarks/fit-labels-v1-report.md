# Fit labels v1 evaluation

Status: **pending_human_review**. Overall acceptance: **not_passed**.

Human labels are pending until explicitly confirmed. Missing cases are not skipped successes.

```json
{
  "coverage": {
    "expected_pairs": 72,
    "actual_pairs": 72,
    "expected_prediction_rows": 288,
    "cached_rows": 0,
    "successful_rows": 0,
    "failed_rows": 0,
    "missing_rows": 288,
    "human_reviews_pending": 96
  },
  "quality_metrics": {
    "main": {
      "structured": null,
      "flat": null
    },
    "jev": {
      "structured": null,
      "flat": null
    }
  },
  "thresholds": {
    "format_delta_max": 10,
    "format_delta_passing_fraction": 0.9,
    "requirement_count_ratio_min": 0.8,
    "requirement_count_ratio_max": 1.25,
    "mismatch_fit_auc_min": 0.9,
    "mismatch_median_max": 15,
    "fit_mean_drop_max": 5,
    "main_four_cold_spread_max": 8,
    "typical_jd_requirements_max": 30,
    "concurrent_runs": 32,
    "concurrency": 6,
    "allowed_timeouts": 0
  },
  "unmeasured_acceptance": [
    "A1 four equivalent cold runs, <=30 typical requirements, 32 runs/6 concurrency/zero timeouts",
    "A4 fit mean drop <=5 requires frozen baseline; no partial weight changes",
    "A2 alert calibration requires reviewed labels; no threshold calibration from pending labels"
  ]
}
```
