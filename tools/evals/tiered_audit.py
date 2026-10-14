"""Acceptance audit for tiered-recommendations-v1 (docs/specs/tiered-recommendations-20261013.md).

Phase 1 is blind: request, posting text and candidate facts only, no production labels.
Phase 2 compares the production records with the phase-1 assessment. Structural checks
(citations, identity, freshness) are code; every judgment of meaning is the audit model's.
"""
import hashlib
import json
from typing import Literal
from pydantic import BaseModel, Field
from eregion.domain.search_qualification import PostingDecision
from eregion.domain.jev_fit.resolve import locate
from eregion.runtime.career.qualification import body_hash, verified_checks, FIELDS
from evals.search_semantic_audit import PROMPT, Requirement, candidate_hash

ACCEPTANCE_VERSION = 'tiered-recommendations-v1'


class Opportunity(PostingDecision):
    violates_user_restriction: bool
    restriction_reason: str = Field(max_length=500)
    tier: Literal['priority', 'stretch', 'to_confirm', 'not_an_opportunity']
    important_gaps: list[Requirement] = Field(max_length=8)
    to_confirm: list[Requirement] = Field(max_length=6)
    known_hard_mismatch: list[Requirement] = Field(max_length=4)
    tier_reason: str = Field(min_length=1, max_length=600)


class IndependentAudit(BaseModel):
    decisions: list[Opportunity]


class Presentation(BaseModel):
    posting_id: str
    tier_reasonable: bool
    gaps_and_conditions_disclosed: bool
    unknown_presented_as_met: bool
    ineligible_presented_as_applicable: bool
    score_used_as_eligibility_proof: bool
    reason: str = Field(min_length=1, max_length=600)


class PresentationAudit(BaseModel):
    reviews: list[Presentation]


from eregion.runtime.career.prompt import TIER_DEFINITIONS

# The audit applies the same tier definitions as production (one shared text); it
# judges independently, without seeing production labels.
TIER_PROMPT = PROMPT.split('\n\nSeparately judge personal eligibility')[0] + """

Then classify the posting as an opportunity for this candidate yourself. """ + TIER_DEFINITIONS + """
Use tier not_an_opportunity for the last group. List important_gaps, to_confirm items and
known_hard_mismatch with exact posting text. Set violates_user_restriction only for a restriction the
human actually stated."""

PRESENTATION_PROMPT = """You review how a job-search assistant presented opportunities, against an independent
assessment of each posting that was made earlier without seeing the assistant's output. For each posting_id
compare the assistant's tier, reason, gaps, items to confirm, next steps and score with that assessment:
- tier_reasonable: the assistant's tier is a defensible reading of the assessment (adjacent judgment calls
  can be reasonable; presenting a not_an_opportunity posting is not);
- gaps_and_conditions_disclosed: every important gap and item to confirm in the assessment is stated clearly
  by the assistant (not hidden in vague wording);
- unknown_presented_as_met: the assistant states or implies that something unknown is satisfied;
- ineligible_presented_as_applicable: a known hard mismatch is presented as applicable;
- score_used_as_eligibility_proof: the score is presented as proof of eligibility rather than a fit estimate.
Judge only from the supplied material. Explain briefly. Do not improve the pass count."""

PRESENTED = ('tier', 'reason', 'gaps', 'to_confirm', 'next_steps', 'match_score', 'score_meaning', 'caveats')


def _ask(schema, prompt, payload, purpose, size, items):
    from eregion.domain.model import invoke_structured, shared_model
    from eregion.runtime.provider_usage import usage_scope
    # One retry only for an unusable reply (identities); a verdict is never retried.
    for attempt in range(2):
        with usage_scope(purpose=purpose):
            result = invoke_structured(shared_model(purpose='search_qualification'), schema, prompt,
                                       json.dumps(payload, ensure_ascii=False))
        rows = getattr(result, items)
        ids = [r.posting_id for r in rows]
        if len(ids) == size and set(ids) == {str(i) for i in range(size)}:
            return rows
    raise ValueError('Audit identities do not match the supplied postings.')


