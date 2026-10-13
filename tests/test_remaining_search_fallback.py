import base64
from urllib.parse import parse_qs

import httpx
from test_career_flow import career,execute

from eregion.runtime.career.discovery import JobDiscovery


def test_duckduckgo_challenge_is_a_blocked_source_and_bing_links_are_unwrapped():
    requests=[]
    target='https://jobs.lever.co/example/posting-one'
    encoded=base64.urlsafe_b64encode(target.encode()).decode().rstrip('=')
    def handle(request):
        requests.append(request)
        if request.url.host=='html.duckduckgo.com':
            return httpx.Response(200,text='<title>DuckDuckGo</title><form id="challenge-form">Unfortunately bots use DuckDuckGo too</form>')
        assert request.url.host=='www.bing.com'
        return httpx.Response(200,text=f'<a href="https://www.bing.com/ck/a?u=a1{encoded}">Junior Data Analyst</a>')
    discovery=JobDiscovery(transport=httpx.MockTransport(handle),resolver=lambda *a,**k:[(None,None,None,None,('8.8.8.8',443))])
    result=discovery.search('junior data analyst','New York',excluded_hosts=['www.linkedin.com'])
    assert len(requests)==2 and result['jobs'][0]['url']==target
    assert result['errors'][0]['blocked'] is True
    assert '-site:www.linkedin.com' in parse_qs(requests[1].url.query.decode())['q'][0]
    assert 'Read each result' in result['note']


def test_empty_results_have_source_evidence_instead_of_implying_no_vacancies():
    discovery=JobDiscovery(transport=httpx.MockTransport(lambda _:httpx.Response(200,text='<title>Search</title>')),
        resolver=lambda *a,**k:[(None,None,None,None,('8.8.8.8',443))])
    result=discovery.search('data analyst')
    assert result['jobs']==[] and len(result['errors'])==2
    assert all(e['error']=='no_extracted_results' for e in result['errors'])


def test_first_query_word_dictionary_or_senior_living_is_not_a_job_candidate():
    discovery=JobDiscovery(transport=httpx.MockTransport(lambda _:httpx.Response(200,text=
        '<a href="https://dictionary.example.com/junior">Junior definition</a>'
        '<a href="https://living.example.com/senior">Senior living</a>')),
        resolver=lambda *a,**k:[(None,None,None,None,('8.8.8.8',443))])
    for query in ('junior data analyst','senior backend engineer'):
        result=discovery.search(query)
        assert result['jobs']==[] and len(result['errors'])==2
        assert 'already authorized' in result['note']


def test_blocked_and_repeated_empty_engines_are_not_retried_for_every_query_or_restart(career):
    from eregion.runtime.career.harness import CareerHarness
    c=career;requests=[]
    def handle(request):
        requests.append(request.url.host)
        return httpx.Response(200,text='<form id="challenge-form">Blocked</form>' if request.url.host=='html.duckduckgo.com' else '<title>Search</title>')
    discovery=JobDiscovery(transport=httpx.MockTransport(handle),resolver=lambda *a,**k:[(None,None,None,None,('8.8.8.8',443))])
    c.harness.discovery=discovery
    for query in ('junior data analyst','entry level data analyst','data analyst'):
        result=execute(c,'search_jobs',query=query,location='New York, NY')
        assert not result['jobs']
    assert requests.count('html.duckduckgo.com')==1
    assert requests.count('www.bing.com')==2
    assert result['skipped_sources']
    fresh=CareerHarness(c.runtime,c.applications,c.repository,discovery=discovery)
    fresh.execute(c.state['task_id'],'search_jobs',{'query':'analyst entry level','location':'New York, NY'},call_id='restart-source-test')
    assert len(requests)==3
    # A new user turn can explicitly retry changed external conditions.
    c.repository.append(c.state['task_id'],role='user',text='Retry the search now.')
    c.repository.change(c.state['task_id'],chat_revision=1)
    execute(c,'search_jobs',query='data analyst',location='New York, NY')
    assert len(requests)==5


def test_public_board_city_state_aliases_preserve_ny_and_reject_pa():
    items=[{'title':'Junior Data Analyst','absolute_url':f'https://careers.example.com/{i}',
        'location':{'name':location}} for i,location in enumerate(
        ('New York, New York, USA','New York City, NY','Albany, New York, USA','York, PA','New York, PA'))]
    discovery=JobDiscovery(transport=httpx.MockTransport(lambda _:httpx.Response(200,json={'jobs':items})),
        resolver=lambda *a,**k:[(None,None,None,None,('8.8.8.8',443))])
    result=discovery.search('junior data analyst','New York, NY',boards=[{'platform':'greenhouse','company':'synthetic'}])
    assert [j['url'] for j in result['jobs']]==['https://careers.example.com/0','https://careers.example.com/1']


def test_city_suffix_is_not_removed_from_unrelated_place_names():
    from eregion.runtime.career.discovery import location_matches
    assert location_matches('Kansas City, MO','Kansas City, Missouri, USA')
    assert not location_matches('Kansas, MO','Kansas City, Missouri, USA')


def test_bare_matching_city_remains_a_candidate_without_inventing_a_state():
    discovery=JobDiscovery(transport=httpx.MockTransport(lambda _:httpx.Response(200,json={'jobs':[
        {'title':'Junior Data Analyst','absolute_url':f'https://careers.example.com/{i}',
         'location':{'name':name}} for i,name in enumerate(('New York','Albany','York, PA'))]})),
        resolver=lambda *a,**k:[(None,None,None,None,('8.8.8.8',443))])
    result=discovery.search('junior data analyst','New York, NY',boards=[{'platform':'greenhouse','company':'synthetic'}])
    assert len(result['jobs'])==1 and result['jobs'][0]['location']=='New York'
