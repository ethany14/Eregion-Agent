"""Capture bounded public ATS records and create an explicitly UNLABELLED cohort.

No model calls. Existing human work is never overwritten. Run as a module.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import hashlib
import html
import json
from pathlib import Path
import re

from agent_runtime.career.job_body import Tree, clean
from scripts.e2e_repair_evaluation import APPLICANTS

# Primary employer ATS postings, not search snippets or old whole-page snapshots.
SOURCES = [
    ("software", "coursera", "6126490004", "Coursera"),
    ("software", "caseguard", "5387488008", "CaseGuard"),
    ("software", "pipetechnologies", "4265275009", "Pipe"),
    ("analytics", "capco", "8110277", "Capco"),
    ("analytics", "blockchain", "8045355", "Blockchain.com"),
    ("analytics", "workatbackbase", "7721248", "Backbase"),
    ("design", "inthepocket", "8143396", "In The Pocket"),
    ("design", "livefront", "4215612009", "Livefront"),
    ("design", "costar", "6126531004", "Co-Star"),
    ("ml", "closure-tech", "4251322009", "Closure Technologies"),
    ("ml", "awin", "8009279003", "Awin"),
    ("ml", "lynxanalytics", "8470862002", "Lynx Analytics"),
]


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def capture(source, raw_dir):
    import httpx
    field, board, identifier, company = source
    api = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{identifier}"
    key = f"{board}-{identifier}"
    response = httpx.get(api, timeout=35, follow_redirects=True)
    response.raise_for_status()
    data = response.json()
    if str(data.get("id")) != identifier:
        raise ValueError("ATS record identity mismatch")
    title = data.get("title", "").strip()
    location = (data.get("location") or {}).get("name", "").strip()
    url = data.get("absolute_url", "")
    if not title or not location or not url or f"/{board}/" not in url or identifier not in url:
        raise ValueError("Missing or ambiguous ATS title/location/URL identity")
    content = html.unescape(data.get("content", ""))
    body = clean(Tree(content).root)
    if len(body) < 250:
        raise ValueError("Posting body is empty or incomplete")
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(data, ensure_ascii=False, indent=2)
    (raw_dir/f"{key}.json").write_text(raw, encoding="utf-8")
    flat = " ".join(body.split())
    return {"job_id": key, "field": field, "title": title, "company": company,
        "location": location, "url": url, "revision": "primary-ats-r1",
        "source": {"api_url": api, "captured_at": datetime.now(UTC).isoformat(),
            "raw_path": str(raw_dir/f"{key}.json"), "raw_sha256": sha(raw),
            "body_scope": "single ATS job record content; application form and related jobs excluded",
            "record_id": identifier, "board": board,
            "boundary_checks": {"identity": True, "title": True, "location": True, "single_record_body": True},
            "human_review": {"status": "pending", "reviewer": None,
                "checklist": ["Confirm actual title/company/location against linked primary posting",
                    "Confirm description is target vacancy only; no other company/sidebar/recommended posting",
                    "Mark benefits/EEO/agency notices as non-qualification context, not applicant requirements"]}},
        "structured": body, "flat": flat,
        "structured_sha256": sha(body), "flat_sha256": sha(flat),
        "requirements_review": {"status": "pending", "reviewer": None,
            "requirements": [], "excluded_context": [],
            "instruction": "Human selects atomic requirements with exact structured source spans, level and accepted equivalent wording; do not copy model predictions as gold."}}


def applicants():
    values = dict(APPLICANTS)
    values["senior_ds"] = """SYNTHETIC APPLICANT E
EXPERIENCE
Senior Data Scientist - Fictional Research Company (Jan 2020 - Present)
Built Python and SQL pipelines, trained statistical models with scikit-learn and PyTorch.
Deployed models on AWS and monitored drift. Mentored three data scientists.
Data Scientist - Fictional Retail Company (Jun 2016 - Dec 2019)
Designed A/B tests and presented experimental results to product teams.
EDUCATION
M.S. in Statistics, Fictional University, 2016. B.S. in Mathematics, 2014.
SKILLS
Python, SQL, PyTorch, scikit-learn, AWS, statistical modelling. No Figma, OpenLink or security clearance.
"""
    values["newgrad_swe"] = """SYNTHETIC APPLICANT F
EDUCATION
B.S. in Computer Science, Fictional University, May 2026.
PROJECTS
Built a Python Flask REST API and PostgreSQL course project with unit tests.
Software Engineering Intern - Fictional Tools Company (Jun 2025 - Aug 2025)
Implemented Java API endpoints and wrote automated tests under supervision.
SKILLS
Python, Java, SQL, Git, unit testing. No production Kubernetes, leadership, Figma or security clearance.
"""
    return [{"applicant_id": key, "synthetic": True, "resume": resume,
             "resume_sha256": sha(resume)} for key, resume in values.items()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("evals/fit_labels_v1.json"))
    parser.add_argument("--raw-dir", type=Path, default=Path("tmp/fit-label-source-fetch"))
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output exists; create a new revision path to preserve human work and prior failures.")
    jobs, errors = [], []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [(source, pool.submit(capture, source, args.raw_dir)) for source in SOURCES]
        for source, future in futures:
            try:
                jobs.append(future.result())
            except Exception as exc:
                errors.append({"field": source[0], "board": source[1], "record_id": source[2],
                    "status": "source_read_failed_not_empty", "error_type": type(exc).__name__})
    people = applicants()
    pairs = [{"pair_id": f"{person['applicant_id']}::{job['job_id']}",
        "applicant_id": person["applicant_id"], "job_id": job["job_id"],
        "review": {"status": "pending", "reviewer": None},
        "requirement_statuses": [], "labelled_score": None, "fit_label": None,
        "notes": "Human must label all reviewed requirements; no model-derived gold."}
        for person in people for job in jobs]
    data = {"schema_version": 1, "dataset_id": "fit-labels-v1", "revision": "primary-ats-r1",
        "status": "pending_human_labels" if len(jobs)==12 else "incomplete_sources",
        "expected": {"applicants": 6, "jobs": 12, "pairs": 72, "fields": 4, "jobs_per_field": 3},
        "applicants": people, "jobs": jobs, "pairs": pairs, "read_errors": errors,
        "human_gold_policy": "Only explicit human source/requirement/pair review is gold. Pending labels yield null metrics and non-passing coverage, never skipped-case success.",
        "thresholds": {"format_delta_max": 10, "format_delta_passing_fraction": 0.9,
            "requirement_count_ratio_min": 0.8, "requirement_count_ratio_max": 1.25,
            "mismatch_fit_auc_min": 0.9, "mismatch_median_max": 15,
            "fit_mean_drop_max": 5, "main_four_cold_spread_max": 8,
            "typical_jd_requirements_max": 30, "concurrent_runs": 32, "concurrency": 6, "allowed_timeouts": 0}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": data["status"], "jobs": len(jobs), "pairs": len(pairs), "read_errors": errors}))
    return 0 if len(jobs)==12 else 2


if __name__ == "__main__":
    raise SystemExit(main())
