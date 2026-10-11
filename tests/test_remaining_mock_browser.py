"""Real Chrome with every request intercepted; never contacts an employer."""
import json
import os

import pytest

from agent_runtime.auto_apply.browser import ApplicationBrowser
from agent_runtime.auto_apply.contracts import ContinueApplication, ChatRequest
from agent_runtime.auto_apply.loop import ApplicationLoop
from agent_runtime.auto_apply.repository import ApplyRepository, DuplicateApplication
from test_auto_apply import database, request, wait

pytestmark=pytest.mark.skipif(os.getenv('JOB_AGENT_BROWSER_TESTS')!='1',reason='Opt-in offline real Chrome')


@pytest.mark.parametrize('ambiguous',[False,True])
def test_review_remember_submit_second_job_and_restart(database,tmp_path,ambiguous):
    clicks=[]
    stages=[]
    class MockBrowser(ApplicationBrowser):
        def __init__(self,url):super().__init__(url,headless=True)
        def _guard_request(self,route):
            if route.request.method=='POST':
                clicks.append(json.loads(route.request.post_data))
                route.fulfill(content_type='application/json',body='{}')
            elif route.request.is_navigation_request():
                route.fulfill(content_type='text/html',body='''<html><body><h1>Mock Engineer Application</h1>
                <form id="application"><label for="country">Country*</label>
                <select id="country" required><option value="">Choose</option><option value="United States">United States</option></select>
                <label for="source">How did you hear about this job?*</label><input id="source" required>
                <label for="arrangement">Preferred work arrangement*</label><select id="arrangement" required>
                <option value="">Choose</option><option value="Remote">Remote</option><option value="Office">Office</option></select>
                <label for="consent">I certify my answers are accurate*</label><input type="checkbox" id="consent" required>
                <button type="submit">Submit application</button></form><script>
                document.querySelector('form').onsubmit=async e=>{e.preventDefault();
                await fetch('/mock-submit',{method:'POST',body:JSON.stringify({country:country.value,source:source.value,arrangement:arrangement.value,consent:consent.checked})});
                document.body.innerHTML='''+json.dumps('<h1>Processing your application</h1>' if ambiguous else '<h1>Thank you for applying. Your application has been received.</h1>')+''';};
                </script></body></html>''')
            else:route.abort()
    repo=ApplyRepository(database.session_factory)
    repo.save_candidate(request().profile.model_dump())
    from agent_runtime.auto_apply.agent import HybridApplicationAgent
    from langchain_core.messages import AIMessage,HumanMessage
    from uuid import uuid4
    class BindingModel:
        def __init__(self):self.started=False
        def invoke(self,messages,tools):
            snapshot=json.loads(next(m.content for m in reversed(messages) if isinstance(m,HumanMessage)))
            missing=[f for f in snapshot['fields'] if not f.get('done')]
            if not self.started:
                self.started=True;name,args='autofill',{}
            elif not missing:name,args='ready_for_review',{}
            elif any(m['id']=='mock-free-text-answer' for m in snapshot['user_messages']):
                field=missing[0]
                label=field['label'].rstrip('*').strip()
                if 'certify' in label:
                    name,args='request_input',{'field_keys':[field['key']]}
                else:
                    answer={'Country':'United States','How did you hear about this job?':'Company website','Preferred work arrangement':'Remote'}[label]
                    name,args='use_chat_answer',{'observation_id':snapshot['observation_id'],
                        'field_key':field['key'],'message_id':'mock-free-text-answer','answer':answer}
            else:name,args='request_input',{'field_keys':[f['key'] for f in missing]}
            return AIMessage(content='',tool_calls=[{'name':name,'args':args,'id':str(uuid4())}])
    loop=ApplicationLoop(repo,browser_factory=MockBrowser,
        agent_factory=lambda:HybridApplicationAgent(model_factory=BindingModel))
    def record(label,state):
        stages.append({'stage':label,'status':state['status'],'message':state.get('message'),
            'answers':state.get('answers'),'fields':state.get('fields'),'submit_clicks':len(clicks)})
        (tmp_path/'browser-chain.json').write_text(json.dumps({'ambiguous':ambiguous,'stages':stages,'clicks':clicks},indent=2),encoding='utf-8')
    try:
        first=loop.start(request(url='https://qa.example.com/jobs/1001',automation_mode='hybrid'))
        initial=wait(loop,first['run_id']);record('question',initial)
        assert initial['status']=='needs_input' and len(clicks)==0
        by_label={f['label'].rstrip('*').strip():f['key'] for f in initial['fields']}
        country=by_label['Country'];source=by_label['How did you hear about this job?'];consent=by_label['I certify my answers are accurate']
        arrangement=by_label['Preferred work arrangement']
        loop.chat(first['run_id'],ChatRequest(message_id='mock-free-text-answer',
            text='Please use United States as my country. I found the opening on Company website. My preferred work arrangement is Remote.'))
        consent_wait=wait(loop,first['run_id']);record('consent-question',consent_wait)
        assert consent_wait['pending_fields']==[consent]
        assert repo.memories(consent_wait['profile'])==[]
        loop.chat(first['run_id'],ChatRequest(message_id='mock-explicit-consent',field_key=consent,text='yes'))
        review=wait(loop,first['run_id']);record('review',review)
        assert review['status']=='awaiting_review' and len(clicks)==0
        assert source in {a['key'] for a in review['pending_approvals']}
        assert arrangement in {a['key'] for a in review['pending_approvals']}
        assert not any(m['question'].startswith('How did') for m in repo.memories(review['profile']))
        loop.continue_run(first['run_id'],ContinueApplication(expected_version=review['version'],
            remember={country:True,source:True,arrangement:False},confirm_submit=True))
        done=wait_long(loop,first['run_id']);record('submitted-or-unknown',done)
        assert done['status']==('submission_unknown' if ambiguous else 'submitted')
        assert len(clicks)==1 and clicks[0]=={'country':'United States','source':'Company website','arrangement':'Remote','consent':True}
        assert bool(done.get('confirmation')) is not ambiguous
        assert repo.saved_candidate()['profile']['country']=='United States'
        second=loop.start(request(url='https://qa.example.com/jobs/1002',idempotency_key='second-mock-job',automation_mode='hybrid',profile=repo.saved_candidate()['profile']))
        next_state=wait(loop,second['run_id']);record('second-job',next_state)
        assert next_state['status']=='needs_input'
        assert next_state['pending_fields']==[arrangement]
        values={f['key']:f['value'] for f in next_state['fields']}
        assert values[country]=='United States' and values[source]=='Company website'
        assert values[arrangement]==''
        assert not any(m['question'].startswith('Preferred work arrangement') for m in repo.memories(next_state['profile']))
        assert len(clicks)==1
    finally:loop.close()
    restarted=ApplicationLoop(ApplyRepository(database.session_factory),browser_factory=lambda _:pytest.fail('Terminal alias must not open Chrome'))
    try:
        with pytest.raises(DuplicateApplication):restarted.start(request(url='https://qa.example.com/jobs/1001/apply',idempotency_key='restart-mock-job'))
        record('restart-fenced',repo.get(first['run_id']))
        assert len(clicks)==1
    finally:restarted.close()


def wait_long(loop,run_id):
    import time
    deadline=time.monotonic()+65
    while time.monotonic()<deadline:
        state=loop.repository.get(run_id)
        if state['status'] not in {'queued','running','submitting'}:return state
        time.sleep(.1)
    raise AssertionError(state['status'])
