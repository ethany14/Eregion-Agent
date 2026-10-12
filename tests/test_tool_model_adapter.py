from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
import json
from pathlib import Path
import pytest
from types import SimpleNamespace

from agent_runtime import AgentMessage, LangChainToolModelAdapter, NormalizedToolCall
from agent_runtime.errors import ToolModelError


class FakeLangChainModel:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.bound_tools = None
        self.messages = None

    def bind_tools(self, tools):
        self.bound_tools = tools
        return self

    def invoke(self, messages, config=None):
        self.messages = messages
        if self.error:
            raise self.error
        return self.result


class TimeoutAwareLangChainModel(FakeLangChainModel):
    def __init__(self, result=None):
        super().__init__(result=result)
        self.timeout = None

    def invoke(self, messages, config=None, **kwargs):
        self.messages = messages
        self.timeout = kwargs.get("timeout")
        return self.result


def schema():
    return [{"name": "echo", "description": "Echo text", "input_schema": {
        "type": "object", "properties": {"text": {"type": "string"}}}}]


def test_adapter_converts_all_internal_message_roles_and_tools():
    provider = FakeLangChainModel(AIMessage(content="done", id="response-1"))
    adapter = LangChainToolModelAdapter(provider)
    adapter.invoke([
        AgentMessage(message_id="system-1", role="system", content="system"),
        AgentMessage(message_id="user-1", role="user", content="user"),
        AgentMessage(message_id="assistant-1", role="assistant", tool_calls=[
            NormalizedToolCall(tool_call_id="call-1", tool_name="echo", arguments={"text": "x"})]),
        AgentMessage(message_id="tool-1", role="tool", content="{}",
            tool_call_id="call-1", tool_name="echo"),
    ], schema())
    assert [type(item) for item in provider.messages] == [
        SystemMessage, HumanMessage, AIMessage, ToolMessage]
    assert provider.bound_tools[0]["function"]["name"] == "echo"
    assert provider.messages[2].tool_calls[0]["id"] == "call-1"


@pytest.mark.parametrize("arguments", [{"text": "hello"}, '{"text":"hello"}'])
def test_adapter_accepts_dict_and_json_string_arguments(arguments):
    response = SimpleNamespace(content="", tool_calls=[{
        "name": "echo", "args": arguments, "id": "provider-1", "type": "tool_call"}],
        usage_metadata={}, response_metadata={}, id=None)
    provider = FakeLangChainModel(response)
    result = LangChainToolModelAdapter(provider).invoke([], schema())
    assert result.message.tool_calls[0].arguments == {"text": "hello"}


def test_adapter_supports_multiple_calls_and_missing_usage():
    provider = FakeLangChainModel(AIMessage(content="", tool_calls=[
        {"name": "echo", "args": {"text": "a"}, "id": "a", "type": "tool_call"},
        {"name": "echo", "args": {"text": "b"}, "id": "b", "type": "tool_call"},
    ]))
    result = LangChainToolModelAdapter(provider).invoke([], schema())
    assert [item.tool_call_id for item in result.message.tool_calls] == ["a", "b"]
    assert result.usage.total_tokens == 0


def test_adapter_generates_stable_ids_when_provider_ids_are_missing():
    def normalize():
        response = AIMessage(content="", additional_kwargs={"tool_calls": [{
            "type": "function", "function": {"name": "echo", "arguments": '{"text":"x"}'}}]})
        return LangChainToolModelAdapter(FakeLangChainModel(response)).invoke([], schema())
    first = normalize(); second = normalize()
    assert first.message.message_id == second.message.message_id
    assert first.message.tool_calls[0].tool_call_id == second.message.tool_calls[0].tool_call_id


def test_adapter_safely_normalizes_malformed_json_and_missing_name():
    response = AIMessage(content="", additional_kwargs={"tool_calls": [
        {"function": {"name": "echo", "arguments": "not-json"}},
        {"function": {"arguments": "[]"}},
    ]})
    result = LangChainToolModelAdapter(FakeLangChainModel(response)).invoke([], schema())
    assert result.message.tool_calls[0].arguments == {}
    assert result.message.tool_calls[0].invalid_reason == "malformed_arguments"
    assert result.message.tool_calls[1].tool_name == "__invalid_tool_call__"
    assert result.message.tool_calls[1].arguments == {}
    assert result.message.tool_calls[1].invalid_reason == "missing_tool_name"


def raw_response(raw_calls):
    # A provider payload that bypasses LangChain's own argument parsing.
    return SimpleNamespace(content="", tool_calls=[], invalid_tool_calls=[],
        additional_kwargs={"tool_calls": raw_calls}, usage_metadata={},
        response_metadata={}, id=None)


@pytest.mark.parametrize("arguments", ["", "  ", None, {}])
def test_adapter_keeps_legitimately_empty_arguments_valid(arguments):
    response = raw_response(
        [{"id": "c1", "function": {"name": "echo", "arguments": arguments}}])
    call = LangChainToolModelAdapter(FakeLangChainModel(response)).invoke(
        [], schema()).message.tool_calls[0]
    assert call.arguments == {} and call.invalid_reason is None


