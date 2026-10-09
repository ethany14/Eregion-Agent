"""Background startup and explicit, fenced browser-window handoff."""
import os
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient

from agent_runtime.auto_apply.browser import ApplicationBrowser, BrowserBlocked
from agent_runtime.auto_apply.loop import ApplicationLoop
from agent_runtime.auto_apply.repository import ApplyRepository, ApplyConflict
from api.main import create_app
from test_auto_apply import database, FakeBrowser, request, wait
from test_career_flow import career
from test_job_alerts import start_service


class IsolatedBrowser(ApplicationBrowser):
    def __init__(self,*,purpose='browse'):
        self.launch_modes=[]
        super().__init__('https://jobs.lever.co/example/abc123',purpose=purpose)
    def _launch(self,headless):
        self.launch_modes.append(headless)
        # Record the production visibility decision without opening desktop
        # windows in tests. Real Chrome still exercises context/session transfer.
        return super()._launch(True)
    def _guard_request(self,route):
        route.fulfill(status=200,content_type='text/html',body='<h1>Job page</h1><input aria-label="Draft"><a href="?next=1">Next view</a>')


@pytest.mark.skipif(os.getenv('JOB_AGENT_BROWSER_TESTS')!='1',reason='Offline Chrome opt-in')
@pytest.mark.parametrize('purpose',['browse','application'])
def test_default_is_headless_and_only_explicit_handoff_requests_a_window(purpose):
    b=IsolatedBrowser(purpose=purpose)
    try:
        assert b.headless and b.launch_modes==[True]
        b.context.add_cookies([{'name':'session','value':'synthetic-login','domain':'jobs.lever.co','path':'/','secure':True}])
        b.page.evaluate("localStorage.setItem('test-login','local');sessionStorage.setItem('test-flow','step-one')")
        b.set_visible(True)
        assert not b.headless and b.launch_modes==[True,False]
        assert b.context.cookies()[0]['value']=='synthetic-login'
        assert b.page.evaluate("localStorage.getItem('test-login')")=='local'
        assert b.page.evaluate("sessionStorage.getItem('test-flow')")=='step-one'
        # The restoration script must not replace newer state on later navigation.
        b.page.evaluate("sessionStorage.setItem('test-flow','step-two')")
        b.page.reload(wait_until='domcontentloaded')
        assert b.page.evaluate("sessionStorage.getItem('test-flow')")=='step-two'
        b.set_visible(False)
        assert b.headless and b.launch_modes==[True,False,True]
        assert b.page.evaluate("sessionStorage.getItem('test-flow')")=='step-two'
    finally:b.close()


@pytest.mark.skipif(os.getenv('JOB_AGENT_BROWSER_TESTS')!='1',reason='Offline Chrome opt-in')
def test_failed_window_launch_keeps_original_browser_alive():
    b=IsolatedBrowser()
    try:
        old=b.browser
        b._launch=lambda _:(_ for _ in ()).throw(RuntimeError('synthetic launch failure'))
        with pytest.raises(BrowserBlocked,match='original session'):b.set_visible(True)
        assert b.browser is old and b.is_open() and b.headless
        assert b.page.locator('h1').inner_text()=='Job page'
    finally:b.close()


def test_application_window_handoff_pauses_and_invalidates_submit_review(database):
    class WindowBrowser(FakeBrowser):
        def set_visible(self,visible):self.visible=visible
    loop=ApplicationLoop(ApplyRepository(database.session_factory),browser_factory=WindowBrowser)
    try:
        state=loop.start(request());state=wait(loop,state['run_id'])
        assert state['status']=='awaiting_review' and state['review_digest']
        paused=loop.set_browser_visible(state['run_id'],True,state['version'])
        assert paused['pause_requested'] and paused['review_digest'] is None
        assert paused['status']=='needs_input' and loop.browsers[state['run_id']].visible
        assert loop.browsers[state['run_id']].submissions==0
        with pytest.raises(ApplyConflict):loop.set_browser_visible(state['run_id'],False,state['version'])
        loop.set_browser_visible(state['run_id'],False,paused['version'])
        assert not loop.browsers[state['run_id']].visible
    finally:loop.close()


def visibility_service(c):
    service=start_service(c)
    state,_=service.repository.create('Inspect this search','window-handoff')
    state=service.repository.change(state['task_id'],status='needs_input',browser={'url':'https://www.linkedin.com/jobs/search/'},active_browser='research')
    calls=[]
    def change(task_id,visible,active):
        assert active() and service.repository.get(task_id)['pause_requested']
        calls.append(visible)
        return {'url':'https://www.linkedin.com/jobs/search/','heading':'Jobs','controls':[]}
    service.harness._browsing=SimpleNamespace(set_visible=change,close=lambda:None,preview=lambda _:None)
    return service,state,calls


def test_career_window_api_pauses_before_handoff_and_rejects_stale_or_external_requests(career):
    c=career;service,state,calls=visibility_service(c)
    app=create_app(run_service=object(),session_runtime=c.runtime)
    app.state.auto_apply=c.applications;app.state.career_agent=service
    with TestClient(app,base_url='http://localhost') as client:
        url=f'/api/career/tasks/{state["task_id"]}/browser-window'
        body={'visible':True,'expected_version':state['version']}
        assert client.post(url,json=body,headers={'origin':'https://another.example'}).status_code==403
        shown=client.post(url,json=body)
        assert shown.status_code==200 and shown.json()['pause_requested']
        assert calls==[True]
        assert client.post(url,json=body).status_code==409
        hidden=client.post(url,json={'visible':False,'expected_version':shown.json()['task_version']})
        assert hidden.status_code==200 and calls==[True,False]
        assert all('visible' not in t['function']['parameters']['properties'] for t in service.harness.tools)


@pytest.mark.skipif(os.getenv('JOB_AGENT_BROWSER_TESTS')!='1',reason='Offline Chrome opt-in')
def test_activity_panel_only_opens_window_on_explicit_button_click(career,tmp_path):
    from urllib.parse import urlsplit
    from playwright.sync_api import sync_playwright, expect
    c=career;service,state,calls=visibility_service(c)
    app=create_app(run_service=object(),session_runtime=c.runtime)
    app.state.auto_apply=c.applications;app.state.career_agent=service
    with TestClient(app,base_url='http://localhost') as client,sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1000},reduced_motion='reduce')
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        def route(r):
            req=r.request
            if urlsplit(req.url).hostname!='localhost':r.abort();return
            response=client.request(req.method,req.url,content=req.post_data,headers={k:v for k,v in req.headers.items() if k in {'content-type','origin'}},follow_redirects=False)
            r.fulfill(status=response.status_code,body=response.content,headers={'content-type':response.headers.get('content-type','')})
        page.route('**/*',route);page.goto('http://localhost/apply')
        page.locator(f'.attempt-row[data-id="{state["task_id"]}"] button').first.click()
        page.locator('#browser-toggle').click()
        expect(page.locator('#take-over')).to_be_visible()
        assert calls==[]  # Viewing the preview alone must never show Chrome.
        page.locator('#background-browser').click()
        expect(page.locator('#pause-agent')).to_have_text('Resume')
        assert calls==[True]
        # Background operation is the default. The separate window is now a fallback.
        page.screenshot(path=str(tmp_path/'background-browser-light.png'))
        page.emulate_media(color_scheme='dark');page.screenshot(path=str(tmp_path/'background-browser-dark.png'))
        page.set_viewport_size({'width':390,'height':844});page.emulate_media(color_scheme='light')
        page.screenshot(path=str(tmp_path/'background-browser-mobile.png'))
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert errors==[]
        browser.close()
