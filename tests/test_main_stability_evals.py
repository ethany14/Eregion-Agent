"""Offline scheduler/attribution contracts, never real model stability or gold."""
import copy
import json
from pathlib import Path
from threading import Barrier, Lock

import pytest

from evals import run_main_stability as runner


def dataset():
    return json.loads(Path('evals/fit_labels_v1.json').read_text(encoding='utf-8'))


def runtime():
    return {'cache_signature': 'offline-synthetic-signature', 'typesafe_enabled': False}


def valid_row():
    return {'status': 'completed', 'score': 45, 'requirement_count': 12, 'cache_hits': [],
            'ledger_complete': True, 'signature_unchanged': True, 'timeout_count': 0,
            'scoring_signature': 'offline-synthetic-signature'}


def test_offline_plan_does_not_read_model_configuration_or_claim_pass(monkeypatch):
    monkeypatch.setattr('job_agent.model.dotenv_values', lambda *a: pytest.fail('offline read .env'))
    monkeypatch.setattr(runner, 'cold_service', lambda: pytest.fail('offline created live service'))
    data = dataset(); plan = runner.make_plan(data)
    assert len(plan['trials']) == 288+32
    assert len(plan['pending_human_reviews']) == 96
    for pair in data['pairs']:
        rows = [t for t in plan['trials'] if t['pair_id'] == pair['pair_id'] and t['lane'] == 'cold4']
        assert len(rows) == 4 and len({(t['resume_sha256'],t['body_sha256']) for t in rows}) == 1
    result = runner.report(plan, [], 0)
    assert result['status'] == 'not_passed' and result['human_quality_metrics'] is None
    assert result['cold4_spread_check'] is False and result['stress32_check'] is False


def test_real_six_worker_dispatch_records_all_32_including_failure_and_timeout(tmp_path):
    data=dataset();plan=runner.make_plan(data,suite='stress32',runtime=runtime())
    barrier=Barrier(6,timeout=8);seen=[];lock=Lock()
    def trial(t,*_):
        with lock: seen.append(t['trial_id'])
        if t['repeat'] < 6: barrier.wait()
        if t['repeat'] == 7: raise TimeoutError('synthetic secret payload must not persist')
        if t['repeat'] == 8: raise ValueError('synthetic invalid output')
        return valid_row()
    out=tmp_path/'32';result=runner.execute_plan(plan,data,out,trial)
    rows=[json.loads(s) for s in (out/'trials.jsonl').read_text().splitlines()]
    assert len(seen)==len(set(seen))==len(rows)==32
    assert result['peak_active_trials']==6 and result['timeout_events']==1
    assert len(result['failed_trials'])==2 and result['stress32_check'] is False
    assert result['status']=='not_passed' and 'secret payload' not in (out/'trials.jsonl').read_text()
    with pytest.raises(FileExistsError): runner.execute_plan(plan,data,out,trial)
    historical=runner.evaluate_run(out)
    assert historical['peak_active_trials']==6 and historical['timeout_events']==1
    assert historical['status']=='not_passed' and historical['observed_trials']==32


def test_four_equivalent_cold_inputs_spread_and_requirement_count_not_truncated(tmp_path):
    data=dataset();plan=runner.make_plan(data,suite='cold4',runtime=runtime())
    seen=[]
    def trial(t,plan,data,out):
        seen.append((t['resume_sha256'],t['body_sha256'],plan['manifest_sha256']))
        return {**valid_row(),'score':40+3*t['repeat'], 'requirement_count':31 if t['repeat']==3 else 12}
    result=runner.execute_plan(plan,data,tmp_path/'cold',trial)
    assert len(seen)==288 and len(set(seen))==72
    assert result['status']=='not_passed' and result['cold4_spread_check'] is False
    rows=[json.loads(s) for s in (tmp_path/'cold'/'trials.jsonl').read_text().splitlines()]
    assert max(r['requirement_count'] for r in rows)==31
    # Even with valid counts, a nine point spread cannot pass.
    for r in rows:r['requirement_count']=12
    assert runner.report(plan,rows,4)['cold4_spread_check'] is False
    rows[-1]['scoring_signature']='old-model-version'
    assert runner.report(plan,rows,4)['status']=='not_passed'
    rows[-1]['manifest_sha256']='old-run'
    assert runner.report(plan,rows,4)['integrity'] is False
    assert runner.report(plan,rows[:3],3)['status']=='not_passed'


