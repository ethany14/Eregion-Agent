"""Standard application questions answered once in setup and reused as approved answers.

Each topic recognizes the common wordings of one question, so a single saved
answer covers "Desired salary", "Salary expectations" and "Expected compensation".
Work authorization and sponsorship keep their country-aware identities.
"""
import re

# (topic, question shown in setup, kind, wording pattern on a cleaned label)
TOPICS = (
    ("preferred_name", "Preferred name", "text", r"^preferred (?:first )?name$|\bpreferred name\b"),
    ("pronouns", "Pronouns", "text", r"\bpronouns?\b"),
    ("address", "Street address", "text", r"^(?:street |home |mailing |current )?address(?: line 1)?$"),
    ("postal_code", "ZIP / postal code", "text", r"^(?:(?:zip|postal|post)\s?)+code$|^zip$|^postcode$"),
    ("state", "State / province", "text", r"^(?:state|province|state province|state or province|state region)$"),
    ("salary", "Desired salary", "text",
     r"\b(?:desired|expected|target)\s+(?:(?:annual|monthly|weekly|hourly|daily|base)\s+)*(?:salary|compensation|pay)\b|"
     r"\b(?:salary|compensation|pay)\s+(?:expectations?|requirements?)\b"),
    ("start_date", "Earliest start date", "text",
     r"\b(?:earliest|desired|available|availability)\s+(?:to\s+)?start(?:\s+date)?\b|^start date$|\bwhen (?:can|could) you start\b"),
    ("relocation", "Willing to relocate?", "yes_no", r"\b(?:willing|open) to relocat\w*$|\bwilling to relocate\b(?!\s+to\b)"),
    ("referral_source", "How did you hear about us?", "text",
     r"\bhow did you (?:hear|find out|learn) about\b|\bwhere did you (?:hear|find)\b|\bsource of (?:application|referral)\b"),
    ("over_18", "Are you at least 18 years old?", "yes_no", r"\b(?:at least|over) (?:18|eighteen)\b|\b18 years of age\b"),
    ("gender", "Gender", "text", r"^(?:gender|sex)\b|\bgender identity\b|\bwhat is your gender\b"),
    # Race first: its label may say "(if not Hispanic or Latino)".
    ("race", "Race / ethnicity", "text", r"^(?:race|ethnicity)\b|\brace ethnicity\b|\bwhat is your race\b"),
    ("hispanic_latino", "Are you Hispanic or Latino?", "text", r"\bhispanic\b|\blatin[oax]\b"),
    ("veteran", "Veteran status", "text", r"\bveteran\b"),
    ("disability", "Disability status", "text", r"\bdisabilit(?:y|ies)\b"),
)
# Country-aware identities from question_identity, answered in setup for the US.
AUTHORIZATION = (
    ("us_work_authorization", "Are you authorized to work in the United States?", "yes_no"),
    ("us_sponsorship_now", "Will you require sponsorship to work in the United States?", "yes_no"),
    ("us_sponsorship_future", "Will you require sponsorship to work in the United States in the future?", "yes_no"),
)
_PATTERNS = [(topic, re.compile(pattern)) for topic, _, _, pattern in TOPICS]


def topic(cleaned_label):
    """The standard topic of a cleaned question label, if any."""
    return next((name for name, pattern in _PATTERNS if pattern.search(cleaned_label)), None)


def catalog():
    """Setup questions with the identity each answer is saved under."""
    from .matching import question_identity
    items = [{"topic": name, "question": question, "kind": kind, "identity": f"standard:{name}"}
             for name, question, kind, _ in TOPICS]
    items += [{"topic": name, "question": question, "kind": kind, "identity": question_identity(question)}
              for name, question, kind in AUTHORIZATION]
    return items
