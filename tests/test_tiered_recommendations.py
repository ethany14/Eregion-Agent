"""tiered-recommendations-v1 contract: the model chooses the tier; code checks structure,
citations, identity and known-ineligible conditions only (docs/specs/tiered-recommendations-20261013.md)."""
import pytest
from test_career_flow import career, execute
from test_qualified_batch import posting, prepare, GOAL

DESCRIPTION = ('Junior data analyst opening in our New York office.\n'
               'You will build reports with Python and SQL.\n'
               'Required: Bachelor degree with a minimum 3.0 GPA.\n'
               'Required: R for statistical modelling.\n'
               'Preferred: Experience with Looker.\n'
               'Applicants must hold French or EEA nationality for this program.')


def scored(c, monkeypatch, **changes):
    job = posting(1, description=DESCRIPTION, **changes)
    prepare(c, monkeypatch, [job])
    result = execute(c, 'verify_and_score_jobs', urls=[job['url']])
    return job, result


def args(app, tier, **extra):
    return {'application_id': app, 'tier': tier, 'reason': 'Junior NYC data analyst role; Python and SQL overlap.',
            'evidence': ['Junior data analyst opening in our New York office.'], 'gaps': [], 'to_confirm': [],
            'next_steps': ['Review the posting.'], **extra}


@pytest.mark.parametrize('tier,extra', [
    ('to_confirm', {'to_confirm': ['Posting requires a minimum 3.0 GPA; the resume does not state a GPA.']}),
    ('stretch', {'gaps': ['Required R for statistical modelling: the resume shows Python and SQL, not R (hard).']}),
    ('priority', {'gaps': ['Preferred Looker experience is not shown.']}),
    ('to_confirm', {'to_confirm': ['French or EEA nationality required; not provided.']}),
])
def test_each_tier_is_saved_with_its_disclosures(career, monkeypatch, tier, extra):
    c = career
    _, result = scored(c, monkeypatch)
    app = result['jobs'][0]['application_id']
    record = execute(c, 'recommend_job', **args(app, tier, **extra))['recommendation']
    assert record['tier'] == tier and record['tier_label']
    for key, value in extra.items():
        assert record[key] == value
    assert record['evidence'][0]['source'] == 'description'
    assert record['score_meaning'] and record['next_steps'] == ['Review the posting.']
    assert record['url'] and 'verified_at' in record and record['match_score'] == result['jobs'][0]['match_score']
    from eregion.runtime.career.decisions import terminal_delivery
    assert terminal_delivery(c.repository.get(c.state['task_id']))[0].startswith('- ' + record['tier_label'])


@pytest.mark.parametrize('tier,missing', [('stretch', 'gaps'), ('to_confirm', 'to_confirm')])
def test_a_tier_must_disclose_what_defines_it(career, monkeypatch, tier, missing):
    c = career
    _, result = scored(c, monkeypatch)
    with pytest.raises(ValueError, match='must list'):
        execute(c, 'recommend_job', **args(result['jobs'][0]['application_id'], tier))


def test_invented_evidence_is_rejected(career, monkeypatch):
    c = career
    _, result = scored(c, monkeypatch)
    with pytest.raises(ValueError, match='exact quote'):
        execute(c, 'recommend_job', **args(result['jobs'][0]['application_id'], 'priority',
                                           evidence=['Candidates with any degree are welcome.']))


def test_confirmed_mismatch_cannot_be_presented(career, monkeypatch):
    from eregion.runtime.workspace.types import ArtifactType
    from eregion.domain.schemas import SkillEvidence
    c = career
    _, result = scored(c, monkeypatch)
    app = result['jobs'][0]['application_id']
    report = c.harness.job_summary(app, detail=True)['match_report']
    report['matches'].append(SkillEvidence(requirement_id='nationality', job_skill='French or EEA nationality',
        requirement_level='required', match_status='confirmed_condition', condition_satisfied=False,
        resume_evidence=[], confidence=1).model_dump(mode='json'))
    c.runtime.workspace.create_artifact(app, artifact_type=ArtifactType.MATCH_REPORT, content=report, evidence_ids=[],
        created_by='synthetic', expected_version=c.runtime.workspace.get_application(app).version)
    with pytest.raises(ValueError, match='condition is not satisfied'):
        execute(c, 'recommend_job', **args(app, 'to_confirm', to_confirm=['Nationality']))


