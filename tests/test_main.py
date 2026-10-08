import json
from unittest.mock import patch

from job_agent.domain import make_evidence_id
from runtime_helpers import CompleteFakeHandler, sqlite_url
from job_agent.schemas import TailoredResume
from main import analyze_files, main

FACT = "Built Python APIs."
FACT_ID = make_evidence_id(FACT)


def test_analyze_files_serializes_supported_claims(tmp_path):
    resume = tmp_path / "resume.txt"
    job = tmp_path / "job.txt"
    resume.write_text(FACT, encoding="utf-8")
    job.write_text("Requires Python", encoding="utf-8")
    with patch("main.JobAgentStepHandler", return_value=CompleteFakeHandler()):
        result = analyze_files(resume, job, thread_id="test-001",
                               database_url=sqlite_url(tmp_path / "runs.sqlite"))
    assert TailoredResume.model_validate(
        result["tailored_resume"]
    ).professional_summary[0].evidence_ids == [FACT_ID]
    assert result["skill_match"]["missing_preferred_requirements"] == []


def test_main_writes_json_output(tmp_path):
    resume = tmp_path / "resume.txt"
    job = tmp_path / "job.txt"
    output = tmp_path / "result.json"
    resume.write_text(FACT, encoding="utf-8")
    job.write_text("Requires Python", encoding="utf-8")
    with (
        patch("main.JobAgentStepHandler", return_value=CompleteFakeHandler()),
        patch("main._console_review", return_value={"approved": True, "feedback": None}),
    ):
        assert main([str(resume), str(job), "--thread-id", "test-002",
                     "--output", str(output), "--database-url", sqlite_url(tmp_path / "runs.sqlite")]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["verification"]["passed"] is True


def test_main_reports_missing_input(capsys, tmp_path):
    assert main([str(tmp_path / "missing.txt"), str(tmp_path / "job.txt"),
                 "--thread-id", "test-003"]) == 1
    assert "Resume file does not exist" in capsys.readouterr().err


def test_cli_pause_is_durable_and_duplicate_run_does_not_overwrite(tmp_path):
    import pytest
    from api.db import create_database
    from api.repositories.run_repository import RunRepository
    from custom_agent.errors import RunAlreadyExistsError
    resume, job = tmp_path / "resume.txt", tmp_path / "job.txt"
    resume.write_text(FACT, encoding="utf-8")
    job.write_text("Python", encoding="utf-8")
    url = sqlite_url(tmp_path / "runs.sqlite")
    analyze_files(resume, job, "durable", database_url=url, handler=CompleteFakeHandler())
    with pytest.raises(RunAlreadyExistsError):
        analyze_files(resume, job, "durable", database_url=url, handler=CompleteFakeHandler())
    database = create_database(url)
    try:
        record = RunRepository(database.session_factory).get("durable")
        assert record.status == "awaiting_review"
        assert record.backend == "custom"
    finally:
        database.close()
