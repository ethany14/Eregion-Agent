"""A multi-question chat reply remains usable even when the model fails."""
import pytest

from eregion.runtime.auto_apply.agent import AgentTools
from eregion.runtime.auto_apply.browser import BrowserBlocked
from eregion.runtime.auto_apply.conversation import ordered_answers, input_prompt
from eregion.runtime.auto_apply.contracts import ChatRequest, ContinueApplication
from eregion.runtime.auto_apply.loop import ApplicationLoop
from eregion.runtime.auto_apply.repository import ApplyRepository
from test_auto_apply import FakeBrowser, database, field, request, wait


def test_chat_explicitly_updates_visual_preference_and_omission_preserves_it(database):
    repository=ApplyRepository(database.session_factory)
    saved,_=repository.create(request(automation_mode='hybrid'))
    saved=repository.save(saved,status='needs_input',pause_requested=True)
    loop=ApplicationLoop(repository,browser_factory=FakeBrowser)
    try:
        assert saved['visual_fallback'] is False
        enabled=loop.chat(saved['run_id'],ChatRequest(text='pause',message_id='enable-visual-test',visual_fallback=True))
        assert enabled['visual_fallback'] is True
        kept=loop.chat(saved['run_id'],ChatRequest(text='pause',message_id='keep-visual-test'))
        assert kept['visual_fallback'] is True
        disabled=loop.chat(saved['run_id'],ChatRequest(text='pause',message_id='disable-visual-test',visual_fallback=False))
        assert disabled['visual_fallback'] is False
    finally:loop.close()


def questions():
    return [field("city", "combobox", "Location (City)*"),
        field("english", "select", "Are you fluent in English?*"),
        field("referral", "text", "How did you hear about this job?*"),
        field("sponsor", "select", "Do you now or will you in the future require immigration sponsorship to work at Cloudflare?*"),
        field("consent", "checkbox", "Acknowledge/Confirm")]


def prompt(fields):
    return {"role": "assistant", "id": "question-1", "text": "I need your answer for: " +
        "; ".join(f["label"] for f in fields) + ". Reply here or use the fields below."}


class UnavailableAgent:
    def run(self, *args, **kwargs):
        return {"reason": "model_error", "field_keys": []}


@pytest.mark.parametrize("text", ["ithaca，yes, linkedin, yes", "ithaca; yes; linkedin; yes", "ithaca\nyes\nlinkedin\nyes"])
def test_partial_ordered_reply_does_not_answer_trailing_consent(text):
    fields = questions()
    assert ordered_answers(text, [prompt(fields)], fields) == {
        "city": "ithaca", "english": "yes", "referral": "linkedin", "sponsor": "yes"}


@pytest.mark.parametrize("text", ["yes", "ithaca,,linkedin,yes", "ithaca,linkedin,yes", "ithaca,yes,linkedin,yes,yes,extra",
    "For sponsorship, use No", "I live in Ithaca, yes, linkedin, yes"])
def test_ambiguous_replies_are_left_for_clarification(text):
    fields = questions()
    assert ordered_answers(text, [prompt(fields)], fields) == {}


def test_semicolon_preserves_city_commas_and_prompt_order():
    fields = questions()
    message = {"role": "assistant", "question_keys": [f["key"] for f in fields]}
    assert ordered_answers("Ithaca, New York; yes; linkedin; yes", [message], list(reversed(fields)))["city"] == "Ithaca, New York"
    assert ordered_answers("yes, yes", [message, {"role":"user", "text":"some intervening feedback"}], fields) == {}


def test_chat_saves_and_fills_four_answers_with_model_down(database):
    browser = FakeBrowser("")
    browser.fields = questions()
    loop = ApplicationLoop(ApplyRepository(database.session_factory), browser_factory=lambda _: browser, agent_factory=UnavailableAgent)
    try:
        run_id = loop.start(request(automation_mode="hybrid"))["run_id"]
        initial = wait(loop, run_id)
        assert initial["messages"][-1]["question_keys"] == [f["key"] for f in questions()]
        reply = ChatRequest(text="ithaca，yes, linkedin, yes", message_id="batch-answer-0001")
        loop.chat(run_id, reply)
        state = wait(loop, run_id)
        assert state["answers"] == {"city":"ithaca", "english":"yes", "referral":"linkedin", "sponsor":"yes"}
        assert state["pending_fields"] == ["consent"]
        assert state["messages"][-1]["question_keys"] == ["consent"]
        assert "Location" not in state["messages"][-1]["text"]
        assert [f["value"] for f in browser.fields] == ["ithaca", "yes", "linkedin", "yes", ""]
        assert loop.chat(run_id, reply)["version"] == state["version"]
        # A separate response now answers only the remaining consent question.
        loop.chat(run_id, ChatRequest(text="no", message_id="consent-answer-1"))
        state = wait(loop, run_id)
        assert state["answers"]["consent"] is False and browser.fields[-1]["value"] is False
        assert state["messages"][-1]["question_keys"] == []
        assert "I have your answers" in state["messages"][-1]["text"]
        assert browser.submissions == 0
    finally:
        loop.close()


