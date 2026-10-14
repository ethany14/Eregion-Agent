"""Acceptance audit for tiered recommendations (docs/specs/tiered-recommendations-20261013.md).

Phase 1 is blind: request, posting text and candidate facts only, no production labels.
Phase 2 compares the production records with the phase-1 assessment; a last call reviews
the final reply against facts code collected about the run. Structural checks (citations,
identity, freshness) are code; every judgment of meaning is the audit model's.

v1 counted a recommendation only when every check, tier agreement included, passed.
v2 (current) has no count threshold: a shown job fails only for a substantive error
(not relevant to the request, unknown presented as met, a known conflict hidden, an
unsupported claim, a score used as eligibility proof). A reasonable tier disagreement is
reported, never failed. Historical v1 results keep their recorded verdicts.
"""
import hashlib
import json
from typing import Literal
from pydantic import BaseModel, Field
from eregion.domain.search_qualification import PostingDecision
from eregion.domain.jev_fit.resolve import locate
from eregion.runtime.career.qualification import body_hash, verified_checks, FIELDS
from evals.search_semantic_audit import PROMPT, Requirement, candidate_hash

V1 = 'tiered-recommendations-v1'
V2 = 'tiered-recommendations-v2'
# v3 = v2 plus a judgment of whether the search stopped at a reasonable point.
V3 = 'tiered-recommendations-v3'
# v4 = the model still decides when to stop; the reply must state accurately what remains
# and offer to continue. Stop reasonableness is advisory unless the user asked for an
# exhaustive search (one audit call proved too inconsistent to pass or fail a run on).
V4 = 'tiered-recommendations-v4'
# v5 = v4 with one clarified audit term: leaving out a preferred / 'a plus' item is a minor
# omission, not a hidden conflict (tiered-v4-01 failed DraftKings on Databricks 'is a plus').
ACCEPTANCE_VERSION = 'tiered-recommendations-v5'
VERSIONS = {V1, V2, V3, V4, ACCEPTANCE_VERSION}


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
    # v2: substantive errors only; minor omissions are listed, not failed.
    known_conflict_hidden: bool = False
    unsupported_claim: bool = False
    minor_omissions: list[str] = Field(default_factory=list, max_length=6)
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
- score_used_as_eligibility_proof: the score is presented as proof of eligibility rather than a fit estimate;
- known_conflict_hidden: a known hard mismatch, an important gap or a condition the user must confirm is
  missing or worded so that a reader would be misled about whether to apply. An important gap is a required
  qualification the candidate does not show; items the posting marks as preferred, a plus or nice to have are
  minor_omissions unless the assessment shows they decide the application;
- unsupported_claim: the reason or evidence states something the posting or candidate material does not support;
- minor_omissions: smaller details left out that would not mislead a reader (listed only).
A different but defensible tier is not an error. Judge only from the supplied material. Explain briefly.
Do not improve the pass count."""

REPLY_PROMPT = """You review the final reply of a job-search assistant against facts recorded by its runtime
(what was searched, what failed, how many postings were read, scored and decided, and how the run ended).
- explains_results_and_search: the reply says what was searched and, when there are few or no results,
  why, in a way consistent with the facts;
- hides_or_misreports_problems: the reply omits or misstates a recorded fetch or source failure, unprocessed
  candidates, a budget or abnormal stop, or claims work that the facts do not show. Check every entry of
  failed_actions: a failed search or read that the reply does not mention, especially one just before the run
  stopped, is a hidden problem;
- misstates_jobs: the reply lists a job, tier, score or count that differs from the recorded recommendations.
A small number of results is not itself a problem.
- stop_assessment: whether stopping the search was reasonable given the recorded trajectory (each query's provider
  total versus cards seen, boards searched and remaining, failures, budget_remaining, candidate quality, and the
  assistant's stop_reason). premature = a clearly worthwhile, reasonably cheap next step was skipped without a
  sound reason; borderline = a further step was plausible but its value was uncertain (an improvement suggestion);
  reasonable = further steps were unlikely to add relevant openings. Unused budget alone is not a reason to continue,
  and one search can be enough. Cite the specific facts in stop_review.
- user_asked_exhaustive: the user explicitly asked for an exhaustive or as-complete-as-possible search.
- continuation_stated: when the facts show results remaining (unseen LinkedIn results, unsearched boards or
  unread candidates), the reply says what remains and offers a way to continue; true when nothing remains.
- continuation_accurate: what the reply says remains agrees with the recorded numbers (rounding is fine).
Judge only from the supplied material. Explain briefly."""


class ReplyAudit(BaseModel):
    explains_results_and_search: bool
    hides_or_misreports_problems: bool
    misstates_jobs: bool
    stop_assessment: Literal['reasonable', 'borderline', 'premature'] = 'reasonable'
    stop_review: str = Field(default='', max_length=800)
    user_asked_exhaustive: bool = False
    continuation_stated: bool = True
    continuation_accurate: bool = True
    reason: str = Field(min_length=1, max_length=800)

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
    for start in range(0, len(jobs), 8):
        group = jobs[start:start + 8]
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


def review_reply(request, final, facts, recommendations):
    from eregion.domain.model import invoke_structured, shared_model
    from eregion.runtime.provider_usage import usage_scope
    payload = {'request': request, 'final_reply': final, 'run_facts': facts,
               'recommendations': [{k: r.get(k) for k in ('title', 'company', 'url', 'tier', 'match_score')}
                                   for r in recommendations]}
    with usage_scope(purpose='acceptance_tier_audit_reply'):
        result = invoke_structured(shared_model(purpose='search_qualification'), ReplyAudit, REPLY_PROMPT,
                                   json.dumps(payload, ensure_ascii=False, default=str))
    return result.model_dump()


def substantive_checks(job, audit, request, candidate_digest=None):
    """v2: True means no substantive error was found in how this shown job was presented."""
    row = audit.get(job.get('url')) or {}
    fresh = (row.get('body_hash') == body_hash(job)
             and row.get('request_hash') == hashlib.sha256(request.encode()).hexdigest()
             and (candidate_digest is None or row.get('candidate_hash') == candidate_digest))
    checks = row.get('checks') or {}
    independent = row.get('independent') or {}
    presentation = row.get('presentation') or {}
    reviewed = bool(fresh and independent and presentation)
    return {'audited': reviewed,
            # Relevance: the role must be confirmed; no requested field may be in known conflict.
            'relevant_role': bool(fresh and checks.get('role', {}).get('citation_valid')
                                  and checks['role']['status'] in {'met', 'not_requested'}),
            'no_known_request_conflict': bool(fresh) and not any(c.get('status') == 'unmet' for c in checks.values()),
            'no_user_restriction_violated': reviewed and not independent.get('violates_user_restriction'),
            'no_unknown_as_met': reviewed and not presentation.get('unknown_presented_as_met'),
            'no_ineligible_as_applicable': reviewed and not presentation.get('ineligible_presented_as_applicable'),
            'no_hidden_conflict': reviewed and not presentation.get('known_conflict_hidden'),
            'no_unsupported_claim': reviewed and not presentation.get('unsupported_claim'),
            'score_not_eligibility_proof': reviewed and not presentation.get('score_used_as_eligibility_proof')}


def contract_checks(job, audit, request, candidate_digest=None):
    """v1 (historical): every check, tier agreement included, had to pass to count."""
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
