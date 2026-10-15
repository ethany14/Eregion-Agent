import json
import os

import pytest

from eregion.runtime.career.discovery import JobDiscovery, PageText
from eregion.domain.jev_fit.core import JevFit
from test_career_flow import career

TARGET = '''<h2>Requirements</h2><p>Required: Python backend development and PostgreSQL experience.</p>
<p>Required: Kubernetes production deployments.</p><h2>Restrictions</h2><p>No Agencies Please</p>
<p>Remote within the United States. Build reliable production APIs for Target Co.</p>'''


def page(unrelated='Fusionbox Python + TypeScript Engineers', scoped=False):
    return f'''<html><head><title>Senior Python Engineer - Target Co</title></head><body>
<nav>Other companies and jobs</nav><main><article><h1>Senior Python Engineer</h1>
{('<div class="job-description">'+TARGET+'</div>') if scoped else TARGET}
<p class="previous-next">{unrelated}</p></article></main>
<aside><h2>Related jobs</h2><p>{unrelated}</p></aside>
<footer>Subscribe to unrelated job recommendations</footer></body></html>'''


def read(source):
    discovery=JobDiscovery()
    discovery.read=lambda url:(source,url)
    return discovery.job('https://careers.example.com/jobs/5001')


@pytest.mark.parametrize('scoped',[False,True])
def test_actual_job_extraction_excludes_sidebar_footer_and_previous_next(scoped):
    source=page(scoped=scoped)
    original=PageText();original.feed(source)
    assert 'Fusionbox' in original.text and 'Subscribe' in original.text  # Original failure reproduction.
    job=read(source)
    assert all(text not in job['description'] for text in ('Fusionbox','Subscribe','Other companies'))
    assert 'PostgreSQL' in job['description'] and 'Kubernetes' in job['description']
    assert 'No Agencies Please' in job['description']  # Keep source; classify before scoring.
    assert job['body_scope']=='bounded_html'
    assert job['description']==read(page('Different Company requires Rust and a PhD',scoped))['description']


def test_multiple_unidentified_jobs_or_whole_page_fallback_cannot_be_scored():
    with pytest.raises(ValueError,match='bounded'):
        read('<body>'+TARGET+'<aside>Fusionbox</aside></body>')
    with pytest.raises(ValueError,match='bounded'):
        read('<article><h1>First</h1>'+TARGET+'</article><article><h1>Second</h1>'+TARGET+'</article>')


def test_jsonld_selects_the_requested_posting_instead_of_first_related_job():
    data=[{'@type':'JobPosting','url':'https://careers.example.com/jobs/9999','title':'Fusionbox',
        'description':'Unrelated TypeScript requirement '*10},
        {'@type':'JobPosting','url':'https://careers.example.com/jobs/5001','title':'Target Co',
        'description':TARGET}]
    job=read('<script type="application/ld+json">'+json.dumps(data)+'</script>')
    assert job['title']=='Target Co' and 'TypeScript' not in job['description']
    assert job['body_scope']=='jsonld_jobposting'


class ExtractClient:
    def __init__(self):self.calls=[]
    def evaluate(self,state,questions,purpose):
        self.calls.append((state,questions,purpose))
        # Deliberately classify every supplied span as required. The local
        # boundary/context rules must hold even with this adversarial provider.
        return {k:{'type':'noul','noul':.99 if k.startswith('e') else .01} for k in questions},[]


def test_agency_instruction_reaches_the_model_and_page_noise_does_not_change_inputs():
    # Since a37f6e4 the model classifies every span; no local rule relabels it. With this
    # adversarial classifier the agency line is therefore "required"; the real model decides.
    client=ExtractClient()
    requirements,ledger,errors=JevFit(client).extract(read(page())['description'])
    assert not errors
    assert any(r['text']=='No Agencies Please' and r['classification']=='required' for r in ledger)
    assert not any('Fusionbox' in r['text'] for r in requirements)
    other=ExtractClient()
    assert JevFit(other).extract(read(page('An unrelated company requires ten years of Rust'))['description'])[0]==requirements
    assert client.calls==other.calls  # Identical source, questions and therefore scoring inputs.


