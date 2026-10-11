"""Local Chrome control recovery, no real credentials, sites or model calls."""
import os
from urllib.parse import urlsplit

import pytest

from agent_runtime.auto_apply.browser import ApplicationBrowser
from agent_runtime.browser.manager import BrowsingManager
from agent_runtime.browser.handoff import BrowserControlRequest
from test_career_flow import career,execute

pytestmark=pytest.mark.skipif(os.getenv('JOB_AGENT_BROWSER_TESTS')!='1',reason='Local Chrome opt-in')


def test_user_control_refreshes_actual_blocked_cache_before_agent_read(career,tmp_path):
    c=career
    class Browser(ApplicationBrowser):
        def __init__(self,url):super().__init__(url,headless=True,purpose='browse')
        def _guard_request(self,route):
            if urlsplit(route.request.url).path=='/signin':
                body='''<title>Synthetic sign in</title><h1>Sign in</h1><label>Password<input type=password></label>
                <button style="margin:40px" onclick="location.href='/jobs/1'">Finish synthetic user sign in</button>'''
            else:body='<title>Senior Backend Engineer</title><main><h1>Senior Backend Engineer</h1><p>We are hiring. Build Python APIs for our full-time backend position.</p></main>'
            route.fulfill(content_type='text/html',body=body)
    manager=BrowsingManager(factory=Browser);c.harness._browsing=manager
    task=c.state['task_id'];events=[]
    try:
        first=execute(c,'browser_open',url='https://synthetic.example.com/signin')
        assert first['blocked']=='credentials'
        manager.worker.submit(lambda:manager.sessions[task].browser.page.screenshot(path=str(tmp_path/'blocked.png'))).result()
        with pytest.raises(ValueError,match='Source blocked'):execute(c,'browser_read')
        scope='synthetic-user-control'
        frame=manager.browser_control(task,BrowserControlRequest(action='start',expected_version=1),scope=scope,active=lambda:True)
        box=manager.worker.submit(lambda:manager.sessions[task].browser.page.locator('button').bounding_box()).result()
        frame=manager.browser_control(task,BrowserControlRequest(action='click',session=frame['session'],frame_id=frame['frame_id'],
            x=box['x']+box['width']/2,y=box['y']+box['height']/2),scope=scope,active=lambda:True)
        manager.browser_control(task,BrowserControlRequest(action='end',session=frame['session']),scope=scope,active=lambda:True)
        observed=manager.inspect(task)
        events.append({'step':'after_user_control_end','url':observed['url'],'blocked':observed.get('blocked'),'observation_id':observed.get('observation_id')})
        assert not observed.get('blocked') and observed['url'].endswith('/jobs/1')
        current=execute(c,'browser_read')
        assert not current.get('blocked') and 'Senior Backend Engineer' in current['text']
        events.append({'step':'agent_read_recovered','url':current['url'],'blocked':current.get('blocked')})
        manager.worker.submit(lambda:manager.sessions[task].browser.page.screenshot(path=str(tmp_path/'recovered.png'))).result()
    finally:
        import json
        (tmp_path/'control-recovery.json').write_text(json.dumps(events,indent=2),encoding='utf-8')
        manager.worker.submit(lambda:manager.sessions[task].browser.page.screenshot(path=str(tmp_path/'final-page.png'))).result()
        manager.close()


def test_actual_failure_challenge_wording_is_blocked_and_recovery_pending_restores_after_control(career,tmp_path):
    from agent_runtime.career.alerts import job_key
    from agent_runtime.career.search_recovery import recovery
    c=career;task=c.state['task_id']
    class Browser(ApplicationBrowser):
        def __init__(self,url):super().__init__(url,headless=True,purpose='browse')
        def _guard_request(self,route):
            if urlsplit(route.request.url).path=='/challenge':
                body='<title>Public jobs</title><p>Verifying you are human. This may take a few seconds.</p><button onclick="location.href=\'/jobs/1\'">Finish synthetic user verification</button>'
            else:body='<title>Junior Data Analyst</title><main><h1>Junior Data Analyst</h1><p>We are hiring a full time Junior Data Analyst. Requires SQL and Python, 0-2 years experience.</p></main>'
            route.fulfill(content_type='text/html',body=body)
    manager=BrowsingManager(factory=Browser);c.harness._browsing=manager
    c.repository.append(task,role='user',text='Find two junior data analyst jobs.')
    url='https://synthetic.example.com/jobs/1'
    c.repository.change(task,observed_job_candidates={job_key(url):{'url':url,'title':'Junior Data Analyst'}})
    try:
        result=execute(c,'browser_open',url='https://synthetic.example.com/challenge')
        manager.worker.submit(lambda:manager.sessions[task].browser.page.screenshot(path=str(tmp_path/'challenge.png'))).result()
        assert result.get('blocked')=='bot_challenge'
        assert not recovery(c.repository.get(task))['pending_candidates']
        scope='synthetic-control'
        frame=manager.browser_control(task,BrowserControlRequest(action='start',expected_version=1),scope=scope,active=lambda:True)
        box=manager.worker.submit(lambda:manager.sessions[task].browser.page.locator('button').bounding_box()).result()
        frame=manager.browser_control(task,BrowserControlRequest(action='click',session=frame['session'],frame_id=frame['frame_id'],
            x=box['x']+box['width']/2,y=box['y']+box['height']/2),scope=scope,active=lambda:True)
        manager.browser_control(task,BrowserControlRequest(action='end',session=frame['session']),scope=scope,active=lambda:True)
        execute(c,'browser_read')
        pending=recovery(c.repository.get(task))['pending_candidates']
        assert pending[0]['read_job_arguments']=={'url':url}
        assert not c.repository.get(task)['jobs']  # no automatic verification/import
        manager.worker.submit(lambda:manager.sessions[task].browser.page.screenshot(path=str(tmp_path/'recovered.png'))).result()
    finally:manager.close()
