"""Semantic guidance to the model; no lexical acceptance or rejection rules."""
PARTIAL_POLICY = ('Partial credit requires concrete relevant evidence for part of the actual requirement. '
    'Interpret synonyms, equivalent activities, scope, negation and missing components semantically. '
    'Shared words alone do not prove relevance; lack of shared words does not disprove it. '
    'Explain which component is supported and which remains missing, with a verbatim source quote.')
