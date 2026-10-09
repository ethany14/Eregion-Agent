"""Hybrid decisions use a scripted tool model; no live provider or candidate data."""
import json
from threading import Event

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from agent_runtime.auto_apply.agent import AgentTools, HybridApplicationAgent
from agent_runtime.auto_apply.autofill import autofill
from agent_runtime.auto_apply.browser import BrowserBlocked
from agent_runtime.auto_apply.contracts import ContinueApplication
from agent_runtime.auto_apply.loop import ApplicationLoop
from agent_runtime.auto_apply.repository import ApplyRepository
from test_auto_apply import FakeBrowser, database, field, request, wait


class ScriptModel:
    def __init__(self, steps):
        self.steps = iter(steps)
        self.calls = []

    def invoke(self, messages, tools):
        snapshot = json.loads(next(m.content for m in reversed(messages)
            if isinstance(m, HumanMessage) and isinstance(m.content, str)))
        name, arguments = next(self.steps)
        if callable(arguments):
            arguments = arguments(snapshot)
        self.calls.append(name)
        return AIMessage(content="", tool_calls=[{"id": str(len(self.calls)), "name": name, "args": arguments}])


def args(key, **extra):
    return lambda snapshot: {"observation_id": snapshot["observation_id"], "field_key": key, **extra}


class RepairBrowser(FakeBrowser):
    def __init__(self):
        super().__init__("")
        self.fields = [field("First name"), field("Country", "combobox")]
        self.actions = []

    def fill(self, current, value):
        self.actions.append(("bulk", current["key"]))
        raise BrowserBlocked("This control needs individual browser actions.")

    def type_field(self, key, value):
        self.actions.append(("type", key))
        self.fields[0]["value"] = value

    def inspect_options(self, key):
        self.fields[1]["options"] = [{"label": "Canada", "value": "CA"}, {"label": "United States", "value": "US"}]
        return self.fields[1]["options"]

    def choose_option(self, key, label):
        self.actions.append(("choose", key))
        self.fields[1]["value"] = label


def state(**changes):
    return {"profile": request().profile.model_dump(), "answers": {"Country": "CA"}, **changes}


def test_model_calls_autofill_then_repairs_text_and_dropdown():
    browser, saved = RepairBrowser(), state()
    model = ScriptModel([
        ("autofill", {}),
        ("type_from_source", args("First name", source_ref="profile:first_name")),
        ("inspect_field", args("Country")),
        ("choose_option", args("Country", source_ref="answer:Country", option_label="Canada")),
        ("ready_for_review", {}),
    ])
    reservations, reports = [], []
    result = HybridApplicationAgent(model_factory=lambda: model).run(browser, saved,
        autofill=lambda: autofill(browser, saved, lambda: b""), active=lambda: True,
        reserve=lambda kind: reservations.append(kind) or True,
        report=lambda *values: reports.append(values))
    assert result["reason"] == "ready"
    assert [f["value"] for f in browser.observe()] == ["Test", "Canada"]
    assert model.calls == ["autofill", "type_from_source", "inspect_field", "choose_option", "ready_for_review"]
    assert reservations == ["model", "tool"] * 5
    assert len(reports) == 5


def test_compacted_tool_history_keeps_the_user_turn_required_by_provider():
    class ProtocolModel(ScriptModel):
        def invoke(self, messages, tools):
            for index, message in enumerate(messages):
                if isinstance(message, AIMessage) and message.tool_calls:
                    assert index > 0 and messages[index - 1].type in {"human", "tool"}
            return super().invoke(messages, tools)
    model = ProtocolModel([("autofill", {}), ("observe", {}), ("request_input", {"field_keys":["Country"]})])
    result = HybridApplicationAgent(model_factory=lambda: model).run(RepairBrowser(), state(),
        autofill=lambda: {}, active=lambda: True, reserve=lambda kind: True, report=lambda *args: None)
    assert result["reason"] == "needs_input"
    assert model.calls == ["autofill", "observe", "request_input"]