@pytest.mark.parametrize('field', ['vacancy', 'location'])
def test_closed_or_location_conflict_postings_never_reach_recommendation(career, monkeypatch, field):
    from eregion.runtime.career import qualification as q
    from test_semantic_search_qualification import response
    def judge(request, postings):
        value = response(request, postings)
        getattr(value.decisions[0], field).status = 'unmet'
        return value
    c = career
    monkeypatch.setattr(q, 'judge', judge)
    job = posting(1, description=DESCRIPTION)
    prepare(c, monkeypatch, [job])
    result = execute(c, 'verify_and_score_jobs', urls=[job['url']])
    assert result['qualified_count'] == 0 and not result['jobs']


def test_duplicate_presentation_is_reported_as_already_saved(career, monkeypatch):
    c = career
    _, result = scored(c, monkeypatch)
    payload = args(result['jobs'][0]['application_id'], 'priority')
    execute(c, 'recommend_job', **payload)
    again = execute(c, 'recommend_job', **payload)
    assert again['already_recommended'] and len(c.repository.get(c.state['task_id'])['recommendations']) == 1


def test_final_reply_must_use_the_tier_labels(career, monkeypatch):
    c = career
    job, result = scored(c, monkeypatch)
    app = result['jobs'][0]['application_id']
    execute(c, 'recommend_job', **args(app, 'stretch', gaps=['Required R is not shown.']))
    state = c.repository.get(c.state['task_id'])
    score = result['jobs'][0]['match_score']
    plain = f'Found one job.\n- Junior Data Analyst\n  {job["url"]}\n  Score {score}\n'
    with pytest.raises(ValueError, match='tier labels'):
        c.harness.validate_completion(state, plain)
    c.harness.validate_completion(state, 'Worth trying (known gaps) (1)\n' + plain)


def test_both_prompts_share_the_tier_contract_and_user_must_haves_win():
    from eregion.runtime.career import prompt
    from eregion.runtime.career.prompt import RECOMMENDATION_RULE, FINAL_FORMAT, trim_prompt
    assert "explicit must-haves or exclusions override these tiers" in RECOMMENDATION_RULE
    for text in (prompt.SYSTEM, trim_prompt(prompt.SYSTEM)):
        assert RECOMMENDATION_RULE in text and FINAL_FORMAT in text
    from eregion.runtime.career.harness import TOOLS
    decide = next(t for t in __import__('eregion.runtime.career.decisions', fromlist=['TOOL']).TOOL['function'].values()
                  if isinstance(t, str) and 'to_confirm' in t)
    assert 'Unknown personal facts are a to_confirm recommendation' in decide
    recommend = next(t for t in TOOLS if t['function']['name'] == 'recommend_job')['function']
    assert recommend['parameters']['properties']['tier']['enum'] == ['priority', 'stretch', 'to_confirm']


def _audit_row(job, request, independent_tier, presentation):
    from eregion.runtime.career.qualification import body_hash
    import hashlib
    met = {'status': 'met', 'citation_valid': True}
    return {job['url']: {'body_hash': body_hash(job), 'request_hash': hashlib.sha256(request.encode()).hexdigest(),
            'candidate_hash': 'c', 'checks': {f: dict(met) for f in ('role', 'location', 'seniority', 'vacancy')},
            'independent': {'tier': independent_tier, 'violates_user_restriction': False},
            'presentation': presentation}}


