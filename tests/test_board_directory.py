"""Directory mechanism and HTTP safety tests; all transport is offline."""
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from agent_runtime.career import board_directory as directory
from agent_runtime.career.discovery import JobDiscovery, DiscoveryCancelled
from agent_runtime.career.source_health import record_board_outcomes, active_sources
from scripts.verify_board_directory import refresh
from test_career_flow import career


@pytest.fixture(autouse=True)
def no_analysis_warmup(monkeypatch):
    # Career fixture saves a resume; disable background provider warmup before
    # its setup, not only when the later replay installs the IO guard.
    monkeypatch.setenv('JOB_AGENT_ANALYSIS_WARMUP', '0')


def entry(**changes):
    return dict(platform='greenhouse', company='synthetic', display_name='Synthetic test only',
        domains=['data/analytics'], locations=['New York, NY'],
        source_url='https://job-boards.greenhouse.io/synthetic',
        verified_at=datetime.now(UTC).date().isoformat(), verified_by='public_api_get',
        job_count_at_verification=1, notes='Synthetic metadata, test only.', **changes)


def discovery(handler):
    return JobDiscovery(transport=httpx.MockTransport(handler),
        resolver=lambda *a, **k: [(None,None,None,None,('8.8.8.8',443))])


def test_schema_stale_and_matching(tmp_path, monkeypatch):
    row=entry()
    path=tmp_path/'boards.json'; path.write_text(json.dumps([row]))
    assert directory.load_directory(path)==[row]
    assert directory.select_boards('junior data analyst','NYC',entries=[row])[0]==[row]
    assert not directory.select_boards('backend engineer','NYC',entries=[row])[0]
    assert not directory.select_boards('data analyst','Austin, TX',entries=[row])[0]
    monkeypatch.setenv('JOB_AGENT_BOARD_DIRECTORY_MAX_AGE_DAYS','1')
    selected, stale=directory.select_boards('data analyst','NYC',entries=[row],today=datetime.now(UTC).date()+timedelta(days=2))
    assert not selected and stale==['ats:greenhouse:synthetic']
    for invalid in ({**row,'verified_by':'guess'}, {**row,'company':'../bad'}, {**row,'job_count_at_verification':-1}):
        path.write_text(json.dumps([invalid]))
        with pytest.raises(ValueError):directory.load_directory(path)
    path.write_text(json.dumps([row,row]))
    with pytest.raises(ValueError,match='Duplicate'):directory.load_directory(path)


def test_client_reused_and_closed_redirect_safety():
    d=discovery(lambda r: httpx.Response(200,text='ok'))
    d.read('https://example.com/a'); client=d._client
    d.read('https://example.com/b'); assert d._client is client
    assert not client.is_closed
    d.close(); assert client.is_closed
    d=discovery(lambda r:httpx.Response(302,headers={'location':'https://127.0.0.1/private'}))
    with pytest.raises(ValueError):d.read('https://example.com/a')
    d.close()


def test_per_host_spacing_and_concurrency(monkeypatch):
    monkeypatch.setenv('JOB_AGENT_BOARD_MIN_INTERVAL_SECONDS','.02')
    starts=[]; active=0; peak=0; lock=threading.Lock()
    def serve(request):
        nonlocal active, peak
        with lock:starts.append(time.monotonic());active+=1;peak=max(peak,active)
        time.sleep(.005)
        with lock:active-=1
        return httpx.Response(200,json={'jobs':[]})
    d=discovery(serve)
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda i:d.read(f'https://boards-api.greenhouse.io/v1/boards/b{i}/jobs'),range(6)))
    assert peak==1
    assert all(b-a>=.018 for a,b in zip(starts,starts[1:]))
    d.close()


def test_cancel_stops_directory_before_next_board(monkeypatch):
    boards=[{**entry(),'company':f'test{i}'} for i in range(3)]
    monkeypatch.setattr(directory,'load_directory',lambda:boards)
    calls=[]
    d=discovery(lambda r:(calls.append(str(r.url)) or httpx.Response(200,json={'jobs':[]})))
    result=d.search_directory('data analyst','New York, NY',cancelled=lambda:bool(calls))
    assert len(calls)==1 and result['cancelled']
    d.close()


