"""Small style screens, separate from factual grounding and human review."""
import re
from eregion.runtime.application_pack.style import cover_invitation_occurrences


def screens(content):
    paragraphs = content.get('paragraphs') or []
    opening = (paragraphs or [{}])[0].get('text', '')
    text = '\n'.join(p.get('text', '') for p in paragraphs)
    past_claims = 0
    for sentence in re.split(r'(?<=[.!?])\s+|\n', text):
        # A supported past action and a future task involving that technology
        # are not two assertions of past experience.
        past_claims += len(re.findall(r'\b(?:built|developed) (?:Python APIs|APIs using Python)\b', sentence, re.I))
        if not re.search(r'\b(?:would|will|hope|intend|plan)\b', sentence, re.I):
            past_claims += len(re.findall(r'\b(?:prior work|experience)\b.*?\b(?:building|developing) Python APIs\b', sentence, re.I))
    first_sentence = re.split(r'(?<=[.!?])\s+', opening)[0]
    return {
        'past_api_claim_once': past_claims <= 1,
        'no_repeated_invitation': len(cover_invitation_occurrences(content)) <= 1,
        'first_person_opening': bool(re.match(r'I\b', first_sentence)),
        'no_stiff_opening': not bool(re.search(r'this letter (?:addresses|outlines)|contribution would center', text, re.I)),
    }
