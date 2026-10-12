"""LinkedIn read-only source over the project's MCP manager (R7, T0 contract).

Wraps stickerdaniel/linkedin-mcp-server @ 5bdef1c9 (pyproject 4.27.0) business
tools. It is not wired into source selection: adoption needs the T1 (real
read-only) and T2 (agent comparison) gates, which require an explicitly chosen
LinkedIn account. Nothing here logs in, applies, messages or reads profiles.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

SERVER_ID = 'linkedin'
BUSINESS_TOOLS = frozenset({'search_jobs', 'get_job_details', 'get_job_apply_url',
                            'search_companies', 'get_company_profile'})
LIFECYCLE_TOOLS = frozenset({'close_session'})
EXPERIENCE_LEVELS = frozenset({'internship', 'entry', 'associate', 'mid_senior', 'director', 'executive'})
MAX_PAGES = 2                 # T1: at most two pages per search group
DEFAULT_DEADLINE = 120.0      # seconds per tool call (T1)
DEFAULT_CALL_BUDGET = 26      # T1 batch: 3 searches + 15 details + 6 apply URLs + 2 company lookups
MAX_RESPONSE_BYTES = 2_000_000

_STOP = (('rate_limited', re.compile(r'rate.?limit|too many requests|\b429\b', re.I)),
         ('auth_required', re.compile(r'log ?in|sign ?in|authenticat|checkpoint|challenge|captcha|verify', re.I)))


class LinkedInSourceStopped(RuntimeError):
    """The source is stopped for this batch; it must not be retried through another channel."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f'LinkedIn MCP source stopped: {reason}')


def job_url(job_id: str) -> str:
    return f'https://www.linkedin.com/jobs/view/{job_id}/'