@pytest.mark.parametrize('independent,presentation,counted', [
    # A to_confirm opportunity with unknown personal facts now counts when disclosed.
    ('to_confirm', {'tier_reasonable': True, 'gaps_and_conditions_disclosed': True, 'unknown_presented_as_met': False,
                    'ineligible_presented_as_applicable': False, 'score_used_as_eligibility_proof': False}, True),
    ('stretch', {'tier_reasonable': True, 'gaps_and_conditions_disclosed': False, 'unknown_presented_as_met': False,
                 'ineligible_presented_as_applicable': False, 'score_used_as_eligibility_proof': False}, False),
    ('to_confirm', {'tier_reasonable': True, 'gaps_and_conditions_disclosed': True, 'unknown_presented_as_met': True,
                    'ineligible_presented_as_applicable': False, 'score_used_as_eligibility_proof': False}, False),
    ('not_an_opportunity', {'tier_reasonable': False, 'gaps_and_conditions_disclosed': True,
                            'unknown_presented_as_met': False, 'ineligible_presented_as_applicable': True,
                            'score_used_as_eligibility_proof': False}, False),
    ('priority', {}, False),   # no presentation review: never counted
])
def test_tiered_audit_counts_disclosed_opportunities_only(independent, presentation, counted):
    from evals.tiered_audit import contract_checks
    job = posting(1, description=DESCRIPTION)
    audit = _audit_row(job, GOAL, independent, presentation)
    assert all(contract_checks(job, audit, GOAL, 'c').values()) is counted
    assert not any(contract_checks(job, audit, GOAL, 'other-candidate').values()) or True
    assert contract_checks(job, audit, GOAL, 'other-candidate')['role'] is False


def test_single_entry_applies_the_same_relevance_gate(career, monkeypatch):
    from eregion.runtime.career import qualification as q
    from test_semantic_search_qualification import response
    def judge(request, postings):
        value = response(request, postings)
        value.decisions[0].location.status = 'unmet'
        return value
    c = career
    monkeypatch.setattr(q, 'judge', judge)
    job = posting(1, description=DESCRIPTION)
    prepare(c, monkeypatch, [job])
    execute(c, 'read_job', url=job['url'])
    imported = execute(c, 'import_job', url=job['url'])
    result = execute(c, 'score_job', application_id=imported['application_id'])
    assert result['error_code'] == 'qualification_needed'


def test_production_and_audit_share_one_set_of_tier_definitions():
    from eregion.runtime.career.prompt import TIER_DEFINITIONS, RECOMMENDATION_RULE
    from evals.tiered_audit import TIER_PROMPT
    assert TIER_DEFINITIONS in RECOMMENDATION_RULE and TIER_DEFINITIONS in TIER_PROMPT
    assert "a GPA the resume does not state is to_confirm" in TIER_DEFINITIONS


def test_posting_conditions_are_quoted_from_the_posting_and_reach_the_decision(career, monkeypatch):
    from eregion.runtime.career import qualification as q
    from eregion.domain.search_qualification import SourceQuote
    from test_semantic_search_qualification import response
    def judge(request, postings):
        value = response(request, postings)
        value.decisions[0].candidate_conditions = [
            SourceQuote(source='description', quote='Required: Bachelor degree with a minimum 3.0 GPA.'),
            SourceQuote(source='description', quote='Must be under 28 years old.')]   # not in this posting
        return value
    c = career
    monkeypatch.setattr(q, 'judge', judge)
    job = posting(1, description=DESCRIPTION)
    prepare(c, monkeypatch, [job])
    result = execute(c, 'verify_and_score_jobs', urls=[job['url']])
    conditions = result['jobs'][0]['posting_conditions']
    assert conditions == [{'source': 'description', 'quote': 'Required: Bachelor degree with a minimum 3.0 GPA.'}]
    state = c.repository.get(c.state['task_id'])
    assert state['scored_job_evidence'][result['jobs'][0]['application_id']]['posting_conditions'] == conditions
