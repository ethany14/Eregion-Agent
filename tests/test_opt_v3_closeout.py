"""Closeout regressions (docs/specs/opt-v3-closeout-decisions-validation.md)."""
import json

from agent_runtime.loop_context import ConversationWindow
from agent_runtime.request_context import ContextArchive, prepare_request


def _assemble(archive):
    prepare_request('Task', [], ConversationWindow(), {'history': []}, archive)


def test_fully_read_but_evicted_reference_is_restored_not_returned_empty():
    # Paid P2: a fully read JD (8.5K) was pushed out of the 9K context_evidence window
    # by later large reads; read_context(ref) / (ref, offset=0) then returned
    # offset=8516, content="" six times and the run ended on no_progress.
    archive = ContextArchive()
    jd = archive.reference({'description': 'Requires 0-2 years of SQL. ' * 320})['context_ref']
    other = archive.reference({'jobs': ['board listing ' * 3000]})['context_ref']
    offset = 0
    while offset is not None:  # read the JD completely
        offset = archive.read(jd, offset)['next_offset']
    for start in range(0, 12000, 3000):  # later reads fill the evidence window
        archive.read(other, start or None)
    _assemble(archive)
    for args in ({}, {'offset': 0}):
        result = archive.read(jd, args.get('offset'))
        assert result['content'], result
        assert result.get('restored_after_eviction') and not result.get('no_new_evidence')
    # An explicit nonzero offset restores exactly that evicted range.
    exact = archive.read(jd, 3000)
    assert exact['offset'] == 3000 and exact['content'] and exact['restored_after_eviction']


def test_visible_range_is_pointed_to_not_resent():
    archive = ContextArchive()
    ref = archive.reference({'description': 'short JD text ' * 50})['context_ref']
    archive.read(ref)
    _assemble(archive)  # the range is now in context_evidence
    again = archive.read(ref)
    assert again['content'] == '' and again['available_in_context'] and again['no_new_evidence']


def test_partially_read_reference_still_continues_with_default_offset():
    archive = ContextArchive()
    ref = archive.reference({'report': 'whole source ' * 3000})['context_ref']
    archive.read(ref)
    _assemble(archive)
    nxt = archive.read(ref, 0)  # stale default offset keeps advancing
    assert nxt['offset'] == 3000 and nxt['content']


def test_history_replay_content_counts_as_visible():
    archive = ContextArchive()
    ref = archive.reference({'description': 'JD body ' * 100})['context_ref']
    first = archive.read(ref)
    window = ConversationWindow()
    window.groups.append({'request': {}, 'assistant': {'text': '', 'tool_calls': [
        {'id': 'c1', 'name': 'read_context', 'args': {'ref': ref}}]},
        'results': [{'id': 'c1', 'name': 'read_context', 'value': first}]})
    archive.reads.clear()  # not in context_evidence, only in the replayed result
    archive.read(ref)
    prepare_request('Task', [], window, {'history': []}, archive)
    key = json.dumps([ref, []], ensure_ascii=False, separators=(',', ':'))
    assert any(a == 0 and b >= len(first["content"]) for a, b in archive.visible_ranges.get(key, []))


# --- C1: every scored job gets a traceable outcome -------------------------------------
from types import SimpleNamespace  # noqa: E402

import pytest  # noqa: E402
from test_career_flow import career, execute  # noqa: E402,F401
from test_remaining_search_completion import GOAL, URL, prepare  # noqa: E402


def _score_p2_style(c):
    # Paid P2: GoodApple "Data Analyst" was scored 44.03 with junior evidence
    # ("0-2 years ...") and passed every check, but was never recommended or excluded.
    prepare(c)
    c.harness.discovery = SimpleNamespace(job=lambda url: {'url': url, 'title': 'Data Analyst', 'company': 'GoodApple',
        'location': 'New York, NY', 'description': 'Requires SQL.\nRequirements: 0-2 years of marketing or analytics experience.'},
        search=lambda **_: {'jobs': [], 'errors': [], 'sources_checked': [], 'skipped_sources': []})
    execute(c, 'read_job', url=URL)
    job = execute(c, 'import_job', url=URL)
    execute(c, 'score_job', application_id=job['application_id'])
    return job['application_id']


