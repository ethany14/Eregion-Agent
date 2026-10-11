"""C16: main chat routing and persisted interview answers, not serial controller calls."""
import json
import time
from threading import Event
from uuid import uuid4

import pytest

from agent_runtime.career.service import CareerService
from test_career_flow import career, execute, ToolModel


def prepared(c):
    from test_mock_interview import ScriptedModel
    job=execute(c,'import_job',url='https://jobs.lever.co/example/abc123')
    execute(c,'score_job',application_id=job['application_id'])
    controller=c.runtime.mock_interviewer
    controller.model=ScriptedModel()
    interview=controller.start(job['application_id'],target_question_count=5,max_followups_per_question=0,
        idempotency_key='fifo-start')
    c.repository.link(c.state['task_id'],'interviews',interview.mock_interview_id,status='needs_input')
    return controller,interview.mock_interview_id


def wait_for(predicate,seconds=12):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        result=predicate()
        if result:return result
        time.sleep(.02)
    raise AssertionError('FIFO production state did not reach its expected result')


@pytest.mark.parametrize('ending',[False,True])
def test_main_chat_rapid_answers_are_fifo_and_direct_end_waits_for_queue(career,tmp_path,ending):
    c=career;controller,identifier=prepared(c)
    started=Event();release=Event();actual=controller.model.evaluate
    def evaluate(context):
        if not started.is_set():
            started.set()
            assert release.wait(12),'Test did not release synthetic first evaluation'
        return actual(context)
    controller.model.evaluate=evaluate
    def choose(snapshot):
        current=c.harness.interview(identifier)['current_question']
        latest=next(m for m in reversed(snapshot['messages']) if m['role']=='user')
        return 'answer_interview',{'interview_id':identifier,'question_id':current['question_id'],'message_id':latest['id']}
    model=ToolModel(choose)
    service=CareerService(c.runtime,c.applications,harness=c.harness,model_factory=lambda:model,start_alert_scheduler=False)
    ids=[str(uuid4()) for _ in range(3)]
    try:
        service.chat(c.state['task_id'],'A1: I built Python APIs.',ids[0],context={'interview_id':identifier})
        assert started.wait(5)
        service.chat(c.state['task_id'],'A2: I tested the SQL results.',ids[1],context={'interview_id':identifier})
        service.chat(c.state['task_id'],'A3: I explained the result to my team.',ids[2],context={'interview_id':identifier})
        if ending:
            service.chat(c.state['task_id'],'End the interview.',str(uuid4()),context={'interview_id':identifier})
            service.chat(c.state['task_id'],'A4: This arrived after end.',str(uuid4()),context={'interview_id':identifier})
            assert controller.interviews.report(identifier) is None
            assert controller.interviews.get(identifier).status.value!='completed'
        release.set()
        turns=wait_for(lambda:[t for t in controller.interviews.turns(identifier) if t['answer']]
            if len([t for t in controller.interviews.turns(identifier) if t['answer']])==3 else None)
        assert [t['answer']['original_text'].split(':')[0] for t in turns]==['A1','A2','A3']
        assert [t['answer']['sequence'] for t in turns]==[1,2,3]
        assert len({t['question']['question_id'] for t in turns})==3
        if ending:
            report=wait_for(lambda:controller.interviews.report(identifier))
            assert len(report['question_answer_summaries'])>=3
            assert controller.interviews.get(identifier).status.value=='completed'
        else:wait_for(lambda:controller.interviews.get(identifier).status.value=='awaiting_answer')
        assert model.calls==0
        # Replay a received HTTP message cannot record another answer.
        service.chat(c.state['task_id'],'A1: I built Python APIs.',ids[0],context={'interview_id':identifier})
        assert len([t for t in controller.interviews.turns(identifier) if t['answer']])==3
        (tmp_path/'main-chat-fifo.json').write_text(json.dumps({'provider_io':'synthetic',
            'turns':controller.interviews.turns(identifier),'queue':c.repository.get(c.state['task_id']).get('interview_queue'),
            'model_calls':model.calls,'ending':ending},indent=2),encoding='utf-8')
    except Exception:
        (tmp_path/'failure-state.json').write_text(json.dumps({'state':c.repository.get(c.state['task_id']),
            'session':controller.interviews.get(identifier).model_dump(mode='json'),
            'feedback_jobs':controller.interviews.feedback_jobs(identifier),
            'turns':controller.interviews.turns(identifier),'scope':'Captured before releasing feedback gates in teardown'},indent=2),encoding='utf-8')
        raise
    finally:
        release.set();service.close()


