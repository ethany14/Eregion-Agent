"""The actual rejected talent-network body must not become new evidence per tool."""
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from langchain_core.messages import HumanMessage

from agent_runtime.career.candidate_health import active_rejections
from agent_runtime.career.posting_qualification import PostingRejected
from agent_runtime.loop_context import ConversationWindow
from agent_runtime.request_context import ContextArchive,prepare_request
from test_career_flow import career,execute
from test_remaining_search_completion import prepare
from test_remaining_search_runtime import host_for


def rejected_page(c):
    prepare(c)
    actual=json.loads((Path(__file__).parent/'fixtures/remaining_candidate_recovery.json').read_text(encoding='utf-8'))['jobs'][0]
    page={'url':actual['url'],'title':'Junior Data Analyst','primary_heading':'Junior Data Analyst',
        'text':actual['description'],'body_scope':'bounded_selector','page_evidence_hash':'original-source',
        'observation_id':'first','controls':[]}
    calls=[]
    c.harness._browsing=SimpleNamespace(inspect=lambda _:page,call=lambda *a,**k:calls.append((a,k)) or dict(page),close=lambda:None)
    with pytest.raises(PostingRejected) as caught:execute(c,'read_job',url=page['url'])
    assert caught.value.code=='not_current_vacancy'
    return page,calls,caught.value


def test_actual_rejection_is_shared_across_tools_and_survives_new_harness(career,tmp_path):
    from agent_runtime.career.harness import CareerHarness
    c=career;page,calls,first=rejected_page(c)
    assert len(calls)==1
    state=c.repository.get(c.state['task_id']);record=active_rejections(state)[0]
    assert record['body_hash']==first.evidence['body_hash']
    restored=CareerHarness(c.runtime,c.applications,c.repository,discovery=c.harness.discovery,fit_service=c.harness.analysis._fit_service)
    restored._browsing=c.harness._browsing
    try:
        for name,args in [
            ('browser_open',{'url':page['url']}),('read_job',{'url':page['url']}),
            ('browser_read',{'query':'Junior Data Analyst'}),
            ('browser_read',{'query':'requirements','text_offset':500,'navigation_only':True}),
            ('import_job',{'url':page['url'],'title':'Junior Data Analyst'}),
        ]:
            with pytest.raises(PostingRejected) as repeated:
                restored.execute(c.state['task_id'],name,args,call_id=str(uuid4()))
            assert repeated.value.repeated and repeated.value.evidence['body_hash']==record['body_hash']
        assert len(calls)==1
        assert not c.repository.get(c.state['task_id'])['jobs']
        host=host_for(c);turn=host.observe()
        messages,metrics=prepare_request(turn.prompt,turn.tools,ConversationWindow(),turn.snapshot,ContextArchive(),max_chars=48000)
        live=json.loads(next(m.content for m in reversed(messages) if isinstance(m,HumanMessage)))
        assert live['known_results']['excluded_candidates'][0]['body_hash']==record['body_hash']
        assert 'talent network' in live['known_results']['excluded_candidates'][0]['reason']
        (tmp_path/'candidate-exclusion.json').write_text(json.dumps({'record':record,'browser_calls':len(calls),
            'effective_exclusions':live['known_results']['excluded_candidates'],'metrics':metrics},indent=2),encoding='utf-8')
    finally:restored.close()


def test_rejection_progress_is_shared_across_open_read_import(career):
    c=career;page,calls,first=rejected_page(c)
    host=host_for(c);turn=host.observe()
    host.after_action({'name':'read_job','args':{'url':page['url']},'id':str(uuid4())},first.outcome(),turn)
    fingerprints=[]
    for name,args in [('browser_open',{'url':page['url']}),('import_job',{'url':page['url']})]:
        try:execute(c,name,**args)
        except PostingRejected as exc:outcome=host.action_error(exc)
        host.after_action({'name':name,'args':args,'id':str(uuid4())},outcome,turn)
        fingerprints.append(c.repository.get(c.state['task_id'])['history'][-1]['outcome_fingerprint'])
    state=c.repository.get(c.state['task_id'])
    assert len(set(fingerprints))==1 and state['progress_guard']['count']==2
    assert len(calls)==1


