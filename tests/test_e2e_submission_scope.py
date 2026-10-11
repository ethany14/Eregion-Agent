"""Scope-auditor contracts only. Synthetic local files; no product/providers."""
import json

import pytest

from scripts import audit_e2e_submission_scope as scope


@pytest.fixture
def saved_scope(tmp_path, monkeypatch):
    monkeypatch.setattr(scope, "ROOT", tmp_path)
    raw_entries = []
    for directory in scope.HISTORICAL:
        root = tmp_path / directory
        root.mkdir(parents=True)
        raw = root / "failure.log"
        raw.write_text("synthetic historical failure", encoding="utf-8")
        entry = scope.describe(raw.relative_to(tmp_path).as_posix())
        raw_entries.append(entry)
        (root / "publication-index.json").write_text(json.dumps({
            "local_originals": [entry], "original_count": 1, "original_bytes": entry["bytes"]
        }), encoding="utf-8")
    frozen = []
    for i in range(33):
        name = f"tmp/frozen-{i}.txt"
        (tmp_path / name).parent.mkdir(exist_ok=True)
        (tmp_path / name).write_text(f"synthetic frozen {i}", encoding="utf-8")
        frozen.append(scope.describe(name))
    catalogue = tmp_path / scope.CATALOGUE
    catalogue.parent.mkdir(parents=True)
    catalogue.write_text(json.dumps({"artifacts": frozen[:25], "implementation_files": frozen[25:]}), encoding="utf-8")
    matrix = tmp_path / "E2E_ACCEPTANCE_MATRIX_2026-10-11.md"
    rows = [str(i) for i in range(1, 19)] + [f"E{i}" for i in range(1, 7)] + [f"F{i}" for i in range(1, 4)]
    matrix.write_text("\n".join(f"| {row} | pending |" for row in rows), encoding="utf-8")
    ignore = tmp_path / ".gitignore"
    ignore.write_text("synthetic ignore rules", encoding="utf-8")
    manifest_name = "docs/diagnostics/remaining-2026-10-11/scope.json"
    current = {scope.CATALOGUE, matrix.name, ignore.name}
    current.update(f"{directory}/publication-index.json" for directory in scope.HISTORICAL)
    tracked_raw = set()

    def git_paths(*args):
        if args[:2] == ("ls-files", "--modified"):
            return sorted(current)
        if args[:2] == ("ls-files", "--others"):
            return [manifest_name] if (tmp_path / manifest_name).exists() else []
        if args[:2] == ("diff", "--cached"):
            return []
        if args[:2] == ("ls-files", "-z"):
            return sorted(tracked_raw)
        raise AssertionError(args)

    monkeypatch.setattr(scope, "paths", git_paths)
    monkeypatch.setattr(scope, "ignored_paths", lambda names: set(names))
    monkeypatch.setattr(scope, "git", lambda *args: b"synthetic-branch\n" if args[0] == "branch" else b"synthetic-head\n")
    result = scope.audit(manifest_name)
    assert result["checks"]["passed"]
    scope.write_new(manifest_name, result)
    return tmp_path / manifest_name, current, tracked_raw, raw_entries


def check(monkeypatch, capsys, path):
    monkeypatch.setattr("sys.argv", ["scope-audit", "--check", str(path)])
    code = scope.main()
    output = json.loads(capsys.readouterr().out)
    return code, output


@pytest.mark.parametrize("checks", [
    {"passed": False, "errors": ["Credential field requires review: synthetic fixture only"]},
    None,
    {"passed": "true", "errors": []},
    {"passed": True, "errors": "not-a-list"},
    {"passed": True, "errors": ["unresolved failure"]},
])
def test_failed_missing_or_invalid_saved_checks_cannot_pass(saved_scope, monkeypatch, capsys, checks):
    path, *_ = saved_scope
    value = json.loads(path.read_text(encoding="utf-8"))
    if checks is None:
        value.pop("checks")
    else:
        value["checks"] = checks
    path.write_text(json.dumps(value), encoding="utf-8")
    code, output = check(monkeypatch, capsys, path)
    assert code != 0
    assert output["passed"] is False


def test_valid_pass_manifest_rechecks_current_audit(saved_scope, monkeypatch, capsys):
    path, *_ = saved_scope
    code, output = check(monkeypatch, capsys, path)
    assert code == 0 and output["passed"] is True
    assert output["current_audit_checks"]["catalogue_r1_files_checked"] == 33


@pytest.mark.parametrize("change", ["hash", "path"])
def test_changed_hash_or_inventory_fails(saved_scope, monkeypatch, capsys, change):
    path, current, *_ = saved_scope
    if change == "hash":
        (scope.ROOT / ".gitignore").write_text("changed rules", encoding="utf-8")
    else:
        extra = "E2E_NEW.md"
        (scope.ROOT / extra).write_text("new file", encoding="utf-8")
        current.add(extra)
    code, output = check(monkeypatch, capsys, path)
    assert code != 0 and output["passed"] is False


@pytest.mark.parametrize("change", ["ignore", "tracked_raw", "credential", "matrix"])
def test_editable_manifest_cannot_override_current_gates(saved_scope, monkeypatch, capsys, change):
    path, _, tracked_raw, raw_entries = saved_scope
    if change == "ignore":
        monkeypatch.setattr(scope, "ignored_paths", lambda names: set(names) - {".env"})
    elif change == "tracked_raw":
        tracked_raw.add(raw_entries[0]["path"])
    else:
        value = json.loads(path.read_text(encoding="utf-8"))
        target = scope.CATALOGUE if change == "credential" else "E2E_ACCEPTANCE_MATRIX_2026-10-11.md"
        if change == "credential":
            catalogue = json.loads((scope.ROOT / target).read_text(encoding="utf-8"))
            catalogue["password"] = "synthetic-credential-only"
            (scope.ROOT / target).write_text(json.dumps(catalogue), encoding="utf-8")
        else:
            (scope.ROOT / target).write_text("missing required rows", encoding="utf-8")
        # Re-signing file metadata cannot substitute for rerunning the audit gates.
        for entry in value["files"]:
            if entry["path"] == target:
                entry.update(scope.describe(target))
        path.write_text(json.dumps(value), encoding="utf-8")
    code, output = check(monkeypatch, capsys, path)
    assert code != 0 and output["passed"] is False
