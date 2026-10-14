"""Explicit paid checks: synthetic candidates, public research, no real applying."""
import json
import os
import time
from dataclasses import replace
from uuid import uuid4

import pytest

from eregion.runtime.career.discovery import JobDiscovery
from eregion.runtime.career.service import CareerService
from eregion.api.services.fit_analysis_service import FitAnalysisService
from eregion.domain.jev_fit.settings import Settings
from eregion.domain.pdf_rendering import render_letter_pdf
from scripts.e2e_repair_evaluation import APPLICANTS
from test_career_flow import career
from scripts.remaining_search_acceptance import evaluate_search

pytestmark=pytest.mark.skipif(os.getenv('JOB_AGENT_LIVE_REMAINING')!='1',reason='Explicit paid real-model/public research check')


def run_facts(service,state,summary):
    """Runtime-recorded facts the final reply must report faithfully (for the reply audit)."""
    from collections import Counter
    from eregion.runtime.career.source_health import coverage, projection
    from eregion.runtime.career.candidate_queue import stalled
    source=state.get('linkedin_mcp_state') or {}
    log=source.get('log',[])
    scored=[j for j in summary['verified_jobs'] if j.get('match_score') is not None]
    decided=set(summary['job_decisions'])|{r.get('application_id') for r in summary['recommendations']}
    return {'status':state['status'],'error':state.get('error'),
        'linkedin':{'calls_used':source.get('calls_used',0),'stop_reason':source.get('stopped'),
                    'failed_calls':sum(r.get('outcome')!='ok' for r in log),
                    'searches':[r.get('arguments') for r in log if r.get('tool')=='search_jobs']},
        'search_coverage':coverage(state),'source_health':projection(state),
        'postings_read':len(state.get('retrieved_jobs') or {}),'imported':len(state['jobs']),'scored':len(scored),
        'decisions':dict(Counter(d.get('decision') for d in summary['job_decisions'].values())),
        'scored_without_outcome':[j['url'] for j in scored if j.get('application_id') not in decided],
        'recommended_by_tier':dict(Counter(r.get('tier') for r in summary['recommendations'])),
        'stalled_candidates':[{'target':k,**v} for k,v in stalled(state).items()]}