@pytest.mark.skipif(os.getenv('JOB_AGENT_BROWSER_TESTS')!='1',reason='Offline Chrome opt-in')
@pytest.mark.parametrize('scoped',[False,True])
def test_real_chrome_job_only_excludes_other_company_and_footer(tmp_path,scoped):
    from eregion.runtime.auto_apply.browser import ApplicationBrowser
    from eregion.runtime.browser.session import BrowserSession
    class Browser(ApplicationBrowser):
        def _guard_request(self,route):
            route.fulfill(content_type='text/html',body=page(scoped=scoped))
    browser=Browser('https://careers.example.com/jobs/5001',purpose='browse',headless=True)
    try:
        session=BrowserSession(browser)
        original=session.read()
        assert 'Fusionbox' in original['text']
        job=session.read(job_only=True)
        assert 'Fusionbox' not in job['text'] and 'Subscribe' not in job['text']
        assert 'PostgreSQL' in job['text'] and 'No Agencies Please' in job['text']
        assert job['primary_heading']=='Senior Python Engineer'
        browser.page.locator('aside').evaluate("e=>e.textContent='Different Company requires Rust and a PhD'")
        assert session.read(job_only=True)['text']==job['text']
        (tmp_path/'body-audit-chrome.json').write_text(json.dumps({'original':original['text'],
            'scoped':job['text'],'scope':job['body_scope'],'unrelated_changes_preserved_scoring_input':True},indent=2),encoding='utf-8')
    finally:browser.close()


@pytest.mark.skipif(not os.getenv('JOB_AGENT_SAVED_INDEED_HTML'),reason='Explicit saved real public-page replay')
def test_saved_real_indeed_body_and_detail_action_are_consumable(tmp_path):
    from pathlib import Path
    from eregion.runtime.auto_apply.browser import ApplicationBrowser
    from eregion.runtime.browser.session import BrowserSession
    from eregion.runtime.request_context import ContextArchive,prepare_request
    from eregion.runtime.core.context import ConversationWindow
    from eregion.runtime.career.harness import TOOLS
    from langchain_core.messages import HumanMessage
    source=Path(os.environ['JOB_AGENT_SAVED_INDEED_HTML']).read_text(encoding='utf-8')
    class Browser(ApplicationBrowser):
        def _guard_request(self,route):route.fulfill(content_type='text/html',body=source)
    browser=Browser('https://www.indeed.com/jobs?q=junior+data+analyst&l=New+York%2C+NY&vjk=33cd00bb496b557e',
        purpose='browse',headless=True)
    try:
        session=BrowserSession(browser);observed=session.read();bounded=session.read(job_only=True)
        assert observed['job_detail']['read_job_arguments']=={'url':browser.page.url}
        assert bounded['body_scope']=='bounded_selector'
        assert bounded['primary_heading']=='Associate Data Analyst'
        assert bounded['job_location']=='New York, NY 10007'
        assert 'Research Foundation of The City University of New York' in bounded['job_header_text']
        assert 'GoodApple' not in bounded['text'] and 'Explore other jobs' not in bounded['text']
        archive=ContextArchive();compact=archive.tool_result(observed)
        messages,_=prepare_request('Read the observed posting.',TOOLS,ConversationWindow(),{'browser':compact},archive,max_chars=48000)
        effective=json.loads(next(m.content for m in reversed(messages) if isinstance(m,HumanMessage)))
        assert effective['browser']['job_detail']['read_job_arguments']==observed['job_detail']['read_job_arguments']
        assert effective['browser']['regions']
        (tmp_path/'saved-real-page-detail-evidence.json').write_text(json.dumps({'observed':observed,
            'bounded':bounded,'effective_human_message':effective},indent=2),encoding='utf-8')
    finally:browser.close()


