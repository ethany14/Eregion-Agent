"""Model-owned questions, concurrent replies and durable recovery decisions."""
import json
from threading import Event
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent_runtime.auto_apply.agent import AgentTools, HybridApplicationAgent
from agent_runtime.auto_apply.browser import BrowserBlocked
from agent_runtime.auto_apply.contracts import ChatRequest, ReplyQuestion
from agent_runtime.auto_apply.loop import ApplicationLoop
from agent_runtime.auto_apply.repository import ApplyConflict, ApplyRepository
from agent_runtime.auto_apply.runner import trace_value
from api.main import create_app
from test_auto_apply import FakeBrowser, database, field, request, wait
from test_auto_apply_agent import ScriptModel, args, state


def factory(model):
    return lambda: HybridApplicationAgent(model_factory=lambda: model)


@pytest.mark.parametrize('keys', [[], ['First name']])
def test_agent_question_preserves_wording_even_for_completed_fields(database, keys):
    question = 'Your saved name is Test. Which name should appear on this application?'
    model = ScriptModel([('autofill', {}), ('ask_user', {'text':question, 'field_keys':keys})])
    loop = ApplicationLoop(ApplyRepository(database.session_factory), browser_factory=FakeBrowser,
        agent_factory=factory(model))
    try:
        saved = wait(loop, loop.start(request(automation_mode='hybrid'))['run_id'])
        assert saved['status'] == 'needs_input'
        assert saved['messages'][-1]['text'] == question
        assert saved['pending_fields'] == keys
        assert saved['input_request']['id'] == saved['messages'][-1]['id']
        assert saved['fields'][0]['value'] == 'Test'
        identifier = saved['input_request']['id']
        loop.repository.recover()
        restored = loop.repository.get(saved['run_id'])
        assert restored['input_request']['id'] == identifier
        assert restored['decision_history'][-1]['tool'] == 'ask_user'
    finally:
        loop.close()


def test_reply_while_agent_runs_invalidates_stale_action_and_resumes_once(database):
    pending, release = Event(), Event()
    browser = FakeBrowser('')
    browser.fields += [field('Location'), field('Referral')]
    snapshots = []

    class Model:
        def invoke(self, messages, tools):
            snapshot = json.loads(next(m.content for m in reversed(messages)
                if isinstance(m, HumanMessage) and isinstance(m.content, str)))
            snapshots.append(snapshot)
            index = len(snapshots)
            if index == 1:
                name, arguments = 'ask_user', {'text':'Which city and referral source should I use?',
                    'field_keys':['Location','Referral'], 'wait_for_reply':False}
            elif index == 3:
                pending.set()
                assert release.wait(8)
                name, arguments = 'ask_user', {'text':'STALE QUESTION MUST NOT BE SENT', 'field_keys':[]}
            elif index in {2,4}:
                name, arguments = 'autofill', {}
            else:
                name, arguments = 'ready_for_review', {}
            return AIMessage(content='', tool_calls=[{'id':str(index),'name':name,'args':arguments}])

    loop = ApplicationLoop(ApplyRepository(database.session_factory), browser_factory=lambda _:browser,
        agent_factory=factory(Model()))
    app = create_app(run_service=object(),session_runtime=SimpleNamespace(database=database))
    app.state.auto_apply = loop
    try:
        run_id = loop.start(request(automation_mode='hybrid'))['run_id']
        assert pending.wait(8)
        current = loop.repository.get(run_id)
        assert current['status'] == 'running'
        assert current['fields'][0]['value'] == 'Test'  # Filled while the question was pending.
        payload = {'request_id':current['input_request']['id'],
            'answers':{'Location':'Ithaca, New York','Referral':'LinkedIn'}}
        with TestClient(app) as client:
            response = client.post(f'/api/auto-apply/{run_id}/reply',json=payload)
            assert response.status_code == 202
            assert response.json()['status'] == 'running'
            duplicate = client.post(f'/api/auto-apply/{run_id}/reply',json=payload)
            assert duplicate.status_code == 202
            assert duplicate.json()['version'] == response.json()['version']
            stale = client.post(f'/api/auto-apply/{run_id}/reply',json={**payload,'request_id':'old-question'})
            assert stale.status_code == 409
            release.set()
            done = wait(loop, run_id)
            assert done['status'] == 'awaiting_review'
            assert done['input_request'] is None
            assert len(snapshots) == 5
            assert not any('STALE QUESTION' in m['text'] for m in done['messages'])
            assert len([m for m in done['messages'] if m.get('in_reply_to') == payload['request_id']]) == 1
            assert snapshots[3]['sources']['answer:Referral'] == 'LinkedIn'
            assert browser.submissions == 0
    finally:
        release.set()
        loop.close()


