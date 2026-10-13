"""Internal frozen catalogue input. No model, configuration or network effects.

Hashes detect mutation, not authorisation. Only trusted local callers may supply
this object; it is not a public request-body schema. Missing-catalogue default
route selection remains a separate policy decision.
"""
from dataclasses import dataclass
import hashlib
import json

from eregion.domain.schemas import JobAnalysis

CATALOG_VERSION = 'complete-job-payload-v1'
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
            from eregion.domain.jev_fit.core import qualification_text
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

    def cache_signature(self):
        return digest([self.catalogue_version, self.catalogue_sha256, self.producer_signature])
