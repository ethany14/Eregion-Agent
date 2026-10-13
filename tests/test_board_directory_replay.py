"""New directory recovery lane; original B6 replay and archive remain unchanged.

Directory metadata is synthetic TEST ONLY. Board bodies reuse frozen responses;
only the positive board's link list also projects the recorded GoodApple posting.
No synthetic directory entry is shipped in production.
"""
import copy
import json
from datetime import UTC, datetime

from test_b6_offline_replay import frozen_web, offline_guard, replay
from test_career_flow import career
from eregion.runtime.career import board_directory


def install(monkeypatch, frozen_web, include_synthetic):
    boards=copy.deepcopy(frozen_web['replays']['r3']['steps'][0]['arguments']['boards'])
    if include_synthetic:boards.append(frozen_web['synthetic']['board'])
    rows=[{**b,'display_name':'Synthetic test directory metadata', 'domains':['data/analytics'],
        'locations':['New York, NY'], 'source_url':'https://example.com/test-only',
        'verified_at':datetime.now(UTC).date().isoformat(), 'verified_by':'public_api_get',
        'job_count_at_verification':0, 'notes':'Synthetic fixture metadata, NOT a real verification.'} for b in boards]
    monkeypatch.setattr(board_directory,'load_directory',lambda:rows)


def test_directory_blocked_recovery_two_qualified(replay, frozen_web, monkeypatch):
    install(monkeypatch,frozen_web,True)
    steps=copy.deepcopy(frozen_web['replays']['correct']['steps'])
    steps[1]['arguments'].pop('boards');steps[1]['arguments']['use_directory']=True
    # Test-only projection of an already recorded qualifying posting into a board
    # link list. Posting evidence/scoring still comes from the unchanged archive.
    response=frozen_web['responses']['https://boards-api.greenhouse.io/v1/boards/b6synthetic/jobs']
    body=json.loads(response['body'])
    body['jobs'].append({'absolute_url':steps[2]['arguments']['url'],'title':'Junior Data Analyst',
                        'location':{'name':'New York, NY'}})
    response['body']=json.dumps(body)
    steps.insert(2,copy.deepcopy(steps[1]))  # Same directory identities cannot advance discovery.
    frozen_web['replays']['directory-positive']={'steps':steps}
    result=replay('directory-positive')
    assert result.state['status']=='completed'
    assert result.acceptance['status']=='passed',result.acceptance
    assert result.acceptance['qualified_count']==2
    assert 'linkedin' in result.summary['final'].lower() and 'blocked' in result.summary['final'].lower()
    assert result.summary['provider_usage']['calls']==0
    assert len(result.state['search_candidates'])==2
    searches=[h for h in result.state['history'] if h['tool']=='search_jobs']
    assert searches[1]['result']['no_new_evidence']
    assert any(h['arguments'].get('use_directory') for h in result.state['history'] if h['tool']=='search_jobs')


def test_directory_only_nonqualifying_finishes_honestly(replay, frozen_web, monkeypatch):
    install(monkeypatch,frozen_web,False)
    blocked=copy.deepcopy(frozen_web['replays']['correct']['steps'][0])
    search=copy.deepcopy(frozen_web['replays']['r3']['steps'][0])
    search['arguments'].pop('boards');search['arguments']['use_directory']=True
    finish={'tool':'finish_task','arguments':{'text':'LinkedIn was blocked by login. Company boards provided no verified qualifying junior data analyst jobs. Ramp and Plaid reads failed. The requested two recommendations remain incomplete; source coverage is limited. No applications or schedules.'}}
    frozen_web['replays']['directory-negative']={'steps':[blocked,search,finish]}
    result=replay('directory-negative')
    assert result.state['status']=='completed',result.state['history']
    assert not result.state.get('recommendations')
    assert result.acceptance['qualified_count']==0
    assert result.acceptance['failures']==['fewer_than_two_verified_scored_qualifying_recommendations']
    assert result.summary['provider_usage']['calls']==0
