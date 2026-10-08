"""Shared model timing and safe failure classification, independent of a provider."""
from dataclasses import dataclass


def model_timeout(model, default=45.0):
    value = getattr(model, "request_timeout", None)
    if isinstance(value, (int, float)) and value > 0:
        return float(value)
    return default


@dataclass(frozen=True)
class ModelFailure:
    code: str
    retryable: bool
    error_type: str
    status: int | None = None


def model_failure(error):
    """Follow adapter causes without exposing provider bodies or credentials."""
    seen = set()
    while error.__cause__ is not None and id(error) not in seen:
        seen.add(id(error))
        error = error.__cause__
    name = type(error).__name__
    status = getattr(error, "status_code", None)
    status = status if isinstance(status, int) else None
    if isinstance(error, TimeoutError) or "timeout" in name.casefold():
        return ModelFailure("model_timeout", True, name, status)
    if status == 429:
        return ModelFailure("model_rate_limited", True, name, status)
    if isinstance(error, ConnectionError) or "connection" in name.casefold() or (status and status >= 500):
        return ModelFailure("model_unavailable", True, name, status)
    return ModelFailure("model_error", False, name, status)
