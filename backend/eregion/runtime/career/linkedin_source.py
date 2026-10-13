"""LinkedIn read-only source over the project's MCP manager (R7, T0 contract).

Wraps stickerdaniel/linkedin-mcp-server @ 5bdef1c9 (pyproject 4.27.0) business
tools. Career source selection uses this adapter when an explicitly configured
LinkedIn server is available. Nothing here logs in, applies, messages or reads profiles.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlsplit, urljoin
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
MIN_POSTING_CHARS = 400     # a real 'About the job' section; shorter is not a complete JD

_STOP = (('rate_limited', re.compile(r'rate.?limit|too many requests|\b429\b', re.I)),
         ('auth_required', re.compile(r'log ?in|sign ?in|authenticat|checkpoint|challenge|captcha|verify', re.I)))


class LinkedInSourceStopped(RuntimeError):
    """The source is stopped for this batch; it must not be retried through another channel."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f'LinkedIn MCP source stopped: {reason}')


def job_url(job_id: str) -> str:
    return f'https://www.linkedin.com/jobs/view/{job_id}/'


def _matches_job_url(url: str, job_id: str) -> bool:
    """Bind evidence to a public LinkedIn posting, not a substring in another URL."""
    if not re.fullmatch(r'[0-9]{5,20}', job_id):
        return False
    try:
        parsed = urlsplit(url)
        return (parsed.scheme == 'https'
                and parsed.hostname in {'linkedin.com', 'www.linkedin.com'}
                and parsed.username is None and parsed.password is None
                and parsed.port in (None, 443)
                and parsed.path in {f'/jobs/view/{job_id}', f'/jobs/view/{job_id}/'})
    except ValueError:
        return False


def search_cards(payload):
    """Bind titles by reference URL; recover adjacent card fields only when unambiguous."""
    lines=[line.strip() for line in str((payload.get('sections') or {}).get('search_results') or '').splitlines() if line.strip()]
    refs=(payload.get('references') or {}).get('search_results') or []
    cards={}
    titles={r.get('text') for r in refs if isinstance(r,dict) and r.get('kind')=='job'}
    for ref in refs:
        if not isinstance(ref,dict) or ref.get('kind')!='job':continue
        url=urljoin('https://www.linkedin.com',str(ref.get('url') or ''))
        match=re.fullmatch(r'/jobs/view/([0-9]{5,20})/?',urlsplit(url).path)
        if not match or not _matches_job_url(url,match[1]):continue
        title=str(ref.get('text') or '').strip()
        if not title:continue
        card={'title':title,'company':None,'location':None}
        if lines.count(title)==1:
            i=lines.index(title)
            if i+2<len(lines):
                company,location=lines[i+1:i+3]
                # A location-shaped line prevents treating a UI badge as company/place.
                if (company not in titles and location not in titles
                    and re.search(r',|\((?:Remote|Hybrid|On-site)\)$',location,re.I)
                    and company.casefold() not in {'promoted','easy apply','viewed','saved'}):
                    card.update(company=company,location=location)
        cards[match[1]]=card
    return cards


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
        cards=search_cards(payload)
        jobs, dropped = [], 0
        for raw in payload.get('job_ids') or []:
            job_id = str(raw)
            if not re.fullmatch(r'\d{5,20}', job_id):
                dropped += 1
                continue
            jobs.append({'url': job_url(job_id), 'provider_job_id': job_id, 'source': 'linkedin_mcp',
                         'completeness': 'card', 'title': None, 'company': None, 'location': None, **cards.get(job_id,{})})
        jobs = list({j['provider_job_id']: j for j in jobs}.values())
        total = payload.get('total') or {}
        return {'status': 'partial' if errors else 'ok', 'jobs': jobs, 'partial': bool(errors),
                'section_errors': sorted(errors), 'dropped_without_identity': dropped,
                'total': total.get('count'), 'total_exact': total.get('exact'),
                'unapplied_filters': unapplied}

    def details(self, job_id: str) -> dict:
        """Complete only when the job_posting section itself is present, long enough, bound to
        this job id and has no section error; anything else keeps evidence but is incomplete."""
        job_id = str(job_id)
        payload = self._invoke('get_job_details', {'job_id': job_id})
        sections = payload.get('sections') or {}
        errors = payload.get('section_errors') or {}
        apply = payload.get('apply') or {}
        posting = str(sections.get('job_posting') or '').strip()
        from .posting_text import scope
        scoped=scope(posting)
        evidence = '\n\n'.join(f'[{name}]\n{value}' for name, value in sections.items() if value).strip()
        reasons = []
        if 'job_posting' in errors:
            error = errors['job_posting']
            reasons.append('job_posting_' + (error.get('type') if isinstance(error, dict) and error.get('type')
                                             else 'error'))
        if not posting:
            reasons.append('job_posting_missing')
        elif len(scoped['text']) < MIN_POSTING_CHARS:
            reasons.append('job_posting_too_short')
        url = str(payload.get('url') or '')
        if not _matches_job_url(url, job_id):
            reasons.append('identity_unverified')  # the page must be this job, not a redirect or another posting
        if apply.get('type') == 'closed':
            status = 'closed'
        elif reasons:
            status = 'incomplete'
        else:
            status = 'complete_jd'
        return {'status': status, 'incomplete_reasons': reasons, 'url': url or job_url(job_id),
                'provider_job_id': job_id, 'description': scoped['text'] if status == 'complete_jd' else None,
                'raw_posting':posting,'posting_scope':{k:v for k,v in scoped.items() if k!='text'},
                'evidence_text': evidence, 'section_errors': sorted(errors),
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