def settle_live(service,task_id,output,applicant,timeout=600,*,semantic_review=False,limits=None,acceptance_version=None):
    from eregion.runtime.provider_usage import UsageLedger
    started=time.monotonic()
    while time.monotonic()-started<timeout:
        state=service.repository.get(task_id)
        if state['status'] in {'completed','needs_input','cancelled'}:break
        time.sleep(.3)
    else:
        service.cancel(task_id)
        state=service.repository.get(task_id)
    (output/'transcript.json').write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
    summary={'status':state['status'],'calls':state['model_calls'],'seconds':round(time.monotonic()-started,2),
        'jobs':len(state['jobs']),'materials':len(state['packs']),'applications':len(state['application_runs']),
        'error':(state.get('error') or {}).get('code'),'tools':[h['tool'] for h in state['history']],
        'final':next((m['text'] for m in reversed(state['messages']) if m['role']=='assistant'),'')}
    summary['usage']=UsageLedger(service.repository.sessions).summary(task_id=task_id,run_ids=state['application_runs'])
    summary['recommendations']=state.get('recommendations',[])
    summary['job_decisions']=state.get('job_decisions') or {}
    from datetime import datetime,timezone
    from scripts.remaining_search_acceptance import run_metrics
    summary['metrics']=run_metrics(state,state.get('updated_at') or datetime.now(timezone.utc).isoformat(),
                                   service.runtime.workspace)
    summary['schedules']=len(service.harness.alerts.list())
    from eregion.runtime.career.alerts import job_key
    retrieved={job_key(j['url']) for j in state.get('retrieved_jobs',{}).values() if j.get('url')}
    summary['verified_jobs']=[]
    for identifier in state['jobs']:
        job=service.harness.job_summary(identifier,detail=True)
        job['retrieved']=bool(job.get('url')) and job_key(job['url']) in retrieved
        job['disqualified']=any(m.get('match_status')=='confirmed_condition' and m.get('condition_satisfied') is False
            for m in (job.get('match_report') or {}).get('matches',[]))
        summary['verified_jobs'].append(job)
    summary['tool_evidence']=[{'tool':h['tool'],'arguments':h.get('arguments'),'result':h.get('result')} for h in state['history']]
    if semantic_review:
        from eregion.runtime.provider_usage import usage_scope,TaskProviderBudgetExceeded
        from eregion.runtime.career.qualification import user_request
        from evals.search_semantic_audit import review
        summary['qualification_method']='model'
        summary['user_request']=user_request(state)
        audit_id=str(uuid4());audit_started=time.monotonic()
        saved={k:os.environ.get(k) for k in ('JOB_AGENT_TASK_MAX_PROVIDER_ATTEMPTS','JOB_AGENT_TASK_MAX_INPUT_TOKENS')}
        try:
            os.environ.update(JOB_AGENT_TASK_MAX_PROVIDER_ATTEMPTS='6',JOB_AGENT_TASK_MAX_INPUT_TOKENS='200000')
            urls={r['url'] for r in summary['recommendations']}
            with usage_scope(task_id=audit_id,ledger=UsageLedger(service.repository.sessions)):
                # The audit judges personal mandatory qualifications from the candidate's own
                # facts (resume text + stated facts), never from production fit labels.
                from evals.search_semantic_audit import candidate_hash
                _,resume_text=service.harness.candidate()
                facts=service.harness.fit_facts()
                candidate=(resume_text or '')+('\nCANDIDATE-STATED FACTS\n'+json.dumps(facts,ensure_ascii=False,sort_keys=True) if facts else '')
                summary['audit_candidate_hash']=candidate_hash(candidate)
                audited=[j for j in summary['verified_jobs'] if j['url'] in urls]
                if acceptance_version in {'tiered-recommendations-v1','tiered-recommendations-v2'}:
                    from evals.tiered_audit import review as tiered_review
                    summary['acceptance_version']=acceptance_version
                    summary['semantic_review']=tiered_review(summary['user_request'],audited,summary['recommendations'],candidate)
                if acceptance_version=='tiered-recommendations-v2':
                    from evals.tiered_audit import review_reply
                    summary['reply_review']=review_reply(summary['user_request'],summary['final'],
                                                         run_facts(service,state,summary),summary['recommendations'])
                else:
                    summary['semantic_review']=review(summary['user_request'],audited,candidate)
        except (Exception,TaskProviderBudgetExceeded) as exc:
            summary['semantic_review_error']=type(exc).__name__
        finally:
            for k,v in saved.items():
                if v is None:os.environ.pop(k,None)
                else:os.environ[k]=v
            summary['audit_usage']=UsageLedger(service.repository.sessions).summary(task_id=audit_id)
            summary['audit_seconds']=round(time.monotonic()-audit_started,2)
            (output/'semantic-audit.json').write_text(json.dumps({k:v for k,v in summary.items()
                if k.startswith('semantic_review') or k.startswith('audit_')},ensure_ascii=False,indent=2),encoding='utf-8')
    (output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in summary.items() if k not in {'tool_evidence','verified_jobs'}},ensure_ascii=True),flush=True)
    acceptance=evaluate_search(summary,applicant,limits)
    (output/'acceptance.json').write_text(json.dumps(acceptance,ensure_ascii=False,indent=2),encoding='utf-8')
    assert acceptance['status']=='passed',acceptance
    return state


@pytest.mark.parametrize('applicant,query',[
    ('analyst','junior data analyst in New York'),
    ('backend','senior backend engineer, remote US'),
    ('student','machine learning internship, California'),
    ('designer','junior UX designer, Austin'),
])
def test_long_real_search_conversations(career,tmp_path,applicant,query):
    c=career
    c.repository.change(c.state['task_id'],status='cancelled',pause_requested=True)
    c.applications.repository.save_candidate({'first_name':'Synthetic','last_name':applicant,'email':f'{applicant}@example.com'},
        resume=render_letter_pdf(APPLICANTS[applicant]),name='synthetic.pdf',extracted=True)
    c.harness.discovery=JobDiscovery()
    c.harness.analysis._fit_service=FitAnalysisService(jev_enabled=True,
        jev_config=replace(Settings.load(cache_path=tmp_path/'fit.sqlite3'),resolve_unknowns=False))
    service=CareerService(c.runtime,c.applications,harness=c.harness,start_alert_scheduler=False)
    service.loop.budget=60
    try:
        goal=(f'Find two current {query} positions for my saved resume. Start with LinkedIn or Indeed; '
            'if blocked or login is required, immediately use public company career boards or other sources. '
            'Read and score jobs you can verify, recommend any you can verify, and summarize the actual result. '
            'Respect the requested seniority and disclose blocked sources or insufficient results. Do not apply or create a schedule.')
        task=service.start(goal,str(uuid4()))
        result=settle_live(service,task['run_id'],tmp_path,applicant)
        assert not result['application_runs']
    finally:service.close()
