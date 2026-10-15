"""Real browser search and selected-job capture, without HTTP discovery fallback."""
import os
from urllib.parse import urlsplit
import pytest

from eregion.runtime.auto_apply.browser import ApplicationBrowser
from eregion.runtime.browser.manager import BrowsingManager
from test_career_flow import career, execute

pytestmark=pytest.mark.skipif(os.getenv('JOB_AGENT_BROWSER_TESTS')!='1',reason='Offline Chrome opt-in')

PAGE='''<h1>Jobs in New York</h1><form role="search" onsubmit="event.preventDefault();document.querySelector('#results').hidden=false">
  <input type="search" aria-label="Search jobs"><label>Location<input name="location"></label><button>Search</button></form>
  <section id="results" hidden><h2>Search results</h2><p>Unrelated sales job requiring retail sales skills.</p>
  <button onclick="history.pushState({},'', '?currentJobId=123&keywords=Python');document.querySelector('#detail').hidden=false">Python Engineer</button></section>
  <section id="detail" aria-label="Job details" hidden><h2>Python Engineer</h2><p>Example Company, New York.</p>
  <a href="https://www.linkedin.com/jobs/view/123">Python Engineer posting</a>
  <p>Build Python APIs. Work with product teams on reliable production backend services.</p>
  <button onclick="document.querySelector('#full').hidden=false">Show more</button>
  <p id="full" hidden>Requirements: Python and SQL, experience building APIs and maintaining production systems.
  Collaborate with teammates on testing, monitoring, documentation and customer requirements.</p></section>'''


class SearchBrowser(ApplicationBrowser):
    def __init__(self,url):super().__init__(url,purpose='browse',headless=True)
    def _guard_request(self,route):
        if urlsplit(route.request.url).hostname=='www.linkedin.com':route.fulfill(status=200,content_type='text/html',body=PAGE)
        else:route.abort()


def test_browser_search_capture_score_and_recommend_uses_selected_job_only(career):
    c=career
    c.harness._browsing=BrowsingManager(factory=SearchBrowser)
    c.harness.discovery.job=lambda *_:pytest.fail('Browser evidence must not fall back to HTTP')
    def action(name,label=None,**args):
        if label:
            state=execute(c,'browser_read')
            ref=next(item['ref'] for item in state['controls'] if item['label']==label)
            args.update(observation_id=state['observation_id'],ref=ref)
        return execute(c,name,**args)
    try:
        action('browser_open',url='https://www.linkedin.com/jobs/search/')
        action('browser_type','Search jobs',text='Python engineer')
        action('browser_type','Location',text='New York')
        action('browser_click','Search')
        action('browser_click','Python Engineer')
        state=action('browser_click','Show more')
        region=next(r for r in state['regions'] if r['label']=='Job details')
        url='https://www.linkedin.com/jobs/view/123'
        with pytest.raises(ValueError,match='does not identify'):
            execute(c,'read_job',url='https://www.linkedin.com/jobs/view/999',region_ref=region['ref'],observation_id=state['observation_id'])
        state=action('browser_read')
        job=execute(c,'read_job',url=url,region_ref=region['ref'],observation_id=state['observation_id'])
        assert job['source']=='rendered_browser' and job['title']=='Python Engineer'
        assert 'Requirements: Python and SQL' in job['description']
        assert 'retail sales' not in job['description'] and 'Jobs in New York' not in job['description']
        saved=execute(c,'import_job',url=url,title='Python Engineer',company='Example Company',location='New York')
        assert saved['company']=='Example Company' and saved['location']=='New York'
        execute(c,'score_job',application_id=saved['application_id'])
        recommended=execute(c,'recommend_job',application_id=saved['application_id'],tier='to_confirm',reason='Relevant Python API experience.',
            evidence=['Python Engineer'],gaps=[],to_confirm=['Work authorization.'],next_steps=['Apply.'],caveats='Confirm work authorization.')
        assert recommended['recommended']
        assert c.repository.get(c.state['task_id'])['recommendations'][0]['url']==url
    finally:c.harness.close()
