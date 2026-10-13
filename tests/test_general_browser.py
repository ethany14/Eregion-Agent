"""Site-independent browser regressions, using real Chrome and intercepted sites."""
import json
import os
from urllib.parse import urlsplit
import pytest

from eregion.runtime.auto_apply.browser import ApplicationBrowser, BrowserBlocked
from eregion.runtime.browser.session import BrowserSession

pytestmark=pytest.mark.skipif(os.getenv('JOB_AGENT_BROWSER_TESTS')!='1',reason='Offline Chrome opt-in')

HOME='''<h1>Public website</h1><form role="search" action="https://second.example/results" method="get">
  <input type="search" name="q" aria-label="Find articles"><button>Search</button></form>
  <a target="_blank" href="https://second.example/details">Open details</a>
  <button onclick="setTimeout(()=>document.querySelector('#loaded').hidden=false,700)">Load content</button>
  <div id="loaded" hidden>Loaded successfully</div><div id="shadow"></div>
  <script>const button=document.createElement('button');button.textContent='Expand shadow details';button.onclick=()=>button.textContent='Expanded';document.querySelector('#shadow').attachShadow({mode:'open'}).append(button);</script>'''


class LocalWebBrowser(ApplicationBrowser):
    def __init__(self,url='https://first.example/',**kwargs):super().__init__(url,purpose='browse',headless=True,**kwargs)
    def _guard_request(self,route):
        if route.request.is_navigation_request():
            parts=urlsplit(route.request.url)
            body=HOME if parts.hostname=='first.example' else '<h1>Result page</h1><p>Verified second site content.</p>'
            route.fulfill(content_type='text/html',body=body)
        else:route.abort()


@pytest.fixture
def session():
    b=LocalWebBrowser();s=BrowserSession(b)
    try:yield s
    finally:b.close()


def find(s,label):
    state=s.read()
    item=next(c for c in state['controls'] if c['label']==label)
    return {'observation_id':state['observation_id'],'ref':item['ref']}


def test_home_search_cross_site_back_and_tabs(session):
    s=session
    assert s.read()['heading']=='Public website'
    s.type(**find(s,'Find articles'),text='synthetic browser query')
    result=s.click(**find(s,'Search'))
    assert result['heading']=='Result page' and 'synthetic' in result['url']
    assert s.back()['heading']=='Public website'
    popup=s.click(**find(s,'Open details'))
    assert len(popup['tabs'])==2 and popup['heading']=='Result page'
    first=next(t for t in popup['tabs'] if 'first.example' in t['url'])
    assert s.tabs('switch',first['id'])['heading']=='Public website'
    second=next(t for t in s.read()['tabs'] if 'second.example' in t['url'])
    assert len(s.tabs('close',second['id'])['tabs'])==1


def test_shadow_controls_delayed_content_and_recovery_from_stale_ref(session):
    s=session
    s.click(**find(s,'Expand shadow details'))
    assert any(c['label']=='Expanded' for c in s.read()['controls'])
    stale=find(s,'Load content');s.read()
    with pytest.raises(BrowserBlocked,match='stale'):s.click(**stale)
    s.click(**find(s,'Load content'))
    assert 'Loaded successfully' in s.wait()['text']


def test_long_pages_expose_late_controls_and_text(session):
    s=session
    s.browser.page.set_content('<h1>Long page</h1>'+''.join(f'<button>Item {i}</button>' for i in range(160))+'<p>'+'x'*9000+'</p><p>Last section evidence</p>')
    first=s.read();assert first['control_count']==160 and len(first['controls'])==90
    assert any(c['label']=='Item 159' for c in s.read(offset=90)['controls'])
    last=s.read(query='Last section evidence');assert 'Last section evidence' in last['text']


def test_local_editor_dropdown_and_toggle_need_no_candidate_profile(session):
    s=session
    s.browser.page.set_content('''<input placeholder="New task" onkeydown="if(event.key==='Enter')document.querySelector('p').textContent=this.value">
      <p></p><label>Filter<input type="checkbox"></label><label>Sort<select><option>Recent</option><option>Oldest</option></select></label>''')
    s.type(**find(s,'New task'),text='Northstar demo')
    assert 'Northstar demo' in s.key(**find(s,'New task'),key='Enter')['text']
    s.check(**find(s,'Filter'),checked=True)
    s.select(**find(s,'Sort'),option='Oldest')
    assert s.browser.page.locator('select').input_value()=='Oldest'


def test_final_send_credentials_consent_and_private_url_stay_guarded(session):
    s=session
    s.browser.page.set_content('''<form><button>Submit Application</button><input name="first_name"></form>
      <label>I agree to privacy terms<input type="checkbox"></label>''')
    with pytest.raises(BrowserBlocked,match='review'):s.click(**find(s,'Submit Application'))
    with pytest.raises(BrowserBlocked,match='consent'):s.check(**find(s,'I agree to privacy terms'),checked=True)
    with pytest.raises(ValueError):s.navigate('https://127.0.0.1/admin')
    s.browser.page.set_content('<input type="password" value="NOT-FOR-MODEL"><p>Account details</p>')
    state=s.read()
    assert state['blocked']=='credentials' and 'NOT-FOR-MODEL' not in json.dumps(state) and 'Account details' not in json.dumps(state)
    with pytest.raises(BrowserBlocked):s.screenshot()


def test_searches_remain_available_inside_application_worker(session):
    s=BrowserSession(session.browser,application=True)
    s.type(**find(s,'Find articles'),text='Data analyst')
    s.browser.page.set_content('<label>First name<input></label>')
    with pytest.raises(BrowserBlocked,match='grounded'):s.type(**find(s,'First name'),text='Invented name')


