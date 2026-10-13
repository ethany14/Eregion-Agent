"""Bounded exact excerpts for triage, never an eligibility verdict."""
import re


def with_brief(job):
    text = job.get('description') or ''
    excerpts = []
    # Preserve offsets in the complete source, including evidence beyond its prefix.
    for line in re.finditer(r'[^\n]+', text):
        if re.search(r'\byears?\b|experience|qualifications|requirements|eligible|authorization|sponsor|location|remote|hybrid|onsite|on-site|entry.level|junior|graduate', line[0], re.I):
            start, end = line.start(), min(line.end(), line.start() + 280)
            excerpts.append({'quote':text[start:end], 'start':start, 'end':end})
        if len(excerpts) == 8:
            break
    return {**job, 'triage_evidence':excerpts,
            'next':'These excerpts are incomplete source evidence, not a qualification verdict. Use verify_and_score (or import_job then score_job) for a promising posting; dismiss_candidate with an exact quote for a mismatch. Read complete context only if a necessary fact is still missing.'}
