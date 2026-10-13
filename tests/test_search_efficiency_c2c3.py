"""Efficiency changes keep semantics with the model: fewer requests, same evidence contracts."""
import asyncio
import json
import threading
import time
import unittest

import httpx
import pytest

from langchain_core.messages import AIMessage
from test_career_flow import career
from test_semantic_search_qualification import job, setup, response
import test_jev_fit_production as jev_fixture
import test_shared_agent_loop as loop_fixture
from eregion.domain.jev_fit.core import job_units
from eregion.runtime.career import qualification as q
from eregion.runtime.career.linkedin_source import search_cards
from eregion.runtime.provider_usage import TaskProviderBudgetExceeded


def test_one_item_per_line_lists_keep_each_qualifier_whole():
    jd=("Key Responsibilities:\nBuild weekly SQL reports for clients and internal teams\n\n"
        "Desired Skills/Qualifications:\n\n"
        "Bachelor's Degree with 3.0 or higher GPA or equivalent work experience\n"
        "0-2 years of marketing or analytics experience\n"
        "Fast learner, comfortable using advanced SQL, experience working with data pipelines\n")
    units=[u['text'] for u in job_units(jd)]
    assert "Bachelor's Degree with 3.0 or higher GPA or equivalent work experience" in units
    assert '0-2 years of marketing or analytics experience' in units
    assert 'Key Responsibilities:' in units and 'Key' not in units and "Bachelor's" not in units
    assert 'Desired Skills/Qualifications:' in units
    # Wrapped prose ending in a connector still stays one requirement.
    assert job_units('Requirements:\nExperience with\nPython and SQL')[-1]['text']=='Experience with\nPython and SQL'


def test_multi_page_search_text_binds_repeated_promoted_cards_without_guessing():
    text=('Data Analyst\nA Co\nNew York, NY (On-site)\nPromoted\nYield Analyst\nB Co\nNew York, NY (Hybrid)\n'
          'Data Analyst\nA Co\nNew York, NY (On-site)\nPromoted\n'          # page 2 repeats the promoted card
          'Data Analyst\nC Co\nBrooklyn, NY (Hybrid)\n')
    refs=[{'kind':'job','url':f'/jobs/view/{i}/','text':t} for i,t in
          (('111111','Data Analyst'),('222222','Yield Analyst'),('333333','Data Analyst'))]
    cards=search_cards({'sections':{'search_results':text},'references':{'search_results':refs}})
    assert cards['111111']['company']=='A Co' and cards['333333']['location']=='Brooklyn, NY (Hybrid)'
    assert cards['222222']['location']=='New York, NY (Hybrid)'
    # A third distinct card for two references is ambiguous: fields stay unknown.
    text+='Data Analyst\nD Co\nChicago, IL (On-site)\n'
    cards=search_cards({'sections':{'search_results':text},'references':{'search_results':refs}})
    assert cards['111111']['location'] is None and cards['333333']['location'] is None


def test_jev_broker_keeps_concurrent_jobs_in_one_request_per_stage():
    from eregion.domain.jev_fit.settings import Settings
    from eregion.domain.jev_fit.transport import Broker, Client
    seen=[]
    def handle(request):
        payload=json.loads(request.content);seen.append(payload)
        if 'cases' in payload['state']:  # Only the cases referenced by this request.
            assert {q['instructions']['context_case'] for q in payload['questions'].values()}==set(payload['state']['cases'])
        return httpx.Response(200,json={'model':payload['model'],'usage':{'prompt_tokens':1,'completion_tokens':1},
            'answers':{k:{'type':'noul','noul':.99} for k in payload['questions']}})
    broker=Broker(Settings(key='test-only'),None,transport=httpx.MockTransport(handle))
    scope={'owner':'t','resume':'r','facts':'f'}
    q=lambda text:{'x':{'type':'noul','instructions':{'question':text}}}
    def fast():
        c=Client(broker,{**scope,'job':'a'})
        try:
            c.evaluate({'doc':'A'},q('stage one A'),'one');c.evaluate({'doc':'A'},q('optional A'),'optional')
            c.evaluate({'doc':'A'},q('stage two A'),'two')
        finally:broker.leave()
    def slow():
        c=Client(broker,{**scope,'job':'b'})
        try:
            time.sleep(.2);c.evaluate({'doc':'B'},q('stage one B'),'one')
            time.sleep(.2);c.checkpoint('optional')   # Nothing to ask at this optional stage.
            time.sleep(.2);c.evaluate({'doc':'B'},q('stage two B'),'two')
        finally:broker.leave()
    broker.expect(2)
    threads=[threading.Thread(target=fast),threading.Thread(target=slow)]
    try:
        for t in threads:t.start()
        for t in threads:t.join(10)
    finally:broker.close()
    assert len(seen)==3  # one, optional, two: never split by worker timing
    assert [len(p['questions']) for p in seen]==[2,1,2]


class DecisionHarness(loop_fixture.Harness):
    batch_decision_tools = {'write_item'}


