"""C16 model routing and reproducible latency measurements; paid checks opt in."""
import json
import os
import statistics
import time
from uuid import uuid4

import pytest

from agent_runtime.career.service import CareerService
from agent_runtime.mock_interview.model import SharedMockInterviewModel
from agent_runtime.provider_usage import UsageLedger, current_scope, usage_scope
from test_career_flow import career, execute, ToolModel


def feedback_terminal(view,queue,observed_count):
    """Stop on durable failure after other accepted work settles, not at 360s."""
    jobs=view.get('feedback_jobs',[])
    if observed_count==3:return 'feedback_complete'
    in_flight=any(j['status']=='pending' for j in jobs)
    queue_active=any(e['status'] in {'pending','running'} for e in queue)
    if not in_flight and not queue_active:
        if any(j['status']=='failed' for j in jobs):return 'feedback_failed'
        if any(e['status']=='failed' for e in queue):return 'input_queue_failed'
    return None


def test_live_feedback_observer_stops_on_durable_failure_without_abandoning_other_work():
    failed={'status':'failed','failure':{'error_type':'ConnectError'}}
    assert feedback_terminal({'feedback_jobs':[failed]},[{'status':'done'}],0)=='feedback_failed'
    assert feedback_terminal({'feedback_jobs':[failed,{'status':'pending'}]},[{'status':'done'}],0) is None
    assert feedback_terminal({'feedback_jobs':[failed]},[{'status':'running'}],0) is None
    assert feedback_terminal({'feedback_jobs':[failed,{'status':'done'}]},[{'status':'done'}],1)=='feedback_failed'
    assert feedback_terminal({'feedback_jobs':[]},[{'status':'failed'}],0)=='input_queue_failed'
    assert feedback_terminal({'feedback_jobs':[{'status':'done'}]*3},[{'status':'done'}]*3,3)=='feedback_complete'


def test_wrapped_httpx_connection_failure_is_unavailable_without_exposing_provider_body():
    import httpx
    from agent_runtime.mock_interview.controller import evaluation_failure
    cause=httpx.ConnectError('Synthetic private endpoint and credential must stay hidden')
    adapter=RuntimeError('Provider adapter failure');adapter.__cause__=cause
    failure=evaluation_failure(adapter)
    assert failure=={'error_code':'model_unavailable','error_type':'ConnectError','retryable':True,'http_status':None}
    assert 'private' not in str(failure)


@pytest.mark.parametrize('purpose',['agent','fast'])
def test_feedback_routes_requested_model_and_preserves_ledger_scope(monkeypatch,purpose):
    import agent_runtime.mock_interview.model as module
    calls=[]
    monkeypatch.setattr(module,'create_model',lambda **kwargs:kwargs)
    def invoke(model,schema,policy,context):
        calls.append((model,schema.__name__,current_scope(),json.loads(context)))
        return 'structured-result'
    monkeypatch.setattr(module,'invoke_structured',invoke)
    with usage_scope(task_id='synthetic-task',ledger='synthetic-ledger'):
        assert SharedMockInterviewModel(evaluation_purpose=purpose).evaluate({'answer_untrusted':'Built APIs.'})=='structured-result'
    model,schema,scope,context=calls[0]
    # Same purpose/model routing; interview calls additionally bound hidden reasoning.
    assert model['purpose']==purpose and schema=='MockAnswerEvaluation'
    assert model['environ']['LLM_AGENT_REASONING']=='low'
    assert scope['purpose']=='mock_interview_feedback'
    assert scope['task_id']=='synthetic-task' and scope['ledger']=='synthetic-ledger'
    assert context=={'answer_untrusted':'Built APIs.'}


def test_default_feedback_uses_configured_fast_model_with_main_fallback(tmp_path):
    from job_agent.model import create_model
    path=tmp_path/'empty.env';path.write_text('',encoding='utf-8')
    for setting,expected in [({'LLM_FAST_MODEL_ID':'synthetic-fast'},'synthetic-fast'),({},'synthetic-main')]:
        options=create_model(env_path=path,environ={'LLM_MODEL_ID':'synthetic-main',**setting},
            purpose=SharedMockInterviewModel().evaluation_purpose,model_factory=lambda **kwargs:kwargs)
        assert options['model']==expected


