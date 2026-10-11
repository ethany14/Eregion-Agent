"""Main-model decisions for requirements Jev left unresolved.

Jev answers every question it can with calibrated confidence. Only requirements
whose status is still `unknown` afterwards are sent here, in one structured call
per job. A matched/partial verdict must quote the candidate evidence verbatim;
an unverifiable quote leaves the requirement unknown rather than inventing support.
"""
import hashlib
import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from .core import POLICY, score


class UnknownDecision(BaseModel):
    requirement_id: str
    is_candidate_requirement: bool = Field(description='False for company descriptions, duties, benefits, salary, EEO or legal text.')
    level: Literal['required', 'preferred']
    personal_condition: bool = Field(description='True for work authorization, sponsorship, consent, availability, location or willingness.')
    status: Literal['matched', 'partial', 'missing']
    evidence_quote: str | None = Field(default=None, description='Exact contiguous text copied from the candidate evidence. Required for matched or partial.')
    reason: str = Field(max_length=400)


class UnknownResolution(BaseModel):
    decisions: list[UnknownDecision]


PROMPT = POLICY + '''
You resolve job requirements that an earlier classifier could not decide.
For each requirement: decide whether it is a real candidate qualification (not a duty, benefit,
salary, company description or EEO/legal text), whether it is preferred or required, whether it is a
personal condition, and whether the candidate evidence fully establishes it (matched), shows related
but incomplete experience (partial), or does not establish it (missing).
Matched requires every stated component and qualifier, including years, level and degree completion.
For matched or partial, evidence_quote must be copied exactly from the candidate evidence.
Return one decision for every requirement_id supplied, and no others.'''


def identity(enabled):
    from job_agent.model import model_settings_fingerprint
    code = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return hashlib.sha256(repr([bool(enabled), code, model_settings_fingerprint() if enabled else None]).encode()).hexdigest()


_GLYPHS = str.maketrans({**{chr(c): ' ' for c in [*range(0, 9), 11, 12, *range(14, 32), 127]},
                         '•': ' ', '▪': ' ', '■': ' ', '◦': ' ', '●': ' ', '·': ' ', '': ' ',
                         '‘': "'", '’': "'", '“': '"', '”': '"', '–': '-', '—': '-', ' ': ' '})


def locate(quote, text):
    """Exact quote position in the original text.

    Every word must match. Only presentation differences are tolerated: line
    wraps, PDF bullet/control glyphs (extractors emit e.g. \\x7f, models echo
    \\x07), curly quotes and dash variants. The 1:1 character mapping keeps
    offsets pointing at the original source.
    """
    words = (quote or '').translate(_GLYPHS).split()
    if not words:
        return None
    match = re.search(r'\s+'.join(re.escape(word) for word in words), text.translate(_GLYPHS))
    return (match.start(), match.end()) if match else None


class DecisionStore:
    """Persist resolver decisions so a requirement decided once stays decided.

    Without this, Jev's short-lived uncertain answers would re-trigger the main
    model every few minutes and the same job could drift between scores.
    """
    TTL = 86400

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS resolver_decisions (key TEXT PRIMARY KEY, body TEXT NOT NULL, expires REAL NOT NULL)')

    def _db(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.execute('PRAGMA busy_timeout=15000')
        return db

    def get_many(self, keys):
        if not keys:
            return {}
        with self._db() as db:
            rows = db.execute('SELECT key, body FROM resolver_decisions WHERE expires > ? AND key IN (%s)' % ','.join('?' * len(keys)),
                              [time.time(), *keys]).fetchall()
        found = {}
        for key, body in rows:
            try:
                found[key] = UnknownDecision.model_validate_json(body)
            except ValueError:
                continue  # A corrupt or old-format row is a miss.
        return found

    def put_many(self, items):
        if not items:
            return
        with self._db() as db:
            db.executemany('INSERT OR REPLACE INTO resolver_decisions VALUES (?, ?, ?)',
                           [(key, decision.model_dump_json(), time.time() + self.TTL) for key, decision in items.items()])


def decision_key(evidence, match):
    """Same resolver/model, same evidence, same requirement wording -> same decision."""
    return hashlib.sha256(json.dumps([identity(True), hashlib.sha256(evidence.encode()).hexdigest(),
        ' '.join(match['text'].split()), match['level']]).encode()).hexdigest()


def resolve_unknowns(raw, evidence, *, model, invoke=None, store=None):
    targets = {m['requirement_id']: m for m in raw.get('matches', []) if m['status'] == 'unknown'}
    if not targets:
        return raw
    if invoke is None:
        from job_agent.model import invoke_structured as invoke
    keys = {rid: decision_key(evidence, m) for rid, m in targets.items()}
    cached = store.get_many(list(keys.values())) if store else {}
    decisions = [cached[keys[rid]].model_copy(update={'requirement_id': rid}) for rid in targets if keys[rid] in cached]
    pending = {rid: m for rid, m in targets.items() if keys[rid] not in cached}
    calls = 0
    if pending:
        calls = 1
        request = '\n'.join(['CANDIDATE EVIDENCE:', evidence, '', 'UNRESOLVED REQUIREMENTS:',
            *[f'- {key} [{m["level"]}]: {m["text"]}' for key, m in pending.items()]])
        try:
            result = invoke(model, UnknownResolution, PROMPT, request)
        except Exception as exc:  # Keep Jev's honest interval; never fail the whole analysis.
            if not decisions:
                return {**raw, 'resolver': {'status': 'failed', 'error': type(exc).__name__}, 'main_model_calls': 1}
            result = UnknownResolution(decisions=[])
        fresh = [d for d in result.decisions if d.requirement_id in pending]
        if store:
            store.put_many({keys[d.requirement_id]: d for d in fresh})
        decisions += fresh
    ledger = {item['id']: item for item in raw.get('extraction', [])}
    resolved, dropped = 0, set()
    for decision in decisions:
        match = targets.get(decision.requirement_id)
        if match is None:
            continue
        unit = ledger.get(decision.requirement_id)
        if not decision.is_candidate_requirement:
            dropped.add(decision.requirement_id)
            if unit is not None:
                unit['classification'] = 'context'
            resolved += 1
            continue
        status = 'needs_confirmation' if decision.personal_condition else decision.status
        citation = None
        if status in ('matched', 'partial'):
            span = locate(decision.evidence_quote, evidence)
            if span is None:
                continue  # An unverifiable quote cannot become support.
            text = evidence[span[0]:span[1]]
            citation = {'source_id': 'main_model_quote', 'exact_text': text, 'spans': [list(span)],
                        'sha256': hashlib.sha256(text.encode()).hexdigest()}
        match.update(status=status, level=decision.level, weight=1 if decision.level == 'preferred' else 2,
                     reason='Resolved by the main model after Jev left it uncertain: ' + decision.reason,
                     resolved_by='main_model', citations=[citation] if citation else [],
                     citation_scope='verified_excerpt' if citation else None)
        if unit is not None and unit['classification'] == 'unknown':
            unit['classification'] = decision.level
        resolved += 1
    matches = [m for m in raw['matches'] if m['requirement_id'] not in dropped]
    totals = score(matches)
    if any(item['classification'] == 'unknown' for item in ledger.values()):
        totals['score'] = None
    status = 'needs_review' if raw.get('provider_errors') or not matches or totals['score'] is None else 'completed'
    return {**raw, **totals, 'matches': matches, 'status': status, 'main_model_calls': calls,
            'resolver': {'status': 'completed', 'requested': len(targets), 'resolved': resolved,
                         'cached': len(targets) - len(pending)}}
