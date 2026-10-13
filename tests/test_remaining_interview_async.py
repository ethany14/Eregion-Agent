"""Production chat/DB pipeline with deterministic delayed providers, no fees."""
import copy
import json
from threading import Barrier, Event, RLock, Thread
from types import SimpleNamespace
from uuid import uuid4

import pytest

from eregion.runtime.career.service import CareerService
from eregion.runtime.mock_interview.errors import MockInterviewConflict
from test_career_flow import career, ToolModel
from test_remaining_interview_fifo import prepared,wait_for


def service_for(c,runtime=None,harness=None):
    return CareerService(runtime or c.runtime,c.applications,harness=harness or c.harness,
        model_factory=lambda:ToolModel(lambda _:('finish_task',{'text':'Unexpected router'})),start_alert_scheduler=False)


def chat(service,c,identifier,text):
    mid=str(uuid4());service.chat(c.state['task_id'],text,mid,context={'interview_id':identifier});return mid


def answered(controller,identifier):
    return [turn for turn in controller.interviews.turns(identifier) if turn['answer']]


def test_two_repository_instances_cannot_overwrite_answer_receipt_with_chat_update(career):
    from eregion.runtime.career.repository import TaskRepository
    c=career;other=TaskRepository(c.repository.sessions);barrier=Barrier(2)
    seen={};errors=[]
    def mutate(key):
        def update(state):
            seen[key]=seen.get(key,0)+1
            if seen[key]==1:barrier.wait(timeout=5)
            return {'interview_answer_receipts':{'interview':['A1']}} if key=='receipt' else {
                'messages':[*state['messages'],{'id':'A2','role':'user','text':'Second answer','at':'2099-01-01'}]}
        return update
    def work(repo,key):
        try:repo.change(c.state['task_id'],mutate(key))
        except Exception as exc:errors.append(exc)
    workers=[Thread(target=work,args=(repo,key)) for repo,key in ((c.repository,'receipt'),(other,'chat'))]
    for worker in workers:worker.start()
    for worker in workers:worker.join(timeout=8)
    assert not errors and all(not worker.is_alive() for worker in workers)
    saved=c.repository.get(c.state['task_id'])
    assert saved['interview_answer_receipts']=={'interview':['A1']}
    assert sum(message['id']=='A2' for message in saved['messages'])==1


def test_q2_q3_visible_before_old_feedback_and_end_waits_for_complete_report(career,tmp_path):
    c=career;controller,identifier=prepared(c)
    actual=controller.model.evaluate;gates={f'A{i}':Event() for i in range(1,4)}
    def evaluate(context):
        prefix=context['answer_untrusted'].split(':')[0]
        assert gates[prefix].wait(15)
        return actual(context)
    controller.model.evaluate=evaluate
    service=service_for(c)
    try:
        questions=[]
        for i in range(1,4):
            questions.append(controller.interviews.get(identifier).current_question_id)
            chat(service,c,identifier,f'A{i}: I built Python APIs.')
            wait_for(lambda:len(answered(controller,identifier))==i and
                controller.interviews.get(identifier).status.value=='awaiting_answer')
        current=controller.interviews.get(identifier).current_question_id
        assert current not in questions and len(set(questions))==3
        assert all(t['evaluation'] is None for t in answered(controller,identifier))
        assert controller.interviews.get(identifier).questions_completed==0
        chat(service,c,identifier,'End the interview.')
        assert controller.interviews.report(identifier) is None
        gates['A3'].set()
        wait_for(lambda:controller.interviews.evaluation(answered(controller,identifier)[2]['answer']['answer_id']))
        assert controller.interviews.get(identifier).current_question_id==current
        assert controller.interviews.get(identifier).questions_completed==1
        gates['A2'].set();gates['A1'].set()
        report=wait_for(lambda:controller.interviews.report(identifier))
        assert controller.interviews.get(identifier).questions_completed==3
        turns=answered(controller,identifier)
        assert [t['answer']['sequence'] for t in turns]==[1,2,3]
        assert [t['answer']['question_id'] for t in turns]==questions
        assert all(t['evaluation']['answer_id']==t['answer']['answer_id'] for t in turns)
        assert all(t['overall_score'] is not None for t in report['question_answer_summaries'] if t['answer'])
        before=controller.interviews.get(identifier).questions_completed
        controller.interviews.save_deferred_evaluation(identifier,
            controller.interviews.evaluation(turns[0]['answer']['answer_id']),followup=False)
        assert controller.interviews.get(identifier).questions_completed==before
        (tmp_path/'async-order-and-end.json').write_text(json.dumps({'questions':questions,'turns':turns,
            'report':report,'queue':c.repository.get(c.state['task_id'])['interview_queue'],
            'provider_io':'deterministic events, no real-model latency claim'},indent=2),encoding='utf-8')
    except Exception:
        (tmp_path/'failure-state.json').write_text(json.dumps({'state':c.repository.get(c.state['task_id']),
            'session':controller.interviews.get(identifier).model_dump(mode='json'),
            'feedback_jobs':controller.interviews.feedback_jobs(identifier),
            'turns':controller.interviews.turns(identifier),'scope':'Captured before releasing feedback gates in teardown'},indent=2),encoding='utf-8')
        raise
    finally:
        for gate in gates.values():gate.set()
        service.close()


