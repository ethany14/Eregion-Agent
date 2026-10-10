"""Resume, aliases, durable memory and conversation steering without external calls."""
import base64
import json
from io import BytesIO
from threading import Event

import pytest
from langchain_core.messages import AIMessage

from agent_runtime.auto_apply.agent import AgentTools, HybridApplicationAgent
from agent_runtime.auto_apply.contracts import ChatRequest, ContinueApplication, ResumeProfileRequest
from agent_runtime.auto_apply.loop import ApplicationLoop
from agent_runtime.auto_apply.matching import resolve_option, question_identity
from agent_runtime.auto_apply.repository import ApplyRepository
from agent_runtime.auto_apply.resume_profile import ResumeFacts, extract_profile
from test_auto_apply import FakeBrowser, database, field, request, wait
from test_auto_apply_agent import ScriptModel


def choices(*labels):
    return [{"label": label, "value": str(index)} for index, label in enumerate(labels)]


@pytest.mark.parametrize("label,answer,option", [
    ("Country*", "US", "United States"), ("Country*", "USA", "United States +1"),
    ("Country", "UK", "United Kingdom"), ("Country", "中国", "China"),
    ("School", "MIT", "Massachusetts Institute of Technology"),
    ("School", "UC Berkeley", "University of California, Berkeley"),
    ("School", "Stanford", "Stanford University"), ("School", "Univ. of Michigan", "University of Michigan"),
    ("School", "Penn State", "Pennsylvania State University"),
    ("Consent", True, "I agree"), ("Consent", False, "No"),
    ("Do you need sponsorship?", "不需要", "No"),
    ("Degree", "Bachelor of Science", "Bachelor's Degree"),
    ("Degree", "MS", "Master's Degree"),
    ("Degree", "PhD", "Doctor of Philosophy (Ph.D.)"),
    ("Location (City)", "New York", "New York, New York, United States"),
    ("Location (City)", "Ithaca, New York", "Ithaca, New York, United States"),
    ("Location (City)", "ithaca newyork", "Ithaca, New York, United States"),
    ("Location (City)", "Ithaca New York", "Ithaca, New York, United States"),
    ("Location (City)", "Ithaca，New York", "Ithaca, New York, United States"),
    ("Location (City)", "Ithaca NY", "Ithaca, New York, United States"),
    ("Location (City)", "Ithaca， NY、", "Ithaca, New York, United States"),
    ("Location (City)", "Ithaca MI", "Ithaca, Michigan, United States"),
    ("Location (City)", "Los Angeles CA", "Los Angeles, California, United States"),
])
def test_option_aliases_are_field_aware(label, answer, option):
    assert resolve_option(label, answer, choices(option))["label"] == option


def test_ambiguous_schools_and_different_meanings_are_not_equivalent():
    assert resolve_option("School", "USC", choices("University of Southern California", "University of South Carolina")) is None
    assert resolve_option("School", "CMU", choices("Carnegie Mellon University", "Central Michigan University")) is None
    assert resolve_option("School", "University of California Berkeley", choices("University of California Los Angeles")) is None
    assert resolve_option("Work authorization", "US", choices("United States")) is None
    assert resolve_option("Consent", "No", choices("Yes")) is None
    assert resolve_option("Degree", "Master of Science", choices("Master of Business Administration (M.B.A.)")) is None
    assert resolve_option("Location (City)", "Springfield", choices("Springfield, Illinois, United States", "Springfield, Missouri, United States")) is None
    assert resolve_option("Location (City)", "Ithaca, New York", choices("Ithaca, Michigan, United States")) is None
    assert resolve_option("Location (City)", "ithaca newyork", choices("Ithaca, Michigan, United States")) is None
    assert resolve_option("Location (City)", "ithaca new", choices("Ithaca, New York, United States")) is None
    assert resolve_option("Location (City)", "ithaca", choices("Ithaca Falls, New York, United States")) is None
    assert resolve_option("Location (City)", "ithaca newyork", choices(
        "Ithaca, New York, United States", "Ithaca, New York, Another Country")) is None
    assert resolve_option("Location (City)", "Ithaca NY", choices("Ithaca, Michigan, United States")) is None
    assert resolve_option("Location (City)", "Ithaca NY", choices("Ithaca, New York, Another Country")) is None