@pytest.mark.parametrize('change',['body','new_turn','view_only'])
def test_real_source_changes_or_new_user_turn_can_recheck_but_views_cannot(career,change):
    c=career;page,calls,_=rejected_page(c)
    if change=='new_turn':c.repository.change(c.state['task_id'],chat_revision=1)
    elif change=='body':
        page.update(page_evidence_hash='changed-source',text='We are hiring a Junior Data Analyst for our New York office. This full-time position requires SQL and Python, 0-2 years of experience. Apply for this role using requisition DA-123.')
    else:page.update(query='new wording',observation_id='different-view',region_ref='other-region')
    if change=='view_only':
        with pytest.raises(PostingRejected) as caught:execute(c,'read_job',url=page['url'])
        assert caught.value.repeated and len(calls)==1
    elif change=='new_turn':
        assert active_rejections(c.repository.get(c.state['task_id']))==[]
        with pytest.raises(PostingRejected) as caught:execute(c,'read_job',url=page['url'])
        assert not caught.value.repeated and len(calls)==2
    else:
        assert execute(c,'read_job',url=page['url'])['description'].endswith('DA-123.')
        assert not active_rejections(c.repository.get(c.state['task_id']))
        assert len(calls)==2


def test_unrelated_source_change_does_not_turn_same_rejected_body_into_progress(career):
    c=career;page,calls,first=rejected_page(c)
    page['page_evidence_hash']='different-sidebar-same-target-body'
    with pytest.raises(PostingRejected) as caught:execute(c,'read_job',url=page['url'])
    assert caught.value.repeated and caught.value.evidence['body_hash']==first.evidence['body_hash']
    with pytest.raises(PostingRejected):execute(c,'import_job',url=page['url'])
    assert len(calls)==2  # One changed-source probe, then no further cross-tool retry.


def test_http_rejection_without_hash_allows_one_observation_not_infinite_progress(career):
    c=career;prepare(c)
    actual=json.loads((Path(__file__).parent/'fixtures/remaining_candidate_recovery.json').read_text(encoding='utf-8'))['jobs'][0]
    # Match the actual rendered title/body so the first observation adds a
    # source hash, not a different target body or invented identity.
    job={**actual,'title':'Junior Data Analyst','company':'','location':'',
        'description':'Junior Data Analyst\n'+actual['description']}
    c.harness.discovery.job=lambda _:job
    with pytest.raises(PostingRejected) as first:execute(c,'read_job',url=job['url'])
    record=active_rejections(c.repository.get(c.state['task_id']))[0]
    assert record['page_evidence_hash'] is None
    page={'url':job['url'],'title':job['title'],'primary_heading':job['title'],
        'text':actual['description'],'body_scope':'bounded_selector','page_evidence_hash':'first-real-observation',
        'observation_id':'first','controls':[]}
    calls=[]
    c.harness._browsing=SimpleNamespace(inspect=lambda _:page,call=lambda *a,**k:calls.append(a) or page,close=lambda:None)
    host=host_for(c);turn=host.observe()
    host.after_action({'name':'read_job','args':{'url':job['url']},'id':str(uuid4())},first.value.outcome(),turn)
    with pytest.raises(PostingRejected) as probe:execute(c,'read_job',url=job['url'])
    assert probe.value.repeated and len(calls)==1
    assert active_rejections(c.repository.get(c.state['task_id']))[0]['page_evidence_hash']=='first-real-observation'
    host.after_action({'name':'read_job','args':{'url':job['url']},'id':str(uuid4())},probe.value.outcome(),turn)
    assert c.repository.get(c.state['task_id'])['progress_guard']['count']==1
    for name in ('browser_open','read_job','import_job'):
        with pytest.raises(PostingRejected) as repeat:execute(c,name,url=job['url'])
        assert repeat.value.repeated
    assert len(calls)==1