def test_feedback_version_advances_while_q2_provider_paused_without_losing_q2_or_fifo(career):
    c=career;controller,identifier=prepared(c)
    q2_started=Event();release_q2=Event();release_feedback=Event()
    question=controller.model.question;evaluate=controller.model.evaluate
    def paused_question(context):
        q2_started.set();assert release_q2.wait(15)
        return question(context)
    def paused_feedback(context):
        assert release_feedback.wait(15);return evaluate(context)
    controller.model.question=paused_question;controller.model.evaluate=paused_feedback
    service=service_for(c)
    try:
        chat(service,c,identifier,'A1: I wrote an API.')
        assert q2_started.wait(5)
        before=controller.interviews.get(identifier).version
        release_feedback.set()
        wait_for(lambda:answered(controller,identifier)[0]['evaluation'])
        assert controller.interviews.get(identifier).version>before
        assert controller.interviews.get(identifier).current_question_id is None
        release_q2.set()
        q2=wait_for(lambda:controller.interviews.get(identifier).current_question_id)
        assert controller.interviews.get(identifier).status.value=='awaiting_answer'
        chat(service,c,identifier,'A2: I tested the result.')
        wait_for(lambda:len(answered(controller,identifier))==2)
        assert answered(controller,identifier)[1]['answer']['question_id']==q2
        assert not any(e['status']=='failed' for e in c.repository.get(c.state['task_id'])['interview_queue'])
    finally:release_q2.set();release_feedback.set();service.close()


@pytest.mark.parametrize('answer_count',[2,3])
def test_saved_answer_dispatch_retries_old_feedback_version_race_without_duplicate_answer(career,monkeypatch,answer_count):
    from eregion.runtime.mock_interview.repository import MockInterviewRepository
    c=career;controller,identifier=prepared(c)
    release_old=Event();old_saved=Event();paused=Event();conflicts=[]
    evaluate=controller.model.evaluate;advance=MockInterviewRepository._advance
    save=controller.interviews.save_deferred_evaluation;old_commits=[]
    def delayed(context):
        if not context['answer_untrusted'].startswith(f'A{answer_count}:'):assert release_old.wait(10)
        return evaluate(context)
    controller.model.evaluate=delayed
    def save_feedback(*args,**kwargs):
        result=save(*args,**kwargs);old_commits.append(True)
        if len(old_commits)>=answer_count-1:old_saved.set()
        return result
    monkeypatch.setattr(controller.interviews,'save_deferred_evaluation',save_feedback)
    def advance_at_dispatch(db,row,version,**values):
        if row.mock_interview_id==identifier and row.answer_sequence==answer_count and values.get('status')=='planning' and not paused.is_set():
            # The final answer is committed; its defer transaction read an old
            # version. Let Q1 (and Q2) feedback commit before that CAS write.
            paused.set();release_old.set();assert old_saved.wait(6)
            try:return advance(db,row,version,**values)
            except MockInterviewConflict:
                conflicts.append(version);raise
        return advance(db,row,version,**values)
    monkeypatch.setattr(MockInterviewRepository,'_advance',staticmethod(advance_at_dispatch))
    service=service_for(c)
    try:
        for i in range(1,answer_count+1):
            current=controller.interviews.get(identifier).current_question_id
            chat(service,c,identifier,f'A{i}: I built and tested an API.')
            wait_for(lambda:controller.interviews.get(identifier).current_question_id not in {None,current})
        chat(service,c,identifier,'End the interview.')
        report=wait_for(lambda:controller.interviews.report(identifier))
        wait_for(lambda:all(e['status']=='done' for e in c.repository.get(c.state['task_id'])['interview_queue']))
        assert paused.is_set() and len(conflicts)==1
        assert len(controller.interviews.feedback_jobs(identifier))==answer_count
        assert [t['answer']['sequence'] for t in answered(controller,identifier)]==list(range(1,answer_count+1))
        assert controller.interviews.get(identifier).questions_completed==answer_count
        assert all(turn['overall_score'] is not None for turn in report['question_answer_summaries'] if turn['answer'])
    finally:release_old.set();service.close()


