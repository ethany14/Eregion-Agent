"""Real Chrome over the local API: immediate chat and optional daily schedules."""
import os
from pathlib import Path
from urllib.parse import urlsplit
import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright, expect
from api.main import create_app
from test_job_alerts import career, start_service
from test_career_flow import settled

pytestmark=pytest.mark.skipif(os.getenv('JOB_AGENT_BROWSER_TESTS')!='1',reason='Offline Chrome opt-in')


def test_chat_discovery_and_daily_alerts_share_ui_without_forcing_schedule(career,tmp_path):
    c=career;service=start_service(c)
    app=create_app(run_service=object(),session_runtime=c.runtime)
    app.state.auto_apply=c.applications;app.state.career_agent=service
    with TestClient(app,base_url='http://localhost') as client,sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1000},reduced_motion='reduce')
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.add_init_script('''window.notificationRequests=0;window.notifications=[];
          window.Notification=class {static permission=localStorage.getItem('northstar.jobNotifications')==='on'?'granted':'default';static async requestPermission(){window.notificationRequests++;this.permission='granted';return 'granted';}
          constructor(title,options){window.notifications.push({title,...options});}close(){}};''')
        def route(r):
            req=r.request
            if urlsplit(req.url).hostname!='localhost':r.abort();return
            response=client.request(req.method,req.url,content=req.post_data,headers={k:v for k,v in req.headers.items() if k in {'content-type','origin'}},follow_redirects=False)
            r.fulfill(status=response.status_code,body=response.content,headers={'content-type':response.headers.get('content-type','')})
        page.route('**/*',route);page.goto('http://localhost/apply')
        page.locator('#chat-text').fill('Find jobs for my resume now.');page.locator('#send-message').click()
        expect(page.locator('.recommendation-reason')).to_contain_text('Python API',timeout=25000)
        assert service.alerts.list()==[] and page.evaluate('window.notificationRequests')==0
        page.screenshot(path=str(tmp_path/'discovery-chat-light.png'))
        page.locator('[data-view=alerts]').click();page.get_by_role('button',name='New schedule',exact=True).click()
        dialog=page.locator('.alert-settings')
        dialog.locator('[name=preferences]').fill('Python backend engineer, remote US')
        dialog.locator('[name=min_score]').fill('0')
        dialog.locator('[name=timezone]').fill('America/New_York')
        dialog.get_by_role('button',name='Save schedule').click()
        expect(dialog).to_have_count(0)
        expect(page.locator('.alert-schedule')).to_contain_text('09:00')
        page.get_by_role('button',name='Pause schedule',exact=True).click()
        expect(page.get_by_role('button',name='Resume schedule',exact=True)).to_be_visible()
        page.get_by_role('button',name='Search now',exact=True).click()
        expect(page.locator('.alert-digest')).to_be_visible(timeout=10000)
        run=service.alerts.feed()[0];settled(service.repository,run['task_id']);service.alert_scheduler.tick()
        expect(page.locator('.digest-job')).to_contain_text('Python API',timeout=20000)
        page.get_by_role('button',name='Enable browser notifications').click()
        assert page.evaluate('window.notificationRequests')==1
        assert page.evaluate("localStorage.getItem('northstar.jobNotifications')")=='on'
        page.screenshot(path=str(tmp_path/'job-alerts-light.png'))
        page.emulate_media(color_scheme='dark');page.screenshot(path=str(tmp_path/'job-alerts-dark.png'))
        page.set_viewport_size({'width':390,'height':844});page.emulate_media(color_scheme='light')
        page.screenshot(path=str(tmp_path/'job-alerts-mobile.png'),animations='disabled')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.goto('http://localhost/apply?view=alerts')
        page.wait_for_function('window.notifications.length===1')
        page.reload();page.locator('.alert-digest').wait_for()
        assert page.evaluate('window.notifications.length')==0
        page.get_by_role('button',name='Mark read',exact=True).click()
        expect(page.get_by_role('button',name='Mark read',exact=True)).to_have_count(0)
        assert service.alerts.feed()[0]['read_at']
        assert errors==[]
        browser.close()
