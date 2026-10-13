"""Replay the actual final request; synthetic growth is a capacity test only."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from eregion.runtime.career.candidate_health import validate_and_record
from eregion.runtime.career.posting_qualification import PostingRejected
from eregion.runtime.core.context import ConversationWindow
from eregion.runtime.request_context import ContextArchive, encoded, prepare_request
from test_career_flow import career
from test_remaining_candidate_health import rejected_page


FIXTURES=Path(__file__).parent/'fixtures'


def replay_input():
    return json.loads((FIXTURES/'remaining_request_volume.json').read_text(encoding='utf-8'))


def rejection():
    job=json.loads((FIXTURES/'remaining_candidate_recovery.json').read_text(encoding='utf-8'))['jobs'][0]
    state={'chat_revision':0}
    def change(_,update):state.update(update(state))
    with pytest.raises(PostingRejected):validate_and_record(SimpleNamespace(change=change),'offline',job)
    return next(iter(state['candidate_rejections'].values()))


def records(count):
    actual=rejection()
    return [actual if i==0 else {**actual,'url':f'https://careers.example.com/jobs/rejected-{i}',
        'title':f'Synthetic rejected candidate {i}','body_hash':f'{i:064x}',
        'page_evidence_hash':f'source-{i}'} for i in range(count)]


def prepare(f):
    archive=ContextArchive(f['archive_values'],f['archive_reads'],f['archive_resources'])
    messages,metrics=prepare_request(f['prompt'],f['tools'],ConversationWindow(f['groups']),
        f['snapshot'],archive,max_chars=48000)
    return json.loads(messages[-1].content),archive,messages,metrics


def original(archive,ref):
    return json.loads(archive.values[ref])['value']


@pytest.mark.parametrize('count',[1,8,20,58])
def test_real_last_request_with_actual_rejection_and_synthetic_growth(count,tmp_path):
    f=replay_input();before=copy.deepcopy(f)
    excluded=records(count)
    f['snapshot']['known_results']['excluded_candidates']=excluded
    live,archive,messages,metrics=prepare(f)
    assert metrics['request_text_chars']<=48000 and not metrics['protected_overflow']
    assert sum(metrics['request_parts_chars'].values())==metrics['request_text_chars']
    assert metrics['request_text_chars']==sum(len(m.content) for m in messages)+len(encoded(f['tools']))
    for key in ('current_request','candidate','resume_text','browser'):
        assert live[key]==before['snapshot'][key]
    for actual_job,visible_job in zip(before['snapshot']['jobs'],live['jobs'],strict=True):
        for key in ('url','match_score','score_range','qualification_evidence'):
            assert visible_job[key]==actual_job[key]
    assert live['jobs'][0]['match_score']==43.95
    assert live['jobs'][0]['qualification_evidence'][0]['quote']=='0-2 years of marketing or analytics experience'
    recommendations=live['recommended_jobs']
    if isinstance(recommendations,dict):recommendations=original(archive,recommendations['context_ref'])
    assert recommendations==before['snapshot']['recommended_jobs']
    if count==1:
        assert live['known_results']['excluded_candidates']==excluded
    else:
        registry=live['known_results']['excluded_candidate_registry']
        assert registry['count']==count
        assert original(archive,registry['context_ref'])==excluded
        assert len(live['known_results']['excluded_candidates'])==2
    # Every exact already-read range survives; archiving old progress prose is
    # not permission to remove previously fetched source text from the request.
    baseline,_,_,_=prepare(before)
    assert live['context_evidence']==baseline['context_evidence']
    assert [m for m in live['messages'] if m['role']=='user']==[
        m for m in baseline['messages'] if m['role']=='user']
    assert original(archive,live['assistant_progress_history']['context_ref'])
    assert f['snapshot']['known_results']['excluded_candidates']==excluded  # caller not mutated
    (tmp_path/f'request-growth-{count}.json').write_text(json.dumps({
        'scope':'Actual final request with synthetic exclusion capacity growth; not a new real search',
        'exclusion_count':count,'metrics':metrics,'actual_record':excluded[0],
        'retained_job_facts':[{k:job[k] for k in ('url','match_score','qualification_evidence')} for job in live['jobs']],
        'registry_full_exact':True,'source_ranges_unchanged':True},ensure_ascii=False,indent=2),encoding='utf-8')


def test_compacted_older_rejections_still_block_production_preflight_after_new_harness(career):
    from eregion.runtime.career.alerts import job_key
    from eregion.runtime.career.harness import CareerHarness
    c=career;page,calls,_=rejected_page(c)
    excluded=records(58)
    excluded[0]=next(iter(c.repository.get(c.state['task_id'])['candidate_rejections'].values()))
    c.repository.change(c.state['task_id'],candidate_rejections={job_key(r['url']):r for r in excluded})
    f=replay_input();f['snapshot']['known_results']['excluded_candidates']=excluded
    live,_,_,metrics=prepare(f)
    assert len(live['known_results']['excluded_candidates'])==2
    restored=CareerHarness(c.runtime,c.applications,c.repository,discovery=c.harness.discovery,
        fit_service=c.harness.analysis._fit_service)
    restored._browsing=c.harness._browsing
    try:
        for row in (excluded[0],excluded[28],excluded[-1]):
            for name in ('browser_open','read_job','import_job'):
                with pytest.raises(PostingRejected) as caught:
                    restored.execute(c.state['task_id'],name,{'url':row['url']},call_id=str(uuid4()))
                assert caught.value.repeated
        assert len(calls)==1  # no I/O despite older entries no longer shown inline
        assert len(c.repository.get(c.state['task_id'])['candidate_rejections'])==58
        assert not metrics['protected_overflow']
    finally:restored.close()
