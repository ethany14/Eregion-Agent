"""Shared model configuration and structured invocation."""

from __future__ import annotations

import os
import hashlib
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, TypeVar

from dotenv import dotenv_values
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

Result = TypeVar("Result", bound=BaseModel)
DEFAULT_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
GEMINI_OPENAI_COMPATIBILITY_HOST = "generativelanguage.googleapis.com"
GEMINI_MISSING_THOUGHT_SIGNATURE = "skip_thought_signature_validator"


class ProviderCompatibleChatOpenAI(ChatOpenAI):
    """Patch provider-specific wire metadata without changing shared messages.

    Gemini 3 requires a thought signature when a function-call message is sent
    back with its tool result. The installed OpenAI/LangChain compatibility
    stack drops Gemini's ``extra_content`` while normalizing the first response.
    Google's documented fallback signature is added only for Gemini's
    OpenAI-compatible endpoint and only when the signature is absent.
    """

    def _get_request_payload(
        self,
        input_: Any,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        base_url = str(self.openai_api_base or "")
        if GEMINI_OPENAI_COMPATIBILITY_HOST not in base_url.casefold():
            return payload
        for message in payload.get("messages", []):
            if message.get("role") != "assistant" or not message.get("tool_calls"):
                continue
            first_call = message["tool_calls"][0]
            extra_content = first_call.setdefault("extra_content", {})
            google = extra_content.setdefault("google", {})
            google.setdefault(
                "thought_signature", GEMINI_MISSING_THOUGHT_SIGNATURE
            )
        return payload


def optional_setting(settings: Mapping[str, Any], key: str) -> str | None:
    value = settings.get(key)
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def create_model(
    *,
    env_path: Path = DEFAULT_ENV_PATH,
    environ: Mapping[str, str] | None = None,
    model_factory: Callable[..., Any] = ProviderCompatibleChatOpenAI,
) -> Any:
    """Create the configured chat model with environment values taking priority."""
    environment = os.environ if environ is None else environ
    settings = {**dotenv_values(env_path), **environment}
    model_id = optional_setting(settings, "LLM_MODEL_ID")
    if not model_id:
        raise ValueError("Set LLM_MODEL_ID in the environment or project's .env file.")
    options: dict[str, Any] = {
        "model": model_id,
        "temperature": 0,
        "max_retries": 0,
        "timeout": 45.0,
    }
    api_key = optional_setting(settings, "LLM_API_KEY")
    base_url = optional_setting(settings, "LLM_BASE_URL")
    timeout = optional_setting(settings, "LLM_TIMEOUT")
    max_retries = optional_setting(settings, "LLM_MAX_RETRIES")
    if api_key is not None:
        options["api_key"] = api_key
    if base_url is not None:
        options["base_url"] = base_url
    if timeout is not None:
        try:
            seconds = float(timeout)
        except ValueError as exc:
            raise ValueError("LLM_TIMEOUT must be a positive number of seconds.") from exc
        if not 0 < seconds < float("inf"):
            raise ValueError("LLM_TIMEOUT must be a positive number of seconds.")
        options["timeout"] = seconds
    if max_retries is not None:
        try:
            retries = int(max_retries)
        except ValueError as exc:
            raise ValueError("LLM_MAX_RETRIES must be a non-negative integer.") from exc
        if retries < 0:
            raise ValueError("LLM_MAX_RETRIES must be a non-negative integer.")
        options["max_retries"] = retries
    return model_factory(**options)


def model_settings_fingerprint(*, env_path: Path = DEFAULT_ENV_PATH, environ=None) -> str:
    """Opaque cache identity. Never return or log credentials or raw settings."""
    settings = {**dotenv_values(env_path), **(os.environ if environ is None else environ)}
    keys = ('LLM_MODEL_ID','LLM_BASE_URL','LLM_API_KEY','LLM_TIMEOUT','LLM_MAX_RETRIES',
        'OPENAI_API_KEY','OPENAI_API_BASE','OPENAI_BASE_URL','OPENAI_ORG_ID')
    return hashlib.sha256(json.dumps({key:optional_setting(settings,key) for key in keys},
        sort_keys=True).encode()).hexdigest()


def invoke_structured(
    model: Any,
    schema: type[Result],
    system_message: str,
    human_message: str,
    config: Any = None,
) -> Result:
    """Invoke a Pydantic structured model using the baseline message layout."""
    from agent_runtime.multi_agent.model_usage import invoke_model

    return invoke_model(_invoke_structured, model, schema, system_message, human_message, config)


def _invoke_structured(model, schema, system_message, human_message, config):
    from agent_runtime.multi_agent.model_usage import current_model_call

    call = current_model_call()
    if call is not None and isinstance(model, ChatOpenAI):
        # One reservation corresponds to one provider request; retries must
        # acquire their own reservation. Raw usage replaces fallback estimates.
        updates = {"max_tokens": call["output_tokens"], "max_retries": 0}
        # The SDK client was initialized earlier; changing only the model field
        # would leave its internal HTTP retries enabled.
        if model.root_client is not None:
            client = model.root_client.with_options(max_retries=0)
            updates.update(root_client=client, client=client.chat.completions)
        if model.root_async_client is not None:
            client = model.root_async_client.with_options(max_retries=0)
            updates.update(root_async_client=client, async_client=client.chat.completions)
        model = model.model_copy(update=updates)
        response = model.with_structured_output(schema, include_raw=True).invoke(
            [("system", system_message), ("human", human_message)], config=config)
        raw_usage = getattr(response.get("raw"), "usage_metadata", None)
        if raw_usage:
            call["usage"] = {key: int(raw_usage.get(key, 0)) for key in ("input_tokens", "output_tokens")}
        if response.get("parsing_error") or response.get("parsed") is None:
            raise ValueError("The model did not return valid structured output.")
        result = response["parsed"]
        return result if isinstance(result, schema) else schema.model_validate(result)
    structured_model = model.with_structured_output(schema)
    result = structured_model.invoke(
        [("system", system_message), ("human", human_message)], config=config
    )
    if isinstance(result, schema):
        return result
    return schema.model_validate(result)
