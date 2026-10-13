# Development and evaluation tools

- `scripts/`: developer checks, reproducible evidence and benchmark runners.
- `evals/`: evaluation harnesses and their datasets.

Run files from the repository root, for example
`python tools/scripts/check_latency_contracts.py`. Editable installation also
supports module entry points such as `python -m scripts.check_latency_contracts`.
Live/billable evaluations still require their existing explicit opt-in flags.

`scripts/baseline_imports.py` only adapts imports in source loaded from historical
Git revisions by offline comparisons. It does not register old runtime packages.
