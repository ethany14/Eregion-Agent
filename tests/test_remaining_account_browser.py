"""Offline Chrome checks for sibling login reuse and control after navigation."""
import json
import os
from urllib.parse import urlsplit

import pytest

from eregion.runtime.auto_apply.browser import ApplicationBrowser
from eregion.runtime.auto_apply.browser_sessions import BrowserSessionStore
from eregion.runtime.browser.handoff import BrowserControlRequest,control_browser

pytestmark=pytest.mark.skipif(os.getenv('JOB_AGENT_BROWSER_TESTS')!='1',reason='Opt-in offline Chrome')


def test_shared_login_same_owner_host_only_and_stale_close_cannot_erase(tmp_path):
    store=BrowserSessionStore(tmp_path/'sessions',codec=lambda data,**_:data)
    class Browser(ApplicationBrowser):
        def _guard_request(self,route):
            signed='session=synthetic' in route.request.headers.get('cookie','')
            route.fulfill(content_type='text/html',body=('<form id="application"><label>Country<input name="country"></label></form>' if signed
                else '<h1>Sign in</h1><form><label>Password<input type="password"></label><button>Sign in</button></form>'))
    opened=[]
    def new(owner='synthetic-owner',host='qa.example.com'):
        b=Browser(f'https://{host}/jobs/1',headless=True,session_store=store,owner_key=owner);opened.append(b);return b
    try:
        first,second,stale,other_owner,other_host=new(),new(),new(),new('another-owner'),new(host='other.example.com')
        assert second.barrier()
        first.context.add_cookies([{'name':'session','value':'synthetic','domain':'qa.example.com','path':'/','secure':True,'httpOnly':True}])
        first.save_login_state(force=True)
        revision=store.revision('synthetic-owner','qa.example.com')
        stale.close()
        assert store.revision('synthetic-owner','qa.example.com')==revision
        assert second.reload_shared_login() and second.barrier() is None
        assert not second.reload_shared_login()
        assert not other_owner.reload_shared_login() and other_owner.barrier()
        assert not other_host.reload_shared_login() and other_host.barrier()
        (tmp_path/'shared-login-evidence.json').write_text(json.dumps({'same_owner_host_reloaded':True,
            'other_owner_isolated':True,'other_host_isolated':True,'stale_close_preserved_auth':True}),encoding='utf-8')
    finally:
        for b in opened:b.close()


def test_control_enter_navigation_frame_and_end(tmp_path):
    class Browser(ApplicationBrowser):
        def _guard_request(self,route):
            route.fulfill(content_type='text/html',body=('<h1>Verified</h1><label>Country<input></label>'
                if urlsplit(route.request.url).path=='/verified' else
                '<h1>Verification</h1><form action="/verified"><input autocomplete="one-time-code"><button>Continue</button></form>'))
    b=Browser('https://qa.example.com/verify',headless=True)
    try:
        frame=control_browser(b,BrowserControlRequest(action='start',expected_version=1),'synthetic-control')
        b.page.locator('input').focus()
        for action,extra in [('text',{'text':'123456'}),('key',{'key':'Enter'})]:
            frame=control_browser(b,BrowserControlRequest(action=action,session=frame['session'],frame_id=frame['frame_id'],**extra),'synthetic-control')
        assert frame['url'].endswith('/verified')
        refreshed=control_browser(b,BrowserControlRequest(action='frame',session=frame['session']),'synthetic-control')
        assert refreshed['frame_id']!=frame['frame_id']
        assert control_browser(b,BrowserControlRequest(action='end',session=frame['session']),'synthetic-control')=={'closed':True}
        (tmp_path/'control-navigation-evidence.json').write_text(json.dumps({'url':frame['url'],'frame_refreshed':True,'end_closed':True}),encoding='utf-8')
    finally:b.close()
