"""Internal frozen catalogue input. No model, configuration or network effects.

Hashes detect mutation, not authorisation. Only trusted local callers may supply
this object; it is not a public request-body schema. Missing-catalogue default
route selection remains a separate policy decision.
"""
from dataclasses import dataclass
import hashlib
import json

import re

from job_agent.schemas import JobAnalysis, JobRequirement

CATALOG_VERSION = 'complete-job-payload-v1'
LOCAL_PRODUCER = 'local-units-v3'

REQUIREMENT_SECTION = re.compile(r'requirement|qualification|must have|nice to have|who you are|about you|you have|you bring|'
    r'what you.ll bring|what we.re looking for|skills|experience|^required$|^preferred$', re.I)
PREFERRED_SECTION = re.compile(r'preferred|nice to have|bonus|plus', re.I)
DUTY_SECTION = re.compile(r'responsibilit|what you.ll do|what you will do|the role|day to day|your impact|in this role', re.I)
QUALIFICATION_SIGNAL = re.compile(r'\b(?:\d+\+?\s*(?:years?|yrs)|experience (?:with|in)|proficien\w*|familiar\w*|knowledge of|'
    r'degree|bachelor\w*|master\w*|ph\.?d|certif\w*|ability to|skills? in|expertise|fluen\w*|must (?:have|be))\b', re.I)


LEADING_QUALIFICATION = re.compile(r'^(?:\d+\+?\s*(?:years?|yrs)|experience|strong|solid|high proficiency|proficien\w*|familiar\w*|'
    r'knowledge|degree|bachelor\w*|master\w*|ph\.?d|ability to|demonstrated|proven|expertise|fluen\w*|deep understanding|'
    r'understanding of|comfort\w* with|track record|background in)\b', re.I)


def local_job_analysis(body):
    from job_agent.domain import extract_minimum_years
    from job_agent.jev_fit.core import CANDIDATE_CONDITION, boilerplate, job_units, qualification_text
    units = [u for u in job_units(body) if not boilerplate(u) and u['text'].rstrip(':').strip() != (u.get('section') or '')]
    has_requirement_section = any(REQUIREMENT_SECTION.search(u.get('section') or '') for u in units)
    requirements, responsibilities, duties = [], [], []
    for u in units:
        section = u.get('section') or ''
        text = qualification_text(u['text'])
        if not text or len(text) < 3:
            continue
        leading = bool(LEADING_QUALIFICATION.match(text))
        if DUTY_SECTION.search(section) and not REQUIREMENT_SECTION.search(section) and not leading:
            responsibilities.append(text)
            duties.append((u, text))
            continue
        inline_pref = re.match(r'\s*preferred\s*:', u['text'], re.I)
        is_requirement = (REQUIREMENT_SECTION.search(section) or re.match(r'\s*(?:required|preferred)\s*:', u['text'], re.I)
            or leading or (not has_requirement_section and QUALIFICATION_SIGNAL.search(text)) or CANDIDATE_CONDITION.search(text))
        if not is_requirement:
            continue
        condition = bool(CANDIDATE_CONDITION.search(text)) and not QUALIFICATION_SIGNAL.search(text)
        level = 'preferred' if inline_pref or PREFERRED_SECTION.search(section) else 'required'
        # An explicit duration ("8+ years") enables the pipeline's deterministic years
        # guard: 'matched' requires evidence that states at least that many years.
        years = None if condition else extract_minimum_years(text)
        requirements.append(JobRequirement(requirement_id=u['id'], requirement_group_id=u['id'], canonical_name=text,
            display_name=text, original_text=text, source_text=text, atomic_text=text,
            category='eligibility' if condition else 'experience' if years else 'other',
            verification_mode='user_confirmation' if condition else 'years_experience' if years else 'resume_evidence',
            minimum_years=years, level=level))
    if duties and not any(r.category != 'eligibility' for r in requirements):
        # No stated qualifications (some postings only describe the work): score the
        # stated duties as required capabilities, deterministically, instead of letting
        # a free extraction invent a different 38-50 item list on every run.
        requirements += [JobRequirement(requirement_id=u['id'], requirement_group_id=u['id'], canonical_name=text,
            display_name=text, original_text=text, source_text=text, atomic_text=text, category='responsibility',
            verification_mode='resume_evidence', level='required') for u, text in duties]
        requirements.sort(key=lambda r: int(r.requirement_id[1:]))
    return JobAnalysis(title=None, summary='', requirements=requirements, responsibilities=responsibilities)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':')).encode()).hexdigest()


def freeze_catalog(job, body, *, provenance):
    job = JobAnalysis.model_validate(job.model_dump(mode='json'))
    payload = job.model_dump(mode='json')
    ids = [r.requirement_id for r in job.requirements]
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate catalogue IDs')
    if any(not r.source_text or r.source_text not in body for r in job.requirements):
        raise ValueError('Catalogue source is not verbatim target body')
    identity = {'catalogue_version': CATALOG_VERSION,
        'body_sha256': hashlib.sha256(body.encode()).hexdigest(), 'job_analysis': payload}
    return {**identity, 'requirements': payload['requirements'],
        'provenance': provenance, 'catalogue_sha256': digest(identity)}


