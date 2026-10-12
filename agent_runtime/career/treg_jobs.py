"""Map Treg search/scrape responses onto our candidate and evidence shape (P4d / B1).

Search results are candidates (cards), never complete job descriptions. A scrape is a
complete JD only when the text is bound to the target job and passes conservative checks;
an HTTP 200 or non-empty Markdown is not enough. Missing fields stay unknown.
"""
from datetime import UTC, datetime
import hashlib
import re
from urllib.parse import urlsplit

SEARCH_ENDPOINTS = {'anyapi': 'anyapi.linkedin.search.jobs', 'crawl4ai': 'crawl4ai.linkedin.search.jobs'}
SCRAPE_ENDPOINT = 'crawl4ai.web.scrape'
POSTED = {'24h': ('24h', 'day'), 'week': ('week', 'week'), 'month': ('month', 'month')}
LINKEDIN_ID = re.compile(r'(?:-|/|currentJobId=)(\d{8,12})(?:[/?#]|$)')


def linkedin_job_id(url):
    match = LINKEDIN_ID.search(url or '')
    return match.group(1) if match else None


def canonical_url(url, job_id=None):
    host = (urlsplit(url or '').hostname or '').lower()
    if job_id and host.endswith('linkedin.com'):
        return f'https://www.linkedin.com/jobs/view/{job_id}/'
    return url


def search_body(provider, query, location=None, posted=None):
    """Same common inputs for both providers; anything without an equivalent is not applied."""
    if provider == 'anyapi':
        body = {'query': query}
        if location: body['location'] = location
        if posted: body['postedLimit'] = POSTED[posted][0]
    else:
        body = {'query': query, 'limit': 10}
        if location: body['location'] = location
        if posted: body['posted'] = POSTED[posted][1]
    return body


def normalize_search(provider, payload, *, fetched_at=None, max_results=10):
    """Return (candidates, info). Candidates have stable identity or are dropped."""
    fetched_at = fetched_at or datetime.now(UTC).isoformat()
    if provider == 'anyapi':
        output = (payload or {}).get('output') or {}
        items = ((output.get('data') or {}).get('items')) or []
        cursor = output.get('nextCursor') or (payload or {}).get('nextCursor')
    else:
        items = (payload or {}).get('rows') or []
        cursor = None
    candidates, dropped = [], 0
    for item in items:
        if not isinstance(item, dict):
            dropped += 1
            continue
        url = item.get('url')
        job_id = str(item.get('id') or item.get('job_id') or '') or linkedin_job_id(url)
        if not url or not job_id or not url.startswith('https://'):
            dropped += 1  # no stable identity: never invent one
            continue
        posted = None
        if provider == 'anyapi' and isinstance(item.get('createdUtc'), (int, float)):
            posted = datetime.fromtimestamp(item['createdUtc'], UTC).date().isoformat()
        elif provider == 'crawl4ai' and item.get('posted_on'):
            posted = str(item['posted_on'])[:10]
        candidates.append({
            'url': canonical_url(url, job_id), 'original_url': url, 'provider_job_id': job_id,
            'title': item.get('title') or None, 'company': item.get('company') or None,
            'location': item.get('location') or None, 'posted_on': posted,
            'posted_precision': 'day' if posted else None,
            'source': f'treg:{provider}', 'source_endpoint': SEARCH_ENDPOINTS[provider],
            'fetched_at': fetched_at, 'completeness': 'card'})
    unique = list({c['provider_job_id']: c for c in candidates}.values())
    meta = (payload or {}).get('meta') if provider == 'crawl4ai' else None
    meta = meta if isinstance(meta, dict) else {}
    warnings = meta.get('warnings') or []
    return unique[:max_results], {'raw_items': len(items), 'dropped_without_identity': dropped,
                                  'unique': len(unique), 'next_cursor': bool(cursor),
                                  # Provider coverage signals; unknown stays unknown, never "complete".
                                  'source_blocked': bool(meta.get('blocked')),
                                  'partial': bool(meta.get('partial')),
                                  'warnings': len(warnings) if isinstance(warnings, list) else 1}


BLOCK = re.compile(r'sign in to (?:view|see)|join (?:now )?to see|log ?in to|captcha|verify you are human|'
                   r'are you a robot|access denied|this job is no longer|no longer accepting applications', re.I)
SECTION = re.compile(r'responsibilit|requirement|qualification|what you.ll|about the role|you will|experience', re.I)


OTHER_JOBS = re.compile(r'\n#{1,3}\s*(?:similar jobs|people also viewed|more searches|explore (?:top|collaborative)|'
                        r'similar searches|explore more opportunities)', re.I)
JOB_LINK = re.compile(r'/jobs/view/[^\s)\]]*?\d{8,12}')


def posting_text(markdown):
    """Cut a job page at the first list of OTHER jobs; those must never be scored as this JD."""
    match = OTHER_JOBS.search(markdown or '')
    return (markdown or '')[:match.start()] if match else (markdown or '')


def assess_scrape(target, payload):
    """Judge whether a scrape is one complete, open job description for target."""
    payload = payload if isinstance(payload, dict) else {}
    raw = payload.get('markdown') or ''
    text = posting_text(raw)
    checks = {'ok_flag': payload.get('ok') is True, 'length': len(text) >= 800,
              'sections': len(set(m.group(0).lower()[:6] for m in SECTION.finditer(text))) >= 2,
              'not_blocked': not BLOCK.search(text[:4000]),
              'title_bound': _title_overlap(target.get('title'), text[:6000]) >= 0.7,
              # The page's own header/criteria may link back to itself; a list of other jobs may not.
              'single_job': len(set(JOB_LINK.findall(text))) <= 3}
    closed = bool(re.search(r'no longer accepting applications|this job is no longer available|position (?:has been )?filled',
                            text, re.I))
    complete = all(checks.values()) and not closed
    return {'complete': complete, 'closed_signal': closed, 'checks': checks, 'text_len': len(text),
            'raw_len': len(raw), 'trimmed_other_jobs': len(raw) - len(text), 'description_text': text if complete else None,
            'content_hash': hashlib.sha256(text.encode()).hexdigest(),
            'cache': payload.get('cache'), 'engine': payload.get('engine'),
            'status': 'complete_jd' if complete else 'closed' if closed else 'blocked' if not checks['not_blocked']
                      else 'insufficient'}


def _words(text):
    return {w for w in re.findall(r'[a-z0-9]+', (text or '').lower()) if len(w) > 2}


def _title_overlap(title, text):
    words = _words(title) - _stop()
    return len(words & _words(text)) / len(words) if words else 0.0


def _stop():
    return {'and', 'the', 'for', 'with', 'senior', 'junior', 'remote', 'hybrid'}