def test_model_answer_and_end_cannot_skip_earlier_unconsumed_chat_messages(career):
    c=career;controller,identifier=prepared(c)
    question=controller.interviews.get(identifier).current_question_id
    ids=[]
    for text in ['A1: First answer.','A2: Second answer.','A3: Third answer.']:
        mid=str(uuid4());ids.append(mid)
        c.repository.append(c.state['task_id'],role='user',text=text,id=mid,context={'interview_id':identifier})
    with pytest.raises(ValueError,match='earlier|arrival order|FIFO'):
        execute(c,'answer_interview',interview_id=identifier,question_id=question,message_id=ids[2])
    with pytest.raises(ValueError,match='earlier|queued|pending'):
        execute(c,'control_interview',interview_id=identifier,action='end',message_id=ids[2])
    assert not [t for t in controller.interviews.turns(identifier) if t['answer']]
    assert controller.interviews.report(identifier) is None


@pytest.mark.parametrize('crash',['trimmed','after_evaluation','after_receipt'])
def test_new_service_recovers_durable_inputs_and_post_commit_crash_exactly_once(career,tmp_path,crash):
    from copy import copy
    from types import SimpleNamespace
    from api.db import create_database
    from agent_runtime.career.harness import CareerHarness
    from agent_runtime.career.repository import TaskRepository
    from agent_runtime.mock_interview.repository import MockInterviewRepository
    c=career;controller,identifier=prepared(c)
    ids=[str(uuid4()) for _ in range(3)]
    for i,mid in enumerate(ids):
        c.repository.append(c.state['task_id'],id=mid,role='user',text=f'A{i+1}: Saved answer.',context={'interview_id':identifier})
        state=c.repository.get(c.state['task_id'])
        message=next(m for m in state['messages'] if m['id']==mid)
        c.harness.interview_inputs.route(state,message)  # Persist, deliberately do not start old worker.
    question=controller.interviews.get(identifier).current_question_id
    if crash!='trimmed':
        c.harness.interview_inputs._update(c.state['task_id'],ids[0],status='running',question_id=question)
        controller.answer(identifier,'A1: Saved answer.',expected_version=controller.interviews.get(identifier).version,
            idempotency_key=f'career:{ids[0]}:{question}')
        assert controller.interviews.get(identifier).current_question_id!=question
        if crash=='after_receipt':c.repository.change(c.state['task_id'],interview_answer_receipts={identifier:[ids[0]]})
    # Simulate the real bounded message window rolling past all queued messages.
    c.repository.change(c.state['task_id'],messages=[{'id':str(uuid4()),'role':'assistant','text':'Later activity','at':'2099-01-01'} for _ in range(150)])
    db=create_database(f"sqlite:///{(tmp_path/'career.db').as_posix()}")
    restored_controller=copy(controller);restored_controller.interviews=MockInterviewRepository(db.session_factory)
    runtime=SimpleNamespace(**{**vars(c.runtime),'database':db,'mock_interviewer':restored_controller})
    repo=TaskRepository(db.session_factory)
    harness=CareerHarness(runtime,c.applications,repo,discovery=c.harness.discovery,fit_service=c.harness.analysis._fit_service)
    model=ToolModel(lambda _:('finish_task',{'text':'Must not route answers through a model.'}))
    service=CareerService(runtime,c.applications,harness=harness,model_factory=lambda:model,start_alert_scheduler=False)
    try:
        wait_for(lambda:all(e['status']=='done' for e in repo.get(c.state['task_id'])['interview_queue']))
        turns=[t for t in restored_controller.interviews.turns(identifier) if t['answer']]
        assert [t['answer']['original_text'] for t in turns]==[f'A{i+1}: Saved answer.' for i in range(3)]
        assert [t['answer']['sequence'] for t in turns]==[1,2,3]
        assert len({t['question']['question_id'] for t in turns})==3
        assert model.calls==0
        (tmp_path/'restart-fifo.json').write_text(json.dumps({'crash':crash,'turns':turns,
            'queue':repo.get(c.state['task_id'])['interview_queue'],'new_service':True,'new_db_connection':True,
            'provider_io':'synthetic'},indent=2),encoding='utf-8')
    finally:service.close();db.close()