@pytest.mark.skipif(os.getenv('JOB_AGENT_LIVE_INTERVIEW')!='1',reason='Explicit paid real feedback latency check')
@pytest.mark.parametrize('lane,limit',[('agent',30),('fast',10)])
def test_real_main_chat_feedback_latency(career,tmp_path,lane,limit):
    from dotenv import dotenv_values
    settings={**dotenv_values('.env'),**os.environ}
    if lane=='fast' and not settings.get('LLM_FAST_MODEL_ID'):
        pytest.skip('LLM_FAST_MODEL_ID is not configured; main fallback is not fast evidence')
    selected_model=settings.get('LLM_FAST_MODEL_ID') if lane=='fast' else settings.get('LLM_MODEL_ID')
    c=career
    job=execute(c,'import_job',url='https://jobs.lever.co/example/feedback-synthetic')
    execute(c,'score_job',application_id=job['application_id'])
    controller=c.runtime.mock_interviewer
    controller.model=SharedMockInterviewModel(evaluation_purpose=lane)
    task_id=c.state['task_id'];ledger=UsageLedger(c.repository.sessions)
    with usage_scope(task_id=task_id,ledger=ledger,purpose='interview_setup'):
        interview=controller.start(job['application_id'],target_question_count=3,max_followups_per_question=0,
            idempotency_key='latency-start',root_task_id=task_id)
    identifier=interview.mock_interview_id
    c.repository.link(task_id,'interviews',identifier,status='needs_input')
    router=ToolModel(lambda _:('finish_task',{'text':'Unexpected model routing.'}))
    service=CareerService(c.runtime,c.applications,harness=c.harness,model_factory=lambda:router,start_alert_scheduler=False)
    texts=[
        'I built Python APIs. I added input validation and tested the error responses. The tests passed.',
        'I discussed an API response format with my teammate. I wrote an example and we agreed on the same format.',
        'I used Python to implement an API endpoint. I wrote a test for its response and checked that it passed.',
    ]
    accepted={};observed={};question_observed={};started=time.monotonic();max_pending_feedback=0
    termination='deadline'
    try:
        for text in texts:
            mid=str(uuid4());accepted[text]={'message_id':mid,'seconds':time.monotonic()-started}
            service.chat(task_id,text,mid,context={'interview_id':identifier})
        deadline=time.monotonic()+360
        while time.monotonic()<deadline:
            # Measure user-visible production projection, including queue wait,
            # not provider duration or model-supplied creation timestamps.
            view=service.view(task_id)['interviews'][0]
            if view.get('question'):
                question_observed.setdefault(view['question']['question_id'],time.monotonic()-started)
            for feedback in view.get('feedback_history',[]):
                turn=next(t for t in controller.interviews.turns(identifier)
                    if t['answer'] and t['answer']['answer_id']==feedback['answer_id'])
                if feedback['evaluation']:
                    text=turn['answer']['original_text']
                    observed.setdefault(text,{'feedback_observed_seconds':time.monotonic()-started,
                        'question_id':turn['question']['question_id'],'answer_id':turn['answer']['answer_id']})
            max_pending_feedback=max(max_pending_feedback,sum(j['status']=='pending' for j in view.get('feedback_jobs',[])))
            queue=c.repository.get(task_id).get('interview_queue',[])
            terminal=feedback_terminal(view,queue,len(observed))
            if terminal:
                termination=terminal;break
            time.sleep(.1)
        turns=controller.interviews.turns(identifier)
        samples=[observed[t]['feedback_observed_seconds']-accepted[t]['seconds'] for t in texts if t in observed]
        p50=statistics.median(samples) if len(samples)==3 else None
        usage=ledger.summary(task_id=task_id)
        feedback_groups=[g for g in usage['groups'] if g['purpose'].startswith('mock_interview_feedback:')]
        feedback_before_next=[]
        for a,b in zip(turns,turns[1:]):
            if a['answer'] and a['answer']['original_text'] in observed:
                feedback_before_next.append(question_observed.get(b['question']['question_id'],float('inf')) >=
                    observed[a['answer']['original_text']]['feedback_observed_seconds'])
        checks={'three_answers_fifo':[t['answer']['original_text'] for t in turns if t['answer']]==texts,
            'three_feedback_samples':len(samples)==3,'p50_within_original_limit':p50 is not None and p50<=limit,
            'complete_usage':usage['usage_complete'] and usage['pending']==0 and usage['unknown_usage_calls']==0,
            'feedback_uses_selected_model':bool(feedback_groups) and all(g['model']==selected_model for g in feedback_groups),
            'no_main_chat_router_calls':router.calls==0,
            'next_questions_visible_before_old_feedback':len(feedback_before_next)==2 and not any(feedback_before_next),
            'exact_feedback_binding':all(t['evaluation'] and t['evaluation']['answer_id']==t['answer']['answer_id']
                and all(q in t['answer']['original_text'] for q in t['evaluation']['exact_answer_quotes']) for t in turns if t['answer'])}
        evidence={'scope':'Production main chat FIFO, real question/feedback providers, synthetic candidate/job, polling repository feedback at 100ms',
            'lane':lane,'configured_feedback_model':selected_model,'threshold_seconds':limit,'p50_seconds':p50,
            'samples_seconds':samples,'accepted':accepted,'observed':observed,'turns':turns,
            'feedback_before_next_question':feedback_before_next,
            'next_question_first_implemented':True,'max_pending_feedback':max_pending_feedback,
            'configured_reasoning':settings.get('LLM_AGENT_REASONING'),'usage':usage,'checks':checks,
            'termination':termination,'feedback_jobs':controller.interviews.feedback_jobs(identifier),
            'session':controller.interviews.get(identifier).model_dump(mode='json'),
            'queue':c.repository.get(task_id).get('interview_queue',[])}
        (tmp_path/'feedback-latency.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
        assert all(checks.values()),checks
    finally:service.close()


def test_interview_reasoning_falls_back_when_provider_rejects_it(monkeypatch):
    import agent_runtime.mock_interview.model as module
    monkeypatch.delenv('LLM_INTERVIEW_REASONING',raising=False)
    monkeypatch.setattr(module,'create_model',lambda **kwargs:kwargs)
    seen=[]
    def invoke(model,schema,policy,context):
        seen.append(model)
        if 'environ' in model:raise ValueError("Unsupported parameter: 'reasoning_effort'")
        return 'plain-result'
    monkeypatch.setattr(module,'invoke_structured',invoke)
    assert SharedMockInterviewModel(evaluation_purpose='agent').evaluate({'answer_untrusted':'x'})=='plain-result'
    assert len(seen)==2 and 'environ' not in seen[1]
    # Unrelated provider errors are not retried.
    def failing(model,schema,policy,context):raise TimeoutError('provider')
    monkeypatch.setattr(module,'invoke_structured',failing)
    import pytest
    with pytest.raises(TimeoutError):SharedMockInterviewModel(evaluation_purpose='agent').evaluate({'answer_untrusted':'x'})
