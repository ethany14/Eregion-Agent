"""L3 follow-up: an opening that states the employer's requirement is not a candidate claim.

Grounding is unchanged: first-person claims and requirements absent from the job
text still need cited evidence.
"""
import pytest

from agent_runtime.application_pack.types import CoverLetter, CoverLetterParagraph
from agent_runtime.application_pack.verifier import ArtifactVerifier, _without_employer_requirements

JD = 'Backend Engineer at Example. Requirements: Python API experience, SQL.'
ROLE = 'Backend Engineer'
# Verbatim failing opening from docs/benchmarks/r1-closeout-20261012/L3-full-r1/verification.json
L3_OPENING = ('I am applying for the Backend Engineer role at Example. '
              'I understand the Backend Engineer role requires Python API experience.')


# Synthetic artifact produced by the paid L3 full sample (r1 closeout, L3-full-r1/result/full.json).
L3_ARTIFACT = {'closing': 'Sincerely,', 'greeting': 'Dear Hiring Team,', 'schema_version': 2, 'signer_name': None,
    'paragraphs': [
        {'evidence_ids': [], 'evidence_version_ids': [], 'paragraph_type': 'opening',
         'target_requirement_ids': [], 'text': L3_OPENING},
        {'evidence_ids': ['24788621-1ac7-44ef-bfb2-ab4c4192dfc4'],
         'evidence_version_ids': ['b920ce9e-1080-4919-a9e4-60ccc12707f3'], 'paragraph_type': 'evidence',
         'target_requirement_ids': ['REQ-1'], 'text': 'I have built Python APIs.'},
        {'evidence_ids': [], 'evidence_version_ids': [], 'paragraph_type': 'motivation',
         'target_requirement_ids': [], 'text': 'I would welcome the opportunity to work on Python APIs as a Backend Engineer.'},
    ]}


def letter(opening):
    return CoverLetter(paragraphs=[
        CoverLetterParagraph(paragraph_type='opening', text=opening),
        CoverLetterParagraph(paragraph_type='motivation',
                             text='I would welcome the opportunity to work on Python services at Example.'),
        CoverLetterParagraph(paragraph_type='closing', text='Thank you for your consideration.'),
    ]).model_dump(mode='json')


def opening_issues(opening, context=JD):
    result = ArtifactVerifier().verify(letter(opening), 'cover_letter', [], expected_role=ROLE,
                                       employer_context=context)
    return [i.reason for i in result.issues if i.block_id == 'paragraph-1']


def test_the_l3_opening_is_employer_context_when_the_job_states_it():
    assert opening_issues(L3_OPENING) == []


@pytest.mark.parametrize('opening', [
    # The requirement is not in the job text.
    'I am applying for the Backend Engineer role at Example. The role requires Kubernetes experience.',
    # A first-person claim rides along with the requirement.
    'I am applying for the Backend Engineer role. The role requires Python API experience, which I have.',
    'The role requires Python API experience and I have built Python APIs.',
    # A plain candidate claim in the opening.
    'I am applying for the Backend Engineer role at Example. I have built Python APIs.',
])
def test_candidate_claims_and_unverified_requirements_still_need_evidence(opening):
    assert 'Factual claim must cite a confirmed evidence version.' in opening_issues(opening)


def test_without_job_context_nothing_is_exempt():
    assert opening_issues(L3_OPENING, context=None) == ['Factual claim must cite a confirmed evidence version.']


def test_only_the_attribution_sentence_is_removed():
    text = 'I understand the role requires Python API experience. I have shipped SQL reports.'
    assert _without_employer_requirements(text, JD) == 'I have shipped SQL reports.'


def test_offline_replay_of_the_frozen_l3_full_artifact():
    """Re-verify the stored paid L3 artifact (no model call) with production pairing semantics."""
    import json
    from pathlib import Path
    from agent_runtime.application_pack.types import EvidenceSnapshotItem
    artifact = json.loads(json.dumps(L3_ARTIFACT))
    frozen = Path(__file__).resolve().parents[1] / 'docs/benchmarks/r1-closeout-20261012/L3-full-r1/result/full.json'
    if frozen.exists():  # local evidence bundle; the copy below must match it exactly
        assert json.loads(frozen.read_text(encoding='utf-8'))['artifact'] == artifact
    cited = artifact['paragraphs'][1]
    evidence = EvidenceSnapshotItem(evidence_id=cited['evidence_ids'][0],
        evidence_version_id=cited['evidence_version_ids'][0], content_hash='frozen', source_type='resume',
        selection_reason='fixture', associated_requirement_ids=['REQ-1'], claim_text='Built Python APIs.')
    judged = []

    def judge(claims):
        judged.extend(claims)
        return {item['claim_id']: True for item in claims}

    result = ArtifactVerifier(judge).verify(artifact, 'cover_letter', [evidence], expected_role=ROLE,
                                            employer_context='Requires Python API experience.')
    # Paragraph 1 (employer requirement) no longer needs candidate evidence. Paragraph 2 is
    # either directly supported or left to the semantic judge, never rejected by wiring.
    assert [i.block_id for i in result.issues if i.block_id in {'paragraph-1', 'paragraph-2'}] == []


# M3-GROUNDING-001 (review): an employer requirement is exempt only when the job text
# states that exact requirement; otherwise it stays an unverified factual claim.
@pytest.mark.parametrize('context,opening', [
    # A changed number.
    ('The role requires 3 years of Python experience.', 'The role requires 5 years of Python experience.'),
    ('Requires 3+ years of Python.', 'The role requires 3 years of Python.'),
    # Negation in the job text.
    ('Python experience is not required.', 'The role requires Python experience.'),
    ('No Python experience needed.', 'The role requires Python experience.'),
    ("Python experience isn't required.", 'The role requires Python experience.'),
    # Preferred is not required.
    ('Python API experience preferred.', 'The role requires Python API experience.'),
    ('Nice to have: Python API experience.', 'The role needs Python API experience.'),
    # Words scattered across sentences or reordered are not the stated requirement.
    ('Python and SQL. API experience with REST.', 'The role requires Python API experience.'),
    ('Requires API Python experience.', 'The role requires Python API experience.'),
    # A negated requirement in the opening itself.
    ('Requires Python API experience.', 'The role requires no Python API experience.'),
])
def test_unverified_or_altered_requirements_are_not_exempt(context, opening):
    assert 'Factual claim must cite a confirmed evidence version.' in opening_issues(opening, context=context)


@pytest.mark.parametrize('context,opening', [
    ('Requires Python API experience.', L3_OPENING),
    ('The role requires 3 years of Python experience.', 'The role requires 3 years of Python experience.'),
    ('Python API experience preferred.', 'The team is looking for Python API experience.'),
])
def test_exactly_stated_requirements_remain_exempt(context, opening):
    assert opening_issues(opening, context=context) == []