def test_previous_failed_chat_recovers_on_continue_without_replacing_newer_answer(database):
    browser = FakeBrowser("")
    browser.fields = questions()
    repo = ApplyRepository(database.session_factory)
    loop = ApplicationLoop(repo, browser_factory=lambda _: browser, agent_factory=UnavailableAgent)
    try:
        run_id = loop.start(request(automation_mode="hybrid"))["run_id"]
        state = wait(loop, run_id)
        state = repo.save(state, answers={"referral":"careers site"}, messages=[prompt(browser.fields),
            {"id":"old-reply", "role":"user", "text":"ithaca，yes, linkedin, yes"}, prompt(browser.fields)])
        loop.continue_run(run_id, ContinueApplication(expected_version=state["version"]))
        state = wait(loop, run_id)
        assert state["answers"] == {"city":"ithaca", "english":"yes", "referral":"careers site", "sponsor":"yes"}
        assert state["pending_fields"] == ["consent"]
        assert state["messages"][1]["bound_answers"]["sponsor"] == "yes"
    finally:
        loop.close()


def test_model_cannot_reuse_sponsorship_yes_as_consent():
    browser = FakeBrowser("")
    browser.fields = questions()
    answers = {"city":"ithaca", "english":"yes", "referral":"linkedin", "sponsor":"yes"}
    state = {"profile": request().profile.model_dump(), "answers":answers,
        "messages":[{"id":"batch-reply", "role":"user", "text":"ithaca，yes, linkedin, yes", "bound_answers":answers}]}
    session = AgentTools(browser, state, autofill=lambda: {}, active=lambda: True)
    snapshot = session.observe()
    with pytest.raises(BrowserBlocked, match="does not answer this field"):
        session.execute("use_chat_answer", {"observation_id":snapshot["observation_id"], "field_key":"consent",
            "message_id":"batch-reply", "answer":"yes"})
    assert not browser.fields[-1]["value"]


def test_ambiguous_city_asks_for_region_only_and_can_bind_clarification():
    city, *_, consent = questions()
    city["options"] = [{"label":label, "value":label} for label in [
        "Ithaca, New York, United States", "Ithaca, Michigan, United States", "Town of Ithaca, New York, United States"]]
    text, keys = input_prompt([consent], [city], {"city":"ithaca"})
    assert keys == ["city", "consent"]
    assert "matches multiple options" in text and "Ithaca, Michigan" in text
    assert "Town of Ithaca" not in text
    assert ordered_answers("Ithaca, New York; no", [{"role":"assistant", "text":text, "question_keys":keys}],
        [city, consent]) == {"city":"Ithaca, New York", "consent":False}


def test_failed_control_does_not_trigger_repeated_question(database):
    class BrokenCity(FakeBrowser):
        def fill(self, current, value):
            if current["key"] == "city":
                raise BrowserBlocked("No matching city option")
            return super().fill(current, value)
    browser = BrokenCity("")
    browser.fields = questions()
    loop = ApplicationLoop(ApplyRepository(database.session_factory), browser_factory=lambda _: browser, agent_factory=UnavailableAgent)
    try:
        run_id = loop.start(request(automation_mode="hybrid"))["run_id"]
        wait(loop, run_id)
        loop.chat(run_id, ChatRequest(text="ithaca，yes, linkedin, yes", message_id="batch-answer-0001"))
        state = wait(loop, run_id)
        assert state["pending_fields"] == ["city", "consent"]
        assert state["messages"][-1]["question_keys"] == ["consent"]
        assert "could not finish filling these controls: Location (City)" in state["messages"][-1]["text"]
        assert state["answers"]["city"] == "ithaca"
    finally:
        loop.close()


@pytest.mark.parametrize("text,expected", [
    ("ithaca newyork 2.linkedin", {"city": "ithaca newyork", "referral": "linkedin"}),
    ("1. ithaca newyork 2.linkedin", {"city": "ithaca newyork", "referral": "linkedin"}),
    ("1) Ithaca, New York; 2) LinkedIn", {"city": "Ithaca, New York", "referral": "LinkedIn"}),
    ("2.linkedin", {"referral": "linkedin"}),
    ("2.linkedin 1.ithaca newyork", {"referral": "linkedin", "city": "ithaca newyork"}),
    ("ithaca newyork 3.linkedin", {}),
    ("1.ithaca 1.linkedin", {}),
    ("1.ithaca 2.", {}),
])
def test_numbered_reply_maps_question_numbers_without_shifting(text, expected):
    fields = [questions()[0], questions()[2]]
    message = {"role": "assistant", "question_keys": ["city", "referral"]}
    assert ordered_answers(text, [message], fields) == expected


