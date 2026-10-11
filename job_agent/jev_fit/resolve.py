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

from .core import POLICY, expected_score, score
from job_agent.partial_support import PARTIAL_POLICY, partial_overlap


class UnknownDecision(BaseModel):
    requirement_id: str
    is_candidate_requirement: bool = Field(description='Judge the job text alone, independently of resume support. False flags a classification concern for review; it never removes the supplied requirement. Missing candidate evidence means status=missing, not this flag=false.')
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
but incomplete experience in the SAME explicitly required skill/domain (partial), or does not establish it (missing).
Partial requires concrete support for a stated component with an explicit shortfall in years, level or scope.
Adjacent generic skills, a tool mentioned only incidentally, or school exposure without the required hands-on
work do not establish partial support. Explain which component is supported and which remains missing.
Matched requires every stated component and qualifier, including years, level and degree completion.
For matched or partial, evidence_quote must be copied exactly from the candidate evidence.
The supplied requirements were retained upstream. Qualification classification and candidate
support are separate decisions: absence of resume evidence is missing support, never proof
that the job requirement is context. Do not discard a requirement to improve the score.
If classification remains doubtful, flag it false for human review; local code retains its
original weight and unknown status instead of removing it from the score denominator.
Return one decision for every requirement_id supplied, and no others.'''
PROMPT += '\n' + PARTIAL_POLICY


def identity(enabled):
    from job_agent.model import model_settings_fingerprint
    code = hashlib.sha256(Path(__file__).read_bytes() +
        (Path(__file__).parent.parent/'partial_support.py').read_bytes()).hexdigest()
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
            from agent_runtime.provider_usage import capture_provider_attempts
            from job_agent.reasoning import cacheable_attempts
            with capture_provider_attempts() as attempts:
                result = invoke(model, UnknownResolution, PROMPT, request)
        except Exception as exc:  # Keep Jev's honest interval; never fail the whole analysis.
            if not decisions:
                return {**raw, 'resolver': {'status': 'failed', 'error': type(exc).__name__}, 'main_model_calls': 1}
            result = UnknownResolution(decisions=[])
        fresh = [d for d in result.decisions if d.requirement_id in pending]
        if store and cacheable_attempts(attempts):
            store.put_many({keys[d.requirement_id]: d for d in fresh})
        decisions += fresh
    ledger = {item['id']: item for item in raw.get('extraction', [])}
    resolved = 0
    classification_review=[]
    for decision in decisions:
        match = targets.get(decision.requirement_id)
        if match is None:
            continue
        unit = ledger.get(decision.requirement_id)
        if not decision.is_candidate_requirement:
            # The resolver sees the resume, so its classification cannot erase
            # an upstream retained qualification ("no evidence" is not context).
            # Preserve the original match, source and denominator for review.
            classification_review.append(decision.requirement_id)
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
            if status == 'partial' and not partial_overlap(match['text'], text):
                status = 'missing'
                match['partial_relevance_guard'] = {'status':'rejected',
                    'reason':'Exact quote has no requirement content term or listed synonym.'}
        match.update(status=status, level=decision.level, weight=1 if decision.level == 'preferred' else 2,
                     reason=('Partial support rejected: exact quote has no requirement content term or listed synonym. '
                             if match.get('partial_relevance_guard') else '') +
                            'Resolved by the main model after Jev left it uncertain: ' + decision.reason,
                     resolved_by='main_model', citations=[citation] if citation else [],
                     citation_scope='verified_excerpt' if citation else None)
        if unit is not None and unit['classification'] == 'unknown':
            unit['classification'] = decision.level
        resolved += 1
    matches = raw['matches']
    interval = score(matches)
    totals = {**expected_score(matches), 'decision_interval': interval['score_range'],
              'resolved_weight_fraction': interval['resolved_weight_fraction']}
    status = 'needs_review' if raw.get('provider_errors') or not matches or totals['score'] is None else 'completed'
    return {**raw, **totals, 'matches': matches, 'status': status, 'main_model_calls': calls,
            'resolver': {'status': 'completed', 'requested': len(targets), 'resolved': resolved,
                         'classification_review':classification_review,'cached': len(targets) - len(pending)}}


def resolve_unknowns_many(raws,evidence,*,model,invoke=None,store=None):
    """One provider request for up to eight jobs; keep job IDs and call attribution distinct."""
    if not 1<=len(raws)<=8:raise ValueError('Resolve one to eight jobs.')
    if invoke is None:
        from job_agent.model import invoke_structured as invoke
    pending={};primary_keys={};aliases={};alias_ids={}
    for index,(job_id,raw) in enumerate(raws.items()):
        targets=[m for m in raw.get('matches',[]) if m['status']=='unknown']
        keys={m['requirement_id']:decision_key(evidence,m) for m in targets}
        cached=store.get_many(list(keys.values())) if store else {}
        for m in targets:
            if keys[m['requirement_id']] not in cached:
                wire=f'job{index}:{m["requirement_id"]}'
                primary=primary_keys.setdefault(keys[m['requirement_id']],wire)
                pending.setdefault(primary,(job_id,m))
                aliases.setdefault(primary,[]).append((job_id,m))
                alias_ids.setdefault(primary,[]).append(wire)
    result,error=None,None
    if pending:
        request='CANDIDATE EVIDENCE:\n'+evidence+'\n\nUNRESOLVED REQUIREMENTS (job-prefixed IDs must remain exact):\n'+ '\n'.join(
            f'- {wire} [{m["level"]}]: {m["text"]}' for wire,(_,m) in pending.items())
        if any(len(ids)>1 for ids in alias_ids.values()):
            request+='\n\nLOCAL EQUIVALENT-ID FANOUT (metadata only, not additional requested decisions):\n'+ '\n'.join(
                f'{wire} -> '+', '.join(ids) for wire,ids in alias_ids.items())
            request+='\nReturn decisions only for primary bullet IDs above. These aliases have identical candidate evidence, complete requirement wording and level; local code copies the decision to each original ID.'
        try:result=invoke(model,UnknownResolution,PROMPT,request)
        except Exception as exc:error=exc
    grouped={key:[] for key in raws}
    if result:
        seen=set()
        for decision in result.decisions:
            if decision.requirement_id not in pending or decision.requirement_id in seen:continue
            seen.add(decision.requirement_id)
            for job_id,match in aliases[decision.requirement_id]:
                grouped[job_id].append(decision.model_copy(update={'requirement_id':match['requirement_id']}))
    outputs={};assigned=False
    for job_id,raw in raws.items():
        def replay(*_):
            if error:raise error
            return UnknownResolution(decisions=grouped[job_id])
        value=resolve_unknowns(raw,evidence,model=model,invoke=replay,store=store)
        charged=bool(pending) and not assigned
        value['main_model_calls']=int(charged)
        assigned=assigned or charged
        if value.get('resolver'):value['resolver'].update(batch_model_calls=int(bool(pending)),batch_jobs=len(raws),
            batch_unique_requirements=len(pending),batch_requirement_aliases=alias_ids)
        outputs[job_id]=value
    return outputs