def test_adapter_marks_non_object_arguments_invalid():
    response = raw_response(
        [{"id": "c1", "function": {"name": "echo", "arguments": '["x"]'}}])
    call = LangChainToolModelAdapter(FakeLangChainModel(response)).invoke(
        [], schema()).message.tool_calls[0]
    assert call.invalid_reason == "non_object_arguments"


def test_adapter_keeps_langchain_invalid_tool_calls_as_invalid():
    # LangChain parses the provider payload itself and moves broken JSON to
    # invalid_tool_calls; it must not vanish or become an empty-argument call.
    response = AIMessage(content="", tool_calls=[
        {"name": "echo", "args": {"text": "ok"}, "id": "good", "type": "tool_call"}],
        invalid_tool_calls=[{"name": "echo", "args": '{"text": "cut', "id": "bad",
            "error": "bad json", "type": "invalid_tool_call"}])
    calls = LangChainToolModelAdapter(FakeLangChainModel(response)).invoke(
        [], schema()).message.tool_calls
    assert [(c.tool_call_id, c.invalid_reason) for c in calls] == [
        ("good", None), ("bad", "malformed_arguments")]
    assert calls[1].arguments == {}


def test_adapter_marks_every_call_of_a_truncated_response_invalid():
    response = AIMessage(content="", tool_calls=[
        {"name": "echo", "args": {"text": "partial"}, "id": "c1", "type": "tool_call"}],
        response_metadata={"finish_reason": "length", "model_name": "m-1",
            "token_usage": {"prompt_tokens": 3}})
    result = LangChainToolModelAdapter(FakeLangChainModel(response)).invoke([], schema())
    assert result.finish_reason == "length"
    assert result.message.tool_calls[0].invalid_reason == "truncated_response"
    assert result.message.tool_calls[0].arguments == {}
    assert result.provider_metadata == {"model_name": "m-1", "finish_reason": "length"}


def test_adapter_reports_finish_reason_for_normal_and_unreported_responses():
    stop = AIMessage(content="done", response_metadata={"finish_reason": "stop"})
    assert LangChainToolModelAdapter(FakeLangChainModel(stop)).invoke(
        [], []).finish_reason == "stop"
    anthropic = AIMessage(content="done", response_metadata={"stop_reason": "end_turn"})
    assert LangChainToolModelAdapter(FakeLangChainModel(anthropic)).invoke(
        [], []).finish_reason == "end_turn"
    bare = AIMessage(content="done")
    assert LangChainToolModelAdapter(FakeLangChainModel(bare)).invoke(
        [], []).finish_reason is None


def test_valid_calls_keep_the_previous_persisted_shape():
    call = NormalizedToolCall(tool_call_id="c", tool_name="echo", arguments={"a": 1})
    assert call.model_dump(mode="json") == {
        "tool_call_id": "c", "tool_name": "echo", "arguments": {"a": 1}}
    invalid = NormalizedToolCall(tool_call_id="c", tool_name="echo",
        invalid_reason="malformed_arguments")
    restored = NormalizedToolCall.model_validate(invalid.model_dump(mode="json"))
    assert restored.invalid_reason == "malformed_arguments"


def test_adapter_reads_usage_metadata_and_normalizes_provider_errors():
    response = AIMessage(content="done", usage_metadata={
        "input_tokens": 4, "output_tokens": 3, "total_tokens": 7})
    result = LangChainToolModelAdapter(FakeLangChainModel(response)).invoke([], [])
    assert result.usage.total_tokens == 7
    with pytest.raises(ToolModelError, match="could not complete") as exc:
        LangChainToolModelAdapter(FakeLangChainModel(
            error=RuntimeError("Authorization: Bearer secret"))).invoke([], [])
    assert "secret" not in str(exc.value)


def test_adapter_propagates_dynamic_timeout_only_when_provider_accepts_it():
    aware = TimeoutAwareLangChainModel(AIMessage(content="done"))
    LangChainToolModelAdapter(aware).invoke([], [], timeout_seconds=4.5)
    assert aware.timeout == 4.5

    unaware = FakeLangChainModel(AIMessage(content="done"))
    LangChainToolModelAdapter(unaware).invoke([], [], timeout_seconds=4.5)
    assert unaware.messages == []


def test_tool_calling_evaluation_dataset_contract():
    path = Path(__file__).resolve().parent.parent / "evals" / "tool_calling_cases.json"
    cases = json.loads(path.read_text(encoding="utf-8"))
    assert len(cases) >= 4
    assert len({case["id"] for case in cases}) == len(cases)
    assert any(not case["expected_tools"] for case in cases)
    for case in cases:
        assert set(case["expected_tools"]) <= set(case["allowed_tools"])
        assert len(case["expected_tools"]) == len(case["expected_arguments"])
