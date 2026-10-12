"""Live synthetic-only latency comparison. No production state is modified."""
import argparse, importlib.util, json, os, statistics, sys, tempfile, time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from job_agent.model import create_model, invoke_structured
from job_agent.schemas import JobAnalysis, ResumeAnalysis
from job_agent.workflow.handlers import SharedModelAnalyzer, JobAgentStepHandler
from api.services.fit_analysis_service import FitAnalysisService
from scripts.benchmark_jev import RESUME_TEXT, JOB_TEXT
from agent_runtime.fast_decisions import configured_decisions

class LegacyAnalyzer(SharedModelAnalyzer):
    def __call__(self,schema,prompt,text):
        if schema in {JobAnalysis, ResumeAnalysis}:
            return invoke_structured(create_model(),schema,prompt,text)
        return super().__call__(schema,prompt,text)

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module
    spec.loader.exec_module(module);return module

def fit(mode):
    fast=configured_decisions(scope='career');fast.clear_cache()
    handler=JobAgentStepHandler(analyzer=LegacyAnalyzer() if mode=='before' else SharedModelAnalyzer(),decisions=fast)
    # Fixed, explicit skill requirements isolate transport changes from the known
    # baseline variance over whether prose responsibilities become requirements.
    job=JOB_TEXT.replace('Build data services and collaborate with the engineering team.\n','')
    result=FitAnalysisService(handler,cache_size=0)._analyze_sync(resume_text=RESUME_TEXT,job_description=job)
    assert len(result.job_analysis.requirements)==6
    assert result.skill_match.overall_score==83.3
    return {'seconds':result.latency_seconds, 'stages':result.stage_seconds,
            'score':result.skill_match.overall_score,'calls':result.model_calls,
            'requirements':[(r.canonical_name,r.source_text,r.category.value,r.verification_mode.value,r.level,r.minimum_years)
                            for r in result.job_analysis.requirements],
            'statuses':[(m.job_skill,m.match_status) for m in result.skill_match.matches],
            'valid_quotes':all(q in {e.exact_text for e in result.resume_analysis.evidence}
                               for m in result.skill_match.matches for q in m.resume_evidence)}

