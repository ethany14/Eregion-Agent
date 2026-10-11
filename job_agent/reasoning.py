"""Purpose configuration and bounded retry policy; no provider IO."""
import os
import re
from contextlib import contextmanager
from contextvars import ContextVar

_cache_observers = ContextVar('reasoning_cache_observers', default=())

LEVELS = {'none', 'minimal', 'low', 'medium', 'high'}
SCHEMA_PURPOSES = {
    'ClaimDecisions': 'claim_verifier', 'CoverLetter': 'pack_writer',
    'ApplicationAnswer': 'pack_writer', 'TailoredResume': 'pack_writer',
    'ResumeSelection': 'pack_writer', 'FactualVerificationResult': 'claim_verifier',
    'VerificationResult': 'claim_verifier', 'RelevantMemories': 'memory_relevance',
    'QuestionCategory': 'question_category', 'PastedJobText': 'job_screening',
    'MockInterviewQuestion': 'interview_question', 'MockAnswerEvaluation': 'interview_feedback',
    'CompactSkillAssessment': 'scoring', 'SkillAssessment': 'scoring',
    'ResumeExtraction': 'extraction', 'ReferencedJobExtraction': 'extraction',
    'ResumeAnalysis': 'extraction', 'JobAnalysis': 'extraction',
    'UnknownResolution': 'jev_fit_resolver',
}


def purpose_key(purpose):
    text = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', purpose or 'none')
    return 'LLM_REASONING_' + re.sub(r'[^a-zA-Z0-9]+', '_', text).strip('_').upper()


def resolve(settings, purpose, fallback=None):
    value = settings.get(purpose_key(purpose))
    value = str(value).strip() if value is not None else ''
    value = value or fallback
    if value is not None and value not in LEVELS:
        raise ValueError(f'{purpose_key(purpose)} has an unsupported reasoning level.')
    return value


def escalated(level):
    return {'low': 'medium', 'medium': 'high'}.get(level, level)


def escalation_enabled():
    return os.getenv('JOB_AGENT_REASONING_ESCALATION') == '1'


REJECTION_WORDING = re.compile(r'unsupported|not supported|does not support|unknown|unrecognized|unrecognised|'
    r'invalid|not allowed|not permitted|extra (?:inputs?|fields?)', re.I)


def reasoning_rejection_text(status, text):
    """A 400/422 response that names the reasoning parameter as unsupported."""
    text = str(text or '')
    return (status in (400, 422) and re.search(r'reasoning', text, re.I) is not None
            and REJECTION_WORDING.search(text) is not None)


def reasoning_parameter_rejected(exc):
    status = getattr(exc, 'status_code', None)
    if status is None:
        status = getattr(getattr(exc, 'response', None), 'status_code', None)
    return reasoning_rejection_text(status, exc)


def rejection_retry_enabled():
    return os.getenv('JOB_AGENT_REASONING_REJECTION_RETRY') == '1'


def configured_overrides(settings=None):
    return {k: v for k, v in (os.environ if settings is None else settings).items()
            if k.startswith('LLM_REASONING_') and str(v or '').strip()}


def cacheable_attempts(attempts):
    """A changed effective level must not populate the original level's key."""
    return not any(a.get('reasoning_escalation') or a.get('reasoning_fallback') for a in attempts)


def mark_uncacheable():
    for observer in _cache_observers.get():
        observer[0] = True


@contextmanager
def cache_observation():
    """Propagate changed levels through nested caches and shared worker results."""
    from agent_runtime.provider_usage import capture_provider_attempts
    changed = [False]
    token = _cache_observers.set((*_cache_observers.get(), changed))
    with capture_provider_attempts() as attempts:
        eligible = lambda: not changed[0] and cacheable_attempts(attempts)
        try:
            yield eligible
        finally:
            safe = eligible()
            _cache_observers.reset(token)
            if not safe:
                mark_uncacheable()
