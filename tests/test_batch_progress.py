"""Regressions from the 39-call live run that never imported/scored a candidate."""
import pytest
from test_career_flow import career, execute
from eregion.runtime.career.posting_brief import with_brief
from eregion.runtime.career.search_filters import filter_cards
from eregion.runtime.career.candidate_queue import enabled
from eregion.runtime.core.engine import ToolArgumentsError
from eregion.runtime.tasks.host import TaskHost


def test_api_first_defaults_enable_existing_workflow_and_queue(career, monkeypatch):
    monkeypatch.setenv('JOB_AGENT_JOB_API_FIRST','1')
    monkeypatch.delenv('JOB_AGENT_OPT_VERIFY_AND_SCORE',raising=False)
    monkeypatch.delenv('JOB_AGENT_OPT_CANDIDATE_BATCHES',raising=False)
    assert enabled()
    assert 'verify_and_score' in {t['function']['name'] for t in career.harness.available_tools(career.state)}
    monkeypatch.setenv('JOB_AGENT_OPT_VERIFY_AND_SCORE','0')
    monkeypatch.setenv('JOB_AGENT_OPT_CANDIDATE_BATCHES','0')
    assert not enabled()
    assert 'verify_and_score' not in {t['function']['name'] for t in career.harness.available_tools(career.state)}


def test_dismiss_requires_read_literal_evidence_and_expires(career, monkeypatch):
    monkeypatch.setenv('JOB_AGENT_JOB_API_FIRST','1')
    c=career
    monkeypatch.setattr(c.harness.discovery,'search_directory',c.harness.discovery.search,raising=False)
    c.repository.change(c.state['task_id'],goal='Find 15 current Python engineer jobs.',messages=[])
    url='https://jobs.lever.co/example/abc123'
    with pytest.raises(ValueError,match='Read this posting'):
        execute(c,'dismiss_candidate',url=url,quote='Remote',reason='User requests onsite')
    execute(c,'read_job',url=url)
    assert execute(c,'search_jobs',query='Python')['error_code']=='candidates_in_progress'
    with pytest.raises(ValueError,match='exact excerpt'):
        execute(c,'dismiss_candidate',url=url,quote='New York',reason='Wrong city')
    result=execute(c,'dismiss_candidate',url=url,quote='Remote',reason='User requests onsite')
    assert result['decision']=='dismissed'
    assert 'error_code' not in execute(c,'search_jobs',query='Python',use_directory=False)
    from eregion.runtime.career.candidate_health import active_rejections
    state=c.repository.get(c.state['task_id'])
    assert len(active_rejections(state))==1
    assert not active_rejections({**state,'chat_revision':state['chat_revision']+1})


def test_brief_keeps_exact_late_requirements_without_replacing_body():
    text=('Company introduction.\n'*400)+'Requires 0–2 years of experience.\nLocation: New York.\n'
    job={'url':'https://example.com/jobs/1','title':'Data Analyst','description':text}
    result=with_brief(job)
    assert result['description']==text
    assert any(e['start']>3000 and '0–2' in e['quote'] for e in result['triage_evidence'])
    assert all(text[e['start']:e['end']]==e['quote'] for e in result['triage_evidence'])
    from eregion.runtime.request_context import ContextArchive
    archive=ContextArchive()
    compact=archive.tool_result(result)
    assert compact['triage_evidence']==result['triage_evidence']
    assert 'context_ref' in compact


def test_role_ranking_retains_unknown_candidates():
    state={'goal':'Find 15 current junior data analyst positions in New York.'}
    cards=[{'title':'Yield Analyst'},{'title':'Data Analyst'},{'title':'Unknown'}]
    result,info=filter_cards(cards,state)
    assert result[0]['title']=='Data Analyst'
    assert len(result)==3 and info['excluded']==[]


def test_plan_repair_returns_exact_valid_shape():
    result=TaskHost._action_error(None,ToolArgumentsError('update_plan.steps[] must have type string.'))
    assert '"steps":["Verify candidates","Score matches"]' in result['next']


def test_workflow_scores_unverified_location_as_unconfirmed(career,monkeypatch):
    # Show by default (handoff 12.22): an unverified location is scored and carried as a
    # near miss (never priority); a clear mismatch is what skips paid scoring (test_qualified_batch).
    monkeypatch.setenv('JOB_AGENT_JOB_API_FIRST','1')
    c=career
    c.repository.change(c.state['task_id'],goal='Find 15 current junior data analyst positions in New York.',messages=[])
    result=execute(c,'verify_and_score',url='https://jobs.lever.co/example/abc123')
    state=c.repository.get(c.state['task_id'])
    assert state['jobs']==[result['application_id']]
    (row,)=state['candidate_qualifications'].values()
    assert row['qualified'] and 'location' in [m['field'] for m in row['near_misses'] if m['status']=='unknown']
    repeated=execute(c,'verify_and_score',url='https://jobs.lever.co/example/abc123')
    assert repeated['no_new_evidence']


def test_explicit_high_experience_overrides_junior_title():
    from fake_search_qualification import recommendation_warning
    warning=recommendation_warning({'levels':['junior'],'strict':False},'Junior Data Analyst','Requires 5 years of experience.')
    assert warning['actual']=='senior'