def _bounded(rows, description):
    out = []
    for row in rows:
        span = locate(row.requirement_quote, description)
        out.append({'quote': description[span[0]:span[1]] if span else row.requirement_quote,
                    'reason': row.reason, 'citation_valid': span is not None})
    return out


def review(request, jobs, recommendations, candidate=''):
    from eregion.runtime.career.alerts import job_key
    outputs = {}
    for start in range(0, len(jobs), 5):
        group = jobs[start:start + 5]
        payload = {'request': request, 'candidate': candidate, 'postings': [{'posting_id': str(i),
                   **{k: j.get(k) or '' for k in ('title', 'location', 'description')}} for i, j in enumerate(group)]}
        for d in _ask(IndependentAudit, TIER_PROMPT, payload, 'acceptance_tier_audit_independent', len(group), 'decisions'):
            job = group[int(d.posting_id)]
            description = job.get('description') or ''
            outputs[job['url']] = {'body_hash': body_hash(job),
                'request_hash': hashlib.sha256(request.encode()).hexdigest(),
                'candidate_hash': candidate_hash(candidate), 'checks': verified_checks(d, request, job),
                'independent': {'tier': d.tier, 'violates_user_restriction': d.violates_user_restriction,
                    'restriction_reason': d.restriction_reason, 'tier_reason': d.tier_reason,
                    'important_gaps': _bounded(d.important_gaps, description),
                    'to_confirm': _bounded(d.to_confirm, description),
                    'known_hard_mismatch': _bounded(d.known_hard_mismatch, description)}}
    produced = {job_key(r['url']): r for r in recommendations if r.get('url')}
    reviewable = [j for j in jobs if job_key(j['url']) in produced and j['url'] in outputs]
    for start in range(0, len(reviewable), 8):
        group = reviewable[start:start + 8]
        payload = {'request': request, 'postings': [{'posting_id': str(i), 'title': j.get('title'),
            'independent_assessment': outputs[j['url']]['independent'],
            'assistant_presentation': {k: produced[job_key(j['url'])].get(k) for k in PRESENTED}}
            for i, j in enumerate(group)]}
        for r in _ask(PresentationAudit, PRESENTATION_PROMPT, payload, 'acceptance_tier_audit_presentation',
                      len(group), 'reviews'):
            outputs[group[int(r.posting_id)]['url']]['presentation'] = r.model_dump()
    return outputs


def contract_checks(job, audit, request, candidate_digest=None):
    row = audit.get(job.get('url')) or {}
    fresh = (row.get('body_hash') == body_hash(job)
             and row.get('request_hash') == hashlib.sha256(request.encode()).hexdigest()
             and (candidate_digest is None or row.get('candidate_hash') == candidate_digest))
    checks = row.get('checks') or {}
    independent = row.get('independent') or {}
    presentation = row.get('presentation') or {}
    result = {field: bool(fresh and checks.get(field, {}).get('citation_valid')
                          and checks[field]['status'] in {'met', 'not_requested'}) for field in FIELDS}
    result['no_user_restriction_violated'] = bool(fresh and independent) and not independent.get('violates_user_restriction')
    result['is_opportunity'] = bool(fresh) and independent.get('tier') in {'priority', 'stretch', 'to_confirm'}
    result['tier_reasonable'] = bool(presentation.get('tier_reasonable'))
    result['gaps_disclosed'] = bool(presentation.get('gaps_and_conditions_disclosed'))
    result['no_unknown_as_met'] = bool(presentation) and not presentation.get('unknown_presented_as_met')
    result['no_ineligible_as_applicable'] = bool(presentation) and not presentation.get('ineligible_presented_as_applicable')
    result['score_not_eligibility_proof'] = bool(presentation) and not presentation.get('score_used_as_eligibility_proof')
    return result
