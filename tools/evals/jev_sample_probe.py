"""Explicit paid fit-scoring probe on already captured public postings.

--route jev uses the Jev scorer; --route main simulates a user without a Jev/Typesafe
key (TYPESAFE disabled in this process only), so the main model scores alone.

Fresh fit cache only: no earlier score is reused as evidence for the current
classification. No source request, import, recommendation or application.
"""
import argparse
import json
import os
from pathlib import Path
import time
from uuid import uuid4


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,required=True,help='Live sample directory with transcript.json')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--url',action='append',required=True)
    parser.add_argument('--max-attempts',type=int,default=30)
    parser.add_argument('--max-input-tokens',type=int,default=250000)
    parser.add_argument('--route',choices=('jev','main'),default='jev')
    args=parser.parse_args()
    if args.route=='main':
        os.environ.update(TYPESAFE_ENABLED='false',TYPESAFE_API_KEY='',TYPESAFE_CAREER_ENABLED='false')
    if args.output.exists():raise FileExistsError(args.output)
    args.output.mkdir(parents=True)
    os.environ.update(JOB_AGENT_TASK_MAX_PROVIDER_ATTEMPTS=str(args.max_attempts),
                      JOB_AGENT_TASK_MAX_INPUT_TOKENS=str(args.max_input_tokens))
    from dataclasses import replace
    from eregion.api.db import create_database
    from eregion.domain.jev_fit.service import JevFitService
    from eregion.domain.jev_fit.settings import Settings
    from eregion.runtime.provider_usage import UsageLedger,usage_scope
    from scripts.e2e_repair_evaluation import APPLICANTS
    captured=json.loads((args.source/'transcript.json').read_text(encoding='utf-8'))
    bodies={j['url']:j for j in captured['retrieved_jobs'].values()}
    jobs=[{'id':str(i),'source_version':'probe','job_description':bodies[u]['description']} for i,u in enumerate(args.url)]
    db=create_database('sqlite:///'+(args.output/'usage.sqlite3').as_posix(),create_schema_for_tests=True)
    ledger=UsageLedger(db.session_factory);task=str(uuid4());started=time.monotonic()
    # Same settings as the live acceptance: Jev only, unknowns stay unknown.
    values={};error=None
    try:
        with usage_scope(task_id=task,ledger=ledger):
            if args.route=='jev':
                service=JevFitService(replace(Settings.load(cache_path=args.output/'fit.sqlite3'),resolve_unknowns=False),owner='probe')
                values=service.analyze_many(resume_text=APPLICANTS['analyst'],jobs=jobs)
            else:
                import asyncio
                from eregion.api.services.fit_analysis_service import FitAnalysisService
                values={k:v.model_dump(mode='json') for k,v in asyncio.run(FitAnalysisService(jev_enabled=False)
                        .analyze_many(resume_text=APPLICANTS['analyst'],jobs=jobs)).items()}
    except Exception as exc:
        error=f'{type(exc).__name__}: {exc}'
    finally:
        seconds=round(time.monotonic()-started,2)
        (args.output/'results.json').write_text(json.dumps([{'url':u,'title':bodies[u].get('title'),
            'result':values.get(str(i))} for i,u in enumerate(args.url)],indent=2,ensure_ascii=False,default=str),encoding='utf-8')
        (args.output/'summary.json').write_text(json.dumps({'usage':ledger.summary(task_id=task),'seconds':seconds,
            'jobs':len(jobs),'route':args.route,'error':error,'source':str(args.source),'new_source_requests':0,'cost_usd':None,
            'cache':'fresh; no earlier fit cache','kind':'paid fit scoring probe on captured public postings; not a live search'},
            indent=2),encoding='utf-8')
        db.close()
    if error:raise SystemExit(error)


if __name__=='__main__':main()