def compare_catalog(reference, candidate):
    for frozen in (reference,candidate):
        if frozen.get('catalogue_version') != CATALOG_VERSION or 'job_analysis' not in frozen:
            raise ValueError('Incomplete or historical catalogue identity must be re-frozen explicitly')
        identity = {k:frozen[k] for k in ('catalogue_version','body_sha256','job_analysis')}
        if digest(identity) != frozen.get('catalogue_sha256') or frozen['requirements'] != frozen['job_analysis']['requirements']:
            raise ValueError('Catalogue audit payload differs from frozen identity')
    left = {r['requirement_id']:r for r in reference['requirements']}
    right = {r['requirement_id']:r for r in candidate['requirements']}
    return {'same_body': reference['body_sha256'] == candidate['body_sha256'],
        'same_ordered_ids': list(left) == list(right),
        'missing_ids': sorted(left.keys()-right.keys()), 'extra_ids': sorted(right.keys()-left.keys()),
        'changed_predicates': [key for key in left if key in right and left[key] != right[key]],
        'exact_catalogue_agreement': (reference['body_sha256'] == candidate['body_sha256']
            and reference.get('catalogue_version') == candidate.get('catalogue_version')
            and reference.get('job_analysis') == candidate.get('job_analysis'))}


@dataclass(frozen=True)
class FrozenRequirementCatalog:
    """Immutable payload and source binding; provenance is descriptive only."""
    payload_json: str
    body_sha256: str
    catalogue_sha256: str
    producer_signature: str
    provenance: str
    catalogue_version: str = CATALOG_VERSION

    @classmethod
    def from_jev_result(cls, result, body, *, producer_signature, provenance):
        if not producer_signature.strip():
            raise ValueError('Catalogue producer signature is required')
        match = result.skill_match
        details = match.decision_details or {}
        if match.algorithm != 'jev-only' or details.get('jd_sha256') != hashlib.sha256(body.encode()).hexdigest():
            raise ValueError('Catalogue is not bound to this Jev target body')
        job = result.job_analysis
        ids = [r.requirement_id for r in job.requirements]
        match_ids = [m.requirement_id for m in match.matches]
        if len(set(match_ids)) != len(match_ids) or set(ids) != set(match_ids):
            raise ValueError('Catalogue and Jev assessment IDs do not agree')
        ledger = details.get('extraction', [])
        spans = {u['id']:u for u in ledger}
        if len(spans) != len(ledger) or any(type(u.get('start')) is not int
                or type(u.get('end')) is not int or not 0 <= u['start'] < u['end'] <= len(body)
                for u in ledger):
            raise ValueError('Invalid or duplicate catalogue source spans')
        for r in job.requirements:
            span = spans.get(r.requirement_id)
            if not span or type(span.get('start')) is not int or type(span.get('end')) is not int:
                raise ValueError('Catalogue requirement has no target source span')
            from job_agent.jev_fit.core import qualification_text
            # Jev projection removes a leading bullet/Required:/Preferred: only.
            # Bind to that exact documented transformation of the recorded span,
            # never to an arbitrary substring somewhere else on the page.
            if not 0 <= span['start'] < span['end'] <= len(body) or qualification_text(body[span['start']:span['end']]) != r.source_text:
                raise ValueError('Catalogue source span does not match target body')
            m = next(m for m in match.matches if m.requirement_id == r.requirement_id)
            if m.requirement_level != r.level:
                raise ValueError('Catalogue typed level differs from Jev assessment')
        frozen = freeze_catalog(job, body, provenance=provenance)
        return cls(json.dumps(frozen['job_analysis'], ensure_ascii=False, sort_keys=True),
            frozen['body_sha256'], frozen['catalogue_sha256'], producer_signature, provenance)

    def validate_for(self, body, *, producer_signature=None, expected_catalogue_sha256=None):
        if self.catalogue_version != CATALOG_VERSION:
            raise ValueError('Unsupported catalogue version')
        if not self.producer_signature.strip() or (producer_signature is not None
                and self.producer_signature != producer_signature):
            raise ValueError('Catalogue producer signature mismatch')
        job = JobAnalysis.model_validate_json(self.payload_json)
        frozen = freeze_catalog(job, body, provenance=self.provenance)
        if frozen['body_sha256'] != self.body_sha256 or frozen['catalogue_sha256'] != self.catalogue_sha256:
            raise ValueError('Frozen catalogue payload or target body changed')
        if expected_catalogue_sha256 is not None and self.catalogue_sha256 != expected_catalogue_sha256:
            raise ValueError('Catalogue identity differs from expected frozen catalogue')
        return job

    @classmethod
    def from_local_units(cls, body):
        """Default main-model catalogue: deterministic, local, no provider call.

        Uses the same source units and section detection as Jev. Requirements are
        units under requirement-type headings (preferred/required from the heading);
        units under duty headings become responsibilities; company, benefit, salary
        and EEO text is excluded. A posting without any requirement heading falls
        back to units with explicit qualification signals. The same body always
        yields the same ordered IDs, so main-model scores no longer depend on a
        free-form extraction that changes between runs.
        """
        job = local_job_analysis(body)
        frozen = freeze_catalog(job, body, provenance='local-units: deterministic job_units/section catalogue')
        return cls(json.dumps(frozen['job_analysis'], ensure_ascii=False, sort_keys=True),
            frozen['body_sha256'], frozen['catalogue_sha256'], LOCAL_PRODUCER, frozen['provenance'])

    def cache_signature(self):
        return digest([self.catalogue_version, self.catalogue_sha256, self.producer_signature])