class DecisionBatch(unittest.TestCase):
    setUp=loop_fixture.LoopChecks.setUp
    tearDown=loop_fixture.LoopChecks.tearDown
    start=loop_fixture.LoopChecks.start

    def test_independent_decisions_in_one_response_all_execute(self):
        self.harness=DecisionHarness()
        call,finish=loop_fixture.call,loop_fixture.finish
        model=loop_fixture.Model([AIMessage(content='',tool_calls=[call('write_item',{'value':'first'},'a'),
            call('write_item',{'value':'second'},'b')]),finish('Both decisions recorded.')])
        _,task=self.start(model)
        self.assertEqual(loop_fixture.settled(self.repo,task)['status'],'completed')
        self.assertEqual(self.harness.writes,['first','second'])


def test_qualification_groups_run_concurrently_and_bind_their_own_postings(career,monkeypatch):
    repo,tid=setup(career);active=[];peak=[0];lock=threading.Lock()
    def judge(request,postings):
        with lock:active.append(1);peak[0]=max(peak[0],len(active))
        time.sleep(.2)
        with lock:active.pop()
        return response(request,postings)
    monkeypatch.setattr(q,'judge',judge)
    jobs=[job(i,title=f'Data Analyst {i}') for i in range(12)]
    results=q.record_many(repo,tid,jobs)
    assert peak[0]>1 and all(r['qualified'] for r in results)
    for j,r in zip(jobs,results):
        assert r['url']==j['url'] and r['checks']['role']['evidence'][0]['quote']==j['title']


def test_budget_stop_in_one_group_propagates_and_saves_nothing_unverified(career,monkeypatch):
    repo,tid=setup(career)
    def judge(request,postings):
        if any(p['title'].endswith(' 7') for p in postings):raise TaskProviderBudgetExceeded('limit')
        return response(request,postings)
    monkeypatch.setattr(q,'judge',judge)
    jobs=[job(i,title=f'Data Analyst {i}') for i in range(12)]
    with pytest.raises(TaskProviderBudgetExceeded):
        q.record_many(repo,tid,jobs)
    saved=repo.get(tid).get('candidate_qualifications',{})
    assert all(row['review']['method']=='model_with_verified_quotes' for row in saved.values())
    assert not any(k.endswith('/7') for k in saved)


def test_batch_summary_keeps_every_candidate_visible_without_paging():
    from eregion.runtime.request_context import ContextArchive
    rows=[{'url':f'https://www.linkedin.com/jobs/view/{1000000+i}/','title':f'Data Analyst {i}','status':'needs_evidence',
           'qualification':{'checks':{'role':{'status':'met','quote':'Data Analyst '*40},
                                      'location':{'status':'unknown','quote':'','reason':'Only a country is stated.'}}}}
          for i in range(20)]
    summary=ContextArchive().tool_result({'jobs':[],'candidates':rows,'qualified_count':0,'filler':'x'*6000})
    assert len(summary['candidates'])==20
    assert summary['candidates'][19]['checks']=={'role':{'status':'met'},
        'location':{'status':'unknown','reason':'Only a country is stated.'}}


def test_audit_retries_only_a_structurally_unusable_reply(monkeypatch):
    from evals import search_semantic_audit as audit
    from eregion.domain import model
    replies=[]
    def invoke(_model,schema,prompt,text):
        postings=json.loads(text)['postings']
        value=response('Find junior data analyst jobs in New York.',postings)
        if not replies:value.decisions[0].posting_id='posting-0'   # malformed identity once
        replies.append(value);return value
    monkeypatch.setattr(model,'invoke_structured',invoke)
    monkeypatch.setattr(model,'shared_model',lambda **_:object())
    jobs=[job(i) for i in range(2)]
    out=audit.review('Find junior data analyst jobs in New York.',jobs)
    assert len(replies)==2 and set(out)=={j['url'] for j in jobs}
    replies.clear()
    def always_bad(_model,schema,prompt,text):
        value=response('x',json.loads(text)['postings']);value.decisions[0].posting_id='bad';replies.append(1);return value
    monkeypatch.setattr(model,'invoke_structured',always_bad)
    with pytest.raises(ValueError):audit.review('Find junior data analyst jobs in New York.',jobs)
    assert len(replies)==2   # bounded: never a third attempt


def test_truncated_reply_gets_a_specific_bounded_repair():
    from langchain_core.messages import AIMessage
    from eregion.runtime.model_output import output_problem, REPAIR_INSTRUCTION, TRUNCATED_INSTRUCTION
    cut=AIMessage(content='',tool_calls=[{'name':'recommend_job','args':{'application_id':'a'},'id':'1'}],
                  response_metadata={'finish_reason':'length'})
    assert output_problem(cut)=='incomplete_response'
    seen=[]
    class Fixed(loop_fixture.Model):
        def invoke(self,messages,tools):
            seen.append(messages);return super().invoke(messages,tools)
    case=DecisionBatch('test_independent_decisions_in_one_response_all_execute')
    case.setUp()
    try:
        case.harness=DecisionHarness()
        model=Fixed([cut,loop_fixture.finish('Done.')])
        _,task=case.start(model)
        assert loop_fixture.settled(case.repo,task)['status']=='completed'
        repair=' '.join(str(getattr(m,'content','')) for m in seen[1])
        assert TRUNCATED_INSTRUCTION.strip() in repair and case.harness.writes==[]
    finally:case.tearDown()
