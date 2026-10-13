"""Opt-in billable live comparison using ONLY the synthetic fixtures below.

Run: python scripts/benchmark_jev.py --output <existing-directory> --repeats 2
Does not modify .env, user memories, resumes, servers, or applications.
"""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import statistics
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from eregion.runtime.fast_decisions import FastDecisions, configured_decisions, capture_routing
from eregion.runtime.semantics import SemanticDecisions
from eregion.domain.workflow.handlers import JobAgentStepHandler, SharedModelAnalyzer
from eregion.domain.workflow.state import AgentState, Step
from eregion.domain.model import create_model
from eregion.domain.schemas import ResumeAnalysis, ResumeEvidence, JobAnalysis, JobRequirement
from eregion.api.services.fit_analysis_service import FitAnalysisService


RESUME_TEXT = '''SYNTHETIC CANDIDATE - Jordan Example
Summary
Python and SQL developer focused on data tools.
Experience
Example Lab - Software Developer
Built Python REST APIs with FastAPI and PostgreSQL.
Wrote SQL queries and dashboards in Tableau for weekly reporting.
Used Git and Docker to ship data services.
Projects
Forecast Demo
Built a scikit-learn demand forecasting prototype with Python.
Education
Example University - Bachelor of Science in Computer Science, completed 2023.
Skills
Python, SQL, PostgreSQL, FastAPI, Git, Docker, Tableau, scikit-learn.
'''
JOB_TEXT = '''Synthetic Junior Backend Developer at Example Test Company.
Required skills: Python; SQL; Git; Docker.
Preferred skills: FastAPI; Kubernetes.
Build data services and collaborate with the engineering team.
'''


def prepared():
    quotes = [
        'Built Python REST APIs with FastAPI and PostgreSQL.',
        'Wrote SQL queries and dashboards in Tableau for weekly reporting.',
        'Used Git and Docker to ship data services.',
        'Built a scikit-learn demand forecasting prototype with Python.',
        'Example University - Bachelor of Science in Computer Science, completed 2023.',
        'Master of Science in Statistics, currently pursuing; expected graduation 2028.',
        'Used Python for one year in an academic project.',
    ]
    resume = ResumeAnalysis(summary='Synthetic developer', skills=['Python','SQL','Git','Docker','Tableau'],
        education=quotes[4:6], evidence=[ResumeEvidence(evidence_id=f'ev{i}', source_section='Resume',
        exact_text=quote) for i, quote in enumerate(quotes)])
    def req(i, text, **kwargs):
        return JobRequirement(requirement_id=f'r{i}', canonical_name=text, original_text=text,
                              level='required', **kwargs)
    return resume, [
        ('simple', JobAnalysis(title='Developer', summary='Synthetic skills', responsibilities=[], requirements=[
            req(0,'Python'), req(1,'SQL'), req(2,'Git'), req(3,'Docker'), req(4,'Power BI'),
            req(5,'Kubernetes')]), ['matched']*4+['missing']*2),
        ('complex', JobAnalysis(title='Engineer', summary='Synthetic mixed requirements', responsibilities=[], requirements=[
            req(0,'Python'), req(1,'At least five years of professional Python experience',
                category='experience', verification_mode='years_experience', minimum_years=5),
            req(2,'Completed master degree in Statistics', category='education'),
            req(3,'Authorized to work in Canada', category='eligibility', verification_mode='user_confirmation'),
            req(4,'Claude Code')]), ['matched','partial','partial','needs_confirmation','missing']),
        ('translation', JobAnalysis(title='Data engineer', summary='Synthetic multilingual', responsibilities=[], requirements=[
            req(0,'使用 Python 构建 API'), req(1,'使用 SQL 查询数据'), req(2,'熟悉 Power BI')]),
            ['matched','matched','missing']),
    ]


class MeasuredSemantics(SemanticDecisions):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.main_calls = 0
    def _invoke(self, *args, **kwargs):
        self.main_calls += 1
        return super()._invoke(*args, **kwargs)


def memory_cases():
    rows = [
        ('role','Target junior Python backend and data engineering positions.'),
        ('location','Only remote positions in Canada.'),
        ('writing','Use concise cover letters with no exaggerated claims.'),
        ('interview','Ask one interview practice question at a time.'),
        ('food','Prefer vegetarian meals.'),
        ('theme','Use a dark theme in the dashboard.'),
    ]
    memories = [SimpleNamespace(memory_id=f'm{i}',memory_key=key,display_text=text,content={'preference':text})
                for i,(key,text) in enumerate(rows)]
    return memories, [
        ('find_jobs','Find suitable job openings for me.',{'m0','m1'}),
        ('draft','Revise the wording and length of an existing cover letter. Role and location are fixed; focus only on writing preferences.',{'m2'}),
        ('interview','只练习通用行为面试，关注提问节奏，不涉及具体职位或地点。',{'m3'}),
    ]