def test_wait_reuses_question_and_chat_reply_is_linked(database):
    model = ScriptModel([
        ('ask_user', {'text':'Is this the city you want to use?', 'field_keys':[], 'wait_for_reply':False}),
        ('autofill', {}), ('wait_for_user', {}),
        ('say', {'text':'Understood. I have kept the completed answers.'}), ('ready_for_review', {})])
    loop = ApplicationLoop(ApplyRepository(database.session_factory), browser_factory=FakeBrowser,
        agent_factory=factory(model))
    try:
        saved = wait(loop, loop.start(request(automation_mode='hybrid'))['run_id'])
        question = saved['input_request']
        assert len([m for m in saved['messages'] if m.get('kind') == 'question']) == 1
        loop.chat(saved['run_id'], ChatRequest(message_id='city-confirmed-1',text='Yes, keep it.'))
        done = wait(loop,saved['run_id'])
        assert done['status'] == 'awaiting_review'
        answer = next(m for m in done['messages'] if m['id'] == 'city-confirmed-1')
        assert answer['in_reply_to'] == question['id']
        assert not done['input_request']
    finally:
        loop.close()


def test_reply_preserves_explicit_pause_and_original_field_scope(database):
    repo = ApplyRepository(database.session_factory)
    saved, _ = repo.create(request(automation_mode='hybrid'))
    old_field = field('old-key',label='How did you hear about this job?')
    repo.save(saved,status='needs_input',pause_requested=True,fields=[field('new-page')],
        input_request={'id':'question-old-page','text':'Which source?', 'field_keys':['old-key'], 'fields':[old_field]})
    loop = ApplicationLoop(repo,browser_factory=FakeBrowser)
    try:
        with pytest.raises(ApplyConflict):
            loop.reply_question(saved['run_id'],ReplyQuestion(request_id='question-old-page',answers={'new-page':'x'}))
        updated = loop.reply_question(saved['run_id'],ReplyQuestion(request_id='question-old-page',answers={'old-key':'LinkedIn'}))
        assert updated['pause_requested'] and updated['status'] == 'needs_input'
        assert not loop.browsers
        assert repo.memories(updated['profile'])[0]['question'] == old_field['label']
    finally:
        loop.close()


def test_failure_history_survives_worker_slices_and_allows_new_strategy():
    saved, browser = state(answers={}), FakeBrowser('')
    failed = ScriptModel([('choose_option', args('First name',source_ref='profile:first_name',option_label='Unknown'))])
    # The next provider call fails, but the previous tool error is durably saved.
    callbacks = dict(autofill=lambda:{},active=lambda:True,reserve=lambda kind:True,report=lambda *a:None,
        checkpoint=lambda **changes:saved.update(changes),refresh=lambda:saved)
    assert HybridApplicationAgent(model_factory=lambda:failed).run(browser,saved,**callbacks)['reason'] == 'model_error'
    assert saved['decision_history'][0]['result']['error']

    class Recover(ScriptModel):
        def invoke(self,messages,tools):
            snapshot = json.loads(next(m.content for m in reversed(messages) if isinstance(m,HumanMessage)))
            assert snapshot['decision_history'][0]['tool'] == 'choose_option'
            assert 'error' in snapshot['decision_history'][0]['result']
            return super().invoke(messages,tools)

    recovered = Recover([('ask_user',{'text':'This control is not a dropdown. Can you confirm its intended value?', 'field_keys':[]})])
    result = HybridApplicationAgent(model_factory=lambda:recovered).run(browser,saved,**callbacks)
    assert result['question'].startswith('This control')
    assert len(saved['decision_history']) == 2


