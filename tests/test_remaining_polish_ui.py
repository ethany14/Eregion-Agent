"""Real Chrome UI/API cancellation; synthetic persisted search, no providers."""
import json
import os
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright, expect

from eregion.api.main import create_app
from eregion.runtime.career.service import CareerService
from test_career_flow import career, ToolModel, execute
from test_auto_apply import wait

pytestmark=pytest.mark.skipif(os.getenv('JOB_AGENT_BROWSER_TESTS')!='1',reason='Offline real Chrome opt-in')
GOAL='Find junior data analyst opportunities in New York with strong mentorship and comprehensive training programmes.'


def test_search_title_chronicle_and_cancel_state_in_real_ui(career,tmp_path):
    c=career
    c.repository.change(c.state['task_id'],status='cancelled',pause_requested=True)
    state,_=c.repository.create(GOAL,'polish-real-ui-search')
    c.repository.change(state['task_id'],status='needs_input')
    short,_=c.repository.create('Find Python roles','polish-short-title')
    c.repository.change(short['task_id'],status='needs_input')
    model=ToolModel(lambda _:('finish_task',{'text':'Unused scripted model.'}))
    service=CareerService(c.runtime,c.applications,harness=c.harness,model_factory=lambda:model,start_alert_scheduler=False)
    app=create_app(run_service=object(),session_runtime=c.runtime)
    app.state.auto_apply=c.applications;app.state.career_agent=service
    errors=[];events=[];evidence={'goal':GOAL,'views':[]}
    try:
        with TestClient(app,base_url='http://localhost') as client,sync_playwright() as p:
            browser=p.chromium.launch(channel='chrome',headless=True)
            page=browser.new_page()
            page.on('pageerror',lambda e:errors.append(str(e)))
            def route(r):
                req=r.request
                if not req.url.startswith('http://localhost/'):return r.abort()
                response=client.request(req.method,req.url,content=req.post_data,
                    headers={k:v for k,v in req.headers.items() if k in {'content-type','origin'}})
                if req.method=='POST':events.append({'path':urlsplit(req.url).path,'status':response.status_code})
                r.fulfill(status=response.status_code,body=response.content,headers={'content-type':response.headers.get('content-type','')})
            page.route('**/*',route)
            for theme in ['light','night']:
                for width,height,label in [(1440,1000,'desktop'),(390,844,'mobile')]:
                    page.set_viewport_size({'width':width,'height':height})
                    page.goto('http://localhost/apply')
                    page.evaluate('(theme)=>{localStorage.setItem("eregion.theme",theme)}',theme)
                    page.reload()
                    page.locator('#chat-scroll').evaluate('(element)=>element.scrollTo(0,0)')
                    heading=page.locator('#chron-today .chron-entry b').filter(has_text='Find junior').first
                    expect(heading).to_be_visible()
                    title=service.view(state['task_id'])['title']
                    evidence['views'].append({'theme':theme,'size':label,'title':title,'heading':heading.inner_text()})
                    page.screenshot(path=str(tmp_path/f'before-cancel-{theme}-{label}.png'),full_page=True)
                    shown=heading.inner_text()
                    assert shown.endswith('…'),shown
                    assert GOAL.startswith(shown[:-1]+' '),shown
                    assert 'waiting on you' not in shown
                    expect(page.locator('#chron-today .chron-entry b').filter(has_text='Find Python').first).to_have_text('Find Python roles')
                    # The persisted legacy title is still sliced mid-word; the UI
                    # must recover the automatic title from the original goal.
                    assert title==GOAL[:90]
            # Normal visible Chronicle selection then the actual cancel action.
            page.set_viewport_size({'width':1440,'height':1000})
            page.locator('#chron-today .chron-entry').filter(has_text='Find junior').first.click()
            if not page.locator('#browser-panel').is_visible():page.locator('#browser-toggle').click()
            expect(page.locator('#browser-toggle')).to_have_attribute('aria-expanded','true')
            page.locator('#cancel-attempt').click()
            expect(page.locator('#agent-status')).to_have_text('Cancelled')
            assert c.repository.get(state['task_id'])['status']=='cancelled'
            assert events[-1]=={'path':f'/api/career/tasks/{state["task_id"]}/cancel','status':200}
            evidence.update(final_status=page.locator('#agent-status').inner_text(),events=events,errors=errors,model_calls=model.calls)
            assert not errors and model.calls==0
            page.screenshot(path=str(tmp_path/'after-cancel.png'),full_page=True)
            # A conversation with an application run keeps application wording.
            c.repository.change(c.state['task_id'],status='needs_input',pause_requested=False)
            execute(c,'open_application_url',url='https://qa.example.com/jobs/7011')
            run=c.repository.get(c.state['task_id'])['application_runs'][0]
            wait(c.applications,run)
            c.repository.change(c.state['task_id'],status='needs_input',pause_requested=False)
            page.goto('http://localhost/apply')
            page.locator(f'.attempt-row[data-id="{c.state["task_id"]}"] button').first.click()
            if not page.locator('#browser-panel').is_visible():page.locator('#browser-toggle').click()
            page.locator('#cancel-attempt').click()
            expect(page.locator('#agent-status')).to_have_text('Application cancelled')
            assert c.applications.repository.get(run)['status']=='cancelled'
            assert c.repository.get(c.state['task_id'])['status']=='cancelled'
            evidence['application_cancel_status']=page.locator('#agent-status').inner_text()
            page.screenshot(path=str(tmp_path/'application-after-cancel.png'),full_page=True)
            browser.close()
    finally:
        evidence.update(events=events,errors=errors,model_calls=model.calls)
        (tmp_path/'ui-chain.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
        service.close()
