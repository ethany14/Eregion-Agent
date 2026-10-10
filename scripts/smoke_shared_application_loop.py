"""Opt-in live model + Chrome smoke: synthetic applicant, intercepted local form, no submission.
+
+Uses the project's configured model (billable). Set NORTHSTAR_SMOKE_DIR to an
+existing artifact directory. No candidate profile, real ATS, or saved cookies are used.
+"""
import json
import os
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['JOB_AGENT_HIDDEN_BROWSER'] = 'headless'
from agent_runtime.auto_apply.browser import ApplicationBrowser
from agent_runtime.auto_apply.agent import HybridApplicationAgent
from agent_runtime.auto_apply.autofill import autofill

HTML = '''<main><h1>Local application regression</h1><form id="application" onsubmit="event.preventDefault();window.submitClicks++">
<section id="contact"><label for="first">First name</label><input id="first" required>
<label for="last">Last name</label><input id="last" required>
<label for="email">Email</label><input id="email" type="email" required>
<label for="country">Country</label><select id="country" required><option value="">Choose</option><option value="US">United States</option><option value="CA">Canada</option></select>
<button id="next" type="button" onclick="document.querySelector('#contact').hidden=true;document.querySelector('#questions').hidden=false">Continue</button></section>
<section id="questions" hidden><label for="sponsor">Do you require sponsorship?</label>
<select id="sponsor" required><option value="">Choose</option><option value="Yes">Yes</option><option value="No">No</option></select>
<button type="submit">Submit application</button></section></form></main><script>window.submitClicks=0;</script>'''

class LocalBrowser(ApplicationBrowser):
    def _guard_request(self, route):
        route.fulfill(content_type='text/html', body=HTML)

def main():
    url = 'https://jobs.lever.co/loop-fixture/local-application'
    browser = LocalBrowser(url, headless=True)
    state = {'url': url, 'profile': {'first_name': 'Loop', 'last_name': 'Fixture', 'email': 'loop@example.invalid', 'country': 'US'},
             'answers': {}, 'answer_sources': {}, 'chat_revision': 0, 'visual_fallback': False,
             'messages': [{'id': 'fixture-request', 'role': 'user', 'text': "Fill this test application using my saved details. I don't need sponsorship. Stop before final submission."}]}
    actions, public, calls = [], [], {'model': 0, 'tool': 0}
    def reserve(kind):
        calls[kind] += 1
        return calls[kind] < 25
    def bind(items, revision):
        for item in items:
            state['answers'][item['field_key']] = item['value']
            state['answer_sources'][item['field_key']] = {'type': 'chat', 'message_id': item['message_id'], 'quote': item['quote'],
                'interpretation': 'model', 'pending_approval': True}
    def report(fields, name, key, result):
        actions.append({'tool': name, 'result': result})
        print(json.dumps(actions[-1]), flush=True)
    start = time.monotonic()
    try:
        result = HybridApplicationAgent().run(browser, state,
            autofill=lambda: autofill(browser, state, lambda: b''), active=lambda: True,
            reserve=reserve, report=report, checkpoint=lambda **updates: state.update(updates),
            bind_answers=bind, communicate=public.append)
        values = browser.page.evaluate('Object.fromEntries([...document.querySelectorAll("input,select")].map(e=>[e.id,e.value]))')
        submitted = browser.page.evaluate('window.submitClicks')
        output = {'result': result, 'values': values, 'submit_clicks': submitted, 'calls': calls,
            'actions': actions, 'seconds': round(time.monotonic() - start, 2), 'messages': public,
            'runtime_events': len(state.get('loop_runtime', {}).get('events', []))}
        (Path(os.environ.get('NORTHSTAR_SMOKE_DIR', '.')) / 'application-results.json').write_text(json.dumps(output, indent=2), encoding='utf-8')
        browser.page.screenshot(path=str(Path(os.environ.get('NORTHSTAR_SMOKE_DIR', '.')) / 'application-review.png'), full_page=True)
        print(json.dumps(output), flush=True)
        assert result['reason'] == 'ready', result
        assert values == {'first': 'Loop', 'last': 'Fixture', 'email': 'loop@example.invalid', 'country': 'US', 'sponsor': 'No'}
        assert submitted == 0
    finally:
        browser.close()


if __name__ == '__main__':
    main()