def test_scored_job_is_pending_and_discovery_waits_for_a_decision(career):
    c = career
    app = _score_p2_style(c)
    blocked = execute(c, 'search_jobs', query='junior data analyst', location='New York, NY')
    assert blocked['error_code'] == 'pending_decisions' and blocked['no_new_evidence']
    assert [p['application_id'] for p in blocked['pending']] == [app]
    assert '0-2 years' in str(blocked['pending'][0]['qualification_evidence'])
    with pytest.raises(ValueError, match='specific reason'):
        execute(c, 'decide_job', application_id=app, decision='exclude', reason='no')
    execute(c, 'decide_job', application_id=app, decision='needs_evidence',
            reason='Location says New York but the team may be remote-first.', missing='Confirm the work location.')
    allowed = execute(c, 'search_jobs', query='junior data analyst', location='New York, NY')
    assert 'error_code' not in allowed
    known = c.harness.observe(c.repository.get(c.state['task_id']))['known_results']['scored_not_recommended'][0]
    assert known['decision_status'] == 'needs_evidence' and known['missing'] == 'Confirm the work location.'


def test_decision_reopens_when_the_user_request_changes(career):
    c = career
    app = _score_p2_style(c)
    execute(c, 'decide_job', application_id=app, decision='exclude', reason='Requires a security clearance the user lacks.')
    from agent_runtime.career.decisions import pending
    assert pending(c.repository.get(c.state['task_id'])) == []
    state = c.repository.get(c.state['task_id'])
    c.repository.change(c.state['task_id'], chat_revision=state['chat_revision'] + 1)  # new user request
    state = c.repository.get(c.state['task_id'])
    assert pending(state) == [app]
    from agent_runtime.career.decisions import statuses
    assert statuses(state)[app].get('reopened')


def test_recommended_job_is_not_pending_and_cannot_be_excluded(career):
    c = career
    app = _score_p2_style(c)
    execute(c, 'recommend_job', application_id=app, reason='Junior evidence: 0-2 years; NYC.', caveats='Limited SQL fit.')
    from agent_runtime.career.decisions import pending
    assert pending(c.repository.get(c.state['task_id'])) == []
    with pytest.raises(ValueError, match='already recommended'):
        execute(c, 'decide_job', application_id=app, decision='exclude', reason='Changed my mind about it.')


def test_no_progress_stop_delivers_saved_results_without_a_model_call(career):
    from agent_runtime.career.decisions import terminal_delivery
    c = career
    app = _score_p2_style(c)
    lines = terminal_delivery(c.repository.get(c.state['task_id']))
    assert len(lines) == 1 and 'Scored, not yet decided' in lines[0] and URL in lines[0]
    execute(c, 'recommend_job', application_id=app, reason='Junior evidence: 0-2 years; NYC.', caveats='Limited SQL fit.')
    lines = terminal_delivery(c.repository.get(c.state['task_id']))
    assert lines and lines[0].startswith('- Recommended: Data Analyst')


def test_archived_workflow_result_keeps_decision_fields_inline():
    big = {'application_id': 'a1', 'title': 'Data Analyst', 'url': URL, 'match_score': 44.03,
           'qualification_evidence': [{'quote': '0-2 years of marketing or analytics experience'}],
           'opening_level': 'junior', 'completed_steps': ['read_job', 'import_job', 'score_job'],
           'score_range': [44.03, 44.03], 'match_report': {'matches': ['x' * 200] * 60}}
    summary = ContextArchive().tool_result(big)
    assert summary['context_ref'] and summary['match_score'] == 44.03
    assert summary['opening_level'] == 'junior' and summary['completed_steps'][-1] == 'score_job'
    assert '0-2 years' in summary['qualification_evidence'][0]['quote']