@pytest.mark.skipif(os.getenv('JOB_AGENT_BROWSER_TESTS')!='1',reason='Offline Chrome opt-in')
def test_split_detail_nested_body_metadata_and_region_survive_filtered_reads(tmp_path):
    from eregion.runtime.auto_apply.browser import ApplicationBrowser
    from eregion.runtime.browser.session import BrowserSession
    from eregion.runtime.request_context import ContextArchive,prepare_request
    from eregion.runtime.core.context import ConversationWindow
    from langchain_core.messages import HumanMessage
    from eregion.runtime.career.harness import TOOLS
    source='''<main><section aria-label="Search results"><h2>Unrelated Staff Rust Engineer</h2>
    <p>Fusionbox requires ten years of TypeScript experience. Other search results.</p></section>
    <section data-testid="jobsearch-JobComponent" aria-label="Job details">
    <h1>Senior Backend Engineer</h1><div data-testid="inlineHeader-companyName">Target Co</div>
    <div data-testid="inlineHeader-companyLocation">United States, remote</div>
    <div data-testid="jobsearch-JobComponent-description"><div id="jobDescriptionText">'''+TARGET+'''</div></div>
    </section></main><aside><div class="job-location">Pakistan</div>Other companies</aside>'''
    class Browser(ApplicationBrowser):
        def _guard_request(self,route):route.fulfill(content_type='text/html',body=source)
    browser=Browser('https://careers.example.com/jobs/5001',purpose='browse',headless=True)
    try:
        session=BrowserSession(browser)
        original=session.read()
        region=next(r['ref'] for r in original['regions'] if r['label']=='Job details')
        filtered=session.read(query='a phrase absent from the description')
        paged=session.read(query='Kubernetes',offset=3,text_offset=100)
        assert original['page_evidence_hash']==filtered['page_evidence_hash']==paged['page_evidence_hash']
        assert paged['job_detail']['read_job_arguments']=={'url':browser.page.url}
        archive=ContextArchive()
        compact=archive.tool_result(paged)
        messages,_=prepare_request('Inspect this observed public job.',TOOLS,ConversationWindow(),
            {'browser':compact,'current_request':{'message':{'role':'user','text':'Read and score this job.'}}},
            archive,max_chars=48000)
        effective=json.loads(next(m.content for m in reversed(messages) if isinstance(m,HumanMessage)))
        assert effective['browser']['job_detail']['read_job_arguments']==paged['job_detail']['read_job_arguments']
        assert region in [r['ref'] for r in effective['browser']['regions']]
        assert region in [r['ref'] for r in filtered['regions']]
        bounded=session.read(region_ref=region,observation_id=paged['observation_id'],job_only=True)
        assert bounded['body_scope']=='bounded_selector'
        assert bounded['primary_heading']=='Senior Backend Engineer'
        assert bounded['job_location']=='United States, remote' and bounded['job_company']=='Target Co'
        assert all(word not in bounded['text'] for word in ('Fusionbox','Pakistan','TypeScript'))
        browser.page.locator('#jobDescriptionText').evaluate("e=>e.append(' New target requirement: Rust.')")
        changed=session.read()
        assert changed['page_evidence_hash']!=original['page_evidence_hash']
        browser.page.goto('https://careers.example.com/jobs/5002')
        navigated=session.read()
        assert navigated['page_evidence_hash']!=original['page_evidence_hash']
        assert navigated['job_detail']['read_job_arguments']['url'].endswith('/5002')
        # Two separately bounded descriptions are ambiguous, even inside one
        # article with one heading. Never fall back to flattening that article.
        browser.page.set_content('<article><h1>Two openings</h1><div class="job-description">'+TARGET+
            '</div><div class="job-description">Unrelated company '+TARGET+'</div></article>')
        ambiguous=session.read(job_only=True)
        assert ambiguous['body_scope']=='unbounded' and not ambiguous['text'] and not ambiguous.get('job_detail')
        (tmp_path/'split-detail-recovery.json').write_text(json.dumps({'original':original,'filtered':filtered,
            'paged':paged,'effective_human_message':effective,'bounded':bounded,'changed':changed,
            'navigated':navigated,'ambiguous':ambiguous},indent=2),encoding='utf-8')
    finally:browser.close()


