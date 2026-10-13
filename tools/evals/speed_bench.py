"""Manual, billable fit + tailor benchmark. Never changes candidate/workspace data.

python evals/speed_bench.py --saved-inputs --output report.json
python evals/speed_bench.py --resume resume.txt --jobs jd1.txt jd2.txt jd3.txt --output report.json
All cache writes use a temporary database. Reports contain timings/counts, not source documents.
"""
import argparse
from collections import Counter
from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from eregion.api.db import create_database
from eregion.api.services.fit_analysis_service import FitAnalysisService
from eregion.runtime.analysis_cache import AnalysisCache
from eregion.domain.workflow.handlers import SharedModelAnalyzer, JobAgentStepHandler
from eregion.domain.workflow.state import AgentState, Step

def saved_inputs(database_url):
    from sqlalchemy import select
    from pypdf import PdfReader
    from eregion.runtime.auto_apply.models import SavedCandidateRow
    from eregion.runtime.workspace.models import JobSnapshotRow
    db = create_database(database_url)
    try:
        with db.session_factory() as session:
            candidate = session.get(SavedCandidateRow, 'local')
            if not candidate or not candidate.resume_bytes:
                raise ValueError('No saved candidate resume; use --resume and --jobs.')
            resume = '\n\n'.join((page.extract_text() or '').strip() for page in PdfReader(BytesIO(candidate.resume_bytes)).pages).strip()
            descriptions, seen = [], set()
            for row in session.scalars(select(JobSnapshotRow).order_by(JobSnapshotRow.captured_at.desc())):
                if row.content_hash not in seen and len(row.cleaned_job_description) > 100:
                    descriptions.append(row.cleaned_job_description)
                    seen.add(row.content_hash)
                if len(descriptions) == 3:
                    break
            if len(descriptions) != 3:
                raise ValueError('Three saved job descriptions are required.')
            return resume, descriptions
    finally:
        db.close()

class MeasuredAnalyzer(SharedModelAnalyzer):
    def __init__(self):
        super().__init__()
        self.calls, self.stages = Counter(), []
    def __call__(self, schema, system, human):
        start = time.perf_counter()
        self.calls[schema.__name__] += 1
        try:
            return super().__call__(schema, system, human)
        finally:
            self.stages.append({'stage': schema.__name__, 'seconds': round(time.perf_counter()-start, 3)})
    def write_resume(self, state, content):
        self.calls['ResumeSelection'] += 1
        return super().write_resume(state, content)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--saved-inputs', action='store_true')
    parser.add_argument('--database-url')
    parser.add_argument('--resume', type=Path)
    parser.add_argument('--jobs', type=Path, nargs=3)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.saved_inputs:
        resume, jobs = saved_inputs(args.database_url)
    elif args.resume and args.jobs:
        resume = args.resume.read_text(encoding='utf-8')
        jobs = [p.read_text(encoding='utf-8') for p in args.jobs]
    else:
        parser.error('Choose --saved-inputs or --resume plus three --jobs.')
    report = {'kind': 'live-model-fit-tailor', 'runs': []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='eregion-bench-') as directory:
        db = create_database('sqlite:///' + (Path(directory)/'analysis.db').as_posix(), create_schema_for_tests=True)
        try:
            analyzer = MeasuredAnalyzer()
            handler = JobAgentStepHandler(analyzer=analyzer, analysis_cache=AnalysisCache(db.session_factory))
            # Native analyzer with the same configured Jev routing as production.
            from eregion.runtime.fast_decisions import configured_decisions
            handler._decisions = configured_decisions(scope='career')
            service = FitAnalysisService(handler)
            for index, job in enumerate(jobs, 1):
                run = {'case': index}
                try:
                    fit = service._analyze_sync(resume_text=resume, job_description=job)
                    run.update(fit_seconds=round(fit.latency_seconds, 3), fit_stages=fit.stage_seconds,
                        fit_cache_hits=fit.cache_hits, score=fit.skill_match.overall_score)
                    print(json.dumps({'case': index, 'fit': run['fit_seconds'], 'stages':fit.stage_seconds}), flush=True)
                    # New services + caches emulate restart against the same durable store.
                    restart = FitAnalysisService(JobAgentStepHandler(analyzer=analyzer,
                        decisions=handler._decisions, analysis_cache=AnalysisCache(db.session_factory)))
                    warm = restart._analyze_sync(resume_text=resume, job_description=job)
                    run.update(restart_fit_seconds=round(warm.latency_seconds, 3), restart_model_calls=warm.model_calls)
                    before = sum(analyzer.calls.values())
                    state = AgentState(run_id=f'bench-{index}', resume_text=resume, job_description=job)
                    stage_times = {}
                    run['tailor_stages'] = stage_times
                    for step in (Step.ANALYZE_RESUME, Step.VALIDATE_EVIDENCE, Step.ANALYZE_JOB, Step.MATCH_SKILLS):
                        state = state.model_copy(update=handler.execute(step, state).updates)
                    run['tailor_analysis_model_calls'] = sum(analyzer.calls.values()) - before
                    for step in (Step.WRITE_RESUME, Step.VERIFY_RESUME):
                        start = time.perf_counter()
                        state = state.model_copy(update=handler.execute(step, state).updates)
                        stage_times[step.value] = round(time.perf_counter()-start, 3)
                        print(json.dumps({'case':index, 'stage':step.value, 'seconds':stage_times[step.value]}), flush=True)
                    if not state.verification.passed:
                        for step in (Step.REVISE_RESUME, Step.VERIFY_RESUME):
                            start = time.perf_counter()
                            state = state.model_copy(update=handler.execute(step, state).updates)
                            stage_times[step.value + '_revision'] = round(time.perf_counter()-start, 3)
                    run.update(tailor_stages=stage_times, verified=state.verification.passed,
                        tailor_seconds=round(sum(stage_times.values()), 3))
                except Exception as exc:
                    run['error_type'] = type(exc).__name__
                    from eregion.runtime.telemetry import safe_traceback
                    print(safe_traceback(exc), flush=True)
                report['runs'].append(run)
                report['model_calls'] = dict(analyzer.calls)
                args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
                print(json.dumps(run), flush=True)
        finally:
            db.close()

if __name__ == '__main__':
    main()