def test_health_across_turns_and_refresh():
    result={'errors':[{'source':'ats:greenhouse:synthetic','error':'HTTPStatusError','http_status':404}]}
    sources,history=record_board_outcomes({}, {}, result, 'one')
    assert sources['ats:greenhouse:synthetic']['http_status']==404
    assert history['ats:greenhouse:synthetic']['refresh_required']
    state={'user_turn_id':'two','search_source_health':{'user_turn_id':'one','sources':sources,'history':history}}
    assert active_sources(state)=={}
    sources,history=record_board_outcomes({},history,result,'two')
    assert history['ats:greenhouse:synthetic']['consecutive_errors']==2
    assert history['ats:greenhouse:synthetic']['timestamp']
    d=discovery(lambda r:httpx.Response(404))
    rows,report=refresh([entry()],d,history)
    assert rows[0]['verified_at']==entry()['verified_at']
    assert report[0]['status']=='refresh_required' and report[0]['health_flagged']
    d.close()
    sources,history=record_board_outcomes(sources,history,{'board_outcomes':[{'source':'ats:greenhouse:synthetic','status':'success'}]},'three')
    assert not history['ats:greenhouse:synthetic']['refresh_required']


def test_location_does_not_match_incidental_ca_or_us():
    assert not directory.location_covered('California', 'Chicago, IL')
    assert directory.location_covered('California', 'San Francisco, CA')
    assert not directory.location_covered('remote-US', 'Remote, Australia')
    assert directory.location_covered('remote-US', 'Remote, United States')


def test_three_api_requests_max_across_hosts(monkeypatch):
    monkeypatch.setenv('JOB_AGENT_BOARD_MIN_INTERVAL_SECONDS','0')
    active=0; peak=0; lock=threading.Lock()
    def serve(request):
        nonlocal active, peak
        with lock:active+=1;peak=max(peak,active)
        time.sleep(.03)
        with lock:active-=1
        return httpx.Response(200,json={'jobPostings':[]})
    d=discovery(serve)
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda i:d.read(f'https://tenant{i}.wd1.myworkdayjobs.com/wday/cxs/tenant{i}/site/jobs'),range(6)))
    assert peak==3
    d.close()


def test_health_failure_threshold_resets_after_success():
    failure={'errors':[{'source':'ats:greenhouse:synthetic','error':'ConnectError'}]}
    sources,history=record_board_outcomes({}, {}, failure, 'one')
    sources,history=record_board_outcomes(sources, history, failure, 'one')
    assert sources['ats:greenhouse:synthetic']['error_count']==2
    assert history['ats:greenhouse:synthetic']['refresh_required']


def test_directory_deduplicates_tracking_variants(monkeypatch):
    monkeypatch.setattr(directory,'load_directory',lambda:[entry(),{**entry(),'company':'second'}])
    def serve(request):
        url='https://job-boards.greenhouse.io/synthetic/jobs/1'
        if 'second' in str(request.url):url+='?gh_src=tracking'
        return httpx.Response(200,json={'jobs':[{'absolute_url':url,'title':'Junior Data Analyst','location':{'name':'New York, NY'}}]})
    d=discovery(serve)
    result=d.search_directory('junior data analyst','New York, NY')
    assert len(result['jobs'])==1
    assert len(result['sources_checked'])==2
    d.close()


def test_refresh_updates_metadata_from_get():
    requests=[]
    def serve(request):
        requests.append(request)
        return httpx.Response(200,json={'jobs':[{'title':'Backend Engineer','location':{'name':'Austin, TX'}},
            {'title':'Senior Backend Engineer','location':{'name':'Austin, TX'}},
            {'title':'Data Center Technician','location':{'name':'Dallas, TX'}}]})
    d=discovery(serve)
    rows,report=refresh([entry()],d)
    assert requests[0].method=='GET'
    assert rows[0]['job_count_at_verification']==3
    # One incidental title ("Data Center ...") is not data/analytics coverage.
    assert rows[0]['domains']==['backend'] and rows[0]['family_locations']=={'backend':['Austin, TX']}
    assert rows[0]['locations']==['Austin, TX','Dallas, TX']
    assert report[0]['status']=='verified'
    d.close()