@pytest.mark.skipif(os.getenv('JOB_AGENT_BROWSER_TESTS')!='1',reason='Offline Chrome opt-in')
def test_page_source_hash_ignores_region_and_navigation_views_but_tracks_real_changes(tmp_path,career):
    from eregion.runtime.auto_apply.browser import ApplicationBrowser
    from eregion.runtime.browser.session import BrowserSession,SCAN
    source='''<main><section aria-label="First region"><h1>Senior Backend Engineer</h1>
    <p>Target role requires Python and Kubernetes production services. Build reliable APIs.</p>
    <input aria-label="Search jobs" type="search"><button>Search</button>
    <a href="https://careers.example.com/jobs/5002">Next job</a></section>
    <section aria-label="Second region"><p>Public related information with enough text to be a region.</p>
    <p>Review the company information before exploring the next job.</p><button>Dismiss</button></section></main>'''
    class Browser(ApplicationBrowser):
        def _guard_request(self,route):route.fulfill(content_type='text/html',body=source)
    browser=Browser('https://careers.example.com/jobs/5001',purpose='browse',headless=True)
    try:
        session=BrowserSession(browser);initial=session.read()
        hashes=[initial['page_evidence_hash']];observations=[initial]
        for name in ('First region','Second region'):
            latest=session.read()
            region=next(r['ref'] for r in latest['regions'] if r['label']==name)
            scoped=session.read(region_ref=region,observation_id=latest['observation_id'])
            hashes.append(scoped['page_evidence_hash'])
            observations.append(scoped)
        navigation=browser.page.evaluate(SCAN,{'query':'','offset':0,'text_offset':0,'navigation_only':True})
        hashes.append(navigation['page_evidence_hash'])
        assert len(set(hashes))==1
        assert not any(c.get('editable') for c in navigation['controls'])
        # Feed Chrome's real source hashes through the production progress guard.
        from test_remaining_search_runtime import host_for
        host=host_for(career);turn=host.observe()
        for view in observations+[dict(navigation,url=initial['url'],frame_url=initial['frame_url'])]:
            host.after_action({'name':'browser_read','args':{},'id':str(__import__('uuid').uuid4())},view,turn)
        assert career.repository.get(career.state['task_id'])['progress_guard']['count']>=2
        assert 'read_job' in {t['function']['name'] for t in host.observe().tools}
        browser.page.locator('input').fill('Python')
        typed=session.read();assert typed['page_evidence_hash']!=initial['page_evidence_hash']
        browser.page.locator('section').first.locator('p').evaluate("e=>e.append(' New requirement: Rust.')")
        changed=session.read();assert changed['page_evidence_hash']!=typed['page_evidence_hash']
        browser.page.goto('https://careers.example.com/jobs/5002')
        navigated=session.read();assert navigated['page_evidence_hash']!=initial['page_evidence_hash']
        (tmp_path/'source-hash-views.json').write_text(json.dumps({'view_hashes':hashes,'typed':typed['page_evidence_hash'],
            'changed':changed['page_evidence_hash'],'navigated':navigated['page_evidence_hash']},indent=2),encoding='utf-8')
    finally:browser.close()


