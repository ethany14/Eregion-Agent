"""Local F2 inventory; never stage, delete, call providers, or read .env.

Create immutable indexes and a proposed Git scope with --output NEW_PATH.
Verify a saved snapshot with --check PATH. SHA-256 covers the other files,
not the scope manifest itself. Later work needs a new revision, not overwrite.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
HISTORICAL = (
    "docs/diagnostics/e2e-2026-10-10",
    "docs/diagnostics/repairs-2026-10-10",
)
CATALOGUE = "docs/diagnostics/remaining-2026-10-11/catalogue-attempt-offline-r1.json"
SECRET_KEYS = {"password", "api_key", "access_token", "refresh_token", "authorization", "cookie", "set-cookie"}
RAW_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".log", ".xml", ".png", ".pdf", ".wal"}


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT)


def paths(*args: str) -> list[str]:
    return [p.decode("utf-8") for p in git(*args).split(b"\0") if p]


def ignored_paths(names: list[str]) -> set[str]:
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "-z", "--stdin"], cwd=ROOT,
        input=b"\0".join(n.encode("utf-8") for n in names) + b"\0",
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace"))
    return {p.decode("utf-8") for p in result.stdout.split(b"\0") if p}


def describe(name: str) -> dict:
    file = (ROOT / name).resolve()
    file.relative_to(ROOT)
    data = file.read_bytes()
    return {"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def write_new(name: str, value: dict) -> None:
    dest = (ROOT / name).resolve()
    dest.relative_to(ROOT)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def verify_files(entries: list[dict]) -> list[str]:
    errors = []
    seen = set()
    for entry in entries:
        name = entry["path"]
        if not isinstance(name, str) or Path(name).is_absolute() or ".." in Path(name).parts:
            errors.append("Invalid relative artifact path")
            continue
        if name in seen:
            errors.append(f"Duplicate artifact path: {name}")
        seen.add(name)
        if not (ROOT / name).is_file():
            errors.append(f"missing: {name}")
        elif describe(name) != {k: entry[k] for k in ("path", "bytes", "sha256")}:
            errors.append(f"hash/size changed: {name}")
    return errors


def history_indexes(*, create: bool = True) -> list[dict]:
    indexes = []
    for directory in HISTORICAL:
        name = directory + "/publication-index.json"
        if (ROOT / name).exists():
            index = json.loads((ROOT / name).read_text(encoding="utf-8"))
            errors = verify_files(index["local_originals"])
            actual = {p.relative_to(ROOT).as_posix() for p in (ROOT / directory).rglob("*")
                      if p.is_file() and p.name not in {"README.md", "publication-index.json"}}
            if actual != {e["path"] for e in index["local_originals"]}:
                errors.append(f"Original inventory changed: {directory}")
            if errors:
                raise ValueError("Historical originals changed: " + "; ".join(errors))
        else:
            if not create:
                raise ValueError(f"Missing historical index: {name}")
            entries = []
            for file in sorted((ROOT / directory).rglob("*")):
                if not file.is_file() or file.name in {"README.md", "publication-index.json"}:
                    continue
                entry = describe(file.relative_to(ROOT).as_posix())
                if file.suffix == ".xml":
                    tree = ET.fromstring(file.read_bytes())
                    suites = [tree] if tree.tag == "testsuite" else list(tree.findall("testsuite"))
                    entry["historical_suite_totals"] = {
                        k: sum(int(s.get(k, 0)) for s in suites)
                        for k in ("tests", "failures", "errors", "skipped")
                    }
                    entry["seconds"] = sum(float(s.get("time", 0)) for s in suites)
                entries.append(entry)
            index = {
                "revision": "2026-10-11-f2-r1",
                "scope": "Historical local originals, not current A-F acceptance. Counts may include subtests; suites overlap.",
                "publication": "Only this hash/count index and README are proposed for Git in this directory. Originals are retained locally, not deleted.",
                "original_count": len(entries),
                "original_bytes": sum(e["bytes"] for e in entries),
                "local_originals": entries,
            }
            write_new(name, index)
        indexes.append({"index": name, "original_count": index["original_count"], "original_bytes": index["original_bytes"]})
    return indexes


def group(name: str) -> str:
    if name == ".gitignore":
        return "git_ignore_rules"
    if name.startswith("E2E_") and name.endswith(".md"):
        return "reports_and_plan"
    for prefix, label in (
        ("tests/fixtures/", "bounded_regression_fixtures"),
        ("tests/", "tests"),
        ("docs/diagnostics/", "compact_evidence"),
        ("docs/benchmarks/", "offline_benchmarks_and_frozen_inputs"),
        ("evals/", "evaluation_tools_and_pending_labels"),
        ("scripts/", "reproduction_and_evidence_tools"),
        ("web_app/", "frontend"),
        ("agent_runtime/", "production_python"),
        ("job_agent/", "production_python"),
        ("api/", "production_python"),
        ("custom_agent/", "production_python"),
    ):
        if name.startswith(prefix):
            return label
    raise ValueError(f"Unclassified proposed file: {name}")


def secret_fields(value, path: str = "$") -> list[str]:
    found = []
    if isinstance(value, dict):
        for key, child in value.items():
            here = f"{path}.{key}"
            if key.casefold() in SECRET_KEYS and isinstance(child, str) and child.strip():
                found.append(here)  # Never print the value.
            found.extend(secret_fields(child, here))
    elif isinstance(value, list):
        for i, child in enumerate(value):
            found.extend(secret_fields(child, f"{path}[{i}]"))
    return found


def audit(output: str, *, recheck: bool = False) -> dict:
    output = (ROOT / output).resolve().relative_to(ROOT).as_posix()
    if (ROOT / output).exists() and not recheck:
        raise FileExistsError("Use a new revision; the requested output already exists.")
    archives = history_indexes(create=not recheck)
    catalogue = json.loads((ROOT / CATALOGUE).read_text(encoding="utf-8"))
    frozen_entries = catalogue["artifacts"] + catalogue["implementation_files"]
    errors = verify_files(frozen_entries)
    if len(catalogue["artifacts"]) != 25 or len(catalogue["implementation_files"]) != 8:
        errors.append("Catalogue r1 must retain all 25 artifact and 8 implementation entries.")
    modified = set(paths("ls-files", "--modified", "-z"))
    untracked = set(paths("ls-files", "--others", "--exclude-standard", "-z"))
    staged = set(paths("diff", "--cached", "--name-only", "-z"))
    names = sorted((modified | untracked | staged) - {output})
    entries = []
    for name in names:
        entry = {**describe(name), "group": group(name),
                 "git_state": "staged_preexisting" if name in staged else "modified" if name in modified else "untracked"}
        if name == ".env" or Path(name).suffix in RAW_SUFFIXES or name.startswith("tmp/"):
            errors.append(f"Raw/secret file in proposed scope: {name}")
        if name.endswith(".json"):
            value = json.loads((ROOT / name).read_text(encoding="utf-8"))
            for field in secret_fields(value):
                errors.append(f"Credential field requires review: {name}:{field}")
        entries.append(entry)
    raw_names = []
    for item in archives:
        data = json.loads((ROOT / item["index"]).read_text(encoding="utf-8"))
        raw_names.extend(e["path"] for e in data["local_originals"])
    probes = [".env", "tmp/f2-audit-probe.json", "tmp/f2-audit-probe.db-wal", "uploads/f2-audit-probe.pdf", ".browser-sessions/f2-audit-probe.json", *raw_names]
    ignored = ignored_paths(probes)
    errors.extend(f"Local-only path not ignored: {name}" for name in probes if name not in ignored)
    tracked_raw = set(paths("ls-files", "-z", "--", *probes))
    errors.extend(f"Already tracked local-only file (ignore cannot untrack): {name}" for name in tracked_raw)
    matrix = (ROOT / "E2E_ACCEPTANCE_MATRIX_2026-10-11.md").read_text(encoding="utf-8")
    required = [str(i) for i in range(1, 19)] + [f"E{i}" for i in range(1, 7)] + [f"F{i}" for i in range(1, 4)]
    errors.extend(f"Missing matrix row: {row}" for row in required if f"| {row} |" not in matrix)
    totals = Counter(e["group"] for e in entries)
    return {
        "revision": "2026-10-11-f2-review-r1", "scope": "Proposed working-tree snapshot only; no staging/commit/push/PR/cleanup/provider calls.",
        "branch": git("branch", "--show-current").decode().strip(),
        "base_commit": git("rev-parse", "HEAD").decode().strip(),
        "manifest_self": {"path": output, "included_in_proposal": True, "sha256": None, "reason": "Self hash and size intentionally omitted to avoid a recursive digest."},
        "summary": {"hashed_files": len(entries), "proposed_files_including_manifest": len(entries) + 1,
                    "hashed_bytes_excluding_manifest": sum(e["bytes"] for e in entries), "groups_excluding_manifest": dict(sorted(totals.items()))},
        "checks": {"errors": errors, "passed": not errors, "catalogue_r1_files_checked": len(frozen_entries),
                   "matrix_rows_present": len(required), "ignore_probes_checked": len(probes),
                   "preexisting_staged_paths": sorted(staged),
                   "privacy_scope": "Proposed JSON parsed; nonempty credential-key string fields checked, without .env access. Public JD contacts and synthetic fixtures are retained. This is not a claim of a universal secret/PII scan."},
        "historical_local_only_indexes": archives, "files": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    option = parser.add_mutually_exclusive_group(required=True)
    option.add_argument("--output")
    option.add_argument("--check")
    args = parser.parse_args()
    if args.check:
        errors = []
        current_checks = None
        checked_files = 0
        summary = None
        try:
            name = (ROOT / args.check).resolve().relative_to(ROOT).as_posix()
            saved = json.loads((ROOT / name).read_text(encoding="utf-8"))
            checks = saved.get("checks")
            valid_checks = (isinstance(checks, dict) and type(checks.get("passed")) is bool
                            and isinstance(checks.get("errors"), list)
                            and all(isinstance(e, str) for e in checks["errors"]))
            if not valid_checks:
                errors.append("Saved audit checks are missing or invalid.")
            elif not checks["passed"] or checks["errors"]:
                errors.append("Saved audit was not a clean pass; create a new revision after fixing its failures.")
                errors.extend(checks["errors"])
            if not isinstance(saved.get("files"), list):
                raise ValueError("Saved file inventory is missing or invalid.")
            errors.extend(verify_files(saved["files"]))
            checked_files = len(saved["files"])
            if saved.get("manifest_self", {}).get("path") != name:
                errors.append("Saved manifest identity differs from the checked path.")
            # Derive critical gates from the current repo, not editable saved checks/index names.
            # Recheck mode is read-only: it must not create missing evidence or indexes.
            current = audit(name, recheck=True)
            current_checks = current["checks"]
            errors.extend(current_checks["errors"])
            expected = {e["path"] for e in saved["files"]}
            actual = {e["path"] for e in current["files"]}
            if expected != actual:
                errors.append("Working-tree proposal paths changed; create a new scope revision.")
            summary = current["summary"]
        except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.SubprocessError) as exc:
            errors.append(f"Audit could not be revalidated: {type(exc).__name__}")
        print(json.dumps({"passed": not errors, "errors": errors, "checked_files": checked_files,
                          "current_audit_checks": current_checks, "summary": summary}, ensure_ascii=False, indent=2))
        return bool(errors)
    result = audit(args.output)
    write_new(args.output, result)
    print(json.dumps({"output": args.output, "summary": result["summary"], "checks": result["checks"]}, ensure_ascii=False, indent=2))
    return not result["checks"]["passed"]


if __name__ == "__main__":
    raise SystemExit(main())
