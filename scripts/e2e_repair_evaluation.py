"""Opt-in paid comparison on anonymous, entirely fictional fixtures.

Run explicitly with --live. No saved candidate, database resume or contact data
is read. Results are persisted after each case so provider failures are visible.
"""
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from api.services.fit_analysis_service import FitAnalysisService
from agent_runtime.fast_decisions import FastDecisions
from job_agent.workflow.handlers import JobAgentStepHandler
from job_agent.jev_fit.settings import Settings

APPLICANTS={
    'analyst':'''SYNTHETIC APPLICANT A
EXPERIENCE
Data Analyst - Fictional Analytics Company, New York, NY (Jul 2024 - Present)
• Built Python data pipelines and SQL queries in PostgreSQL.
• Built Tableau dashboards and performed A/B testing with pandas.
EDUCATION
B.S. in Statistics, Fictional University (Sep 2020 - May 2024)
SKILLS
Python, SQL, Tableau, pandas. No Go, Kubernetes, PyTorch or Figma experience.
''',
    'backend':'''SYNTHETIC APPLICANT B
EXPERIENCE
Senior Software Engineer - Fictional Payments Company, Chicago, IL (Mar 2021 - Present)
• Built Go and Python REST APIs. Owned PostgreSQL services in production.
• Deployed production services on AWS EKS using Kubernetes and Terraform.
Software Engineer - Fictional Logistics Company, Chicago, IL (Jul 2017 - Feb 2021)
• Built Python APIs and SQL reporting pipelines. Mentored four junior engineers.
EDUCATION
B.S. in Computer Science, Fictional University (Aug 2013 - May 2017)
SKILLS
Go, Python, PostgreSQL, Kubernetes, Terraform, AWS (EKS, RDS). No PyTorch or Figma experience.
''',
    'student':'''SYNTHETIC APPLICANT C
EXPERIENCE
Machine Learning Intern - Fictional AI Company, San Francisco, CA (May 2026 - Aug 2026)
• Fine-tuned a language model using PyTorch and LoRA. Built a Python evaluation harness.
• Served an internal prototype through FastAPI and Docker; no production ownership.
EDUCATION
M.S. in Computer Science, Fictional Graduate University (Aug 2025 - May 2027 (expected)) - In progress, not graduated
B.E. in Computer Science, Fictional University (Aug 2019 - May 2023)
SKILLS
Python, PyTorch, LoRA, Docker, SQL. No Kubernetes, Go or Figma experience.
''',
    'designer':'''SYNTHETIC APPLICANT D
EXPERIENCE
UX Design Fellow - Fictional Clinics Company, Austin, TX (Feb 2026 - Present)
• Designed patient check-in interfaces with Figma and conducted twelve user interviews.
Registered Nurse - Fictional Medical Center, Austin, TX (Jun 2019 - Jan 2026)
• Led a clinical workflow redesign and trained fifteen nurses.
EDUCATION
B.S. in Nursing, Fictional University (Aug 2015 - May 2019)
SKILLS
Figma, user research, usability testing. No Python, Go, Kubernetes or PyTorch experience.
''',
}
JOBS={
    'backend':'Backend Engineer\nRequired: Python API development.\nRequired: Production Kubernetes deployment.\nPreferred: Go programming.\n',
    'ml':'Machine Learning Engineer\nRequired: PyTorch model training.\nRequired: Completed masters degree in Computer Science.\nPreferred: Python programming.\n',
    'ux':'UX Designer\nRequired: Figma interface design.\nRequired: Conducting user interviews.\nPreferred: Healthcare work experience.\n',
}
# Human-authored expected statuses for unambiguous evidence boundaries. The
# model may safely abstain; a wrong confident decision is reported separately.
ORACLE={
    ('analyst','backend'):['partial','missing','missing'],
    ('backend','backend'):['matched','matched','matched'],
    ('student','backend'):['matched','missing','missing'],
    ('designer','backend'):['missing','missing','missing'],
    ('analyst','ml'):['missing','missing','matched'],
    ('backend','ml'):['missing','missing','matched'],
    ('student','ml'):['matched','partial','matched'],
    ('designer','ml'):['missing','missing','missing'],
    ('analyst','ux'):['missing','missing','missing'],
    ('backend','ux'):['missing','missing','missing'],
    ('student','ux'):['missing','missing','missing'],
    ('designer','ux'):['matched','matched','matched'],
}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if not args.live:parser.error('Paid external model calls require explicit --live.')
    args.output.mkdir(parents=True,exist_ok=True)
    settings=Settings.load(cache_path=args.output/'jev-evaluation.sqlite3')
    services={
        'jev':FitAnalysisService(jev_enabled=True,jev_config=settings),
        'main':FitAnalysisService(JobAgentStepHandler(decisions=FastDecisions()),jev_enabled=False),
    }
    rows=[]
    for algorithm,service in services.items():
        for applicant,resume in APPLICANTS.items():
            for job,jd in JOBS.items():
                start=time.perf_counter();row={'algorithm':algorithm,'applicant':applicant,'job':job,
                    'oracle_statuses':ORACLE[(applicant,job)]}
                try:
                    result=service._analyze_sync(resume_text=resume,job_description=jd)
                    row.update(result=result.model_dump(mode='json'))
                except Exception as exc:
                    # Provider bodies can contain credentials or prompts.
                    row.update(error_type=type(exc).__name__)
                row['seconds']=round(time.perf_counter()-start,3);rows.append(row)
                (args.output/'comparison.json').write_text(json.dumps({'synthetic_only':True,'rows':rows},ensure_ascii=False,indent=2),encoding='utf-8')
                match=(row.get('result') or {}).get('skill_match') or {}
                print(json.dumps({k:row[k] for k in ('algorithm','applicant','job','seconds')}|
                    {'score':match.get('overall_score'),'range':match.get('score_range'),'error':row.get('error_type')},ensure_ascii=False),flush=True)
    # Exact presentation changes use persisted decisions, never copied offsets.
    first=services['jev']._analyze_sync(resume_text=APPLICANTS['backend'],job_description=JOBS['backend'])
    variants=[]
    for jd in (JOBS['backend']+'\n',' '.join(JOBS['backend'].split())):
        result=services['jev']._analyze_sync(resume_text=APPLICANTS['backend'],job_description=jd)
        variants.append({'model_calls':result.model_calls,'score':result.skill_match.overall_score,
            'range':result.skill_match.score_range,'same_score':result.skill_match.overall_score==first.skill_match.overall_score})
    (args.output/'format-variants.json').write_text(json.dumps(variants,indent=2),encoding='utf-8')


if __name__=='__main__':main()
