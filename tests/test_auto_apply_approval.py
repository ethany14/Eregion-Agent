"""Approve-once answer memory, chat-answer grounding and local host protection."""
import json

import pytest

from eregion.runtime.auto_apply.agent import AgentTools, grounded
from eregion.runtime.auto_apply.browser import BrowserBlocked
from eregion.runtime.auto_apply.contracts import ContinueApplication
from eregion.runtime.auto_apply.loop import ApplicationLoop
from eregion.runtime.auto_apply.memory import compatible, pending_approvals, review_required
from eregion.runtime.auto_apply.models import ApplicationMemoryRow
from eregion.runtime.auto_apply.repository import ApplyRepository
from test_auto_apply import FakeBrowser, database, field, request, wait


def interpreted(state, key, value, label):
    """A reply the model mapped to a field: usable now, not yet approved for reuse."""
    return {**state, "fields": [*state.get("fields", []), field(key, "text", label)],
        "answers": {**state["answers"], key: value},
        "answer_sources": {**state.get("answer_sources", {}), key: {
            "type": "chat", "message_id": "m1", "interpretation": "model", "pending_approval": True}}}


def test_model_interpreted_answers_wait_for_approval(database):
    repo = ApplyRepository(database.session_factory)
    state, _ = repo.create(request())
    state = interpreted(state, "hear", "LinkedIn", "How did you hear about us?")
    assert [item["key"] for item in pending_approvals(state, state["fields"])] == ["hear"]
    assert review_required(state, state["fields"])
    # Nothing was written to durable memory by interpreting the reply.
    assert repo.memories(state["profile"]) == []


def test_confirmed_review_remembers_checked_answers_once(database):
    loop = ApplicationLoop(ApplyRepository(database.session_factory), browser_factory=FakeBrowser)
    try:
        state = wait(loop, loop.start(request())["run_id"])
        assert state["status"] == "awaiting_review"
        hear, salary = field("hear", "text", "How did you hear about us?"), field("pay", "text", "Desired salary")
        with loop.lock:
            state = loop.repository.save(interpreted(interpreted(state, "hear", "LinkedIn", hear["label"]),
                "pay", "$120k", salary["label"]), review_fields=[hear, salary])
        loop.continue_run(state["run_id"], ContinueApplication(expected_version=state["version"],
            confirm_submit=True, remember={"hear": True, "pay": False}))
        done = wait(loop, state["run_id"])
        assert done["status"] == "submitted"
        assert not pending_approvals(done, done["fields"])
        memories = {m["question"]: m for m in loop.repository.memories(done["profile"])}
        assert memories["How did you hear about us?"]["value"] == "LinkedIn"
        assert memories["How did you hear about us?"]["status"] == "approved"
        assert "Desired salary" not in memories

        # The next application reuses the approved answer without asking.
        second, _ = loop.repository.create(request(url="https://jobs.lever.co/other/role", idempotency_key="second-0001"))
        answers, sources = loop.repository.recalled_answers(second, [field("q", "text", "How did you hear about us?")])
        assert answers == {"q": "LinkedIn"} and sources["q"]["type"] == "memory"
    finally:
        loop.close()


def test_employer_scope_and_legacy_records(database):
    repo = ApplyRepository(database.session_factory)
    state, _ = repo.create(request(url="https://jobs.lever.co/acme/role"))
    salary = field("pay", "text", "Desired salary")
    saved = repo.save(state, fields=[salary], answers={"pay": "$120k"})
    repo.remember(saved, saved["answers"])
    [memory] = repo.memories(saved["profile"])
    assert memory["scope"] == "employer"  # Sensitive preferences default to this employer.
    same = {**saved, "url": "https://jobs.lever.co/acme/other"}
    other = {**saved, "url": "https://jobs.lever.co/globex/role"}
    assert compatible(memory, salary, same) and not compatible(memory, salary, other)
    repo.update_memory(saved["profile"], memory["memory_id"], scope="global")
    assert compatible(repo.memories(saved["profile"])[0], salary, other)

    # Answers remembered before approval tracking stay approved and global.
    with database.session_factory.begin() as session:
        row = session.get(ApplicationMemoryRow, memory["memory_id"])
        record = json.loads(row.record_json)
        for key in ("status", "scope", "approved_at"):
            record.pop(key)
        row.record_json = json.dumps(record)
    [legacy] = repo.memories(saved["profile"])
    assert legacy["status"] == "approved" and legacy["scope"] == "global"


def test_pending_memory_is_never_reused():
    memory = {"source": "user_answer", "status": "pending", "question": "How did you hear about us?",
        "identity": "x", "value": "LinkedIn", "scope": "global"}
    state = {"profile": {}, "url": "https://jobs.lever.co/acme/role"}
    assert not compatible(memory, field("q", "text", "How did you hear about us?"), state)


@pytest.mark.parametrize("quote,value,ok", [
    ("I heard about it on LinkedIn", "LinkedIn", True),
    ("Yes", "Yes", True),
    ("I don't need sponsorship", "No", False),
    ("I don't need sponsorship", "Yes", False),
    ("I", "US citizen", False),
    ("I heard about it on LinkedIn", "Indeed", False),
    ("a", "anything", False),
])
def test_recorded_answer_must_match_its_quote(quote, value, ok):
    assert grounded(field("q", "text", "Question"), quote, value, []) is ok


def test_recorded_answer_can_name_an_equivalent_option():
    country = {**field("c", "select", "Country"), "options": [{"label": "United States", "value": "US"}]}
    assert grounded(country, "USA", "United States", country["options"])


@pytest.mark.parametrize("label,reference", [
    ("Company name", "profile:first_name"), ("Reference email", "profile:email"),
    ("Tell us about yourself", "profile:phone"), ("Emergency contact phone", "profile:phone"),
])
def test_profile_facts_do_not_fill_other_peoples_details(label, reference):
    tools = AgentTools(None, {"profile": {"first_name": "Test", "email": "t@example.com", "phone": "555"},
        "answers": {}}, autofill=None, active=lambda: True)
    with pytest.raises(BrowserBlocked):
        tools.source(field("x", "text", label), reference)


def test_profile_facts_still_fill_the_candidates_own_contact_fields():
    tools = AgentTools(None, {"profile": {"first_name": "Test", "email": "t@example.com", "phone": "555"},
        "answers": {}}, autofill=None, active=lambda: True)
    assert tools.source(field("x", "text", "Preferred first name"), "profile:first_name") == "Test"
    assert tools.source(field("x", "email", "E-mail address"), "profile:email") == "t@example.com"
    assert tools.source(field("x", "tel", "Mobile phone"), "profile:phone") == "555"


def test_untrusted_host_is_rejected():
    from fastapi.testclient import TestClient
    from eregion.api.main import create_app
    client = TestClient(create_app(session_runtime_factory=lambda: None))
    assert client.get("/health", headers={"host": "attacker.example"}).status_code == 400
    assert client.get("/health", headers={"host": "127.0.0.1:8000"}).status_code != 400