def test_question_identity_preserves_authorization_country_and_time():
    assert question_identity("Do you require sponsorship?") == question_identity("Will you need sponsorship?")
    assert question_identity("Are you authorized to work in the US?") == question_identity("Are you eligible to work in the United States?")
    assert question_identity("Are you authorized to work in Canada?") != question_identity("Are you authorized to work in US?")
    assert question_identity("Do you require sponsorship now or in the future?") != question_identity("Do you require sponsorship?")
    assert question_identity("Are you not authorized to work in the US?") != question_identity("Are you authorized to work in US?")
    assert question_identity("Are you authorized to work in US for 20 hours?") != question_identity("Are you authorized to work in US?")


def test_memory_reuses_confirmed_answer_across_jobs_and_can_forget(database):
    repo = ApplyRepository(database.session_factory)
    first, _ = repo.create(request())
    old = field("old", "select", "Do you require sponsorship?")
    old["options"] = [{"label": "No", "value": "employer-17"}]
    first = repo.save(first, fields=[old], answers={"old": "employer-17"}, status="cancelled")
    repo.remember(first, first["answers"])
    second, _ = repo.create(request(url="https://jobs.lever.co/next/role", idempotency_key="second-application"))
    new = field("new", "select", "Will you need sponsorship?")
    answers, sources = ApplyRepository(database.session_factory).recalled_answers(second, [new])
    assert answers == {"new": "No"}
    memory_id = sources["new"]["memory_id"]
    other = {**second, "profile": {**second["profile"], "email": "other@example.com"}}
    assert repo.recalled_answers(other, [new]) == ({}, {})
    repo.forget(second["profile"], memory_id)
    assert repo.recalled_answers(second, [new]) == ({}, {})


def test_consent_first_answer_then_reuse_and_opt_out(database):
    repo = ApplyRepository(database.session_factory)
    saved, _ = repo.create(request())
    question = field("consent", "checkbox", "I consent to processing my data for this application")
    assert repo.recalled_answers(saved, [question]) == ({}, {})
    saved = repo.save(saved, fields=[question], answers={"consent": True})
    repo.remember(saved, saved["answers"])
    next_state = {**saved, "answers": {}}
    next_field = field("new-consent", "checkbox", "I agree to processing my information for recruitment")
    assert repo.recalled_answers(next_state, [next_field])[0] == {"new-consent": True}
    marketing = field("marketing", "checkbox", "I consent to processing my data for future marketing")
    assert repo.recalled_answers(next_state, [marketing])[0] == {}
    assert repo.recalled_answers({**next_state, "reuse_answers": False}, [next_field])[0] == {}


def test_optional_consent_is_asked_once_and_negative_answer_reused(database):
    def browser_factory(url):
        browser = FakeBrowser(url)
        consent = field("optional", "checkbox", "I consent to processing my data for this application", required=False)
        consent["value"] = True  # The employer preselects consent; saved refusal wins.
        browser.fields.append(consent)
        return browser
    loop = ApplicationLoop(ApplyRepository(database.session_factory), browser_factory=browser_factory)
    try:
        run_id = loop.start(request())["run_id"]
        paused = wait(loop, run_id)
        assert paused["status"] == "needs_input" and paused["pending_fields"] == ["optional"]
        loop.continue_run(run_id, ContinueApplication(expected_version=paused["version"], answers={"optional": False}))
        assert wait(loop, run_id)["status"] == "awaiting_review"
        next_id = loop.start(request(url="https://jobs.lever.co/next/role", idempotency_key="remembered-consent-1"))["run_id"]
        ready = wait(loop, next_id)
        assert ready["status"] == "awaiting_review"
        assert ready["answers"]["optional"] is False
        assert next(f for f in ready["fields"] if f["key"] == "optional")["value"] is False
        assert ready["answer_sources"]["optional"]["type"] == "memory"
    finally:
        loop.close()


