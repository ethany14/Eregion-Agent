"""Real headless Chrome, current UI, synthetic API and a deliberately slow preview."""
import asyncio, copy, json, mimetypes, time
from pathlib import Path
from urllib.parse import urlsplit
from playwright.async_api import async_playwright

ROOT=Path(__file__).resolve().parents[2]/'frontend/web_app'
import os
OUT=Path(os.environ.get('NORTHSTAR_SMOKE_DIR', '.'))
TASK={'run_id':'speed-fixture','career':True,'title':'Speed test conversation','goal':'Synthetic test',
      'status':'running','task_status':'running','version':1,'task_version':1,'fields':[], 'review_fields':[],
      'pending_fields':[],'actions':[],'jobs':[],'materials':[],'interviews':[], 'task_plan':[],
      'recommendations':[],'created_at':'2026-10-09T20:00:00Z','updated_at':'2026-10-09T20:00:00Z',
      'messages':[{'id':'user','role':'user','text':'Synthetic UI performance check.','at':'2026-10-09T20:00:00Z'}],
      'pause_requested':False,'visual_fallback':False,'message':'Working',
      'browser':{'url':'https://example.invalid/jobs'}, 'preview_url':'/api/career/tasks/speed-fixture/browser/preview'}

async def main():
    requests=[];errors=[];state=copy.deepcopy(TASK);preview_started=None;preview_finished=None
    async with async_playwright() as p:
        browser=await p.chromium.launch(channel='chrome',headless=True)
        context=await browser.new_context(viewport={'width':1440,'height':1000})
        page=await context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
        async def route(r):
            nonlocal preview_started,preview_finished
            url=urlsplit(r.request.url);path=url.path
            if path=='/apply':return await r.fulfill(path=str(ROOT/'apply.html'),content_type='text/html')
            if path.startswith('/web-assets/'):
                name=path.removeprefix('/web-assets/');file=(ROOT/name).resolve()
                if file.is_relative_to(ROOT) and file.is_file():
                    kind='text/javascript' if file.suffix=='.js' else mimetypes.guess_type(str(file))[0] or 'application/octet-stream'
                    return await r.fulfill(path=str(file),content_type=kind)
                return await r.fulfill(status=404,body='')
            if path.startswith('/api/'):
                requests.append({'path':path,'time':time.monotonic()})
                if path.endswith('/browser/preview'):
                    preview_started=time.monotonic();await asyncio.sleep(4);preview_finished=time.monotonic()
                    return await r.fulfill(status=204,body='')
                if path=='/api/career/tasks':data={'attempts':[] if url.query else [state],'groups':[]}
                elif path=='/api/career/tasks/speed-fixture':data=state
                elif path=='/api/auto-apply/candidate':data={'profile':{},'needs_extraction':False}
                else:data={'schedules':[],'digests':[],'unread':0,'count':0,'applications':[]}
                return await r.fulfill(json=data)
            await r.fulfill(status=204,body='')
        await context.route('**/*',route)
        await page.goto('https://northstar.example.invalid/apply')
        await page.get_by_text('Speed test conversation',exact=True).click()
        await page.locator('#chat-text').fill('Draft stays while updates arrive')
        await page.locator('#browser-toggle').click()
        start=time.monotonic()
        while preview_started is None and time.monotonic()-start<3:await asyncio.sleep(.05)
        assert preview_started is not None
        await asyncio.sleep(.15)
        state['messages'].append({'id':'agent','role':'assistant','text':'Fast update while the preview is still loading.',
                                   'at':'2026-10-09T20:00:01Z'})
        changed=time.monotonic()
        await page.get_by_text('Fast update while the preview is still loading.',exact=True).wait_for(timeout=2500)
        observed=time.monotonic();assert preview_finished is None
        assert await page.locator('#chat-text').input_value()=='Draft stays while updates arrive'
        await asyncio.sleep(2)
        recent=[r for r in requests if r['time']>=start]
        singles=[r for r in recent if r['path']=='/api/career/tasks/speed-fixture']
        lists=[r for r in recent if r['path']=='/api/career/tasks']
        assert len(singles)>=3 and not lists,(singles,lists)
        assert not errors,errors
        report={'reply_refresh_seconds':round(observed-changed,3),'single_task_polls':len(singles),
                'full_list_polls':len(lists),'slow_preview_did_not_block_chat':True,'draft_preserved':True,'page_errors':errors}
        for theme,width,height in [('light',1440,1000),('dark',1440,1000),('light',390,844),('dark',390,844)]:
            await page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
            await page.set_viewport_size({'width':width,'height':height})
            if width<500 and await page.locator('#browser-close').is_visible():await page.locator('#browser-close').click()
            await asyncio.sleep(.3)
            await page.screenshot(path=str(OUT/f'ui-{theme}-{width}.png'),full_page=True)
        (OUT/'frontend.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))
        await browser.close()

asyncio.run(main())
