"""Actual Chrome/API async presentation; local deterministic interview providers."""
import json
import os
from threading import Event

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright,expect

from eregion.api.main import create_app
from test_career_flow import career
from test_remaining_interview_async import service_for
from test_remaining_interview_fifo import prepared

pytestmark=pytest.mark.skipif(os.getenv('JOB_AGENT_BROWSER_TESTS')!='1',reason='Local Chrome UI opt-in')


def test_current_question_and_late_feedback_binding_in_real_chrome(career,tmp_path):
    c=career;controller,identifier=prepared(c)
    original_question=controller.model.question;original_evaluate=controller.model.evaluate
    gates={1:Event(),2:Event()};counter=[1]
    def question(context):
        counter[0]+=1
        return original_question(context).model_copy(update={'question_text':f'Question {counter[0]}: describe your personal contribution.'})
    def evaluate(context):
        number=1 if context['answer_untrusted'].startswith('A1:') else 2
        assert gates[number].wait(30)
        return original_evaluate(context).model_copy(update={'improvement_areas':[f'Feedback belongs to answer {number}.']})
    controller.model.question=question;controller.model.evaluate=evaluate
    service=service_for(c)
    app=create_app(run_service=object(),session_runtime=c.runtime)
    app.state.auto_apply=c.applications;app.state.career_agent=service
    errors=[];states=[]
    try:
        with TestClient(app,base_url='http://localhost') as client,sync_playwright() as p:
            browser=p.chromium.launch(channel='chrome',headless=True)
            page=browser.new_page(viewport={'width':1440,'height':1000})
            page.on('pageerror',lambda exc:errors.append(str(exc)))
            def route(r):
                request=r.request
                if not request.url.startswith('http://localhost/'):return r.abort()
                response=client.request(request.method,request.url,content=request.post_data,
                    headers={k:v for k,v in request.headers.items() if k in {'content-type','origin'}})
                r.fulfill(status=response.status_code,body=response.content,headers={'content-type':response.headers.get('content-type','')})
            page.route('**/*',route);page.goto('http://localhost/apply')
            page.locator(f'.attempt-row[data-id="{c.state["task_id"]}"] button').first.click()
            expect(page.locator('.career-interview .interview-question')).to_be_visible()
            page.locator('#chat-text').fill('A1: I built Python APIs.');page.locator('#send-message').click()
            expect(page.locator('.career-interview .interview-question')).to_contain_text('Question 2',timeout=10000)
            expect(page.locator('.career-interview')).to_contain_text('1 saved answer')
            expect(page.locator('.career-interview')).not_to_contain_text('Feedback on answer 1')
            page.locator('#chat-text').fill('A2: I tested SQL results.');page.locator('#send-message').click()
            expect(page.locator('.career-interview .interview-question')).to_contain_text('Question 3',timeout=10000)
            gates[2].set()
            expect(page.locator('.career-interview')).to_contain_text('Feedback belongs to answer 2.',timeout=10000)
            expect(page.locator('.career-interview .interview-question')).to_contain_text('Question 3')
            gates[1].set()
            expect(page.locator('.career-interview')).to_contain_text('Feedback belongs to answer 1.',timeout=10000)
            expect(page.locator('.career-interview')).to_contain_text('Feedback on answer 1')
            expect(page.locator('.career-interview')).to_contain_text('Feedback on answer 2')
            for theme in ('light','night'):
                for width,height,label in ((1440,1000,'desktop'),(390,844,'mobile')):
                    page.set_viewport_size({'width':width,'height':height})
                    page.evaluate('(theme)=>localStorage.setItem("eregion.theme",theme)',theme);page.reload()
                    # Reload intentionally returns to Chronicle. Reopen the
                    # saved conversation through the ordinary visible control.
                    if width<700:page.get_by_role('button',name='Show conversation history',exact=True).click()
                    page.locator(f'.attempt-row[data-id="{c.state["task_id"]}"] button').first.click()
                    expect(page.locator('.career-interview .interview-question')).to_contain_text('Question 3')
                    if width<700:
                        # Wait for the normal drawer-close transition before
                        # capture; class removal alone does not finish motion.
                        page.wait_for_function('document.querySelector("#history-panel").getBoundingClientRect().right<=1')
                    page.locator('.career-interview .interview-question').scroll_into_view_if_needed()
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    page.screenshot(path=str(tmp_path/f'async-feedback-{theme}-{label}.png'),full_page=True)
                    for number in (1,2):
                        heading=page.get_by_text(f'Feedback on answer {number}',exact=True)
                        heading.scroll_into_view_if_needed()
                        page.screenshot(path=str(tmp_path/f'feedback-{number}-heading-{theme}-{label}.png'),full_page=True)
                        page.get_by_text(f'Feedback belongs to answer {number}.',exact=True).scroll_into_view_if_needed()
                        page.screenshot(path=str(tmp_path/f'feedback-{number}-notes-{theme}-{label}.png'),full_page=True)
                    states.append({'theme':theme,'size':label,'question':page.locator('.interview-question').inner_text(),
                        'feedback':page.locator('.career-interview').inner_text(),
                        'drawer_right':page.locator('#history-panel').bounding_box()['x']+page.locator('#history-panel').bounding_box()['width'],
                        'horizontal_overflow':page.evaluate('document.documentElement.scrollWidth>innerWidth')})
            page.set_viewport_size({'width':1440,'height':1000})
            page.get_by_role('button',name='End practice',exact=True).click()
            expect(page.locator('.career-interview')).to_contain_text('Interview report',timeout=10000)
            assert controller.interviews.report(identifier)
            assert not errors
            (tmp_path/'async-ui.json').write_text(json.dumps({'states':states,'turns':controller.interviews.turns(identifier),
                'report':controller.interviews.report(identifier),'errors':errors,'providers':'deterministic events, not real model latency'},indent=2),encoding='utf-8')
            browser.close()
    finally:
        for gate in gates.values():gate.set()
        service.close()