def chat(mode,case,baseline_dir):
    from api.db import create_database
    from agent_runtime.career.repository import TaskRepository
    from agent_runtime.career.harness import CareerHarness
    from agent_runtime.workspace.repository import JobWorkspaceRepository
    from agent_runtime.evidence.repository import CareerEvidenceRepository
    from agent_runtime.auto_apply.repository import ApplyRepository
    from agent_runtime.browser.manager import BrowsingManager
    from scripts.smoke_jev_runtime import LocalBrowser
    import agent_runtime.task_loop as task_module
    import agent_runtime.task_host as host_module
    class JobBrowser(LocalBrowser):
        body='''<h1>Synthetic jobs</h1><ul>
<li><a href="https://example.invalid/jobs/python">Junior Python Backend Engineer</a> - Remote US. Python and SQL.</li>
<li><a href="https://example.invalid/jobs/tax">Senior Tax Accountant</a> - London onsite. Ten years corporate tax.</li>
<li><a href="https://example.invalid/jobs/unknown">Software Engineer</a> - Details unknown.</li></ul>'''
    old_engine,old_host=task_module.AgentLoop,task_module.TaskHost
    if mode=='before':
        path=baseline_dir/'agent_runtime'
        ctx=load('before_context',path/'loop_context.py')
        engine=load('before_engine',path/'loop_engine.py');engine.ConversationWindow=ctx.ConversationWindow
        host=load('before_host',path/'task_host.py')
        host.ModelRequests=load('before_wait',path/'loop_model.py').ModelRequests
        task_module.AgentLoop,task_module.TaskHost=engine.AgentLoop,host.TaskHost
    calls=[]
    class MeasuredModel(task_module.TaskModel):
        def invoke(self,messages,tools):
            started=time.perf_counter();response=super().invoke(messages,tools)
            calls.append({'seconds':round(time.perf_counter()-started,3),
                'context_chars':sum(len(m.content) for m in messages if isinstance(m.content,str)),
                'tool_schema_chars':len(json.dumps(tools)), 'usage':response.usage_metadata,
                'tools':[c['name'] for c in response.tool_calls]})
            return response
    with tempfile.TemporaryDirectory(prefix='northstar-speed-') as temp:
        db=create_database('sqlite:///'+(Path(temp)/'task.db').as_posix(),create_schema_for_tests=True)
        repository=TaskRepository(db.session_factory)
        runtime=SimpleNamespace(workspace=JobWorkspaceRepository(db.session_factory),evidence=CareerEvidenceRepository(db.session_factory))
        apps=SimpleNamespace(repository=ApplyRepository(db.session_factory))
        harness=CareerHarness(runtime,apps,repository)
        if mode=='before':harness.prompt=load('before_prompt',baseline_dir/'agent_runtime/career/prompt.py').SYSTEM
        harness._browsing=BrowsingManager(factory=lambda url:JobBrowser(url,headless=True,purpose='browse'))
        reads=[0];get=repository.get
        def counted(*a,**kw):reads[0]+=1;return get(*a,**kw)
        repository.get=counted
        loop=task_module.TaskLoop(repository,harness,model_factory=MeasuredModel,budget=12)
        goal='hi' if case=='greeting' else ('Synthetic test: open https://example.invalid/jobs and use screen_jobs to shortlist '
            'visible links for junior Python jobs, remote US. Report preliminary relevance only. Do not import, score or apply.')
        started=time.perf_counter()
        try:
            state=loop.start(goal,str(uuid4()))
            while time.perf_counter()-started<120:
                state=get(state['task_id'])
                if state['status'] in {'completed','needs_input','failed'}:break
                time.sleep(.05)
            result={'seconds':round(time.perf_counter()-started,3),'status':state['status'],
                'calls':calls,'repository_reads':reads[0], 'actions':[h['tool'] for h in state['history']],
                'reply_count':sum(m['role']=='assistant' for m in state['messages']),
                'fast_statuses':[r['status'] for r in state.get('fast_decisions',[])]}
            assert state['status']=='completed',result
            assert result['reply_count']>0
            if case=='greeting':assert not result['actions'],result
            else:assert 'screen_jobs' in result['actions'],result
            return result
        finally:
            loop.close();harness.close();db.close()
            task_module.AgentLoop,task_module.TaskHost=old_engine,old_host

def main():
    parser=argparse.ArgumentParser();parser.add_argument('suite',choices=['fit','chat'])
    parser.add_argument('--repeats',type=int,default=2)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--baseline-dir',type=Path,help='Pre-change source snapshot; required for chat before/after.')
    parser.add_argument('--mode',choices=['both','after'],default='both')
    args=parser.parse_args()
    if args.suite=='chat' and args.mode=='both' and not args.baseline_dir:
        parser.error('--baseline-dir is required for chat before/after')
    args.output.mkdir(parents=True,exist_ok=True)
    report={'synthetic_only':True,'trials':[]}
    for repeat in range(args.repeats):
        for mode in (['after'] if args.mode=='after' else (['before','after'] if repeat%2==0 else ['after','before'])):
            for case in (['fit'] if args.suite=='fit' else ['greeting','browsing']):
                start=time.perf_counter()
                try:row={'repeat':repeat,'mode':mode,'case':case,**(fit(mode) if case=='fit' else chat(mode,case,args.baseline_dir))}
                except Exception as e:row={'repeat':repeat,'mode':mode,'case':case,'error':type(e).__name__,'seconds':time.perf_counter()-start}
                report['trials'].append(row)
                (args.output/f'live-{args.suite}-controlled.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
                print(json.dumps(row),flush=True)

if __name__=='__main__':main()
