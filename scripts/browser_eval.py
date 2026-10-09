"""Opt-in live public-site evaluation of Northstar's real task loop.

Uses the configured model, isolated headless Chrome, a NEW evaluation database,
and no saved resume, credentials, cookies or candidate records. The agent chooses
its own browser actions; assertions below only check the resulting page.
Run from the repository: .venv/Scripts/python.exe scripts/browser_eval.py --case todo
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from api.db import create_database
from agent_runtime.auto_apply.browser import ApplicationBrowser
from agent_runtime.browser.manager import BrowsingManager
from agent_runtime.career.harness import CareerHarness
from agent_runtime.career.repository import TaskRepository
from agent_runtime.task_loop import TaskLoop


CASES = {
    'linkedin':('https://www.linkedin.com/jobs/search/',
        'Use LinkedIn website search controls to search for Data Analyst jobs in New York. Inspect results, open one actual posting, expand its description if needed, and report its exact title, job URL and one observed requirement. Use the browser, not search_jobs or board APIs. If login is required, report that limitation honestly; do not sign in, register, apply or contact anyone.'),
    'wikipedia':('https://www.wikipedia.org/',
        'Search Wikipedia for Ithaca, New York using the website search. Open its English article and report its heading and one sentence about its location. Do not use a memorized URL.'),
    'todo':('https://demo.playwright.dev/todomvc/',
        'On this public local-storage demo, add one todo named Northstar browser smoke, then mark it completed. Leave the completed item visible. Verify what is on screen.'),
    'combobox':('https://www.w3.org/WAI/ARIA/apg/patterns/combobox/examples/combobox-autocomplete-list/',
        'Test the State combobox: type Ala, inspect its suggested options, then choose Alabama from the suggestions. Verify the final field value.'),
    'greenhouse':('https://job-boards.greenhouse.io/cloudflare',
        'Find one currently listed engineering job by browsing/searching this careers site. Open its job description and report the exact title and its job URL. Do not apply, upload, log in or submit anything.'),
    'ashby':('https://jobs.ashbyhq.com/notion',
        'Find one engineering vacancy on this board, open its job description, and report the title and one observed requirement. Do not apply, upload, log in or submit anything.'),
    'lever':('https://jobs.lever.co/peakgames',
        'Find one engineering vacancy on this board, open its job description, and report its title and URL. Do not apply, upload, log in or submit anything.'),
    'dynamic':('https://the-internet.herokuapp.com/dynamic_loading/1',
        'Click Start, wait for the dynamic result, and report the text that appears. Do not stop before the loading result is visible.'),
    'selenium':('https://www.selenium.dev/selenium/web/dynamic.html',
        'Click Reveal a new input, wait until the delayed text field is visible, then type Northstar dynamic test into that field and verify its value.'),
    'workday':('https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite',
        'Use the careers website search to find a software engineering job, open one job description and report the exact title and one observed requirement. Do not apply, upload, sign in or register.'),
    'visual':('https://www.w3.org/WAI/ARIA/apg/patterns/combobox/examples/combobox-autocomplete-list/',
        'Test visual backup on the State combobox. Type Ala into the State input, scroll it into view if needed, then use browser_screenshot and browser_click_at to choose Alabama using the screenshot coordinates. Verify the final field value. Use a real visual click for this test, not browser_click or keyboard to select the option.'),
}


def verify(name, session):
    page=session.browser.page
    result={'url':page.url,'title':page.title()}
    if name=='todo':
        row=page.locator('.todo-list li').filter(has_text='Northstar browser smoke')
        result['passed']=row.count()==1 and 'completed' in (row.get_attribute('class') or '')
    elif name in {'combobox','visual'}:
        values=page.locator('input[role="combobox"]').evaluate_all('(es)=>es.map(e=>e.value)')
        result.update(passed='Alabama' in values,values=values)
    elif name=='wikipedia':
        heading=page.locator('h1').first.inner_text()
        result.update(passed='en.wikipedia.org/wiki/' in page.url and 'Ithaca' in heading,heading=heading)
    elif name=='dynamic':
        result['passed']=page.get_by_text('Hello World!',exact=True).is_visible()
    elif name=='selenium':
        result['passed']=page.locator('input').evaluate_all("es=>es.some(e=>e.type==='text' && e.value==='Northstar dynamic test' && !!e.getClientRects().length)")
    elif name=='linkedin':
        # LinkedIn can show a real posting in a split panel without changing to
        # /jobs/view. Verify the region the agent actually read, not list text.
        from urllib.parse import parse_qs, urlsplit
        observed=session.observation or {};region=observed.get('region_ref')
        panel=session.scope.locator(f'[data-northstar-browse="{region}"]') if region else page.locator('body')
        text=panel.inner_text() if panel.count()==1 else ''
        links=panel.locator('a[href*="/jobs/view/"]').evaluate_all('(es)=>es.filter(e=>e.getClientRects().length).map(e=>e.href)')
        query=parse_qs(urlsplit(page.url).query)
        result.update(passed=len(text)>500 and bool(links) and (bool(region) or '/jobs/view/' in page.url)
            and any(term in text.casefold() for term in ('requirements','qualifications','responsibilities','what you')),
            detail_region=region,posting_links=links[:5],search_keywords=query.get('keywords'),search_location=query.get('location'))
    else:
        text=page.locator('body').inner_text()
        import re
        is_posting=bool(re.search(r'/jobs/\d+|[?&]gh_jid=\d+|/[0-9a-f]{8}-[0-9a-f-]{27,}',page.url))
        if name=='workday':is_posting=bool(re.search(r'/(?:job|details)/[^?]+_[\w-]+',page.url))
        result.update(passed=is_posting and len(text)>500
            and any(term in text.casefold() for term in ('requirements','qualifications','what you','responsibilities','about the role')),
            headings=page.locator('h1,h2').all_text_contents()[:10])
    return result


def run(name, folder, *, driver=False, seconds=300):
    folder.mkdir(parents=True,exist_ok=True)
    database=create_database(f'sqlite:///{(folder/"evaluation.sqlite").as_posix()}',create_schema_for_tests=True)
    repo=TaskRepository(database.session_factory)
    harness=CareerHarness(SimpleNamespace(workspace=None,evidence=None),SimpleNamespace(repository=None),repo,fit_service=object())
    harness.candidate=lambda:({},'')
    harness._browsing=BrowsingManager(factory=lambda url:ApplicationBrowser(url,purpose='browse',headless=True))
    loop=None;task_id=None;started=time.monotonic();report={'case':name,'started_at':datetime.now(timezone.utc).isoformat(),'mode':'driver' if driver else 'agent'}
    try:
        url,goal=CASES[name]
        if driver:
            task_id='driver'
            state=harness.browsing.call(task_id,'browser_open',{'url':url})
            report.update(reachable=bool(state.get('text')),url=state['url'],heading=state.get('heading'),controls=state.get('control_count'),blocked=state.get('blocked'))
        else:
            loop=TaskLoop(repo,harness,budget=16,retry_delays=(1,))
            task=loop.start(f'Browser test on a public website: {url}\n{goal}\nUse the browser tools autonomously. This is an isolated test, no candidate data or accounts are available.',str(uuid4()),visual_fallback=name=='visual')
            task_id=task['task_id'];last=None
            while time.monotonic()-started<seconds:
                state=repo.get(task_id)
                activity=state.get('tool_activity') or state.get('model_activity') or {}
                progress=(state['status'],state['model_calls'],activity.get('tool'))
                if progress!=last:
                    print(json.dumps({'case':name,'status':state['status'],'model_calls':state['model_calls'],'tool':activity.get('tool')}),flush=True);last=progress
                if state['status'] in {'completed','needs_input','cancelled'}:break
                time.sleep(.5)
            else:repo.change(task_id,status='cancelled',pause_requested=True)
            if loop:loop.close();loop=None
            state=repo.get(task_id)
            report.update(status=state['status'],model_calls=state['model_calls'],actions=state['actions'],
                messages=state['messages'],history=state['history'],timings=state.get('timings',[]),error=state.get('error'))
            session=harness.browsing.sessions.get(task_id)
            if session:
                try:report['verification']=harness.browsing.worker.submit(verify,name,session).result()
                except Exception as exc:report['verification']={'passed':False,'error':type(exc).__name__}
            else:report['verification']={'passed':False,'error':'No browser was opened'}
            if name=='visual':
                completed={a['tool'] for a in state['actions'] if a['outcome']=='completed'}
                report['verification']['visual_tools_used']={'browser_screenshot','browser_click_at'}<=completed
                report['verification']['passed'] &= report['verification']['visual_tools_used']
            if name=='linkedin':
                completed={a['tool'] for a in state['actions'] if a['outcome']=='completed'}
                report['verification']['browser_search_used']='browser_type' in completed and bool({'browser_click','browser_key'}&completed)
                report['verification']['passed'] &= report['verification']['browser_search_used']
        preview=harness.browsing.preview(task_id)
        if preview:(folder/'final.jpg').write_bytes(preview)
    except Exception as exc:report.update(error=type(exc).__name__,detail=str(exc)[:300])
    finally:
        if loop:loop.close()
        harness.close();database.close()
        report['elapsed_seconds']=round(time.monotonic()-started,2)
        (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'case':name,'report':str(folder/'report.json'),'verification':report.get('verification'),'error':report.get('error'),'elapsed_seconds':report['elapsed_seconds']}),flush=True)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--case',choices=CASES,action='append',required=True)
    parser.add_argument('--driver',action='store_true',help='Read-only transport/DOM probe; does not count as an autonomous pass.')
    parser.add_argument('--seconds',type=int,default=300)
    parser.add_argument('--output',type=Path,default=Path('artifacts/browser-eval')/datetime.now().strftime('%Y%m%d-%H%M%S'))
    args=parser.parse_args()
    for name in args.case:run(name,args.output/name,driver=args.driver,seconds=args.seconds)
