"""Offline regression scenarios for model-led interpretation and recoverable work."""
from types import SimpleNamespace
import pytest

from agent_runtime.auto_apply.agent import AgentTools
from agent_runtime.auto_apply.browser import BrowserBlocked
from test_auto_apply import FakeBrowser, field, request
from test_auto_apply_agent import state
from test_session_coordinator import runtime, coordinator, ScriptedModel, response, user
from agent_runtime.sessions import SessionStatus, SessionOutcomeStatus
from agent_runtime.application_pack.types import ApplicationAnswer, GroundedBlock, EvidenceSnapshotItem
from agent_runtime.application_pack.verifier import ArtifactVerifier
from agent_runtime.interviewer.policy import validate_candidate
from agent_runtime.interviewer.types import InterviewAnswerAssessment
from agent_runtime.interviewer.errors import InterviewValidationError
from agent_runtime.memory.retrieval import MemoryRetriever
from agent_runtime.memory import MemoryQuery, MemorySensitivity
from test_memory_retrieval_context import memory, FakeReader
from test_auto_apply import database, wait
from session_paths import session_decision_path  # noqa: F401 (both decision paths)


@pytest.mark.parametrize("reply,quote", [
    ("ithaca ny 2. linkedin", "ithaca ny"),
    ("ithaca， NY、", "ithaca， NY"),
    ("ithaca newyork  ， linkedin", "ithaca newyork"),
    ("第一题纽约州的 Ithaca，另外我是从 LinkedIn 看到的", "纽约州的 Ithaca"),
])
def test_model_can_normalize_chat_without_fixed_response_grammar(reply, quote):
    browser = FakeBrowser("")
    city = field("city", "combobox", "Location (City)")
    city["options"] = [{"label": f"Ithaca, {region}, United States", "value": region}
                       for region in ("New York", "Michigan", "Nebraska")]
    browser.fields = [city, field("referral")]
    data = state(answers={}, messages=[{"id":"u", "role":"user", "text":reply}])
    saved = []
    session = AgentTools(browser, data, autofill=lambda: {}, active=lambda: True,
        bind_answers=lambda answers, revision: saved.extend(answers))
    snapshot = session.observe()
    session.execute("record_answers", {"observation_id": snapshot["observation_id"], "answers":[
        {"field_key":"city", "message_id":"u", "quote":quote,
         "value":"Ithaca, New York, United States"}]})
    assert data["answers"]["city"] == "Ithaca, New York, United States"
    assert saved[0]["quote"] == quote


def test_model_answer_batch_is_atomic_and_does_not_borrow_consent():
    browser = FakeBrowser("")
    browser.fields = [field("sponsor", "select"), field("consent", "checkbox")]
    data = state(answers={}, messages=[{"id":"q", "role":"assistant", "text":"Sponsorship?",
        "question_keys":["sponsor"]}, {"id":"u", "role":"user", "text":"yes"}])
    saved = []
    session = AgentTools(browser, data, autofill=lambda: {}, active=lambda: True,
        bind_answers=lambda answers, revision: saved.extend(answers))
    snapshot = session.observe()
    with pytest.raises(BrowserBlocked):
        session.execute("record_answers", {"observation_id":snapshot["observation_id"],
            "answers":[{"field_key":key,"message_id":"u","quote":"yes","value":"Yes"}
                       for key in ("sponsor", "consent")]})
    assert not saved and not data["answers"]


def test_chat_reaches_model_before_parser_and_stores_the_model_binding(database):
    from agent_runtime.auto_apply.agent import HybridApplicationAgent
    from agent_runtime.auto_apply.loop import ApplicationLoop
    from agent_runtime.auto_apply.repository import ApplyRepository
    from agent_runtime.auto_apply.contracts import ChatRequest
    from test_auto_apply_agent import ScriptModel
    browser = FakeBrowser("")
    browser.fields = [field("city", "combobox", "Location (City)"), field("referral")]
    browser.fields[0]["options"] = [{"label":"Ithaca, New York, United States", "value":"NY"},
                                   {"label":"Ithaca, Michigan, United States", "value":"MI"}]
    models = []
    def record(snapshot):
        message = next(m for m in snapshot["user_messages"] if m["id"] == "free-reply")
        assert not message.get("bound_answers")
        return {"observation_id":snapshot["observation_id"], "answers":[
            {"field_key":"city", "message_id":"free-reply", "quote":"纽约州的 Ithaca",
             "value":"Ithaca, New York, United States"},
            {"field_key":"referral", "message_id":"free-reply", "quote":"LinkedIn", "value":"LinkedIn"}]}
    def factory():
        steps = ([("request_input", {"field_keys":["city","referral"]})] if not models else
                 [("record_answers", record), ("autofill", {}), ("ready_for_review", {})])
        model = ScriptModel(steps)
        models.append(model)
        return HybridApplicationAgent(model_factory=lambda:model)
    loop = ApplicationLoop(ApplyRepository(database.session_factory), browser_factory=lambda _:browser,
                           agent_factory=factory)
    try:
        run = loop.start(request(automation_mode="hybrid"))
        wait(loop, run["run_id"])
        loop.chat(run["run_id"], ChatRequest(message_id="free-reply",
            text="第一题纽约州的 Ithaca，另外我是从 LinkedIn 看到的"))
        result = wait(loop, run["run_id"])
        assert result["status"] == "awaiting_review"
        assert result["answers"]["city"] == "Ithaca, New York, United States"
        assert result["answer_sources"]["city"]["interpretation"] == "model"
        assert result["answer_sources"]["city"]["quote"] == "纽约州的 Ithaca"
        assert browser.submissions == 0
    finally:
        loop.close()


