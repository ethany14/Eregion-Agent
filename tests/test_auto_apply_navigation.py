"""Navigation boundaries, generic job identity, and credential isolation."""
import json
import os
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agent_runtime.auto_apply.agent import AgentTools
from agent_runtime.auto_apply.browser import BrowserBlocked
from agent_runtime.auto_apply.browser_sessions import BrowserSessionStore
from agent_runtime.auto_apply.contracts import AccountCredentials, posting
from agent_runtime.auto_apply.loop import ApplicationLoop
from agent_runtime.auto_apply.navigation import action_kind
from agent_runtime.auto_apply.repository import ApplyRepository
from api.main import create_app
from test_auto_apply import FakeBrowser, database, request, wait


def test_generic_job_links_preserve_job_identity_query():
    first=posting('https://careers.example.com/job?id=123&utm_source=linkedin')
    assert first[0]=='generic' and first==posting('https://careers.example.com/job?id=123')
    assert first[1]!=posting('https://careers.example.com/job?id=456')[1]
    assert posting('https://jobs.ashbyhq.com/example/job-id')[0]=='ashby'


def test_workday_identity_survives_location_locale_and_application_steps():
    base='https://example.wd5.myworkdayjobs.com/'
    paths=['en-US/External/job/Engineer_JR123', 'en-US/External/job/US-CA/Engineer_JR123/apply/applyManually',
           'fr-FR/External/job/US-CA/Ingenieur_JR123/apply/autofillWithResume']
    assert len({posting(base+p)[1] for p in paths})==1
    assert posting(base+paths[0])[1]!=posting(base+'en-US/Internal/job/Engineer_JR123')[1]


@pytest.mark.parametrize('label,kind',[('Apply','open_application'),('Next','next'),('Save and Continue','next'),
    ('Submit Application','submit'),('Create Account','authentication'),('Autofill with Resume','resume')])
def test_navigation_distinguishes_save_from_submission(label,kind):
    assert action_kind({'label':label,'submits_form':True},has_fields=False)==kind
    assert action_kind({'label':'Apply','submits_form':True},has_fields=True)=='submit'


def test_agent_cannot_finish_or_submit_an_intermediate_page():
    browser=FakeBrowser('')
    browser.page_state=lambda:{'url':'https://example.com/job/1','heading':'My Information','text':'Next',
        'can_submit':False,'controls':[{'id':'submit','kind':'submit','disabled':False}]}
    tools=AgentTools(browser, {'profile':request().profile.model_dump(),'answers':{}},
        autofill=lambda:{},active=lambda:True)
    snapshot=tools.observe();tools.execute('autofill',{})
    with pytest.raises(BrowserBlocked): tools.execute('ready_for_review',{})
    with pytest.raises(BrowserBlocked): tools.execute('click_page_action',{'observation_id':snapshot['observation_id'],'control_id':'submit'})
    assert browser.submissions==0


def test_password_validation_errors_do_not_echo_secrets(database):
    loop=ApplicationLoop(ApplyRepository(database.session_factory),browser_factory=FakeBrowser)
    app=create_app(run_service=object(),session_runtime=SimpleNamespace(database=database));app.state.auto_apply=loop
    with TestClient(app) as client:
        for body in [{'password':'SENSITIVE-TEST-PASSWORD','mode':'wrong'},['SENSITIVE-TEST-PASSWORD']]:
            response=client.post('/api/auto-apply/no-run/account',json=body)
            assert response.status_code==422 and 'SENSITIVE' not in response.text
        response=client.post('/api/auto-apply/no-run/account',json={'password':'SENSITIVE-TEST-PASSWORD'},headers={'Origin':'https://evil.example'})
        assert response.status_code==403 and 'SENSITIVE' not in response.text


def test_credentials_cannot_be_sent_to_another_site_or_stale_attempt(database):
    repo=ApplyRepository(database.session_factory);loop=ApplicationLoop(repo,browser_factory=FakeBrowser)
    try:
        run=loop.start(request());state=wait(loop,run['run_id'])
        state=repo.save(state,status='needs_input',account_request={'origin':'https://jobs.lever.co','mode':'login','consents':[]})
        from agent_runtime.auto_apply.repository import ApplyConflict
        cred=AccountCredentials(expected_version=state['version'],origin='https://evil.example',mode='login',username='test@example.com',password='DO-NOT-STORE')
        with pytest.raises(ApplyConflict): loop.account(run['run_id'],cred)
        assert 'DO-NOT-STORE' not in json.dumps(repo.get(run['run_id']))
        assert 'DO-NOT-STORE' not in repr(cred)
    finally:loop.close()


@pytest.mark.skipif(os.name!='nt',reason='Windows DPAPI')
def test_encrypted_login_state_is_owner_and_site_isolated(tmp_path):
    store=BrowserSessionStore(tmp_path/'sessions');state={'cookies':[{'name':'auth','value':'SECRET-SESSION-TOKEN'}],'origins':[]}
    store.save('owner-a','tenant-a.myworkdayjobs.com',state)
    path=next((tmp_path/'sessions').iterdir());assert b'SECRET-SESSION-TOKEN' not in path.read_bytes()
    assert BrowserSessionStore(tmp_path/'sessions').load('owner-a','tenant-a.myworkdayjobs.com')==state
    assert store.load('owner-b','tenant-a.myworkdayjobs.com') is None
    assert store.load('owner-a','tenant-b.myworkdayjobs.com') is None
    path.write_bytes(b'corrupted');assert store.load('owner-a','tenant-a.myworkdayjobs.com') is None
