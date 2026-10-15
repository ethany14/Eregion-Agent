"""Production UI -> API -> worker -> Chrome, with a local synthetic account site."""
import json
import os
import time
from uuid import uuid4
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright, expect

from eregion.api.main import create_app
from eregion.runtime.auto_apply.browser import ApplicationBrowser
from eregion.runtime.auto_apply.browser_sessions import BrowserSessionStore
from eregion.runtime.auto_apply.loop import ApplicationLoop
from eregion.runtime.career.service import CareerService
from test_career_flow import career, ToolModel, execute
from test_auto_apply import wait

pytestmark=pytest.mark.skipif(os.getenv('JOB_AGENT_BROWSER_TESTS')!='1',reason='Offline Chrome UI opt-in')


def test_account_banner_shared_login_and_takeover_navigation_full_chain(career,tmp_path):
    c=career
    c.applications.close()
    store=BrowserSessionStore(tmp_path/'sessions',codec=lambda data,**_:data)
    site_requests=[]
    class Browser(ApplicationBrowser):
        def __init__(self,url):super().__init__(url,headless=True,session_store=store,owner_key='synthetic-ui-owner')
        def _guard_request(self,route):
            path=urlsplit(route.request.url).path
            signed='session=synthetic' in route.request.headers.get('cookie','')
            site_requests.append({'path':path,'signed_in':signed})
            headers={}
            if path=='/verify':
                body='<h1>Verify your email</h1><form action="/verified"><label>Verification code<input autocomplete="one-time-code" autofocus></label><button>Continue</button></form>'
            elif path=='/verified' or signed:
                headers={'Set-Cookie':'session=synthetic; Path=/; Secure; HttpOnly'}
                body='<h1>Application</h1><form><label>Country<input name="country" required></label><button>Submit application</button></form>'
            else:
                body='''<h1>Create your account</h1><form onsubmit="event.preventDefault();location.href='/verify'">
                <label>Email<input type="email"></label><label>Password<input type="password"></label><button>Create account</button></form>'''
            route.fulfill(content_type='text/html',body=body,headers=headers)
    loop=ApplicationLoop(c.applications.repository,browser_factory=Browser)
    real_start=loop.start
    loop.start=lambda request,**kwargs:real_start(request.model_copy(update={'automation_mode':'autofill'}),**kwargs)
    c.applications=loop;c.harness.applications=loop
    result=execute(c,'open_application_url',urls=['https://qa.example.com/jobs/7001','https://qa.example.com/jobs/7002'])
    identifiers=c.repository.get(c.state['task_id'])['application_runs']
    first,second=identifiers
    initial=wait(loop,first);assert initial['account_request']
    assert wait(loop,second)['account_request']
    c.repository.change(c.state['task_id'],status='needs_input',active_application_run=first,
        input_request={'id':'old-account-question','text':'Sign in or register.','application_run_id':first,
            'application_wait_token':c.harness.wait_token({'id':first})})
    model=ToolModel(lambda _:('finish_task',{'text':'The application is waiting for your Country answer.'}))
    service=CareerService(c.runtime,loop,harness=c.harness,model_factory=lambda:model,start_alert_scheduler=False)
    app=create_app(run_service=object(),session_runtime=c.runtime)
    app.state.auto_apply=loop;app.state.career_agent=service
    events=[];errors=[]
    try:
        with TestClient(app,base_url='http://localhost') as client,sync_playwright() as p:
            chrome=p.chromium.launch(channel='chrome',headless=True)
            page=chrome.new_page(viewport={'width':1440,'height':1000})
            page.on('pageerror',lambda e:errors.append(str(e)))
            def route(r):
                req=r.request
                if not req.url.startswith('http://localhost/'):return r.abort()
                response=client.request(req.method,req.url,content=req.post_data,
                    headers={k:v for k,v in req.headers.items() if k in {'content-type','origin'}})
                if req.method=='POST':
                    payload=json.loads(req.post_data or '{}')
                    events.append({'path':urlsplit(req.url).path,'status':response.status_code,
                        'action':payload.get('action'),'key':payload.get('key')})
                r.fulfill(status=response.status_code,body=response.content,
                    headers={'content-type':response.headers.get('content-type','')})
            page.route('**/*',route);page.goto('http://localhost/apply')
            page.locator(f'.attempt-row[data-id="{c.state["task_id"]}"] button').first.click()
            page.get_by_role('button',name='Create candidate account',exact=True).click()
            page.locator('#account-username').fill('synthetic@example.com')
            page.locator('#account-password').fill('synthetic-fixture-password')
            page.locator('#account-submit').click()
            expect(page.get_by_role('button',name='Create candidate account',exact=True)).to_have_count(0,timeout=20000)
            expect(page.locator('#agent-messages')).to_contain_text('verification',timeout=20000)
            if not page.locator('#browser-panel').is_visible():page.locator('#browser-toggle').click()
            # "Control browser" now pops up the real local Chrome window (2026-10-15), which a
            # test must not put on screen. The same takeover chain is driven through the
            # browser-control API that remains for it: take control, type the code, navigate,
            # refresh, then hand back.
            expect(page.locator('#take-over')).to_be_visible()
            task_id=c.state['task_id'];control=f'/api/career/tasks/{task_id}/browser-control';local={'origin':'http://localhost'}
            version=client.get(f'/api/career/tasks/{task_id}').json()['task_version']
            frame=client.post(control,json={'action':'start','expected_version':version},headers=local).json()
            assert frame.get('session') and frame.get('frame_id')
            frame=client.post(control,json={'action':'text','text':'123456','session':frame['session'],'frame_id':frame['frame_id']},headers=local).json()
            frame=client.post(control,json={'action':'key','key':'Enter','session':frame['session'],'frame_id':frame['frame_id']},headers=local).json()
            deadline=time.monotonic()+20
            while '/verified' not in frame.get('url','') and time.monotonic()<deadline:
                page.wait_for_timeout(300)
                frame=client.post(control,json={'action':'frame','session':frame['session']},headers=local).json()
            assert '/verified' in frame['url'],frame.get('url')
            assert not page.locator('#apply-error').is_visible()
            page.screenshot(path=str(tmp_path/'takeover-after-navigation.png'),full_page=True)
            client.post(control,json={'action':'end','session':frame['session']},headers=local)
            assert client.post(f'/api/career/tasks/{task_id}/chat',json={'text':'continue','message_id':str(uuid4())}).status_code<400
            deadline=time.monotonic()+25
            while time.monotonic()<deadline:
                a,b=loop.repository.get(first),loop.repository.get(second)
                if not a.get('account_request') and not b.get('account_request') and b.get('pending_fields'):break
                page.wait_for_timeout(100)
            assert not a.get('account_request') and not b.get('account_request'),(a['message'],b['message'])
            # Autofill exposes pending_fields, hybrid additionally has an
            # input_request envelope. Validate the actual Country control.
            assert b['status']=='needs_input' and b['pending_fields']
            pending=[f for f in b['fields'] if f['key'] in b['pending_fields']]
            assert len(pending)==1 and pending[0]['label']=='Country' and not pending[0].get('value')
            expect(page.get_by_role('button',name='Create candidate account',exact=True)).to_have_count(0)
            expect(page.get_by_role('button',name='Sign in securely',exact=True)).to_have_count(0)
            view=client.get(f'/api/career/tasks/{c.state["task_id"]}').json()
            assert 'sign in or register' not in view['message'].lower()
            assert c.repository.get(c.state['task_id'])['input_request'] is None
            assert any(r['path']=='/jobs/7002' and r['signed_in'] for r in site_requests)
            assert all(e['status']<400 for e in events),events
            assert not errors
            (tmp_path/'account-ui-evidence.json').write_text(json.dumps({'events':events,'site_requests':site_requests,
                'first':{'status':a['status'],'message':a['message']},'second':{'status':b['status'],'message':b['message']},
                'view_message':view['message'],'old_parent_question_cleared':True,'page_errors':errors},indent=2),encoding='utf-8')
            page.screenshot(path=str(tmp_path/'country-without-stale-account-banner.png'),full_page=True)
            chrome.close()
    finally:
        import sys
        (tmp_path/'attempt-events.json').write_text(json.dumps({'events':events,'site_requests':site_requests,
            'exception':type(sys.exc_info()[1]).__name__ if sys.exc_info()[1] else None,'page_errors':errors},indent=2),encoding='utf-8')
        service.close()
