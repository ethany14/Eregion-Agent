"""Opt-in paid production batch performance; synthetic workload, real providers."""
import json
import os
import re
import time
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from test_career_flow import career
from remaining_batch_contract import resolver_coverage

pytestmark=pytest.mark.skipif(os.getenv('JOB_AGENT_LIVE_BATCH')!='1',reason='Explicit real-provider batch performance opt-in')


def test_eight_job_production_cold_resolver_and_persistent_warm(career,tmp_path,monkeypatch):
    from eregion.api.db import create_database
    from eregion.api.services.fit_analysis_service import FitAnalysisService
    from eregion.runtime.auto_apply.loop import ApplicationLoop
    from eregion.runtime.auto_apply.repository import ApplyRepository
    from eregion.runtime.career.harness import CareerHarness
    from eregion.runtime.career.repository import TaskRepository
    from eregion.runtime.evidence.repository import CareerEvidenceRepository
    from eregion.runtime.workspace.repository import JobWorkspaceRepository
    from eregion.runtime.provider_usage import UsageLedger, usage_scope
    from eregion.domain.jev_fit.settings import Settings
    from eregion.domain.pdf_rendering import render_letter_pdf
    from scripts.e2e_repair_evaluation import APPLICANTS
    from test_auto_apply import FakeBrowser
    import eregion.domain.model as model
    import eregion.domain.jev_fit.resolve as resolver

    c=career
    c.applications.repository.save_candidate({'first_name':'Synthetic','last_name':'Batch','email':'batch@example.com'},
        resume=render_letter_pdf(APPLICANTS['analyst']),name='synthetic.pdf',extracted=True)
    config=replace(Settings.load(cache_path=tmp_path/'cold-decisions.sqlite3'),resolve_unknowns=True)
    calls=[];real_invoke=model.invoke_structured
    def traced_invoke(provider,schema,system,human):
        started=time.perf_counter()
        entry={'schema':schema.__name__,'primary_wire_ids':re.findall(r'^- (\S+) \[',human,re.M),
            'wire_ids':list(dict.fromkeys(re.findall(r'\bjob\d+:j\d+\b',human)))}
        calls.append(entry)
        try:
            result=real_invoke(provider,schema,system,human)
            entry['decisions']=[d.model_dump(mode='json') for d in result.decisions]
            return result
        finally:entry['wall_seconds']=time.perf_counter()-started
    monkeypatch.setattr(model,'invoke_structured',traced_invoke)
    batches=[];real_batch=resolver.resolve_unknowns_many
    def traced_batch(raws,evidence,**kwargs):
        before=deepcopy(raws)
        result=real_batch(raws,evidence,**kwargs)
        batches.append(resolver_coverage(before,result,calls,evidence))
        return result
    monkeypatch.setattr(resolver,'resolve_unknowns_many',traced_batch)
    captures=[]
    def fit():
        service=FitAnalysisService(jev_enabled=True,jev_config=config)
        actual=service.analyze_many
        async def capture(**kwargs):
            results=await actual(**kwargs)
            captures.append({key:{'main_model_calls':value.main_model_calls,'fast_model_calls':value.fast_model_calls,
                'routing':value.decision_routing,'score':value.skill_match.overall_score,
                'matches':[{'id':m.requirement_id,'status':m.match_status} for m in value.skill_match.matches]}
                for key,value in results.items()})
            return results
        service.analyze_many=capture
        return service
    c.harness.analysis._fit_service=fit()
    ids=[]
    for index in range(8):
        jd=(f'Synthetic Data Analyst {index}\nProduct team {index}, New York, NY\nRequirements:\n'
            'Collaborate with internal teams to translate business needs into measurement plans and data flows.\n'
            'Create clean, effective, actionable presentations for clients and internal teams.\n'
            "Bachelor's Degree with 3.0 or higher GPA or equivalent work experience.\n"
            '0-2 years of marketing or analytics experience.\n'
            'Excellent analytical skills and clear communication of results to a non-technical audience.\n'
            'Programming experience, Python in particular, is a plus.\n')
        saved=c.runtime.workspace.save_workspace(cleaned_job_description=jd,
            source_url=f'https://careers.example.com/performance/{index}',title=f'Synthetic Data Analyst {index}')
        identifier=saved.application.application_id
        ids.append(identifier);c.repository.link(c.state['task_id'],'jobs',identifier)
    evidence={'entrance':'CareerHarness.execute(score_jobs)','workload':'8 synthetic saved jobs, real Jev and main resolver',
        'cold_cache_existed_before':config.cache_path.exists(),'limit_cold_seconds':60,'status':'running'}
    destination=tmp_path/'eight-production-cold-warm.json'
    def save():destination.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    save();started=time.perf_counter()
    try:
        with usage_scope(ledger=UsageLedger(c.repository.sessions),task_id=c.state['task_id'],purpose='score_jobs'):
            cold=c.harness.execute(c.state['task_id'],'score_jobs',{'application_ids':ids},call_id=str(uuid4()))
    except Exception as exc:
        evidence.update(status='failed',error=type(exc).__name__,cold_wall_seconds=time.perf_counter()-started,calls=calls)
        evidence['usage']=UsageLedger(c.repository.sessions).summary(task_id=c.state['task_id'])
        save();raise
    evidence.update(cold_wall_seconds=time.perf_counter()-started,cold=cold,cold_results=captures[0],
        cold_usage=UsageLedger(c.repository.sessions).summary(task_id=c.state['task_id']))
    db=create_database(f"sqlite:///{(tmp_path/'career.db').as_posix()}")
    applications=ApplicationLoop(ApplyRepository(db.session_factory),browser_factory=FakeBrowser)
    runtime=SimpleNamespace(**{**vars(c.runtime),'database':db,'workspace':JobWorkspaceRepository(db.session_factory),
        'evidence':CareerEvidenceRepository(db.session_factory)})
    repository=TaskRepository(db.session_factory)
    harness=CareerHarness(runtime,applications,repository,fit_service=fit())
    task,_=repository.create('Compare all eight saved jobs after restart.','real-eight-warm-restart')
    for identifier in ids:repository.link(task['task_id'],'jobs',identifier)
    cold_resolver_calls=len(calls)
    try:
        started=time.perf_counter()
        with usage_scope(ledger=UsageLedger(repository.sessions),task_id=task['task_id'],purpose='score_jobs'):
            warm=harness.execute(task['task_id'],'score_jobs',{'application_ids':ids},call_id=str(uuid4()))
        evidence.update(warm=warm,warm_wall_seconds=time.perf_counter()-started,warm_results=captures[-1],calls=calls,
            cold_resolver_calls=cold_resolver_calls,warm_new_resolver_calls=len(calls)-cold_resolver_calls,
            warm_usage=UsageLedger(repository.sessions).summary(task_id=task['task_id']),
            restart='new DB connection, repositories, ApplicationLoop, CareerHarness and FitAnalysisService')
        evidence['resolver_cold_coverage']=batches[0]
        evidence['checks']={
            'eight_cold_jobs':len(cold['jobs'])==8,'real_cold_within_60s':evidence['cold_wall_seconds']<=60,
            'one_resolver_call':cold_resolver_calls==1,
            **batches[0]['checks'],
            'attributed_main_calls':sum(r['main_model_calls'] for r in captures[0].values())==1,
            'jev_real_cold_calls':sum(r['fast_model_calls'] for r in captures[0].values())>0,
            'cold_ledger_complete':evidence['cold_usage']['usage_complete'] and evidence['cold_usage']['pending']==0 and evidence['cold_usage']['unknown_usage_calls']==0,
            'cold_ledger_accounts_for_resolver':sum(g['calls'] for g in evidence['cold_usage']['groups'] if g['purpose'].split(':',1)[0]=='jev_fit_resolver')==cold_resolver_calls,
            'cold_ledger_accounts_for_jev':sum(g['calls'] for g in evidence['cold_usage']['groups'] if g['purpose'].startswith('jev:'))==len({call['call_id'] for result in captures[0].values() for routing in result['routing'] if routing['purpose']=='jev_fit' for call in routing.get('calls',[])}),
            'warm_zero_new_provider_calls':all(r['main_model_calls']==r['fast_model_calls']==0 for r in captures[-1].values()) and len(calls)==cold_resolver_calls,
            'warm_equal_scores':[j['match_score'] for j in cold['jobs']]==[j['match_score'] for j in warm['jobs']],
            'warm_zero_usage':evidence['warm_usage']['calls']==0,
            'no_warm_cache_before_cold':not evidence['cold_cache_existed_before']}
        evidence['warm_usage_interpretation']='No provider requests: checked with new Fit service counters, resolver trace and task-scoped ledger. usage_complete=False for an empty ledger is not a token estimate.'
        evidence['status']='passed' if all(evidence['checks'].values()) else 'failed'
        save()
        assert evidence['status']=='passed',evidence['checks']
    except Exception as exc:
        evidence.update(status='failed',error=type(exc).__name__,calls=calls);save();raise
    finally:harness.close();applications.close();db.close()
