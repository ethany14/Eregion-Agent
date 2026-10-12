"""Opt-in paid A/B using synthetic data only; no applications or user DB changes.

Run: python scripts/benchmark_token_efficiency.py --live --output <directory>
Both variants use the configured main model. Compares fixed-six/adaptive matching
and duplicate/consolidated resume validation. Provider-reported counts are saved.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_runtime.application_pack.types import EvidenceSnapshotItem
from agent_runtime.application_pack.verifier import ArtifactVerifier
from agent_runtime.application_pack.verification import verify_material_resume
from agent_runtime.application_pack.workflow import SharedPackModel
from agent_runtime.fast_decisions import FastDecisions
from agent_runtime.provider_usage import UsageLedger, usage_scope
from api.db import create_database
from job_agent.workflow.handlers import SharedModelAnalyzer
from job_agent.workflow.state import AgentState
from job_agent.fast_match import assess_skills
from job_agent.prompts import MATCH_PROMPT
from job_agent.schemas import (ResumeAnalysis, ResumeEvidence, JobAnalysis, JobRequirement,
    ResumeSourceEntry, ResumeSection, ResumeEntry, SupportedClaim, TailoredResume, SkillAssessment)


def fixtures():
    skills = ['Python APIs', 'SQL reports', 'React interfaces', 'Docker images', 'Git workflows',
              'Linux scripts', 'Pandas transformations', 'PostgreSQL queries', 'Pytest suites']
    absent = ['Kubernetes clusters', 'Rust services', 'Swift apps', 'Tableau dashboards', 'Power BI reports',
              'Oracle databases', 'Terraform modules', 'Scala pipelines', 'Unity games']
    quotes = [f'Built {skill} for the internal Atlas project. Maintained tests and documentation for this work.'
              for skill in skills]
    resume = ResumeAnalysis(summary='Synthetic developer', skills=skills, education=[],
        evidence=[ResumeEvidence(evidence_id=f'e{i}', exact_text=quote, source_section='Experience',
            source_entry_id='s') for i, quote in enumerate(quotes)],
        source_entries=[ResumeSourceEntry(source_entry_id='s', entry_type='experience', heading='Developer',
            organization='Synthetic Atlas', evidence_ids=[f'e{i}' for i in range(len(quotes))])])
    requirements = [JobRequirement(requirement_id=f'r{i}', canonical_name=skill,
        original_text=f'Build {skill}.', level='required', category='responsibility')
        for i, skill in enumerate(skills + absent)]
    job = JobAnalysis(title='Software Engineer', summary='Synthetic benchmark role',
        requirements=requirements, responsibilities=[])
    draft = TailoredResume(sections=[ResumeSection(section_type='experience', title='Experience', entries=[
        ResumeEntry(entry_id='s', heading='Developer', subheading='Synthetic Atlas', bullets=[
            SupportedClaim(text='Developed Python APIs for the internal Atlas project and maintained their tests and documentation.',
                           evidence_ids=['e0'], source_entry_id='s')])])])
    state = AgentState(run_id='synthetic', resume_text='Developer\nSynthetic Atlas\n'+'\n'.join(quotes),
        job_description='Software Engineer\n'+'\n'.join(r.original_text for r in requirements),
        resume_analysis=resume, job_analysis=job, tailored_resume=draft)
    evidence = [EvidenceSnapshotItem(evidence_id=f'e{i}', evidence_version_id=f'e{i}', content_hash='synthetic',
        source_type='resume', selection_reason='benchmark', associated_requirement_ids=[],
        claim_text=quote, exact_quote=quote) for i, quote in enumerate(quotes)]
    return state, evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    # Exclusive new database avoids mixing results with an earlier execution.
    path = args.output / 'usage.sqlite'
    if path.exists():
        parser.error('Use a new output directory for each benchmark.')
    db = create_database('sqlite:///'+path.as_posix(), create_schema_for_tests=True)
    ledger, analyzer = UsageLedger(db.session_factory), SharedModelAnalyzer()
    state, evidence = fixtures()
    model = SharedPackModel()
    verifier = ArtifactVerifier(model.verify_claims)
    check = lambda: verifier.verify(state.tailored_resume.model_dump(), 'tailored_resume', evidence,
                                    employer_context=state.job_description)

    def legacy_match():
        def chunk(items):
            job = state.job_analysis.model_copy(update={'requirements':items})
            return analyzer(SkillAssessment, MATCH_PROMPT,
                f'Resume analysis:\n{state.resume_analysis.model_dump_json()}\n\nJob analysis:\n{job.model_dump_json()}')
        requirements = state.job_analysis.requirements
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(copy_context().run, chunk, requirements[i:i+6])
                       for i in range(0, len(requirements), 6)]
            matches = [match for future in futures for match in future.result().matches]
        return matches

    def legacy_resume():
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(copy_context().run, model.verify_resume, state)
            return check().passed and future.result().passed

    variants = [
        ('match_fixed_six', legacy_match),
        ('match_adaptive', lambda: assess_skills(state.resume_analysis, state.job_analysis,
            analyzer, FastDecisions()).matches),
        ('resume_duplicate_checks', legacy_resume),
        ('resume_consolidated', lambda: verify_material_resume(state, model, check).passed),
    ]
    results = []
    try:
        for name, run in variants:
            start = time.monotonic()
            result = {'variant':name}
            try:
                with usage_scope(ledger=ledger, task_id=name, purpose=name):
                    output = run()
                if name.startswith('match_'):
                    result['statuses'] = {m.requirement_id:m.match_status for m in output}
                    expected = {f'r{i}':'matched' if i < 9 else 'missing' for i in range(18)}
                    result['correct'] = result['statuses'] == expected
                    result['known_quotes_only'] = all(q in {e.exact_text for e in state.resume_analysis.evidence}
                                                      for m in output for q in m.resume_evidence)
                else:
                    result['correct'] = output is True
            except Exception as exc:
                result.update(correct=False, error_type=type(exc).__name__)
            result.update(seconds=round(time.monotonic()-start,3), usage=ledger.summary(task_id=name))
            results.append(result)
            (args.output/'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
            print(json.dumps(result), flush=True)
    finally:
        db.close()


if __name__ == '__main__':
    main()
