"""Opt-in live on-demand discovery: real model, real scoring, synthetic candidate."""
import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from api.db import create_database
from agent_runtime.career.repository import TaskRepository
from agent_runtime.career.alerts import AlertRepository
from agent_runtime.career.harness import CareerHarness
from agent_runtime.task_loop import TaskLoop
from agent_runtime.workspace.repository import JobWorkspaceRepository
from agent_runtime.evidence.repository import CareerEvidenceRepository
from agent_runtime.auto_apply.repository import ApplyRepository
from agent_runtime.auto_apply.browser import ApplicationBrowser
from agent_runtime.browser.manager import BrowsingManager

RESUME='''Synthetic Candidate
Senior Software Engineer
EXPERIENCE
Example Software, Senior Software Engineer, 2018-present
Built and operated Python and Go backend services and REST APIs supporting one million daily requests.
Designed PostgreSQL schemas, SQL analytics and Redis caching. Reduced request latency by 30%.
Deployed services on AWS with Docker, Kubernetes, Terraform and CI/CD; maintained production on-call rotations.
Implemented distributed queues, monitoring with Prometheus and Grafana, and application security reviews.
Collaborated with product and customer teams to investigate incidents, explain tradeoffs and deliver reliable software.
EDUCATION
Bachelor of Science in Computer Science, Example University, 2018.
SKILLS
Python, Go, Java, SQL, PostgreSQL, Redis, Linux, Git, Docker, Kubernetes, AWS, Terraform.
'''


def run(folder,seconds=360,source='boards'):
    folder.mkdir(parents=True,exist_ok=True)
    db=create_database(f'sqlite:///{(folder/"evaluation.sqlite").as_posix()}',create_schema_for_tests=True)
    tasks=TaskRepository(db.session_factory)
    runtime=SimpleNamespace(database=db,workspace=JobWorkspaceRepository(db.session_factory),evidence=CareerEvidenceRepository(db.session_factory))
    harness=CareerHarness(runtime,SimpleNamespace(repository=ApplyRepository(db.session_factory)),tasks)
    harness.alerts=AlertRepository(db.session_factory)
    harness.candidate=lambda:({'profile':{'first_name':'Synthetic','last_name':'Candidate'}},RESUME)
    harness._browsing=BrowsingManager(factory=lambda url:ApplicationBrowser(url,purpose='browse',headless=True))
    loop=TaskLoop(tasks,harness,budget=32,retry_delays=(1,));started=time.monotonic();started_at=datetime.now(UTC).isoformat();report={}
    try:
        sites=('Search LinkedIn for roles in New York. ' if source=='linkedin' else
            'Search both Cloudflare (https://job-boards.greenhouse.io/cloudflare) and Peak (https://jobs.lever.co/peakgames). ')
        state=loop.start('Find and recommend one currently listed software engineering job suitable for my saved resume. '+sites+
            'Read and score promising roles, explain the strongest fit and any location or sponsorship uncertainty. '
            'This is a one-time search; do not create a schedule, apply or contact anyone. The resume is synthetic test data.',str(uuid4()))
        last=None
        while time.monotonic()-started<seconds:
            state=tasks.get(state['task_id']);progress=(state['status'],state['model_calls'],(state.get('tool_activity') or {}).get('tool'))
            if progress!=last:print(json.dumps({'status':progress[0],'model_calls':progress[1],'tool':progress[2]}),flush=True);last=progress
            if state['status'] in {'completed','needs_input','cancelled'}:break
            time.sleep(.5)
        else:tasks.change(state['task_id'],status='cancelled',pause_requested=True,chat_revision=state['chat_revision']+1)
        loop.close();state=tasks.get(state['task_id'])
        picks=state.get('recommendations',[])
        scores_verified=all(harness.job_summary(p['application_id'])['match_score']==p['match_score'] for p in picks)
        completed={a['tool'] for a in state['actions'] if a['outcome']=='completed'}
        browser_used='browser_open' in completed and bool({'browser_type','browser_click'}&completed)
        source_verified=source!='linkedin' or browser_used and any('linkedin.com/jobs/' in p['url'] for p in picks)
        report={'started_at':started_at,'status':state['status'],'model_calls':state['model_calls'],
            'source':source,'browser_used':browser_used,
            'elapsed_seconds':round(time.monotonic()-started,2),'recommendations':picks,'history':state['history'],
            'messages':state['messages'],'timings':state.get('timings',[]),'error':state.get('error'),
            'verification':{'passed':state['status']=='completed' and bool(picks) and scores_verified and source_verified and not harness.alerts.list(),
                'scores_match_saved_analysis':scores_verified,'schedules_created':len(harness.alerts.list())}}
        (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'report':str(folder/'report.json'),'verification':report['verification']}),flush=True)
    finally:loop.close();harness.close();db.close()
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true',required=True)
    parser.add_argument('--seconds',type=int,default=360)
    parser.add_argument('--source',choices=['boards','linkedin'],default='boards')
    parser.add_argument('--output',type=Path,default=Path('artifacts/browser-eval')/datetime.now().strftime('%Y%m%d-%H%M%S')/'job-discovery')
    args=parser.parse_args();run(args.output,args.seconds,args.source)