def test_prechecked_consent_still_allows_agent_to_ask_first():
    browser = FakeBrowser("")
    consent = field("consent", "checkbox", "I agree to this privacy notice", required=False)
    consent["value"] = True
    browser.fields.append(consent)
    saved = {"profile": request().profile.model_dump(), "answers": {}}
    session = AgentTools(browser, saved, autofill=lambda: {}, active=lambda: True)
    session.observe()
    assert session.execute("request_input", {"field_keys":["consent"]}) == {"field_keys":["consent"]}


def test_old_answers_backfill_once_and_forgetting_survives_restart(database):
    repo = ApplyRepository(database.session_factory)
    saved, _ = repo.create(request())
    saved = repo.save(saved, fields=[field("answer", label="Do you require sponsorship?")],
        answers={"answer": "No"}, memory_indexed=False, status="cancelled")
    repo.recover()
    memory = repo.memories(saved["profile"])[0]
    repo.forget(saved["profile"], memory["memory_id"])
    repo.recover()
    assert not repo.memories(saved["profile"])


def test_chat_correction_applies_to_completed_field_and_is_idempotent(database):
    browser = FakeBrowser("")
    loop = ApplicationLoop(ApplyRepository(database.session_factory), browser_factory=lambda _: browser)
    try:
        run_id = loop.start(request())["run_id"]
        assert wait(loop, run_id)["status"] == "awaiting_review"
        message = ChatRequest(text="Corrected", field_key="First name", message_id="name-correction-1")
        loop.chat(run_id, message)
        review = wait(loop, run_id)
        assert browser.fields[0]["value"] == "Corrected"
        assert review["answer_sources"]["First name"]["type"] == "chat"
        assert loop.chat(run_id, message)["version"] == review["version"]
        assert len([m for m in review["messages"] if m["role"] == "user"]) == 1
    finally:
        loop.close()


def test_chat_pause_stops_before_submission(database):
    browser = FakeBrowser("")
    entered, release = Event(), Event()
    browser.after_fill = lambda: (entered.set(), release.wait(4))
    loop = ApplicationLoop(ApplyRepository(database.session_factory), browser_factory=lambda _: browser)
    try:
        run_id = loop.start(request(auto_submit=True))["run_id"]
        assert entered.wait(4)
        paused = loop.chat(run_id, ChatRequest(text="pause", message_id="pause-message-1"))
        assert paused["pause_requested"] and paused["status"] == "needs_input"
        release.set()
    finally:
        release.set(); loop.close()
    assert browser.submissions == 0