@pytest.mark.skipif(os.getenv('JOB_AGENT_BROWSER_TESTS')!='1',reason='Offline Chrome opt-in')
@pytest.mark.parametrize('target_mode',['Remote',''])
def test_location_keeps_work_mode_only_from_the_target_header(tmp_path,target_mode):
    from eregion.runtime.auto_apply.browser import ApplicationBrowser
    from eregion.runtime.browser.session import BrowserSession
    from scripts.remaining_search_acceptance import constraints
    source=f'''<main><article><div data-testid="desktop-job-header"><h1>Senior Backend Software Engineer</h1>
    <p>Atlassian</p><p>San Francisco, CA 94104</p><p>{target_mode}</p></div>
    <div class="simple-job-description-html">{TARGET}</div></article>
    <aside><h2>Other company</h2><p>Remote; United States</p></aside></main>'''
    class Browser(ApplicationBrowser):
        def _guard_request(self,route):route.fulfill(content_type='text/html',body=source)
    browser=Browser('https://careers.example.com/jobs/5003',purpose='browse',headless=True)
    try:
        state=BrowserSession(browser).read(job_only=True)
        assert ('Remote' in state['job_location'])==bool(target_mode)
        assert constraints('backend',dict(title=state['primary_heading'],location=state['job_location']))['location']==bool(target_mode)
        assert 'Other company' not in state['text'] and 'United States' not in state['job_header_text']
        (tmp_path/'target-header-location.json').write_text(json.dumps(state,indent=2),encoding='utf-8')
    finally:browser.close()


@pytest.mark.skipif(os.getenv('JOB_AGENT_BROWSER_TESTS')!='1',reason='Offline Chrome opt-in')
def test_existing_alert_filtered_views_do_not_reset_real_taskhost_progress(tmp_path,career):
    from eregion.runtime.auto_apply.browser import ApplicationBrowser
    from eregion.runtime.browser.session import BrowserSession,SCAN
    from eregion.runtime.progress import browser_evidence
    from eregion.runtime.telemetry import outcome_fingerprint
    from test_remaining_search_runtime import host_for
    from uuid import uuid4
    source=f'''<main><article><h1>Senior Backend Engineer</h1>
    <div class="job-description">{TARGET}</div><div role="alert">Existing warning</div></article>
    <section aria-label="Other region"><p>Other public information on this same unchanged page.</p>
    <p>Inspect the company information while keeping the source state stable.</p></section></main>'''
    class Browser(ApplicationBrowser):
        def _guard_request(self,route):route.fulfill(content_type='text/html',body=source)
    browser=Browser('https://careers.example.com/jobs/5004',purpose='browse',headless=True)
    try:
        session=BrowserSession(browser);full=session.read()
        region=next(r['ref'] for r in full['regions'] if r['label']=='Other region')
        scoped=session.read(region_ref=region,observation_id=full['observation_id'])
        navigation=browser.page.evaluate(SCAN,{'query':'','offset':0,'text_offset':0,'navigation_only':True})
        navigation.update(url=full['url'],frame_url=full['frame_url'])
        views=[full,scoped,navigation]
        assert full['errors']==['Existing warning'] and scoped['errors']==navigation['errors']==[]
        assert len({v['page_evidence_hash'] for v in views})==1
        host=host_for(career);turn=host.observe();counts=[]
        for view in views:
            host.after_action({'name':'browser_read','args':{},'id':str(uuid4())},dict(view),turn)
            counts.append(career.repository.get(career.state['task_id'])['progress_guard']['count'])
        assert counts==[0,1,2]
        assert 'read_job' in {t['function']['name'] for t in host.observe().tools}
        fingerprints=[outcome_fingerprint(browser_evidence(v)) for v in views]
        assert len(set(fingerprints))==1
        browser.page.locator('[role=alert]').evaluate("e=>e.textContent='Changed real warning'")
        changed=session.read()
        assert changed['page_evidence_hash']!=full['page_evidence_hash']
        host.after_action({'name':'browser_read','args':{},'id':str(uuid4())},changed,turn)
        assert career.repository.get(career.state['task_id'])['progress_guard']['count']==0
        blocked=dict(changed,blocked='bot_challenge')
        assert outcome_fingerprint(browser_evidence(blocked))!=outcome_fingerprint(browser_evidence(changed))
        (tmp_path/'alert-view-progress.json').write_text(json.dumps(dict(
            source_hashes=[v['page_evidence_hash'] for v in views],errors=[v['errors'] for v in views],
            fingerprints=fingerprints,counts=counts,changed_hash=changed['page_evidence_hash'],
            blocked_fingerprint=outcome_fingerprint(browser_evidence(blocked))),indent=2),encoding='utf-8')
    finally:browser.close()