def test_reuse_never_resends_server_cookies():
    requests=[]
    def serve(request):
        requests.append(request)
        return httpx.Response(200,text='public',headers={'set-cookie':'tracking=secret; Path=/'})
    d=discovery(serve)
    d.read('https://example.com/first'); d.read('https://example.com/next')
    assert all('cookie' not in r.headers for r in requests)
    d.close()


def test_redirect_to_private_dns_never_requested():
    requests=[]
    def serve(request):
        requests.append(str(request.url))
        return httpx.Response(302,headers={'location':'https://private.example/private'})
    d=discovery(serve)
    d.resolver=lambda host,*a,**k:[(None,None,None,None,('127.0.0.1' if host=='private.example' else '8.8.8.8',443))]
    with pytest.raises(ValueError,match='public internet'):d.read('https://example.com/')
    assert requests==['https://example.com/']
    d.close()


def test_stale_directory_never_falls_back_to_public_search(monkeypatch):
    row={**entry(),'verified_at':'2020-01-01'}
    monkeypatch.setattr(directory,'load_directory',lambda:[row])
    d=discovery(lambda r:pytest.fail('Stale directory must not initiate HTTP'))
    result=d.search_directory('data analyst','New York, NY')
    assert not result['jobs'] and result['stale_boards']==['ats:greenhouse:synthetic']
    d.close()


def test_explicit_boards_observe_cancellation():
    calls=[]
    d=discovery(lambda r:(calls.append(str(r.url)) or httpx.Response(200,json={'jobs':[]})))
    with d.cancellation(lambda:bool(calls)):
        with pytest.raises(DiscoveryCancelled):
            d.search('data analyst',boards=[entry(),{**entry(),'company':'second'}])
    assert len(calls)==1
    # Context-local cancellation is reset; it cannot cancel another task.
    assert d.search('data analyst',boards=[entry()])['jobs']==[]
    d.close()


def test_harness_404_excluded_for_turn_and_history_survives(career, monkeypatch):
    from test_career_flow import execute
    monkeypatch.setattr(directory,'load_directory',lambda:[entry()])
    calls=[]
    d=discovery(lambda r:(calls.append(str(r.url)) or httpx.Response(404)))
    career.harness.discovery=d
    execute(career,'search_jobs',query='data analyst',location='New York, NY',use_directory=True,boards=[])
    second=execute(career,'search_jobs',query='junior data analyst',location='New York, NY',use_directory=True)
    assert len(calls)==1
    assert second['skipped_sources']==['ats:greenhouse:synthetic']
    state=career.repository.get(career.state['task_id'])
    assert state['search_source_health']['history']['ats:greenhouse:synthetic']['refresh_required']
    d.close()


def test_refresh_empty_board_certifies_zero_without_old_coverage():
    d=discovery(lambda r:httpx.Response(200,json={'jobs':[]}))
    rows,report=refresh([entry()],d)
    assert rows[0]['job_count_at_verification']==0
    assert rows[0]['domains']==[] and rows[0]['locations']==[]
    assert report[0]['status']=='verified'
    assert directory.select_boards('data analyst','New York, NY',entries=rows)==([],[])
    d.close()