def test_model_can_ground_unpunctuated_city_and_choose_observed_option():
    browser = FakeBrowser("")
    city = questions()[0]
    city["options"] = [{"label": label, "value": label} for label in [
        "Ithaca, New York, United States", "Ithaca, Michigan, United States", "Ithaca, Nebraska, United States"]]
    browser.fields = [city, questions()[2]]
    text = "ithaca newyork 2.linkedin"
    answers = ordered_answers(text, [{"role": "assistant", "question_keys": ["city", "referral"]}], browser.fields)
    state = {"profile": request().profile.model_dump(), "answers": answers,
        "messages": [{"id": "correction", "role": "user", "text": text, "bound_answers": answers}]}
    session = AgentTools(browser, state, autofill=lambda: {}, active=lambda: True)
    snapshot = session.observe()
    session.execute("use_chat_answer", {"observation_id": snapshot["observation_id"],
        "field_key": "city", "message_id": "correction", "answer": "ithaca newyork"})
    session.execute("autofill", {})
    session.observed_options["city"] = city["options"]
    browser.choose_option = lambda key, label: browser.fill(city, label)
    snapshot = session.observe()
    session.execute("choose_option", {"observation_id": snapshot["observation_id"], "field_key": "city",
        "source_ref": "answer:city", "option_label": "Ithaca, New York, United States"})
    assert city["value"] == "Ithaca, New York, United States"


def city_choices():
    return [{"label": label, "value": label} for label in [
        "Ithaca, New York, United States", "Ithaca, Michigan, United States", "Ithaca, Nebraska, United States"]]


@pytest.mark.parametrize("keys", [["city", "referral"], ["city"]])
@pytest.mark.parametrize("text,expected", [
    ("ithaca， NY、", {"city": "ithaca， NY"}),
    ("ithaca ny 2. linkedin", {"city": "ithaca ny", "referral": "linkedin"}),
    ("ithaca newyork  ， linkedin", {"city": "ithaca newyork", "referral": "linkedin"}),
    ("Ithaca, New York, United States", {"city": "Ithaca, New York, United States"}),
])
def test_city_clarification_preserves_region_when_question_list_shrinks(keys, text, expected):
    fields = questions()
    fields[0]["options"] = city_choices()
    history = [{"role": "assistant", "question_keys": ["city", "referral", "consent"]},
        {"role": "user", "text": "older answer"}, {"role": "assistant", "question_keys": keys}]
    assert ordered_answers(text, history, fields) == expected


def test_city_comma_never_becomes_referral_or_consent():
    fields = questions()
    fields[0]["options"] = city_choices()
    assert ordered_answers("Ithaca, NY", [{"role": "assistant", "question_keys": ["city", "consent"]}], fields) == {"city": "Ithaca, NY"}
    assert ordered_answers("Ithaca, NY; no", [{"role": "assistant", "question_keys": ["city", "consent"]}], fields) == {"city": "Ithaca, NY", "consent": False}
    assert ordered_answers("Ithaca, NY 2. yes", [{"role": "assistant", "question_keys": ["city"]}], fields) == {}


def test_resume_recovers_later_unparsed_correction_but_preserves_newer_edits(database):
    repo = ApplyRepository(database.session_factory)
    state, _ = repo.create(request(automation_mode="hybrid"))
    fields = questions()
    fields[0]["options"] = city_choices()
    old = {"city": "ithaca", "referral": "NY、"}
    messages = [
        {"id": "q0", "role": "assistant", "question_keys": ["city", "referral"]},
        {"id": "old", "role": "user", "text": "ithaca， NY、", "bound_answers": old},
        {"id": "q1", "role": "assistant", "question_keys": ["city"]},
        {"id": "correction", "role": "user", "text": "ithaca ny 2. linkedin"},
        {"id": "q2", "role": "assistant", "question_keys": ["city"]},
        {"id": "newest", "role": "user", "text": "company website", "field_key": "referral"}]
    state = repo.save(state, status="needs_input", fields=fields, messages=messages,
        answers={**old, "referral": "company website"}, answer_sources={
            "city": {"type": "chat", "message_id": "old"},
            "referral": {"type": "chat", "message_id": "newest"}})
    loop = ApplicationLoop(repo, browser_factory=FakeBrowser, agent_factory=UnavailableAgent)
    try:
        recovered = loop._recover_chat_answers(repo.get(state["run_id"]))
        assert recovered["answers"] == {"city": "ithaca ny", "referral": "company website"}
        assert recovered["answer_sources"]["city"]["message_id"] == "correction"
        assert loop._recover_chat_answers(recovered)["version"] == recovered["version"]
    finally:
        loop.close()
