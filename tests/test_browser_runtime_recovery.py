"""Real Chrome lifecycle/observation regressions; all website IO is intercepted."""
from agent_runtime.browser.manager import BrowsingManager
from agent_runtime.auto_apply.browser import _playwright_runtime, BrowserBlocked
from test_general_browser import LocalWebBrowser


def test_parallel_context_owner_and_last_task_close():
    manager=BrowsingManager(factory=LocalWebBrowser)
    try:
        manager.call('a','browser_open',{'url':'https://first.example/'})
        manager.call('b','browser_open',{'url':'https://second.example/'})
        original=manager.worker.submit(lambda:manager.sessions['a'].browser.browser).result()
        assert manager.worker.submit(lambda:manager.sessions['b'].browser.browser is original).result()
        manager.close_task('a').result()
        assert manager.call('b','browser_read',{})['heading']=='Result page'
        manager.close_task('b').result()
        assert manager.worker.submit(lambda:not _playwright_runtime.browsers).result()
        for n in range(4):
            key='fresh-'+str(n)
            assert manager.call(key,'browser_open',{'url':'https://first.example/'})['heading']=='Public website'
            assert manager.worker.submit(lambda:manager.sessions[key].browser.browser is not original).result()
            manager.close_task(key).result()
    finally:manager.close()


def test_changed_url_and_control_refresh_without_replaying_old_action():
    manager=BrowsingManager(factory=LocalWebBrowser)
    try:
        manager.call('task','browser_open',{'url':'https://first.example/'})
        def setup():
            manager.sessions['task'].browser.page.set_content('<button id="act" onclick="window.hits=(window.hits||0)+1">Inspect detail</button>')
        manager.worker.submit(setup).result()
        before=manager.call('task','browser_read',{});item=before['controls'][0]
        manager.worker.submit(lambda:manager.sessions['task'].browser.page.evaluate("history.replaceState(null,'','?tracking=changed')")).result()
        refreshed=manager.call('task','browser_click',{'observation_id':before['observation_id'],'ref':item['ref']})
        assert refreshed['action_performed'] is False and refreshed['recovery']['kind']=='observation_refreshed'
        assert manager.worker.submit(lambda:manager.sessions['task'].browser.page.evaluate('window.hits||0')).result()==0
        actual=manager.call('task','browser_click',{'observation_id':refreshed['observation_id'],'ref':refreshed['controls'][0]['ref']})
        assert manager.worker.submit(lambda:manager.sessions['task'].browser.page.evaluate('window.hits')).result()==1
        manager.worker.submit(lambda:manager.sessions['task'].browser.page.locator('#act').evaluate("e=>e.textContent='Submit Application'")).result()
        changed=manager.call('task','browser_click',{'observation_id':actual['observation_id'],'ref':actual['controls'][0]['ref']})
        assert changed['action_performed'] is False
        try:manager.call('task','browser_click',{'observation_id':changed['observation_id'],'ref':changed['controls'][0]['ref']})
        except BrowserBlocked:pass
        else:raise AssertionError('Refreshed submit action must remain guarded')
        assert manager.worker.submit(lambda:manager.sessions['task'].browser.page.evaluate('window.hits')).result()==1
    finally:manager.close()


def test_closed_chrome_during_creation_recovers_once_with_actual_observation():
    class InterruptedBrowser(LocalWebBrowser):
        launches=0
        def _launch(self,headless):
            browser=super()._launch(headless)
            type(self).launches+=1
            if type(self).launches==1:browser.close()
            return browser
    manager=BrowsingManager(factory=InterruptedBrowser)
    try:
        result=manager.call('task','browser_open',{'url':'https://first.example/'})
        assert result['heading']=='Public website' and not result.get('blocked')
        assert result['recovery']['cause']=='TargetClosedError' and result['recovery']['attempts']==1
        assert InterruptedBrowser.launches==2
    finally:manager.close()


def test_repeated_transport_failure_remains_error_not_site_block():
    class BrokenBrowser(LocalWebBrowser):
        launches=0
        def _launch(self,headless):
            browser=super()._launch(headless);type(self).launches+=1;browser.close();return browser
    manager=BrowsingManager(factory=BrokenBrowser)
    try:
        try:manager.call('task','browser_open',{'url':'https://first.example/'})
        except Exception as exc:assert type(exc).__name__=='TargetClosedError'
        else:raise AssertionError('Persistent browser failure cannot become a site restriction')
        assert BrokenBrowser.launches==2
    finally:manager.close()