class LinkedInMcpSource:
    """Adapter with a per-batch call budget, per-call deadline and stop conditions.

    call(server_id, tool, arguments, timeout_seconds=...) is McpToolManager.call_tool.
    store is a mutable mapping persisted by the caller, so a restart keeps the
    batch counters and stop reason (a restart never resets the budget).
    """

    def __init__(self, call: Callable[..., Any], *, store: dict | None = None, server_id: str = SERVER_ID,
                 call_budget: int = DEFAULT_CALL_BUDGET, deadline_seconds: float = DEFAULT_DEADLINE,
                 max_response_bytes: int = MAX_RESPONSE_BYTES):
        self._call, self.server_id = call, server_id
        self.store = store if store is not None else {}
        self.store.setdefault('calls_used', 0)
        self.store.setdefault('stopped', None)
        self.store.setdefault('log', [])
        self.call_budget, self.deadline, self.max_bytes = call_budget, deadline_seconds, max_response_bytes

    # -- business operations --------------------------------------------------------

    def search(self, keywords: str, location: str | None = None, *, experience_level: str | None = None,
               max_pages: int = 1) -> dict:
        args: dict[str, Any] = {'keywords': keywords, 'max_pages': max(1, min(int(max_pages), MAX_PAGES))}
        if location:
            args['location'] = location
        unapplied = []
        if experience_level:
            levels = [v.strip() for v in experience_level.split(',') if v.strip()]
            if levels and all(v in EXPERIENCE_LEVELS for v in levels):
                args['experience_level'] = ','.join(levels)
            else:
                unapplied.append('experience_level')  # never pretend an unsupported filter was applied
        payload = self._invoke('search_jobs', args)
        errors = payload.get('section_errors') or {}
        if any((e or {}).get('type') == 'no_matching_jobs' for e in errors.values() if isinstance(e, dict)):
            return {'status': 'no_match', 'jobs': [], 'partial': False, 'unapplied_filters': unapplied}
        jobs, dropped = [], 0
        for raw in payload.get('job_ids') or []:
            job_id = str(raw)
            if not re.fullmatch(r'\d{5,20}', job_id):
                dropped += 1
                continue
            jobs.append({'url': job_url(job_id), 'provider_job_id': job_id, 'source': 'linkedin_mcp',
                         'completeness': 'card', 'title': None, 'company': None, 'location': None})
        jobs = list({j['provider_job_id']: j for j in jobs}.values())
        total = payload.get('total') or {}
        return {'status': 'partial' if errors else 'ok', 'jobs': jobs, 'partial': bool(errors),
                'section_errors': sorted(errors), 'dropped_without_identity': dropped,
                'total': total.get('count'), 'total_exact': total.get('exact'),
                'unapplied_filters': unapplied}

    def details(self, job_id: str) -> dict:
        payload = self._invoke('get_job_details', {'job_id': str(job_id)})
        sections = payload.get('sections') or {}
        errors = payload.get('section_errors') or {}
        apply = payload.get('apply') or {}
        text = '\n\n'.join(str(v) for v in sections.values() if v).strip()
        missing = any((e or {}).get('type') == 'description_missing' for e in errors.values() if isinstance(e, dict))
        if apply.get('type') == 'closed':
            status = 'closed'
        elif missing or not text:
            status = 'description_missing'   # text kept for evidence, never a complete JD
        else:
            status = 'complete_jd'
        return {'status': status, 'url': payload.get('url') or job_url(job_id), 'provider_job_id': str(job_id),
                'description': text if status == 'complete_jd' else None, 'evidence_text': text,
                'apply_status': apply.get('type') or 'unknown', 'source': 'linkedin_mcp'}

    def apply_url(self, job_id: str) -> dict:
        payload = self._invoke('get_job_apply_url', {'job_id': str(job_id)})
        apply = payload.get('apply') or {}
        url = apply.get('url') if apply.get('type') == 'external' else None
        return {'type': apply.get('type') or 'unknown', 'url': url, 'source': 'linkedin_mcp'}

    def search_companies(self, keywords: str) -> dict:
        return self._invoke('search_companies', {'keywords': keywords})

    def company_profile(self, company_name: str) -> dict:
        return self._invoke('get_company_profile', {'company_name': company_name})

    # -- guarded invocation ------------------------------------------------------------

    def _invoke(self, tool: str, arguments: dict) -> dict:
        if tool not in BUSINESS_TOOLS:
            raise ValueError(f'{tool} is not a LinkedIn business tool in scope.')
        if self.store['stopped']:
            raise LinkedInSourceStopped(self.store['stopped'])
        if self.store['calls_used'] >= self.call_budget:
            raise LinkedInSourceStopped('call_budget_exhausted')
        self.store['calls_used'] += 1  # counted before sending: retries and failures use the budget
        entry = {'tool': tool, 'arguments': {k: v for k, v in arguments.items()}, 'outcome': 'pending'}
        self.store['log'].append(entry)
        try:
            result = self._call(self.server_id, tool, arguments, timeout_seconds=self.deadline)
        except Exception as exc:
            name = type(exc).__name__
            if 'Timeout' in name:
                # An outer timeout does not prove the browser stopped: no next call until
                # the caller confirms cancellation/recycling and clears the stop.
                entry['outcome'] = 'timeout_unconfirmed'
                self._stop('timeout_cancel_unconfirmed')
            else:
                entry['outcome'] = 'transport_error'
            raise
        payload, error_text = self._payload(result)
        if getattr(result, 'is_error', False):
            entry['outcome'] = 'tool_error'
            for reason, pattern in _STOP:
                if pattern.search(error_text):
                    entry['outcome'] = reason
                    self._stop(reason)
                    raise LinkedInSourceStopped(reason)
            raise RuntimeError('LinkedIn MCP tool reported an error.')
        entry['outcome'] = 'ok'
        return payload

    def confirm_cancelled(self) -> None:
        """Called after the MCP session was confirmed stopped/recycled following a timeout."""
        if self.store['stopped'] == 'timeout_cancel_unconfirmed':
            self.store['stopped'] = None

    def _stop(self, reason: str) -> None:
        self.store['stopped'] = reason

    def _payload(self, result) -> tuple[dict, str]:
        structured = getattr(result, 'structured_content', None)
        texts = [getattr(c, 'text', None) if not isinstance(c, dict) else c.get('text')
                 for c in getattr(result, 'content', None) or []]
        texts = [t for t in texts if isinstance(t, str)]
        size = sum(len(t.encode('utf-8')) for t in texts) + len(json.dumps(structured, default=str).encode('utf-8'))
        if size > self.max_bytes:
            self.store['log'][-1]['outcome'] = 'oversized'
            raise ValueError('LinkedIn MCP response exceeded the size limit; not parsed.')
        if isinstance(structured, dict):
            return structured, ' '.join(texts)
        for text in texts:
            try:
                value = json.loads(text)
            except ValueError:
                continue
            if isinstance(value, dict):
                return value, ' '.join(texts)
        return {}, ' '.join(texts)
