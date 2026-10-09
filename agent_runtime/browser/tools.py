"""One browser capability set, shared by both agent loops."""
TEXT = {'type':'string'}


def tool(name, description, properties=None, optional=None):
    return {'type':'function','function':{'name':name,'description':description,'parameters':{
        'type':'object','properties':{**(properties or {}),**(optional or {})},
        'required':list(properties or {}),'additionalProperties':False}}}

REF = {'observation_id':TEXT,'ref':TEXT}
BROWSER_TOOLS = [
    tool('browser_open','Open a public HTTPS page, including search engines, company home pages and job boards. In the main task this opens an isolated browsing session without requiring a resume.',{'url':TEXT}),
    tool('browser_read','Read the active page, controls, regions, tabs and frames. Query words match labels and nearby row/panel text (e.g. title plus company). Use region_ref plus observation_id to read one observed result/detail panel. Offsets read additional controls or text.',optional={
        'query':TEXT,'offset':{'type':'integer','minimum':0},'text_offset':{'type':'integer','minimum':0},'region_ref':TEXT,'observation_id':TEXT}),
    tool('browser_click','Click an observed ordinary link, button, tab, menu or expandable control. Returns the actual new page. Cannot send applications, messages, purchases or consent.',REF),
    tool('browser_type','Fill an observed noncredential text box. Queries can be composed from the task; they are not candidate facts. Application answers use the application worker and its grounded field tools.',{**REF,'text':TEXT}),
    tool('browser_select','Select an exact observed native dropdown option. Use click/read for custom menus. Applicant facts use the application worker.',{**REF,'option':TEXT}),
    tool('browser_check','Set an ordinary checkbox or radio (for example a filter or a test page). Consent and applicant answers use their dedicated workflows.',{**REF,'checked':{'type':'boolean'}}),
    tool('browser_key','Press a navigation key on an observed control; Enter is allowed for searches and local editors, not unknown form submissions.',
        {**REF,'key':{'type':'string','enum':['Enter','Tab','Shift+Tab','Escape','ArrowDown','ArrowUp','ArrowLeft','ArrowRight','Home','End']}}),
    tool('browser_back','Return to the previous page and observe the result.'),
    tool('browser_tabs','List, switch or close an observed browser tab.',
        {'action':{'type':'string','enum':['list','switch','close']}},optional={'tab_id':TEXT}),
    tool('browser_frame','Inspect an observed embedded frame. Credential entry remains in the secure account workflow.',{'observation_id':TEXT,'frame_id':TEXT}),
    tool('browser_scroll','Scroll and read again. For a separate results or job-detail panel supply its observed region_ref and observation_id; otherwise scroll the viewport.',{'delta_y':{'type':'integer','minimum':-1800,'maximum':1800}},optional={'region_ref':TEXT,'observation_id':TEXT}),
    tool('browser_wait','Wait briefly for a dynamic transition, then read actual state. If unchanged, revise the approach instead of repeating indefinitely.'),
    tool('browser_screenshot','Inspect the current public viewport when visual backup is enabled. Does not send account-page screenshots.'),
    tool('browser_click_at','Click a control using fresh screenshot coordinates normalized to 0..1000. Prefer observed refs when available.',
        {'screenshot_id':TEXT,'x':{'type':'number','minimum':0,'exclusiveMaximum':1000},'y':{'type':'number','minimum':0,'exclusiveMaximum':1000}}),
]
BROWSER_NAMES = {t['function']['name'] for t in BROWSER_TOOLS}
VISUAL_NAMES = {'browser_screenshot','browser_click_at'}


def execute(session, name, args):
    method = {'browser_open':'navigate','browser_read':'read','browser_click':'click','browser_type':'type',
        'browser_select':'select','browser_check':'check','browser_key':'key','browser_back':'back',
        'browser_tabs':'tabs','browser_frame':'choose_frame','browser_scroll':'scroll','browser_wait':'wait',
        'browser_screenshot':'screenshot','browser_click_at':'click_at'}[name]
    return getattr(session,method)(**args)
