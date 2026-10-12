"""LangChain conversion isolated from provider-independent runtime messages."""
from __future__ import annotations

import hashlib
import json
import inspect
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from agent_runtime.errors import ToolModelError
from agent_runtime.security import canonical_json
from agent_runtime.tools.messages import (
    AgentMessage,
    NormalizedToolCall,
    TokenUsage,
    ToolModelResponse,
)


TRUNCATED_FINISH_REASONS = frozenset({"length", "max_tokens"})
# Identifying, non-secret response fields kept for diagnostics.
PROVIDER_METADATA_KEYS = (
    "model_name",
    "model",
    "system_fingerprint",
    "service_tier",
    "finish_reason",
    "stop_reason",
)


class LangChainToolModelAdapter:
    def __init__(self, model: Any, *, config: Any = None) -> None:
        self._model = model
        self._config = config

    def invoke(
        self,
        messages: list[AgentMessage],
        tools: list[dict[str, Any]],
        *,
        timeout_seconds: float | None = None,
    ) -> ToolModelResponse:
        provider_tools = [
            {
                "type": "function",
                "function": {
                    "name": item["name"],
                    "description": item["description"],
                    "parameters": item["input_schema"],
                },
            }
            for item in tools
        ]
        try:
            bound = self._model.bind_tools(provider_tools) if provider_tools else self._model
            invoke = bound.invoke
            signature = inspect.signature(invoke)
            supports_timeout = "timeout" in signature.parameters or any(
                item.kind == inspect.Parameter.VAR_KEYWORD
                for item in signature.parameters.values()
            )
            kwargs = {"config": self._config}
            if timeout_seconds is not None and supports_timeout:
                kwargs["timeout"] = timeout_seconds
            response = invoke(
                [self._to_provider(item) for item in messages], **kwargs
            )
            return self._from_provider(response)
        except ToolModelError:
            raise
        except Exception as exc:
            raise ToolModelError(
                "The model could not complete the tool-calling turn."
            ) from exc

    @staticmethod
    def _to_provider(message: AgentMessage):
        if message.role == "system":
            return SystemMessage(content=message.content, id=message.message_id)
        if message.role == "user":
            return HumanMessage(content=message.content, id=message.message_id)
        if message.role == "tool":
            return ToolMessage(
                content=message.content,
                tool_call_id=message.tool_call_id,
                name=message.tool_name,
                id=message.message_id,
            )
        calls = [
            {
                "name": item.tool_name,
                "args": item.arguments,
                "id": item.tool_call_id,
                "type": "tool_call",
            }
            for item in message.tool_calls
        ]
        return AIMessage(content=message.content, tool_calls=calls, id=message.message_id)

    @classmethod
    def _from_provider(cls, response: Any) -> ToolModelResponse:
        raw_calls = cls._raw_calls(response)
        content = cls._content(response)
        finish_reason = cls._finish_reason(response)
        provider_message_id = getattr(response, "id", None)
        message_id = str(
            provider_message_id
            or cls._stable_id(
                "assistant",
                {
                    "content": content,
                    "tool_calls": [
                        cls._call_fingerprint(item) for item, _ in raw_calls
                    ],
                },
            )
        )
        # A response cut off by its output limit may carry a partial call whose
        # arguments still parse; none of its calls may run.
        truncated = finish_reason in TRUNCATED_FINISH_REASONS
        calls = [
            cls._normalize_call(
                item,
                index,
                message_id,
                forced_reason="truncated_response" if truncated else reason,
            )
            for index, (item, reason) in enumerate(raw_calls)
        ]
        return ToolModelResponse(
            message=AgentMessage(
                message_id=message_id,
                role="assistant",
                content=content,
                tool_calls=calls,
            ),
            usage=cls._usage(response),
            finish_reason=finish_reason,
            provider_metadata=cls._provider_metadata(response),
        )

    @staticmethod
    def _raw_calls(response: Any) -> list[tuple[Any, str | None]]:
        calls = list(getattr(response, "tool_calls", None) or [])
        # LangChain moves calls whose argument JSON failed to parse here; they
        # used to be dropped or re-read from the raw payload as empty arguments.
        invalid = list(getattr(response, "invalid_tool_calls", None) or [])
        if calls or invalid:
            return [(item, None) for item in calls] + [
                (item, "malformed_arguments") for item in invalid
            ]
        additional = getattr(response, "additional_kwargs", None) or {}
        return [(item, None) for item in additional.get("tool_calls") or []]

    @classmethod
    def _normalize_call(
        cls,
        item: Any,
        index: int,
        message_id: str,
        *,
        forced_reason: str | None = None,
    ) -> NormalizedToolCall:
        raw = item if isinstance(item, dict) else {}
        function = raw.get("function") if isinstance(raw.get("function"), dict) else {}
        name = raw.get("name") or function.get("name")
        reason = forced_reason
        if not name:
            name = "__invalid_tool_call__"
            reason = reason or "missing_tool_name"
        arguments = raw.get("args", function.get("arguments"))
        if arguments is None:
            arguments = {}
        elif isinstance(arguments, str):
            if not arguments.strip():
                # An empty string is how some providers send a no-argument call.
                arguments = {}
            else:
                try:
                    arguments = json.loads(arguments)
                except (json.JSONDecodeError, TypeError):
                    arguments = {}
                    reason = reason or "malformed_arguments"
        if not isinstance(arguments, dict):
            arguments = {}
            reason = reason or "non_object_arguments"
        if reason is not None:
            arguments = {}
        call_id = raw.get("id") or cls._stable_id(
            "tool-call",
            {
                "message_id": message_id,
                "index": index,
                "tool_name": str(name),
                "arguments": arguments,
            },
        )
        return NormalizedToolCall(
            tool_call_id=str(call_id),
            tool_name=str(name),
            arguments=arguments,
            invalid_reason=reason,
        )

    @staticmethod
    def _finish_reason(response: Any) -> str | None:
        metadata = getattr(response, "response_metadata", None) or {}
        if not isinstance(metadata, dict):
            return None
        value = metadata.get("finish_reason") or metadata.get("stop_reason")
        return str(value) if value else None

    @staticmethod
    def _provider_metadata(response: Any) -> dict[str, Any]:
        metadata = getattr(response, "response_metadata", None) or {}
        if not isinstance(metadata, dict):
            return {}
        return {
            key: metadata[key]
            for key in PROVIDER_METADATA_KEYS
            if isinstance(metadata.get(key), (str, int, float, bool))
        }

    @staticmethod
    def _call_fingerprint(item: Any) -> dict[str, Any]:
        raw = item if isinstance(item, dict) else {}
        function = raw.get("function") if isinstance(raw.get("function"), dict) else {}
        arguments = raw.get("args", function.get("arguments", {}))
        if not isinstance(arguments, (dict, list, str, int, float, bool, type(None))):
            arguments = "invalid"
        return {
            "id": str(raw.get("id") or ""),
            "name": str(raw.get("name") or function.get("name") or ""),
            "arguments": arguments,
        }

    @staticmethod
    def _content(response: Any) -> str:
        content = getattr(response, "content", "")
        if isinstance(content, str):
            return content
        try:
            return canonical_json(content)
        except (TypeError, ValueError):
            return ""

    @staticmethod
    def _stable_id(prefix: str, value: Any) -> str:
        digest = hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
        return f"{prefix}-{digest[:24]}"

    @staticmethod
    def _usage(response: Any) -> TokenUsage:
        usage = getattr(response, "usage_metadata", None) or {}
        if not usage:
            metadata = getattr(response, "response_metadata", None) or {}
            usage = metadata.get("token_usage") or metadata.get("usage") or {}
        input_tokens = usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0
        output_tokens = usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0
        total_tokens = usage.get("total_tokens", input_tokens + output_tokens) or 0
        return TokenUsage(
            input_tokens=int(input_tokens),
            output_tokens=int(output_tokens),
            total_tokens=int(total_tokens),
        )