def test_provider_timeout_is_reported_without_leaking_error_body():
    class OpenAITimeoutError(Exception):
        pass
    class TimeoutModel:
        def invoke(self, messages, tools):
            raise OpenAITimeoutError("Private provider response must not reach chat")
    checkpoints = []
    result = HybridApplicationAgent(model_factory=TimeoutModel).run(RepairBrowser(), state(),
        autofill=lambda: {}, active=lambda: True, reserve=lambda kind: True,
        report=lambda *args: None, checkpoint=lambda **changes: checkpoints.append(changes))
    assert result["reason"] == "model_timeout"
    assert checkpoints == [{"last_tool_result": {"tool": "model", "result": {"error": "OpenAITimeoutError", "status": None}}}]
    assert "Private" not in str(checkpoints)


@pytest.mark.parametrize("name,extra", [
    ("choose_option", {"source_ref": "answer:Country", "option_label": "United States"}),
    ("choose_option", {"source_ref": "profile:first_name", "option_label": "Canada"}),
    ("press_key", {"key": "ArrowDown"}),
    ("press_key", {"key": "Tab"}),
    ("view_field", {}),
])
def test_browser_tools_do_not_invent_choice_answers_or_enable_images(name, extra):
    session = AgentTools(RepairBrowser(), state(), autofill=lambda: {}, active=lambda: True)
    session.execute("autofill", {})
    snapshot = session.observe()
    target = {"observation_id": snapshot["observation_id"], "field_key": "Country"}
    session.execute("inspect_field", target)
    with pytest.raises(BrowserBlocked):
        session.execute(name, {**target, **extra})


def test_stale_observation_and_unknown_tools_are_rejected():
    session = AgentTools(RepairBrowser(), state(), autofill=lambda: {}, active=lambda: True)
    session.execute("autofill", {})
    old = session.observe()
    session.observe()
    with pytest.raises(BrowserBlocked, match="Stale"):
        session.execute("inspect_field", {"observation_id": old["observation_id"], "field_key": "Country"})
    for name in ("submit", "evaluate", "navigate", "shell"):
        with pytest.raises(BrowserBlocked, match="Unknown"):
            session.execute(name, {})


def test_agent_cannot_request_completed_contact_details_again():
    browser = RepairBrowser()
    browser.fields[0]["value"] = "Test"
    session = AgentTools(browser, state(), autofill=lambda: {}, active=lambda: True)
    session.observe()
    with pytest.raises(BrowserBlocked, match="completed"):
        session.execute("request_input", {"field_keys": ["First name"]})


