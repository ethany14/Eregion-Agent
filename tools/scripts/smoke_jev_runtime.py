"""Real Chrome regression for fast choices; synthetic provider fault injection."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ['JOB_AGENT_HIDDEN_BROWSER'] = 'headless'
import httpx
from eregion.runtime.fast_decisions import FastDecisions, DecisionBatch
from eregion.runtime.auto_apply.agent import AgentTools
from eregion.runtime.auto_apply.browser import ApplicationBrowser
from eregion.runtime.auto_apply.autofill import autofill
from eregion.runtime.auto_apply.fast_options import fill_options


def choice_response(payload):
    answers = {}
    for key, q in payload['questions'].items():
        first = next(iter(q['criteria']))
        answers[key] = {'type':'choice','choice':first,'confidence':1.0,
                        'probabilities':{k:float(k==first) for k in q['criteria']}}
    return {'model':'fixture','answers':answers,'usage':{'input_tokens':10}}


def provider_checks():
    query = {'q':{'type':'choice','instructions':'Choose','criteria':{'a':'A','unknown':'Unknown'}}}
    reports = {}
    for label in ('http_429','http_401','timeout','invalid_response','ok'):
        calls = []
        def respond(request):
            calls.append(True)
            if label == 'timeout':raise httpx.ReadTimeout('fixture')
            if label.startswith('http_'):return httpx.Response(int(label[5:]))
            data = choice_response(json.loads(request.content))
            if label == 'invalid_response':data['answers']['q']['choice'] = 'invented'
            return httpx.Response(200,json=data)
        service = FastDecisions(api_key='synthetic',enabled=True,transport=httpx.MockTransport(respond))
        a = service.evaluate('fixture',query,purpose='test')
        b = service.evaluate('fixture',query,purpose='test')
        assert a.status == label
        assert len(calls) == 1
        assert b.cached if label == 'ok' else b.status == 'cooldown'
        reports[label] = {'first':a.status,'second':b.status,'calls':len(calls),'cached':b.cached}
    return reports


FORM = '''<h1>Synthetic safety form</h1><form onsubmit="event.preventDefault();window.submits++">
<label for="school">School</label><select id="school" required><option value="">Choose</option>
<option value="gt">Georgia Institute of Technology</option><option value="uga">University of Georgia</option></select>
<label for="consent">I agree to data processing</label><select id="consent" required>
<option value="">Choose</option><option>Yes</option><option>No</option></select>
<button type="submit">Submit application</button></form><script>window.submits=0;</script>'''


class LocalBrowser(ApplicationBrowser):
    body = FORM
    def _guard_request(self, route):
        route.fulfill(content_type='text/html',body=self.body)


def browser_checks():
    results = {}
    for mode in ('stale_reply','changed_options','added_ambiguous_option','paused','provider_failure','success'):
        browser = LocalBrowser('https://jobs.lever.co/synthetic/check',headless=True)
        state = {'profile':{'school':'Georgia Tech'},'answers':{},'chat_revision':0,'automation_mode':'hybrid'}
        active, count = [True], [0]
        session = AgentTools(browser,state,autofill=lambda:autofill(browser,state,lambda:b''),active=lambda:active[0])
        def decide(data,questions):
            count[0] += 1
            result = DecisionBatch(choice_response({'questions':questions})['answers'],'ok')
            if mode == 'stale_reply':state['chat_revision'] += 1
            if mode == 'changed_options':
                browser.page.evaluate('(n)=>{document.querySelectorAll("#school option")[1].value="changed"+n}',count[0])
            if mode == 'added_ambiguous_option':
                browser.page.evaluate('(n)=>{let o=document.createElement("option");o.value="new"+n;o.textContent="Georgia Tech other campus";document.querySelector("#school").append(o)}',count[0])
            if mode == 'paused':active[0] = False
            if mode == 'provider_failure':result = DecisionBatch(status='timeout')
            return result
        session.fast_choices = decide
        try:
            filled = fill_options(session)
            values = browser.page.evaluate('Object.fromEntries([...document.querySelectorAll("select")].map(e=>[e.id,e.value]))')
            assert values['school'] == ('gt' if mode == 'success' else ''), (mode,values)
            assert values['consent'] == ''
            assert browser.page.evaluate('window.submits') == 0
            results[mode] = {'values':values,'filled':len(filled),'fast_calls':count[0],'submit_clicks':0}
        finally:
            browser.close()
    return results


def browser_screening(out):
    """Actual main LLM -> browser -> new CareerHarness tool -> actual Jev."""
    from eregion.api.db import create_database
    from eregion.runtime.career.repository import TaskRepository
    from eregion.runtime.career.harness import CareerHarness
    from eregion.runtime.browser.manager import BrowsingManager
    from eregion.runtime.tasks.loop import TaskLoop
    from eregion.runtime.workspace.repository import JobWorkspaceRepository
    from eregion.runtime.evidence.repository import CareerEvidenceRepository
    from eregion.runtime.auto_apply.repository import ApplyRepository
    class JobBrowser(LocalBrowser):
        body = '''<h1>Synthetic job board</h1><ul>
        <li><a href="https://example.invalid/jobs/python">Junior Python Backend Engineer</a> - Remote, United States. Entry level Python APIs and SQL.</li>
        <li><a href="https://example.invalid/jobs/tax">Senior Tax Accountant</a> - London. Onsite. Ten years corporate tax experience.</li>
        <li><a href="https://example.invalid/jobs/unknown">Software Engineer</a> - Location and requirements not stated.</li>
        </ul>'''
    os.environ['TYPESAFE_ENABLED'] = 'true'
    with tempfile.TemporaryDirectory() as temp:
        db = create_database('sqlite:///' + (Path(temp)/'screen.db').as_posix(),create_schema_for_tests=True)
        repository = TaskRepository(db.session_factory)
        runtime = SimpleNamespace(workspace=JobWorkspaceRepository(db.session_factory),
                                  evidence=CareerEvidenceRepository(db.session_factory))
        applications = SimpleNamespace(repository=ApplyRepository(db.session_factory))
        harness = CareerHarness(runtime,applications,repository)
        harness._browsing = BrowsingManager(factory=lambda url:JobBrowser(url,headless=True,purpose='browse'))
        loop = TaskLoop(repository,harness,budget=12)
        started = time.monotonic()
        try:
            state = loop.start('This is a synthetic test with no saved applicant. Open https://example.invalid/jobs '
                'and use screen_jobs to shortlist the visible links for entry-level Python backend jobs, remote in the United States. '
                'Report preliminary relevance only. Do not import jobs, do detailed scoring, or submit anything.',str(uuid4()))
            while time.monotonic()-started < 100:
                state = repository.get(state['task_id'])
                if state['status'] in {'completed','needs_input','failed'}:break
                time.sleep(.1)
            report = {'status':state['status'],'seconds':round(time.monotonic()-started,3),
                'fast_decisions':state.get('fast_decisions',[]),
                'messages':[m['text'] for m in state['messages'] if m['role']=='assistant'],
                'tools':[h.get('tool') or h.get('name') for h in state['history']]}
            (out/'screening-loop.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            assert state['status'] == 'completed' and any(d['status']=='ok' for d in report['fast_decisions']), report
            return report
        finally:
            loop.close();harness.close();db.close()


def main():
    out = Path(os.environ.get('NORTHSTAR_SMOKE_DIR','.'))
    report = {'provider':provider_checks(),'browser':browser_checks()}
    print(json.dumps(report),flush=True)
    (out/'jev-runtime.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(browser_screening(out)),flush=True)


if __name__ == '__main__':
    main()
