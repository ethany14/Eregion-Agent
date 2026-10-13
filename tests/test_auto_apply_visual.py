"""Visual backup in real offline Chrome; no employer submission or model calls."""
import json
import os
import struct
from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage

from eregion.runtime.auto_apply.agent import AgentTools, HybridApplicationAgent, VISUAL_TOOLS
from eregion.runtime.auto_apply.browser import BrowserBlocked
from test_auto_apply_agent import ScriptModel, state
from test_auto_apply_browser import FixtureBrowser

pytestmark=pytest.mark.skipif(os.getenv('JOB_AGENT_BROWSER_TESTS')!='1',reason='Offline Chrome opt-in')
FIXTURE=Path(__file__).parent/'fixtures/auto_apply/visual.html'


@pytest.fixture
def browser():
    b=FixtureBrowser('https://job-boards.greenhouse.io/example/jobs/123')
    b.page.set_content(FIXTURE.read_text(encoding='utf-8'))
    try:yield b
    finally:b.close()


def session(b,**extra):
    key=b.observe()[0]['key']
    s=AgentTools(b,state(answers={key:'LinkedIn'},visual_fallback=True,**extra),autofill=lambda:{},active=lambda:True)
    s.observe()
    return s,key


def view(s):
    snap=s.observe()
    return s.execute('view_browser',{'observation_id':snap['observation_id']})


def action(s,name,**args):
    snap=s.observe()
    return s.execute(name,{'observation_id':snap['observation_id'],'screenshot_id':s.visual.screen['screenshot_id'],**args})


def center(b,selector):
    box=b.page.locator(selector).bounding_box()
    size=b.page.evaluate('() => ({width:innerWidth,height:innerHeight})')
    return {'x':(box['x']+box['width']/2)*1000/size['width'],'y':(box['y']+box['height']/2)*1000/size['height']}


def click(s,b,selector,key=''):
    return action(s,'computer_click',**center(b,selector),click_count=1,field_key=key)


def test_roleless_hierarchical_menu_completed_by_pixels_with_feedback(browser):
    s,key=session(browser)
    view(s);click(s,browser,'#source',key)
    assert browser.inspect_options(key)==[] # DOM does not know these rows are options.
    view(s);parent=click(s,browser,'#choices div:nth-child(3)',key)
    assert parent['image'].startswith(b'\x89PNG') and browser.field(key)['value']==''
    with pytest.raises(BrowserBlocked,match='validation'):
        s.observe();s.execute('ready_for_review',{})
    leaf=click(s,browser,'#choices div:nth-child(3)',key)
    assert leaf['screen']['screenshot_id']!=parent['screen']['screenshot_id']
    assert browser.field(key)['value']=='LinkedIn'
    s.observe();assert s.execute('ready_for_review',{})['host_validation_required']
    assert browser.page.evaluate('selectedPath')==['Job Board','LinkedIn']
    assert browser.page.evaluate('submissions')==0


def test_failed_dom_action_automatically_gives_model_screenshot_and_tools(browser):
    key=browser.observe()[0]['key']
    box=browser.page.locator('#source').bounding_box()
    point={'x':(box['x']+100)*1000/1280,'y':(box['y']+box['height']+1+2*36+18)*1000/900}
    def args(snap):
        # Fixture layout is fixed. The real-model smoke test separately chooses
        # coordinates from pixels, rather than this deterministic script.
        return {'observation_id':snap['observation_id'],'screenshot_id':snap['screen']['screenshot_id'],
            **point,'click_count':1,'field_key':key}
    class VisualModel(ScriptModel):
        def invoke(self,messages,tools):
            if self.calls:
                assert any(isinstance(m,HumanMessage) and isinstance(m.content,list) and
                    any(block.get('type')=='image_url' for block in m.content) for m in messages)
            assert VISUAL_TOOLS <= {t['function']['name'] for t in tools}
            return super().invoke(messages,tools)
    m=VisualModel([('inspect_field',lambda snap:{'observation_id':snap['observation_id'],'field_key':key}),
        ('computer_click',args),('computer_click',args),('ready_for_review',{})])
    result=HybridApplicationAgent(model_factory=lambda:m).run(browser,state(answers={key:'LinkedIn'},visual_fallback=True),
        autofill=lambda:{},active=lambda:True,reserve=lambda _:True,report=lambda *args:None)
    assert result['reason']=='ready'
    assert browser.field(key)['value']=='LinkedIn'