QUESTIONS = [
    ('motivation','What motivates you in your next role?',{'motivation'}),
    ('experience','Describe a software project you built.',{'experience'}),
    ('company','Why do you want to work for this company?',{'company_interest'}),
    ('permission','May we retain your information for future vacancies?',{'legal_or_identity'}),
    ('logistics','您最早什么时候可以入职？',{'logistics'}),
    ('ambiguous','Tell us more.',{'unknown'}),
    ('indirect_consent','Are you happy for our partners to receive your profile?',{'legal_or_identity'}),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--repeats',type=int,default=2)
    parser.add_argument('--suite',choices=['all','semantics','memory','match','e2e'],default='all')
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    # Injection enables only these explicitly synthetic fixture calls.
    fast = configured_decisions(environ={'TYPESAFE_ENABLED':'true', 'TYPESAFE_CAREER_ENABLED':'true'},scope='career')
    assert fast.enabled, 'Configure a TypeSafe key before running this opt-in benchmark.'
    model = create_model()
    report = {'synthetic_only':True,'repeats':args.repeats,
              'main_model':str(getattr(model,'model_name','configured')),'jev_model':fast.model,
              'cache':'disabled for fit; explicitly cleared before every Jev trial', 'trials':[]}
    def save():
        (args.output/f'benchmark-{args.suite}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    def trial(suite,case,mode,repeat,fn):
        fast.clear_cache()
        started=time.perf_counter()
        try:
            with capture_routing() as trace:
                result=fn(fast if mode=='jev' else FastDecisions())
            row={'suite':suite,'case':case,'mode':mode,'repeat':repeat,
                 'seconds':round(time.perf_counter()-started,3), **result, 'routing':trace}
        except Exception as error:
            row={'suite':suite,'case':case,'mode':mode,'repeat':repeat,
                 'seconds':round(time.perf_counter()-started,3),'error':type(error).__name__}
        report['trials'].append(row);save()
        print(json.dumps({k:v for k,v in row.items() if k not in {'result','match'}},ensure_ascii=True),flush=True)
    resume, jobs=prepared()
    for repeat in range(args.repeats):
        modes=('main','jev') if repeat%2==0 else ('jev','main')
        if args.suite in {'all','semantics','memory'}:
            memories, queries=memory_cases()
            for name,query,expected in queries:
                for mode in modes:
                    def run(service):
                        evaluator=MeasuredSemantics(model,decisions=service)
                        actual=evaluator.relevant_memories(query,memories)
                        return {'actual':sorted(actual),'expected':sorted(expected),'correct':actual==expected,
                                'main_calls':evaluator.main_calls}
                    trial('memory',name,mode,repeat,run)
            for name,question,expected in (QUESTIONS if args.suite != 'memory' else []):
                for mode in modes:
                    def run(service):
                        evaluator=MeasuredSemantics(model,decisions=service)
                        actual=evaluator.question(question)
                        return {'actual':actual,'expected':sorted(expected),'correct':actual in expected,
                                'main_calls':evaluator.main_calls}
                    trial('question',name,mode,repeat,run)
        if args.suite in {'all','match'}:
            for name,job,expected in jobs:
                for mode in modes:
                    def run(service):
                        handler=JobAgentStepHandler(decisions=service)
                        state=AgentState(run_id='synthetic-benchmark',resume_text=RESUME_TEXT,job_description=JOB_TEXT,
                                         resume_analysis=resume,job_analysis=job)
                        match=handler.execute(Step.MATCH_SKILLS,state).updates['skill_match']
                        actual=[m.match_status for m in match.matches]
                        return {'actual':actual,'expected':expected,'correct':actual==expected,
                                'score':match.overall_score,'match':match.model_dump(mode='json'),
                                'valid_quotes':all(q in {e.exact_text for e in resume.evidence}
                                    for m in match.matches for q in m.resume_evidence)}
                    trial('match',name,mode,repeat,run)
        if args.suite in {'all','e2e'}:
            for mode in modes:
                def run(service):
                    result=FitAnalysisService(JobAgentStepHandler(decisions=service),cache_size=0)._analyze_sync(
                        resume_text=RESUME_TEXT,job_description=JOB_TEXT)
                    return {'result':result.model_dump(mode='json'), 'score':result.skill_match.overall_score,
                            'main_calls':result.main_model_calls,'fast_calls':result.fast_model_calls}
                trial('fit_e2e','synthetic_backend',mode,repeat,run)
    summaries=defaultdict(lambda:defaultdict(list))
    for row in report['trials']:
        if 'error' not in row:summaries[row['suite']][row['mode']].append(row['seconds'])
    report['summary']={name:{mode:{'n':len(values),'median_seconds':round(statistics.median(values),3),
                                 'total_seconds':round(sum(values),3)} for mode,values in modes.items()}
                       for name,modes in summaries.items()}
    save()
    print(json.dumps({'summary':report['summary']},ensure_ascii=True),flush=True)


if __name__=='__main__':main()