def test_browser_can_inspect_embedded_content(session):
    s=session
    s.browser.page.set_content('<h1>Parent</h1><iframe src="https://second.example/frame"></iframe>')
    s.browser.page.frames[1].wait_for_load_state()
    state=s.read()
    frame=next(f for f in state['frames'] if 'second.example' in f['url'])
    assert s.choose_frame(state['observation_id'],frame['id'])['heading']=='Result page'


def test_control_cannot_change_into_submit_after_observation(session):
    s=session
    s.browser.page.set_content('<button type="button" onclick="window.sent=true">Show details</button>')
    old=find(s,'Show details')
    s.browser.page.locator('button').evaluate("e=>e.textContent='Submit Application'")
    with pytest.raises(BrowserBlocked,match='changed purpose'):s.click(**old)
    assert s.browser.page.evaluate('!!window.sent') is False


def test_hash_routes_are_not_stripped_from_browser_urls(session):
    assert session.navigate('https://first.example/#/jobs/123')['url'].endswith('#/jobs/123')


def test_visual_click_operates_unlabelled_custom_dom_and_checks_freshness(session):
    s=session
    s.browser.page.set_content('''<div id="choice" style="width:200px;height:80px;background:lightblue"
      onclick="document.querySelector('p').textContent='Chosen by mouse'">Choose this item</div><p></p>''')
    assert not s.read()['controls']
    shot=s.screenshot();assert shot['image'].startswith(b'\x89PNG')
    box=s.browser.page.locator('#choice').bounding_box()
    point={'x':(box['x']+box['width']/2)*1000/shot['image_width'],
           'y':(box['y']+box['height']/2)*1000/shot['image_height']}
    clicked=s.click_at(shot['screenshot_id'],**point)
    assert 'Chosen by mouse' in clicked['text'] and clicked['image']
    s.browser.page.locator('#choice').evaluate("e=>e.style.marginTop='100px'")
    with pytest.raises(BrowserBlocked,match='changed'):s.click_at(clicked['screenshot_id'],**point)


def test_visual_capture_blocks_email_only_login_and_coordinate_submission(session):
    s=session
    s.browser.page.set_content('<h1>Sign in</h1><input type="email" value="synthetic@example.com"><button>Continue</button>')
    assert s.read()['blocked']=='credentials'
    with pytest.raises(BrowserBlocked,match='Account'):s.screenshot()
    s.browser.page.set_content('<button style="width:200px;height:80px" onclick="window.sent=true">Submit Application</button>')
    shot=s.screenshot()
    box=s.browser.page.locator('button').bounding_box()
    with pytest.raises(BrowserBlocked,match='review'):
        s.click_at(shot['screenshot_id'],(box['x']+20)*1000/shot['image_width'],(box['y']+20)*1000/shot['image_height'])
    assert not s.browser.page.evaluate('!!window.sent')


def test_job_panels_can_be_read_and_scrolled_independently(session):
    s=session
    s.browser.page.set_content('''<h1>Search results</h1><section aria-label="Results">Unrelated sales jobs</section>
      <section aria-label="Job details" style="height:180px;overflow:auto"><h2>Python Engineer</h2>
      <p>Build Python APIs for a distributed backend. Requirements include Python, SQL and production operations.</p>
      <div style="height:900px">Full job description</div><button>Show more</button></section>''')
    state=s.read();region=next(r for r in state['regions'] if r['label']=='Job details')
    detail=s.read(region_ref=region['ref'],observation_id=state['observation_id'])
    assert detail['primary_heading']=='Python Engineer'
    assert 'Unrelated sales jobs' not in detail['text']
    s.scroll(600,region_ref=region['ref'],observation_id=detail['observation_id'])
    assert s.browser.page.locator('section[aria-label="Job details"]').evaluate('e=>e.scrollTop')>0
    assert s.browser.page.evaluate('scrollY')==0
    with pytest.raises(BrowserBlocked,match='stale'):
        s.read(region_ref=region['ref'],observation_id=state['observation_id'])


def test_job_control_search_matches_title_and_company_across_card_text(session):
    s=session
    s.browser.page.set_content('''<ul><li><a href="https://second.example/job/123">Data Analyst</a><p>Example Company</p></li>
      <li><a href="https://second.example/job/999">Data Analyst</a><p>Unrelated Employer</p></li></ul>''')
    state=s.read(query='Example Company Data Analyst')
    assert len(state['controls'])==1
    assert state['controls'][0]['href'].endswith('/123')


def test_login_overlay_can_be_dismissed_without_exposing_account_contents(session):
    s=session
    s.browser.page.set_content('''<main><h1>Public job search</h1><p>Engineering roles</p></main>
      <div role="dialog"><h2>Sign in</h2><input type="email" value="PRIVATE-IDENTIFIER">
      <input type="password" value="PRIVATE-PASSWORD"><p>PRIVATE-ACCOUNT-TEXT</p>
      <button type="button" aria-label="Dismiss" onclick="this.closest('[role=dialog]').remove()">X</button>
      <button type="submit">Sign in</button></div>''')
    state=s.read()
    assert state['blocked']=='credentials'
    assert 'PRIVATE-' not in json.dumps(state)
    assert [c['label'] for c in state['controls']]==['Dismiss']
    with pytest.raises(BrowserBlocked):s.screenshot()
    state=s.read()
    control=state['controls'][0]
    after=s.click(observation_id=state['observation_id'],ref=control['ref'])
    assert not after.get('blocked') and after['heading']=='Public job search'
