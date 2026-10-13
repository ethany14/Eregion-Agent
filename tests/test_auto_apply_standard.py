"""Standard answers: set once, matched across wordings, reused without asking."""
import base64

import pytest
from fastapi.testclient import TestClient

from eregion.runtime.auto_apply.matching import question_identity
from eregion.runtime.auto_apply.repository import ApplyRepository
from test_auto_apply import database, field, request


@pytest.mark.parametrize("first,second", [
    ("Desired Salary (USD)*", "What are your salary expectations (USD)?"),
    ("ZIP/Postal Code", "Postal code"),
    ("How did you hear about this job?", "How did you find out about us?"),
    ("Are you at least 18 years of age?", "Are you over 18?"),
    ("Gender", "Gender identity (optional)"),
    ("When can you start?", "Earliest start date"),
])
def test_wordings_of_one_standard_question_share_an_identity(first, second):
    assert question_identity(first) == question_identity(second)
    assert question_identity(first).startswith("standard:")


@pytest.mark.parametrize("label", [
    "Is the posted salary range acceptable?", "Email address", "Are you the spouse of a protected veteran?",
    "Are you willing to relocate to Austin?", "First name",
])
def test_lookalike_questions_are_not_standard(label):
    assert not question_identity(label).startswith("standard:")


def test_setup_answers_are_reused_on_any_wording_and_can_be_cleared(database):
    repo = ApplyRepository(database.session_factory)
    profile = request().profile.model_dump()
    saved = {item["topic"]: item for item in repo.save_standard_answers(profile, {
        "salary": "$120,000", "referral_source": "LinkedIn", "us_sponsorship_now": "No", "pronouns": ""})}
    assert saved["salary"]["value"] == "$120,000" and saved["pronouns"]["value"] == ""

    state, _ = repo.create(request())
    fields = [field("pay", "text", "What are your salary expectations?"),
              field("hear", "text", "How did you find out about us?"),
              field("visa", "text", "Will you require sponsorship to work in the US?")]
    answers, sources = repo.recalled_answers(state, fields)
    assert answers == {"pay": "$120,000", "hear": "LinkedIn", "visa": "No"}
    assert all(source["type"] == "memory" for source in sources.values())

    # Saving again replaces the answer; a blank removes it so the question is asked again.
    repo.save_standard_answers(profile, {"salary": "$130,000", "referral_source": ""})
    answers, _ = repo.recalled_answers(state, fields)
    assert answers == {"pay": "$130,000", "visa": "No"}
    assert len([m for m in repo.memories(profile) if question_identity(m["question"]) == "standard:salary"]) == 1


def test_answer_from_an_application_updates_the_standard_answer(database):
    repo = ApplyRepository(database.session_factory)
    profile = request().profile.model_dump()
    repo.save_standard_answers(profile, {"referral_source": "LinkedIn"})
    state, _ = repo.create(request())
    state = repo.save(state, fields=[field("q", "text", "How did you hear about this job?")], answers={"q": "Indeed"})
    repo.remember(state, state["answers"])
    current = {item["topic"]: item["value"] for item in repo.standard_answers(profile)}
    assert current["referral_source"] == "Indeed"


def test_standard_answers_api(database):
    from types import SimpleNamespace
    from eregion.api.main import create_app
    app = create_app(run_service=object(), session_runtime=SimpleNamespace(database=database))
    with TestClient(app, base_url="http://localhost") as client:
        assert client.put("/api/auto-apply/standard-answers", json={"answers": {"salary": "$1"}}).status_code == 409
        repo = ApplyRepository(database.session_factory)
        repo.save_candidate({**request().profile.model_dump()})
        response = client.put("/api/auto-apply/standard-answers", json={"answers": {"salary": "$100k", "gender": "Decline"}})
        assert response.status_code == 200
        listed = {item["topic"]: item for item in client.get("/api/auto-apply/standard-answers").json()["answers"]}
        assert listed["salary"]["value"] == "$100k" and listed["over_18"]["kind"] == "yes_no"
        assert client.put("/api/auto-apply/standard-answers", json={"answers": {"unknown": "x"}}).status_code == 409
