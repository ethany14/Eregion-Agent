from pathlib import Path


def test_ci_runs_python_and_documented_browser_tests_without_live_evals():
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "python -m pytest -q" in workflow
    assert 'node --test "tests/*.mjs"' in workflow
    assert 'node --test "tests/*.mjs"' in readme
    assert "evals.run_" not in workflow