def test_visual_images_stop_after_returning_to_dom_and_capture_once(browser, monkeypatch):
    from eregion.runtime.auto_apply.visual import VisualBrowser
    original = VisualBrowser.capture
    captures, image_turns = [], []
    def capture(self):
        result = original(self)
        captures.append(result['screen']['screenshot_id'])
        return result
    monkeypatch.setattr(VisualBrowser, 'capture', capture)
    class Model(ScriptModel):
        def invoke(self, messages, tools):
            image_turns.append(any(isinstance(m, HumanMessage) and isinstance(m.content, list)
                                   for m in messages))
            snapshot = json.loads(next(m.content for m in reversed(messages)
                if isinstance(m, HumanMessage) and isinstance(m.content, str)))
            assert bool(snapshot.get('screen')) == image_turns[-1]
            return super().invoke(messages, tools)
    def scroll(snap):
        return {'observation_id':snap['observation_id'], 'screenshot_id':snap['screen']['screenshot_id'],
                'x':700, 'y':500, 'delta_x':0, 'delta_y':100}
    key = browser.observe()[0]['key']
    model = Model([('view_browser', lambda snap:{'observation_id':snap['observation_id']}),
                   ('computer_scroll', scroll), ('observe', {}), ('say', {'text':'Using the form controls.'}),
                   ('request_input', {'field_keys':[key]})])
    result = HybridApplicationAgent(model_factory=lambda:model).run(browser,
        state(answers={},visual_fallback=True), autofill=lambda:{}, active=lambda:True,
        reserve=lambda _:True, report=lambda *args:None)
    assert result['reason'] == 'needs_input'
    assert image_turns == [False, True, True, False, False]
    assert len(captures) == 2 and len(set(captures)) == 2
    assert browser.page.evaluate('submissions') == 0


def test_old_coordinates_rejected_after_dom_change_scroll_and_dom_action(browser):
    s,key=session(browser);view(s)
    browser.page.evaluate("document.querySelector('h1').textContent='A new page'")
    with pytest.raises(BrowserBlocked,match='stale'):
        click(s,browser,'#source',key)
    view(s)
    snap=s.observe();s.execute('click_field',{'observation_id':snap['observation_id'],'field_key':key})
    assert s.visual.screen is None
    view(s);old=s.visual.screen['screenshot_id']
    browser.page.evaluate("document.body.style.height='2400px'")
    view(s)
    action(s,'computer_scroll',x=700,y=500,delta_x=0,delta_y=450)
    assert browser.page.evaluate('scrollY')>0
    snap=s.observe()
    with pytest.raises(BrowserBlocked,match='stale'):
        s.execute('computer_click',{'observation_id':snap['observation_id'],'screenshot_id':old,
            'x':220,'y':200,'click_count':1,'field_key':key})


def test_clicks_cannot_submit_or_grant_unknown_consent(browser):
    s,key=session(browser);view(s)
    with pytest.raises(BrowserBlocked,match='submission'):
        click(s,browser,'button span')
    browser.page.evaluate("document.querySelector('form').insertAdjacentHTML('beforeend','<label id=consent><input type=checkbox required>I agree to the privacy policy</label>')")
    view(s)
    with pytest.raises(BrowserBlocked,match='answer|Confirm'):
        click(s,browser,'#consent input')
    assert not browser.page.locator('#consent input').is_checked()
    assert browser.page.evaluate('submissions')==0


def test_typing_uses_source_and_enter_cannot_implicitly_submit(browser):
    browser.page.set_content('<form id="application" onsubmit="window.submissions++;return false"><label for="name">First name</label><input id="name"><button>Submit</button></form><script>window.submissions=0</script>')
    s,key=session(browser);s.state['answers']={}
    view(s);click(s,browser,'#name',key)
    action(s,'computer_type',field_key=key,source_ref='profile:first_name',replace=True)
    assert browser.page.locator('#name').input_value()=='Test'
    with pytest.raises(BrowserBlocked,match='Enter/Space'):
        action(s,'computer_key',key='Enter',field_key=key)
    with pytest.raises(BrowserBlocked):
        action(s,'computer_type',field_key=key,source_ref='profile:not_a_fact',replace=True)
    assert browser.page.evaluate('submissions')==0


