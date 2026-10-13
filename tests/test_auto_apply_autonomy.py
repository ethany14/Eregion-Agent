"""Bounded continuation, durable plans, and interruptible recovery."""
from threading import Event
import time

from eregion.runtime.auto_apply.agent import AgentTools
from eregion.runtime.auto_apply.contracts import ChatRequest
from eregion.runtime.auto_apply.loop import ApplicationLoop
from eregion.runtime.auto_apply.repository import ApplyRepository
from eregion.runtime.auto_apply.resume_profile import extract_chat_profile, ResumeFacts
from test_auto_apply import FakeBrowser, database, request, wait


def test_transient_model_failure_recovers_without_user_continue(database):
    browser = FakeBrowser("")
    calls = []
    class Agent:
        def run(self, browser, state, **callbacks):
            calls.append(state)
            if len(calls) == 1: return {"reason":"model_error", "field_keys":[]}
            callbacks["autofill"]()
            return {"reason":"ready", "field_keys":[]}
    loop = ApplicationLoop(ApplyRepository(database.session_factory), browser_factory=lambda _: browser, agent_factory=Agent, retry_delays=(0, 0))
    try:
        state = wait(loop, loop.start(request(automation_mode="hybrid"))["run_id"])
        assert state["status"] == "awaiting_review" and len(calls) == 2
        assert "model_error" in calls[1]["recovery_note"]
        assert browser.submissions == 0
    finally: loop.close()


def test_progressing_chunk_continues_with_saved_plan(database):
    calls = []
    class Agent:
        def run(self, browser, state, **callbacks):
            calls.append(state)
            if len(calls) == 1:
                callbacks["autofill"]()
                callbacks["checkpoint"](task_plan=["Check completed fields"], approach="Verify browser values")
                return {"reason":"yielded", "field_keys":[]}
            assert state["task_plan"] == ["Check completed fields"]
            return {"reason":"ready", "field_keys":[]}
    loop = ApplicationLoop(ApplyRepository(database.session_factory), browser_factory=FakeBrowser, agent_factory=Agent, retry_delays=(0, 0))
    try:
        state = wait(loop, loop.start(request(automation_mode="hybrid"))["run_id"])
        assert state["status"] == "awaiting_review" and len(calls) == 2
        assert state["continuations"] == 1
    finally: loop.close()


def test_recovery_is_bounded_and_pause_cancels_scheduled_work(database):
    calls = []
    class Agent:
        def run(self, *args, **kwargs):
            calls.append(1)
            return {"reason":"model_error", "field_keys":[]}
    loop = ApplicationLoop(ApplyRepository(database.session_factory), browser_factory=FakeBrowser, agent_factory=Agent, retry_delays=(0, 0))
    try:
        state = wait(loop, loop.start(request(automation_mode="hybrid"))["run_id"])
        assert state["status"] == "needs_input" and len(calls) == 3
        loop.retry_delays = (10, 10)
        loop.chat(state["run_id"], ChatRequest(text="continue", message_id="retry-one-more"))
        deadline = time.monotonic() + 3
        while not loop.scheduled and time.monotonic() < deadline: time.sleep(.01)
        assert loop.scheduled
        paused = loop.chat(state["run_id"], ChatRequest(text="pause", message_id="pause-recovery"))
        assert paused["pause_requested"] and not loop.scheduled
        assert len(calls) == 4
    finally: loop.close()


def test_restart_resumes_running_hybrid_but_never_submitting(database):
    repo = ApplyRepository(database.session_factory)
    state, _ = repo.create(request(automation_mode="hybrid"))
    repo.save(state, status="running", task_plan=["Finish form"])
    submitted, _ = repo.create(request(url="https://jobs.lever.co/example/another", idempotency_key="other-application", automation_mode="hybrid"))
    repo.save(submitted, status="submitting")
    class Agent:
        def run(self, browser, state, **callbacks):
            assert state["task_plan"] == ["Finish form"]
            callbacks["autofill"]()
            return {"reason":"ready", "field_keys":[]}
    loop = ApplicationLoop(repo, browser_factory=FakeBrowser, agent_factory=Agent)
    try:
        assert wait(loop, state["run_id"])["status"] == "awaiting_review"
        assert repo.get(submitted["run_id"])["status"] == "submission_unknown"
        assert submitted["run_id"] not in loop.browsers
    finally: loop.close()


def test_user_resume_gets_fresh_budget_without_erasing_totals(database):
    class Agent:
        def run(self, browser, state, **callbacks):
            assert callbacks["reserve"]("model")
            callbacks["autofill"]()
            return {"reason":"ready", "field_keys":[]}
    repo = ApplyRepository(database.session_factory)
    state, _ = repo.create(request(automation_mode="hybrid"))
    state = repo.save(state, status="needs_input", agent_calls=40)
    loop = ApplicationLoop(repo, browser_factory=FakeBrowser, agent_factory=Agent)
    try:
        loop.chat(state["run_id"], ChatRequest(text="continue", message_id="resume-budget-1"))
        result = wait(loop, state["run_id"])
        assert result["status"] == "awaiting_review" and result["agent_calls"] == 41
    finally: loop.close()


def test_plan_and_failed_action_are_available_to_next_decision():
    state = {"profile": request().profile.model_dump(), "answers":{}, "actions":[{"tool":"inspect_field", "outcome":"failed"}],
        "last_tool_result":{"tool":"inspect_field", "result":{"error":"No options"}}}
    saved = []
    session = AgentTools(FakeBrowser(""), state, autofill=lambda: {}, active=lambda: True, checkpoint=lambda **change:saved.append(change))
    session.execute("update_plan", {"steps":["Search by school name"], "approach":"Open then search the dropdown"})
    observation = session.observe()
    assert observation["task_plan"] == ["Search by school name"]
    assert observation["last_tool_result"]["result"]["error"] == "No options"
    assert saved[0]["task_plan"] == observation["task_plan"]


def test_preparation_chat_never_accepts_invented_profile_facts():
    class Model:
        def with_structured_output(self, schema): return self
        def invoke(self, messages): return ResumeFacts(facts=[
            {"field":"city","value":"Ithaca","quote":"I live in Ithaca"},
            {"field":"country","value":"United States","quote":"United States"}])
    assert extract_chat_profile("I live in Ithaca", model_factory=Model)["profile"] == {"city":"Ithaca"}
    assert extract_chat_profile("not an email", field="email")["profile"] == {}
    assert extract_chat_profile("Demo", field="first_name")["profile"] == {"first_name":"Demo"}


def test_api_startup_recovers_work_without_any_browser_request(database, monkeypatch):
    from fastapi.testclient import TestClient
    from types import SimpleNamespace
    from eregion.api.main import create_app
    repo = ApplyRepository(database.session_factory)
    state, _ = repo.create(request(automation_mode="hybrid"))
    repo.save(state, status="running")
    class Agent:
        def run(self, browser, state, **callbacks):
            callbacks["autofill"]()
            return {"reason":"ready", "field_keys":[]}
    monkeypatch.setattr("eregion.api.auto_apply_routes.ApplicationLoop", lambda repo: ApplicationLoop(repo, browser_factory=FakeBrowser, agent_factory=Agent))
    app = create_app(run_service=object(), session_runtime=SimpleNamespace(database=database))
    with TestClient(app):
        assert wait(app.state.auto_apply, state["run_id"])["status"] == "awaiting_review"