def test_real_fit_service_cold_isolation_and_sqlite_usage_with_offline_provider(tmp_path,monkeypatch):
    from api.db import create_database
    from api.services.fit_analysis_service import FitAnalysisService
    from custom_agent.handlers import JobAgentStepHandler
    from agent_runtime.fast_decisions import FastDecisions
    from agent_runtime.provider_usage import provider_call
    from job_agent.schemas import SkillAssessment
    from test_speed_pipeline import Analyzer
    factories=[]
    class OfflineProvider(Analyzer):
        chunked_matching=True
        def __init__(self):super().__init__();self.failed=False
        def __call__(self,schema,*args):
            with provider_call('offline-synthetic-provider') as usage:
                usage.update(input_tokens=10,output_tokens=5)
                if schema is SkillAssessment and not self.failed:
                    self.failed=True
                    raise TimeoutError('synthetic timeout retained in ledger')
                return super().__call__(schema,*args)
    def factory():
        a=OfflineProvider();factories.append(a)
        return FitAnalysisService(JobAgentStepHandler(analyzer=a,decisions=FastDecisions(),analysis_cache=None),
                                  cache_size=0,jev_enabled=False)
    monkeypatch.setattr(runner,'cold_service',factory)
    data=dataset();signature=factory().cache_signature()
    plan=runner.make_plan(data,suite='cold4',runtime={'cache_signature':signature})
    db=create_database('sqlite:///'+(tmp_path/'usage.db').as_posix(),create_schema_for_tests=True)
    try:
        rows=[runner.live_trial(t,plan,data,db.session_factory) for t in plan['trials'][:4]]
        assert len(factories)==5  # preflight plus FOUR genuinely fresh handlers/services
        assert all(r['status']=='completed' and r['cache_hits']==[] for r in rows)
        assert all(r['ledger_complete'] and r['usage']['calls']==4 for r in rows)
        assert all(r['usage']['failed']==1 and r['usage']['retries']==1 and r['timeout_count']==1 for r in rows)
        assert all(r['usage']['input_tokens']==40 and r['usage']['output_tokens']==20 for r in rows)
        assert len({r['task_id'] for r in rows})==4 and len({r['score'] for r in rows})==1
    finally:db.close()


def test_changed_input_or_threshold_rejects_before_dispatch(tmp_path):
    data=dataset();plan=runner.make_plan(data)
    for changed in ('resume','threshold'):
        p,d=copy.deepcopy(plan),copy.deepcopy(data)
        if changed=='resume':d['applicants'][0]['resume']+=' changed'
        else:p['thresholds']['spread_max']=13
        with pytest.raises(ValueError):runner.execute_plan(p,d,tmp_path/changed,lambda *_:pytest.fail('called'))
        assert not (tmp_path/changed).exists()


def test_factory_is_main_only_and_no_result_or_persistent_cache():
    one,two=runner.cold_service(),runner.cold_service()
    assert one is not two and one._cache is not two._cache
    assert one._cache.limit==two._cache.limit==0 and one._analysis_cache is None
    assert one._handler.analysis_cache is None and not one._handler._decisions.enabled
    assert not one.uses_jev()


def test_live_configuration_gate_keeps_180_seconds_and_sdk_retry_zero(monkeypatch):
    monkeypatch.setattr(runner,'cold_service',lambda:type('Service',(),{'cache_signature':lambda _: 'frozen'})())
    settings={'model':'synthetic-main','temperature':0,'timeout':179,'max_retries':0,'reasoning_effort':'high'}
    monkeypatch.setattr('job_agent.model.create_model',lambda **_:dict(settings))
    with pytest.raises(ValueError):runner.live_runtime()
    settings['timeout']=180;settings['max_retries']=1
    with pytest.raises(ValueError):runner.live_runtime()
    settings['max_retries']=0
    assert runner.live_runtime()['reasoning']=='high'


def test_recovered_timeout_and_warm_cache_cannot_be_green():
    data=dataset();plan=runner.make_plan(data,suite='stress32',runtime=runtime())
    rows=[{**valid_row(),'trial_id':t['trial_id'],'input_sha256':runner.digest(t),
        'manifest_sha256':plan['manifest_sha256']} for t in plan['trials']]
    assert runner.report(plan,rows,6)['stress32_check'] is True  # synthetic contract only
    rows[0]['timeout_count']=1
    assert runner.report(plan,rows,6)['stress32_check'] is False
    rows[0]['cache_hits']=['job']
    assert runner.report(plan,rows,6)['status']=='not_passed'
    rows[0]['cache_hits']=[];rows[0]['ledger_complete']=False
    assert runner.report(plan,rows,6)['status']=='not_passed'
