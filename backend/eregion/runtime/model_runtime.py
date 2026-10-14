"""Shared model timing and safe failure classification, independent of a provider."""
from dataclasses import dataclass
import httpcore
import httpx


MODEL_PAYMENT_MESSAGE = (
    "The model provider requires payment or available credits (HTTP 402). "
    "Check the provider balance or billing, then continue. Your work is saved."
)


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
    retry_after: float | None = None


def retry_after(error):
    """Seconds from a provider's Retry-After header, when it sent one."""
    headers = getattr(getattr(error, "response", None), "headers", None) or {}
    try:
        value = float(headers.get("retry-after") or headers.get("Retry-After"))
    except (TypeError, ValueError, AttributeError):
        return None
    return value if 0 < value <= 3600 else None


def model_failure(error):
    """Follow adapter causes without exposing provider bodies or credentials."""
    # Classify across the whole cause chain: the root may be a transport class of
    # another library (httpcore.ConnectError under OpenAIConnectionError) that the
    # root alone does not identify (acceptance tiered-v3-03 stopped on one).
    chain, seen = [], set()
    while error is not None and id(error) not in seen:
        seen.add(id(error)); chain.append(error); error = error.__cause__
    root = chain[-1]
    name = type(root).__name__
    def status_of(item):
        value = getattr(item, "status_code", None)
        return value if isinstance(value, int) else None
    status = next((status_of(item) for item in reversed(chain) if status_of(item) is not None), None)
    names = [type(item).__name__.casefold() for item in chain]
    if status == 402:
        return ModelFailure("model_payment_required", False, name, status)
    if status == 429:
        return ModelFailure("model_rate_limited", True, name, status, retry_after(next(i for i in chain if status_of(i) == 429)))
    if any(isinstance(item, TimeoutError) for item in chain) or any("timeout" in n for n in names):
        return ModelFailure("model_timeout", True, name, status)
    transport = (ConnectionError, httpx.NetworkError, httpx.ProxyError, httpcore.NetworkError, httpcore.ProxyError)
    if (any(isinstance(item, transport) for item in chain) or any("connection" in n for n in names)
            or (status and status >= 500)):
        return ModelFailure("model_unavailable", True, name, status)
    return ModelFailure("model_error", False, name, status)


class ResponseFormatError(ValueError):
    """The provider answered, but the structured reply is unusable (identities, schema)."""


def recoverable_failure(error):
    """True only for a transport failure or an unusable response format.

    Authentication, payment, rate limits, configuration, programming errors,
    cancellation and budget stops are never retried, and a well-formed semantic
    answer is never retried for a more favourable verdict.
    """
    if not isinstance(error, Exception):
        return False   # BaseException: budget stops, cancellation, interpreter exit
    seen, current = set(), error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, ResponseFormatError):
            return True
        try:
            from pydantic import ValidationError
            from langchain_core.exceptions import OutputParserException
            if isinstance(current, (ValidationError, OutputParserException)):
                return True
        except ImportError:
            pass
        if isinstance(current, ValueError) and str(current) == 'The model did not return valid structured output.':
            return True
        current = current.__cause__ or current.__context__
    return model_failure(error).code in {'model_timeout', 'model_unavailable'}
