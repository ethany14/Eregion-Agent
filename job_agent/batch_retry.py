"""One transport retry for the failed analysis batch, never the whole score."""
from agent_runtime.model_runtime import model_failure
from agent_runtime.provider_usage import usage_scope
from job_agent.reasoning import escalation_enabled


def retry_batch(compute):
    for attempt in (1, 2):
        try:
            with usage_scope(attempt=attempt, reasoning_retry=attempt == 2, reasoning_retry_owner=True,
                             **({'queue_wait_seconds': 0.0} if attempt == 2 else {})):
                return compute()
        except Exception as exc:
            failure = model_failure(exc)
            from pydantic import ValidationError
            from langchain_core.exceptions import OutputParserException
            validation = isinstance(exc, (ValidationError, OutputParserException)) or (
                isinstance(exc, ValueError) and str(exc) == 'The model did not return valid structured output.')
            if attempt == 2 or (failure.code not in {'model_timeout', 'model_unavailable'}
                               and not (escalation_enabled() and validation)):
                raise