@pytest.mark.parametrize("failure", [TimeoutError("private"), ConnectionError("private")])
def test_transient_model_failure_can_resume_the_same_session(runtime, failure):
    _, sessions, calls = runtime
    model = ScriptedModel([failure, response("a", "Continued")])
    service = coordinator(sessions, calls, model)
    session = service.create_session()
    outcome = service.submit_user_message(session.session_id, user(), expected_version=session.version)
    assert outcome.state.status == SessionStatus.AWAITING_USER
    assert "private" not in str(outcome)
    resumed = service.submit_user_message(session.session_id, user("u2", "continue"),
        expected_version=outcome.state.version)
    assert resumed.status == SessionOutcomeStatus.RESPONSE_READY
    assert resumed.final_text == "Continued"
    assert any(m.content == "question" for m in model.calls[-1][0])


def answer(text, evidence_id="e"):
    return ApplicationAnswer(question="Your experience?", answer_blocks=[GroundedBlock(
        block_id="b", text=text, block_type="factual", evidence_ids=[evidence_id],
        evidence_version_ids=["v"])], character_count=len(text), word_count=len(text.split()))


def test_semantic_verifier_allows_paraphrase_but_requires_real_citations():
    evidence = EvidenceSnapshotItem(evidence_id="e", evidence_version_id="v", content_hash="h",
        source_type="resume", selection_reason="application_link", associated_requirement_ids=[],
        claim_text="Developed APIs using Python.")
    called = []
    def judge(batch):
        called.extend(batch)
        return {"b"} if batch[0]["claim"] == "Built APIs in Python." else set()
    verifier = ArtifactVerifier(judge)
    assert verifier.verify(answer("Built APIs in Python.").model_dump(), "application_answer", [evidence]).passed
    assert called[0]["evidence"][0]["claim"] == evidence.claim_text
    assert not verifier.verify(answer("Led 50 engineers.").model_dump(), "application_answer", [evidence]).passed
    called.clear()
    assert not verifier.verify(answer("Built APIs in Python.", "invented").model_dump(), "application_answer", [evidence]).passed
    assert not called


def test_interview_paraphrase_preserves_source_and_rejects_fabricated_quote():
    assessment = InterviewAnswerAssessment(outcome="sufficient_for_candidate",
        proposed_claim="Built APIs in Python.", exact_supporting_quotes=["Developed APIs using Python."])
    claim, quote = validate_candidate("Developed APIs using Python.", assessment,
        semantic_judge=lambda batch: {"answer"})
    assert claim != quote and quote == "Developed APIs using Python."
    with pytest.raises(InterviewValidationError):
        validate_candidate("I have no experience.", assessment, semantic_judge=lambda batch: {"answer"})


def test_multilingual_retrieval_filters_private_and_other_owner_before_model():
    remote = memory("remote", key="job.mode", text="Prefer remote roles")
    items = [remote, memory("foreign", owner="someone-else"),
             memory("sensitive", sensitivity=MemorySensitivity.SENSITIVE)]
    seen = []
    def ranker(query, candidates):
        seen.extend(candidates)
        return {"remote"}
    result = MemoryRetriever(FakeReader(items), semantic_ranker=ranker).retrieve(
        MemoryQuery(owner_id="owner-a", text="我想找可以在家工作的岗位"))
    assert [m.memory_id for m in seen] == ["remote"]
    assert [m.memory.memory_id for m in result.items] == ["remote"]


def test_semantic_retrieval_outage_retains_lexical_fallback():
    def unavailable(*args): raise TimeoutError()
    result = MemoryRetriever(FakeReader([memory("python")]), semantic_ranker=unavailable).retrieve(
        MemoryQuery(owner_id="owner-a", text="Python services"))
    assert [m.memory.memory_id for m in result.items] == ["python"]
