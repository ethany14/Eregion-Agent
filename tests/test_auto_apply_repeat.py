"""Completed fields stay unchanged across repeated model actions and retries."""
import pytest

from agent_runtime.auto_apply.agent import AgentTools
from agent_runtime.auto_apply.matching import resolve_option
from test_auto_apply import FakeBrowser, field, request

CITY = "Ithaca, New York, United States"


def test_identical_suggestions_are_one_choice_but_different_values_remain_ambiguous():
    choice = {"label": CITY, "value": CITY}
    assert resolve_option("Location (City)", CITY, [choice, dict(choice)]) == choice
    assert resolve_option("Location (City)", "ithaca ny", [choice, dict(choice)]) == choice
    assert resolve_option("Location (City)", CITY, [
        {"label": CITY, "value": "place-a"}, {"label": CITY, "value": "place-b"}]) is None


class RecordingBrowser(FakeBrowser):
    def __init__(self):
        super().__init__("")
        city = field("city", "combobox", "Location (City)")
        city.update(value=CITY, options=[{"label": CITY, "value": CITY}] * 2)
        self.fields, self.writes = [city], []

    def inspect_options(self, key, query=None):
        self.writes.append(("inspect", key))
        return self.fields[0]["options"]

    def click_field(self, key): self.writes.append(("click", key))
    def type_field(self, key, value): self.writes.append(("type", key, value))
    def choose_option(self, key, label): self.writes.append(("choose", key, label))
    def press_key(self, key, value): self.writes.append(("press", key, value))
    def fill(self, current, value): self.writes.append(("fill", current["key"], value))


@pytest.mark.parametrize("tool,extra", [
    ("inspect_field", {}), ("search_options", {"source_ref": "answer:city"}),
    ("click_field", {}), ("press_key", {"key": "ArrowDown"}),
    ("type_from_source", {"source_ref": "answer:city"}),
    ("choose_option", {"source_ref": "answer:city", "option_label": CITY}),
    ("use_chat_answer", {"message_id": "u", "answer": "ithaca ny"}),
])
def test_completed_field_is_not_operated_again_even_after_agent_restart(tool, extra):
    browser = RecordingBrowser()
    data = {"profile": request().profile.model_dump(), "answers": {"city": CITY},
            "messages": [{"id":"u", "role":"user", "text":"ithaca ny"}]}
    # New AgentTools instances model automatic continuation/recovery, without
    # relying on a permanent 'done' flag that could hide later page changes.
    for _ in range(2):
        session = AgentTools(browser, data, autofill=lambda: {}, active=lambda: True)
        session.execute("autofill", {})
        observation = session.observe()
        assert observation["completed_fields"] == ["city"]
        result = session.execute(tool, {"observation_id": observation["observation_id"], "field_key":"city", **extra})
        assert result["already_filled"]
    assert browser.writes == []


@pytest.mark.parametrize("change", [{"value": ""}, {"invalid": True}])
def test_a_cleared_or_invalid_field_can_still_be_repaired(change):
    browser = RecordingBrowser()
    data = {"profile": request().profile.model_dump(), "answers": {"city": CITY}}
    session = AgentTools(browser, data, autofill=lambda: {}, active=lambda: True)
    session.execute("autofill", {})
    session.observe()
    browser.fields[0].update(change)
    observation = session.observe()
    assert observation["completed_fields"] == []
    session.execute("click_field", {"observation_id":observation["observation_id"], "field_key":"city"})
    assert browser.writes == [("click", "city")]


def test_user_correction_to_a_different_value_is_not_skipped():
    browser = RecordingBrowser()
    data = {"profile": request().profile.model_dump(), "answers": {"city": "Boston"}}
    session = AgentTools(browser, data, autofill=lambda: {}, active=lambda: True)
    session.execute("autofill", {})
    observation = session.observe()
    session.execute("type_from_source", {"observation_id":observation["observation_id"],
        "field_key":"city", "source_ref":"answer:city"})
    assert browser.writes == [("type", "city", "Boston")]