@pytest.mark.parametrize('phase',['after_answer','after_queue','after_feedback'])
def test_new_service_recovers_pending_or_committed_feedback_without_duplicate_answers(career,tmp_path,phase):
    from eregion.api.db import create_database
    from eregion.runtime.career.harness import CareerHarness
    from eregion.runtime.career.repository import TaskRepository
    from eregion.runtime.mock_interview.repository import MockInterviewRepository
    c=career;controller,identifier=prepared(c)
    mid=str(uuid4());text='A1: Durable Python answer.'
    c.repository.append(c.state['task_id'],role='user',text=text,id=mid,context={'interview_id':identifier})
    state=c.repository.get(c.state['task_id']);message=next(m for m in state['messages'] if m['id']==mid)
    c.harness.interview_inputs.route(state,message)
    q1=controller.interviews.get(identifier).current_question_id
    c.harness.interview_inputs._update(c.state['task_id'],mid,status='running',question_id=q1)
    if phase=='after_answer':
        controller.interviews.save_answer(identifier,q1,text,controller.interviews.get(identifier).version,f'career:{mid}:{q1}')
    else:controller.answer_deferred(identifier,text,question_id=q1,idempotency_key=f'career:{mid}:{q1}',dispatch=lambda:None)
    q2=controller.interviews.get(identifier).current_question_id
    if phase=='after_feedback':controller.evaluate_deferred(identifier,controller.interviews.feedback_jobs(identifier)[0])
    c.repository.change(c.state['task_id'],messages=[])
    db=create_database(f"sqlite:///{(tmp_path/'career.db').as_posix()}")
    restored=copy.copy(controller);restored.interviews=MockInterviewRepository(db.session_factory)
    restored._transition_locks={};restored._transition_locks_guard=RLock()
    runtime=SimpleNamespace(**{**vars(c.runtime),'database':db,'mock_interviewer':restored})
    repo=TaskRepository(db.session_factory)
    harness=CareerHarness(runtime,c.applications,repo,discovery=c.harness.discovery,fit_service=c.harness.analysis._fit_service)
    before=controller.model.evaluations
    service=service_for(c,runtime,harness)
    try:
        wait_for(lambda:bool(restored.interviews.feedback_jobs(identifier)) and
            restored.interviews.feedback_jobs(identifier)[0]['status']=='done')
        wait_for(lambda:repo.get(c.state['task_id'])['interview_queue'][0]['status']=='done')
        assert len(answered(restored,identifier))==1
        if phase=='after_answer':assert restored.interviews.get(identifier).current_question_id not in {None,q1}
        else:assert restored.interviews.get(identifier).current_question_id==q2
        assert restored.interviews.get(identifier).questions_completed==1
        assert controller.model.evaluations-before==(0 if phase=='after_feedback' else 1)
    finally:service.close();db.close()