def test_multiple_tool_calls_get_feedback_without_executing_stale_mutation():
    browser, saved, calls = FakeBrowser(''), state(answers={}), []

    class Model:
        def invoke(self,messages,tools):
            calls.append(messages)
            if len(calls) == 1:
                return AIMessage(content='',tool_calls=[{'id':'one','name':'observe','args':{}},
                    {'id':'two','name':'say','args':{'text':'Do not execute this stale action'}}])
            replies = [json.loads(m.content) for m in messages if isinstance(m,ToolMessage)]
            assert len(replies) == 2 and replies[1]['deferred']
            return AIMessage(content='',tool_calls=[{'id':'three','name':'ask_user','args':{'text':'Which location?', 'field_keys':[]}}])

    result = HybridApplicationAgent(model_factory=Model).run(browser,saved,autofill=lambda:{},active=lambda:True,
        reserve=lambda kind:True, report=lambda *a:None, communicate=lambda text:pytest.fail(text))
    assert result['question'] == 'Which location?'


def test_durable_trace_bounds_large_observations_and_excludes_images_and_credentials():
    trace = trace_value({'options':[{'label':'x'*3000} for _ in range(100)],'password':'SECRET', 'image':b'image'})
    encoded = json.dumps(trace)
    assert len(encoded) < 9000
    assert 'SECRET' not in encoded and 'image' not in encoded


def test_repeated_action_feedback_leaves_room_for_model_to_change_strategy():
    browser, fills = FakeBrowser(''), []
    class Replan(ScriptModel):
        def invoke(self,messages,tools):
            if len(self.calls) == 3:
                reply = next(m for m in reversed(messages) if isinstance(m,ToolMessage))
                assert json.loads(reply.content)['repeated_action']
            return super().invoke(messages,tools)
    model = Replan([('autofill',{})]*3+[
        ('ask_user',{'text':'The control did not change after two attempts. Can you check whether an overlay is open?', 'field_keys':[]})])
    result = HybridApplicationAgent(model_factory=lambda:model).run(browser,state(),
        autofill=lambda:fills.append(1) or {},active=lambda:True,reserve=lambda kind:True,report=lambda *a:None)
    assert len(fills) == 2
    assert result['reason'] == 'needs_input' and result['question'].startswith('The control')


def test_plain_text_question_is_not_duplicated_by_host(database):
    class QuestionModel:
        def invoke(self,messages,tools):return AIMessage(content='Which office should I choose?')
    loop = ApplicationLoop(ApplyRepository(database.session_factory),browser_factory=FakeBrowser,
        agent_factory=factory(QuestionModel()))
    try:
        saved = wait(loop,loop.start(request(automation_mode='hybrid'))['run_id'])
        assert len([m for m in saved['messages'] if m['text']=='Which office should I choose?']) == 1
        assert saved['input_request']['text'] == 'Which office should I choose?'
    finally:loop.close()


@pytest.mark.parametrize('budget,expected,calls', [(2,'needs_input',2),(12,'awaiting_review',9)])
def test_worker_slices_continue_without_new_input_until_done_or_budget(database,budget,expected,calls):
    decisions = []
    class Agent:
        def run(self,browser,state,**callbacks):
            assert callbacks['reserve']('model')
            decisions.append(1)
            if len(decisions) <= 8:return {'reason':'yielded','field_keys':[]}
            callbacks['autofill']()
            return {'reason':'ready','field_keys':[]}
    loop = ApplicationLoop(ApplyRepository(database.session_factory),browser_factory=FakeBrowser,
        agent_factory=Agent,max_model_calls=budget)
    try:
        saved = wait(loop,loop.start(request(automation_mode='hybrid'))['run_id'])
        assert saved['status'] == expected
        assert len(decisions) == calls
        if budget == 2:
            assert saved['agent_reason'] == 'agent_limit'
            assert not saved['messages'][-1]['question_keys']
    finally:loop.close()


def test_confirmed_leaf_answer_can_be_saved_before_parent_category_is_explored():
    browser = FakeBrowser('')
    browser.fields = [field('source','select',label='How did you hear about us?')]
    browser.fields[0]['options'] = [{'label':'Job Board','value':'job-board'}]
    saved = state(answers={},messages=[{'id':'reply-source','role':'user','text':'linkedin'}])
    session = AgentTools(browser,saved,autofill=lambda:{},active=lambda:True)
    snapshot = session.observe()
    result = session.execute('record_answers',{'observation_id':snapshot['observation_id'], 'answers':[
        {'field_key':'source','message_id':'reply-source','quote':'linkedin','value':'LinkedIn'}]})
    assert 'error' not in result
    assert saved['answers']['source'] == 'LinkedIn'
