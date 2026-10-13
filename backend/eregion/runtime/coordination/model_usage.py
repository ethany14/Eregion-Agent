"""Attempt-scoped model accounting, including nested adapters and retries."""
from contextlib import contextmanager
from contextvars import ContextVar

from eregion.runtime.context.budget import estimate_tokens

_meter = ContextVar("task_model_meter", default=None)
_call = ContextVar("task_model_call", default=None)


@contextmanager
def model_usage_scope(repository, task_id, attempt_id):
    token = _meter.set((repository, task_id, attempt_id))
    try:
        yield
    finally:
        _meter.reset(token)


def current_model_call():
    return _call.get()


def _serializable(value):
    if isinstance(value, type):
        return value.__name__
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, (list, tuple)):
        return [_serializable(item) for item in value]
    if isinstance(value, dict):
        return {key: _serializable(item) for key, item in value.items()}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return type(value).__name__


def invoke_model(function, *args, **kwargs):
    meter = _meter.get()
    if meter is None or _call.get() is not None:
        return function(*args, **kwargs)
    repository, task_id, attempt_id = meter
    input_estimate = estimate_tokens(_serializable([args, kwargs]))
    reservation = repository.reserve_model_call(task_id, attempt_id, input_tokens=input_estimate)
    call = {**reservation, "usage": None}
    token = _call.set(call)
    try:
        try:
            result = function(*args, **kwargs)
        except Exception:
            if call["usage"] is not None:
                repository.finish_model_call(task_id, attempt_id, reservation, **call["usage"])
            raise
        usage = call["usage"] or {"input_tokens": input_estimate,
                                  "output_tokens": estimate_tokens(_serializable(result))}
        repository.finish_model_call(task_id, attempt_id, reservation, **usage)
        return result
    finally:
        # Failed/uncertain calls retain their durable reservation. Recovery must
        # not reset their spend or release capacity while a provider may be active.
        _call.reset(token)