def test_delayed_adaptive_followup_keeps_current_question_and_original_parent(career):
    c=career;controller,identifier=prepared(c)
    # Preserve adaptive semantics: a late follow-up is queued after the already
    # displayed question, never replaces it or consumes another answer's text.
    from sqlalchemy import update
    from eregion.runtime.mock_interview.models import MockInterviewRow
    with c.runtime.database.session_factory.begin() as db:
        db.execute(update(MockInterviewRow).where(MockInterviewRow.mock_interview_id==identifier).values(max_followups_per_question=1))
    actual=controller.model.evaluate;gate=Event()
    def evaluate(context):
        if context['answer_untrusted'].startswith('A1:'):assert gate.wait(15)
        result=actual(context)
        needed=context['answer_untrusted'].startswith('A1:')
        return result.model_copy(update={'followup_needed':needed,'followup_reason':'Clarify the result.' if needed else None})
    controller.model.evaluate=evaluate
    service=service_for(c)
    try:
        q1=controller.interviews.get(identifier).current_question_id
        chat(service,c,identifier,'A1: I built a Python API.')
        q2=wait_for(lambda:controller.interviews.get(identifier).current_question_id if
            controller.interviews.get(identifier).current_question_id!=q1 else None)
        gate.set();wait_for(lambda:answered(controller,identifier)[0]['evaluation'])
        assert controller.interviews.get(identifier).current_question_id==q2
        assert controller.interviews.get(identifier).questions_completed==0
        chat(service,c,identifier,'A2: I explained the outcome.')
        followup=wait_for(lambda:controller.interviews.question(controller.interviews.get(identifier).current_question_id)
            if controller.interviews.get(identifier).current_question_id not in {None,q2} else None)
        assert followup.is_followup and followup.parent_question_id==q1
        chat(service,c,identifier,'A3: The API test passed.')
        wait_for(lambda:len(answered(controller,identifier))==3 and all(t['evaluation'] for t in answered(controller,identifier)))
        assert controller.interviews.get(identifier).questions_completed==2  # two base items, one follow-up
    finally:gate.set();service.close()


def test_failed_feedback_waits_for_explicit_retry_and_queued_end_keeps_saved_answer(career,tmp_path):
    c=career;controller,identifier=prepared(c)
    evaluate=controller.model.evaluate;retry_allowed=Event();calls=[]
    def fail_until_retry(context):
        calls.append(context['answer_untrusted'])
        if not retry_allowed.is_set():raise ValueError('Synthetic feedback outage')
        return evaluate(context)
    controller.model.evaluate=fail_until_retry
    service=service_for(c)
    try:
        chat(service,c,identifier,'A1: I built Python APIs.')
        wait_for(lambda:bool(controller.interviews.feedback_jobs(identifier)) and
            controller.interviews.feedback_jobs(identifier)[0]['status']=='failed')
        chat(service,c,identifier,'End the interview.')
        wait_for(lambda:any(e['kind']=='end' and e['status']=='failed'
            for e in c.repository.get(c.state['task_id'])['interview_queue']))
        assert len(calls)==2  # existing validation repair, no automatic retry storm
        assert controller.interviews.report(identifier) is None
        assert len(answered(controller,identifier))==1
        current=controller.interviews.get(identifier).current_question_id
        service.close()
        service=service_for(c)
        assert len(calls)==2  # recovery must not spend on failed feedback silently
        retry_allowed.set()
        chat(service,c,identifier,'Retry interview feedback.')
        report=wait_for(lambda:controller.interviews.report(identifier))
        wait_for(lambda:all(e['status']=='done' for e in c.repository.get(c.state['task_id'])['interview_queue']))
        turns=answered(controller,identifier)
        assert len(calls)==3 and len(turns)==1
        assert controller.interviews.get(identifier).questions_completed==1
        assert turns[0]['evaluation']['answer_id']==turns[0]['answer']['answer_id']
        assert all(j['status']=='done' for j in controller.interviews.feedback_jobs(identifier))
        assert any(t['answer'] and t['overall_score'] is not None for t in report['question_answer_summaries'])
        (tmp_path/'explicit-feedback-retry.json').write_text(json.dumps({'calls':len(calls),
            'question_before_end':current,'turns':turns,'report':report,
            'queue':c.repository.get(c.state['task_id'])['interview_queue']},indent=2),encoding='utf-8')
    finally:retry_allowed.set();service.close()
