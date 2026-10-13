"""Replay the exact synthetic extractions from benchmark_jev with the main matcher."""
import argparse,json
from pathlib import Path
import sys,time
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from benchmark_jev import RESUME_TEXT,JOB_TEXT
from eregion.runtime.fast_decisions import FastDecisions
from eregion.domain.workflow.handlers import JobAgentStepHandler
from eregion.domain.workflow.state import AgentState,Step
from eregion.domain.schemas import ResumeAnalysis,JobAnalysis

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    benchmark=json.loads(args.input.read_text(encoding='utf-8'))
    assert benchmark.get('synthetic_only') is True
    results=[]
    for trial in benchmark['trials']:
        if trial['suite']!='fit_e2e' or trial['mode']!='jev' or 'result' not in trial:continue
        saved=trial['result']
        state=AgentState(run_id='synthetic-cross-check',resume_text=RESUME_TEXT,job_description=JOB_TEXT,
            resume_analysis=ResumeAnalysis.model_validate(saved['resume_analysis']),
            job_analysis=JobAnalysis.model_validate(saved['job_analysis']))
        started=time.perf_counter()
        main_match=JobAgentStepHandler(decisions=FastDecisions()).execute(Step.MATCH_SKILLS,state).updates['skill_match']
        previous={m['requirement_id']:m['match_status'] for m in saved['skill_match']['matches']}
        actual={m.requirement_id:m.match_status for m in main_match.matches}
        report={'repeat':trial['repeat'],'requirements':len(actual),'main_seconds':round(time.perf_counter()-started,3),
                'main_score':main_match.overall_score,'jev_score':saved['skill_match']['overall_score'],
                'same_statuses':actual==previous,'main_match':main_match.model_dump(mode='json')}
        results.append(report)
        args.output.write_text(json.dumps(results,indent=2,ensure_ascii=False),encoding='utf-8')
        print(json.dumps({k:v for k,v in report.items() if k!='main_match'}),flush=True)
    assert results and all(r['same_statuses'] and r['main_score']==r['jev_score'] for r in results)

if __name__=='__main__':main()