def test_secret_page_and_disabled_visual_mode_do_not_capture(browser):
    s,key=session(browser);s.state['visual_fallback']=False
    with pytest.raises(BrowserBlocked,match='not enabled'):view(s)
    s.state['visual_fallback']=True
    browser.page.set_content('<input type="password" value="secret">')
    with pytest.raises(BrowserBlocked,match='secure account'):view(s)


def test_css_pixel_dimensions_and_coordinate_bounds(browser):
    browser.page.set_viewport_size({'width':960,'height':720})
    cdp=browser.context.new_cdp_session(browser.page)
    cdp.send('Emulation.setDeviceMetricsOverride',{'width':960,'height':720,'deviceScaleFactor':2,'mobile':False})
    s,key=session(browser);result=view(s)
    assert struct.unpack('>II',result['image'][16:24])==(960,720)
    assert (result['screen']['width'],result['screen']['height'])==(960,720)
    for x,y in [(1000,0),(-1,0),(0,1000),(float('nan'),0),(True,10)]:
        with pytest.raises(BrowserBlocked,match='Coordinates'):
            action(s,'computer_click',x=x,y=y,click_count=1,field_key=key)


def test_screenshot_coordinates_reach_iframe_target(browser):
    browser.page.set_content('<iframe style="position:absolute;left:200px;top:100px;width:500px;height:300px"></iframe>')
    child=browser.page.frames[1]
    child.set_content('<button type="button" onclick="this.textContent=\'Clicked\'">Open choices</button>')
    s=AgentTools(browser,state(visual_fallback=True),autofill=lambda:{},active=lambda:True)
    view(s);box=child.locator('button').bounding_box()
    action(s,'computer_click',x=(box['x']+10)*1000/1280,y=(box['y']+10)*1000/900,click_count=1,field_key='')
    assert child.locator('button').inner_text()=='Clicked'


def test_visual_navigation_keeps_host_missing_answer_and_review_checks(browser):
    browser.page.locator('button').evaluate("e=>e.textContent='Next'")
    s,key=session(browser);view(s)
    with pytest.raises(BrowserBlocked,match='required answers'):
        click(s,browser,'button')
    assert browser.page.evaluate('submissions')==0


def test_hover_scroll_drag_and_keyboard_use_the_same_screenshot_space(browser):
    browser.page.set_content('''<style>#hover{width:200px;height:50px}#hint{display:none}#hover:hover #hint{display:block}
    #menu{width:250px;height:80px;overflow:auto}#long{height:900px}#thumb{width:30px;height:30px;background:green}</style>
    <div id="hover">Hover for help<span id="hint">Help is visible</span></div>
    <div id="menu"><div id="long">Scrollable choices</div></div>
    <div id="thumb"></div><label for="first">First name</label><input id="first"><label for="last">Last name</label><input id="last">
    <script>window.dragged=false;document.querySelector('#thumb').onmousedown=()=>document.onmouseup=()=>{window.dragged=true;document.onmouseup=null;};</script>''')
    s,key=session(browser);s.state['answers']={};view(s)
    action(s,'computer_move',**center(browser,'#hover'))
    assert browser.page.locator('#hint').is_visible()
    browser.page.locator('#menu').evaluate('e=>e.scrollTop=100')
    with pytest.raises(BrowserBlocked,match='stale'):
        action(s,'computer_scroll',**center(browser,'#menu'),delta_x=0,delta_y=100)
    view(s)
    action(s,'computer_scroll',**center(browser,'#menu'),delta_x=0,delta_y=300)
    assert browser.page.locator('#menu').evaluate('e=>e.scrollTop')>0
    point=center(browser,'#thumb')
    action(s,'computer_drag',**point,end_x=point['x']+50,end_y=point['y'],field_key='')
    assert browser.page.evaluate('dragged')
    click(s,browser,'#first',key)
    action(s,'computer_type',field_key=key,source_ref='profile:first_name',replace=True)
    action(s,'computer_key',field_key=key,key='ControlOrMeta+A')
    action(s,'computer_key',field_key=key,key='Backspace')
    assert browser.page.locator('#first').input_value()==''
    action(s,'computer_key',field_key=key,key='Tab')
    with pytest.raises(BrowserBlocked,match='different field'):
        action(s,'computer_type',field_key=key,source_ref='profile:first_name',replace=True)