def test_new_chat_invalidates_an_inflight_model_action():
    browser = FakeBrowser("")
    saved = {"profile": request().profile.model_dump(), "answers": {}, "chat_revision": 0}
    observed = []
    class Model:
        calls = 0
        def invoke(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                saved["chat_revision"] += 1
                return AIMessage(content="", tool_calls=[{"name":"autofill", "args":{}, "id":"stale"}])
            observed.append(messages[-1].content)
            return AIMessage(content="", tool_calls=[{"name":"ask_user", "args":{
                "text":"Which answer should I use now?", "field_keys":[]}, "id":"fresh"}])
    fills = []
    result = HybridApplicationAgent(model_factory=Model).run(browser, saved, autofill=lambda: fills.append(1),
        active=lambda: True, reserve=lambda kind: True, report=lambda *args: None, refresh=lambda: saved)
    assert fills == [1] and result["reason"] == "needs_input"  # only the initial host pass
    assert json.loads(observed[0])["chat_revision"] == 1


def test_general_chat_answer_is_literal_grounded_and_persisted():
    browser = FakeBrowser("", question=True)
    saved = {"profile": request().profile.model_dump(), "answers": {},
        "messages": [{"id":"message-1", "role":"user", "text":"For sponsorship, use No"}]}
    accepted = []
    session = AgentTools(browser, saved, autofill=lambda: {}, active=lambda: True,
        accept_answer=lambda *args: accepted.append(args))
    snapshot = session.observe()
    session.execute("use_chat_answer", {"observation_id":snapshot["observation_id"],
        "field_key":"Do you need sponsorship?", "message_id":"message-1", "answer":"No"})
    assert accepted == [("Do you need sponsorship?", "No", "message-1")]
    assert browser.fields[-1]["value"] == "No"


def test_agent_reads_general_feedback_and_answers_in_real_loop(database):
    from test_auto_apply_agent import args
    browser = FakeBrowser("", question=True)
    models = []
    def factory():
        if not models:
            model = ScriptModel([("autofill", {}), ("request_input", {"field_keys":["Do you need sponsorship?"]})])
        else:
            model = ScriptModel([("autofill", {}),
                ("say", {"text":"I will use your answer: no sponsorship required."}),
                ("use_chat_answer", args("Do you need sponsorship?", message_id="feedback-0001", answer="No")),
                ("ready_for_review", {})])
        models.append(model)
        return HybridApplicationAgent(model_factory=lambda: model)
    loop = ApplicationLoop(ApplyRepository(database.session_factory), browser_factory=lambda _: browser, agent_factory=factory)
    try:
        run_id = loop.start(request(automation_mode="hybrid"))["run_id"]
        assert wait(loop, run_id)["status"] == "needs_input"
        loop.chat(run_id, ChatRequest(text="For sponsorship, use No", message_id="feedback-0001"))
        review = wait(loop, run_id)
        assert review["status"] == "awaiting_review", review["message"]
        assert browser.fields[-1]["value"] == "No"
        assert any(m["text"].startswith("I will use") for m in review["messages"])
        # The model chose which field the reply answers, so it is reused on later
        # applications only after the user approves it at review.
        assert loop.repository.memories(review["profile"]) == []
        assert [a["key"] for a in review["pending_approvals"]] == ["Do you need sponsorship?"]
    finally:
        loop.close()


def resume_pdf():
    from reportlab.pdfgen.canvas import Canvas
    buffer = BytesIO(); canvas = Canvas(buffer)
    for index, line in enumerate(["Alex Demo", "alex@example.com", "Massachusetts Institute of Technology"]):
        canvas.drawString(40, 750 - index * 20, line)
    canvas.save()
    return base64.b64encode(buffer.getvalue()).decode()


def test_resume_extraction_accepts_only_evidenced_facts():
    class Model:
        def with_structured_output(self, schema): return self
        def invoke(self, messages):
            return ResumeFacts(facts=[
                {"field":"first_name", "value":"Alex", "quote":"Alex Demo"},
                {"field":"last_name", "value":"Demo", "quote":"Alex Demo"},
                {"field":"school", "value":"Massachusetts Institute of Technology", "quote":"Massachusetts Institute of Technology"},
                {"field":"country", "value":"United States", "quote":"United States"}])
    encoded = resume_pdf()
    ResumeProfileRequest(resume_base64=encoded)
    extracted = extract_profile(encoded, model_factory=Model)
    assert extracted["profile"]["first_name"] == "Alex"
    assert extracted["profile"]["email"] == "alex@example.com"
    assert "country" not in extracted["profile"]
    assert extracted["evidence"]["last_name"] == "Alex Demo"


def test_resume_model_failure_keeps_detected_contacts():
    def unavailable(): raise RuntimeError("private provider error")
    extracted = extract_profile(resume_pdf(), model_factory=unavailable)
    assert extracted["profile"]["email"] == "alex@example.com"
    assert extracted["warning"] and "private" not in extracted["warning"]
