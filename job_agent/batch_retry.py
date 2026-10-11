"""One transport retry for the failed analysis batch, never the whole score."""
from agent_runtime.model_runtime import model_failure
from agent_runtime.provider_usage import usage_scope


def retry_batch(compute):
    for attempt in (1, 2):
        try:
            with usage_scope(attempt=attempt):
                return compute()
        except Exception as exc:
            failure = model_failure(exc)
            if attempt == 2 or failure.code not in {'model_timeout', 'model_unavailable'}:
                raise