def test_board_search_cancellation_check_is_throttled(career):
    # Review: the cancellation probe loaded the whole task state once per downloaded
    # chunk; a large board response meant hundreds of repository reads.
    from uuid import uuid4
    from agent_runtime.career.discovery import JobDiscovery
    c = career
    class Discovery(JobDiscovery):
        def search_directory(self, query, location='', limit=10, *, cancelled, **_):
            for _ in range(300):
                assert cancelled() is False
            return {'jobs': [], 'errors': [], 'sources_checked': [], 'skipped_sources': [], 'board_outcomes': []}
    c.harness.discovery = Discovery()
    reads = []
    original = c.repository.get
    c.repository.get = lambda task_id: reads.append(task_id) or original(task_id)
    c.harness.execute(c.state['task_id'], 'search_jobs',
        {'query': 'junior data analyst', 'location': 'New York, NY', 'use_directory': True}, call_id=str(uuid4()))
    assert len(reads) < 30  # was ~300 polls -> ~300 full state loads


def test_family_location_coverage_and_ranking():
    from agent_runtime.career.board_directory import select_boards
    base={'platform':'greenhouse','display_name':'X','verified_at':'2026-10-10','verified_by':'public_api_get',
          'job_count_at_verification':5,'notes':'test','source_url':'https://job-boards.greenhouse.io/x'}
    paris={**base,'company':'paris','domains':['data/analytics','backend'],'locations':['Paris, France','New York, NY'],
           'family_locations':{'data/analytics':['Paris, France'],'backend':['New York, NY']}}
    one={**base,'company':'one','domains':['data/analytics'],'locations':['New York, NY'],
         'family_locations':{'data/analytics':['New York, NY']}}
    many={**base,'company':'many','domains':['data/analytics'],'locations':['New York, NY','New York, NY; Remote'],
          'family_locations':{'data/analytics':['New York, NY','New York, NY; Remote']}}
    selected,_=select_boards('data analyst','New York, NY',entries=[paris,one,many],today=__import__('datetime').date(2026,10,11))
    # Data roles only in Paris do not make a board cover "data analyst, NYC"; most coverage first.
    assert [b['company'] for b in selected]==['many','one']


def test_repeated_directory_search_pages_to_next_boards(career):
    # Paid P1: 30 boards matched "data analyst, NYC" but every repeat searched the same
    # top five, so the agent saw one posting six times and hit the no-progress stop.
    from uuid import uuid4
    from agent_runtime.career import board_directory
    from agent_runtime.career.discovery import JobDiscovery, board_source
    c = career
    base = {'platform': 'greenhouse', 'display_name': 'X', 'verified_at': __import__('datetime').date.today().isoformat(),
            'verified_by': 'public_api_get', 'job_count_at_verification': 3, 'notes': 't', 'domains': ['data/analytics'],
            'locations': ['New York, NY'], 'family_locations': {'data/analytics': ['New York, NY']}}
    rows = [{**base, 'company': f'b{i}', 'source_url': f'https://job-boards.greenhouse.io/b{i}'} for i in range(12)]
    searched = []
    class Discovery(JobDiscovery):
        def search(self, query, location='', boards=None, limit=10, excluded_hosts=(), excluded_sources=()):
            searched.append(board_source(boards[0]))
            return {'jobs': [], 'errors': [], 'sources_checked': [], 'skipped_sources': [], 'board_outcomes': []}
    import pytest
    mp = pytest.MonkeyPatch()
    mp.setattr(board_directory, 'load_directory', lambda path=None: rows)
    try:
        c.harness.discovery = Discovery()
        args = {'query': 'junior data analyst', 'location': 'New York, NY', 'use_directory': True}
        first = c.harness.execute(c.state['task_id'], 'search_jobs', args, call_id=str(uuid4()))
        second = c.harness.execute(c.state['task_id'], 'search_jobs', args, call_id=str(uuid4()))
        third = c.harness.execute(c.state['task_id'], 'search_jobs', args, call_id=str(uuid4()))
        fourth = c.harness.execute(c.state['task_id'], 'search_jobs', args, call_id=str(uuid4()))
    finally:
        mp.undo()
    assert searched == [f'ats:greenhouse:b{i}' for i in range(12)]
    assert first['directory_remaining'] == 7 and second['directory_remaining'] == 2 and third['directory_remaining'] == 0
    assert fourth['directory_searched'] == [] and 'note_exhausted' in fourth