def test_images_are_only_sent_after_enabled_field_inspection():
    browser = RepairBrowser()
    browser.screenshot_field = lambda key: b"fixture-png"
    model = ScriptModel([("autofill", {}), ("view_field", args("First name")), ("request_input", {"field_keys": ["First name"]})])
    original = model.invoke
    image_messages = []
    def invoke(messages, tools):
        image_messages.extend(m.content for m in messages if isinstance(m, HumanMessage) and isinstance(m.content, list))
        return original(messages, tools)
    model.invoke = invoke
    result = HybridApplicationAgent(model_factory=lambda: model).run(browser, state(visual_fallback=True),
        autofill=lambda: {}, active=lambda: True, reserve=lambda kind: True, report=lambda *args: None)
    assert result["reason"] == "needs_input"
    assert len(image_messages) == 1
    assert image_messages[0][1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_disabling_visual_backup_removes_images_from_retained_model_history():
    browser=RepairBrowser();browser.screenshot_field=lambda key:b'fixture-png'
    saved=state(visual_fallback=True)
    class DisableModel(ScriptModel):
        def invoke(self,messages,tools):
            images=[m for m in messages if isinstance(m,HumanMessage) and isinstance(m.content,list)]
            if len(self.calls)==1:
                assert images
                saved['visual_fallback']=False
            if len(self.calls)==2:
                assert not images
                assert not any(t['function']['name'].startswith('computer_') or t['function']['name']=='view_browser' for t in tools)
            return super().invoke(messages,tools)
    model=DisableModel([('view_field',args('First name')),('say',{'text':'Continuing'}),('request_input',{'field_keys':['First name']})])
    result=HybridApplicationAgent(model_factory=lambda:model).run(browser,saved,
        autofill=lambda:{},active=lambda:True,reserve=lambda kind:True,report=lambda *values:None)
    assert result['reason']=='needs_input'


def test_agent_stops_repeating_and_respects_budget():
    model = ScriptModel([("autofill", {})] * 6)
    run = lambda reserve: HybridApplicationAgent(model_factory=lambda: model).run(RepairBrowser(), state(),
        autofill=lambda: {}, active=lambda: True, reserve=reserve, report=lambda *args: None)
    assert run(lambda kind: True)["reason"] == "no_progress"
    assert run(lambda kind: False)["reason"] == "agent_limit"


def test_provider_failure_preserves_fields_and_does_not_leak_error():
    class BrokenModel:
        def invoke(self, *args): raise RuntimeError("secret provider diagnostic")
    result = HybridApplicationAgent(model_factory=BrokenModel).run(RepairBrowser(), state(),
        autofill=lambda: {}, active=lambda: True, reserve=lambda kind: True, report=lambda *args: None)
    assert result == {"reason": "model_error", "field_keys": []}


def test_cancelled_model_response_cannot_execute_tools():
    started, release = Event(), Event()
    class SlowModel:
        def invoke(self, *args):
            started.set(); release.wait(2)
            return AIMessage(content="", tool_calls=[{"id": "1", "name": "autofill", "args": {}}])
    filled = []
    try:
        result = HybridApplicationAgent(model_factory=SlowModel).run(RepairBrowser(), state(),
            autofill=lambda: filled.append(True), active=lambda: not started.is_set(),
            reserve=lambda kind: True, report=lambda *args: None)
        assert result["reason"] == "cancelled"
        assert not filled
    finally:
        release.set()


def test_host_rejects_model_ready_when_required_question_is_unanswered(database):
    browser = FakeBrowser("", question=True)
    loop = ApplicationLoop(ApplyRepository(database.session_factory), browser_factory=lambda _: browser,
        agent_factory=lambda: HybridApplicationAgent(model_factory=lambda: ScriptModel([
            ("autofill", {}), ("ready_for_review", {})])))
    try:
        run_id = loop.start(request(automation_mode="hybrid", auto_submit=True))["run_id"]
        paused = wait(loop, run_id)
        assert paused["status"] == "needs_input"
        assert paused["pending_fields"] == ["Do you need sponsorship?"]
        assert browser.fields[0]["value"] == "Test"
        assert browser.submissions == 0
        # A paused attempt can switch to deterministic mode without starting over.
        loop.continue_run(run_id, ContinueApplication(expected_version=paused["version"],
            answers={"Do you need sponsorship?": "No"}, automation_mode="autofill"))
        assert wait(loop, run_id)["status"] == "submitted"
    finally:
        loop.close()


def test_autofill_retries_replaced_value_but_does_not_repeat_completed_name():
    browser = FakeBrowser("")
    calls = []
    normal_fill = browser.fill
    def fill_once(current, value):
        calls.append(current["key"])
        normal_fill(current, value)
        if current["key"] == "First name" and calls.count("First name") == 1:
            browser.fields[0]["value"] = ""
    browser.fill = fill_once
    result = autofill(browser, state(answers={}), lambda: b"resume")
    assert not result["failed"]
    assert calls.count("First name") == 2
    autofill(browser, state(answers={}), lambda: b"resume")
    assert calls.count("First name") == 2


def test_host_does_not_accept_nonempty_incorrect_value_after_failed_fill(database):
    browser = FakeBrowser("")
    normal_fill = browser.fill
    def wrong_value(current, value):
        normal_fill(current, value)
        if current["key"] == "First name": browser.fields[0]["value"] = "Wrong"
    browser.fill = wrong_value
    loop = ApplicationLoop(ApplyRepository(database.session_factory), browser_factory=lambda _: browser)
    try:
        paused = wait(loop, loop.start(request(auto_submit=True))["run_id"])
        assert paused["status"] == "needs_input"
        assert "First name" in paused["pending_fields"]
        assert not browser.submissions
    finally:
        loop.close()
