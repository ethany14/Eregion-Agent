"""Live synthetic extraction holdout: dual education, dates and eligibility."""
import json,sys,time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from eregion.domain.workflow.handlers import JobAgentStepHandler
from eregion.domain.workflow.state import AgentState, Step
RESUME='''Synthetic Candidate - Example Person
Experience
Example Lab - Software Developer
January 2022 - May 2024
Built Python APIs and SQL reporting pipelines.
Education
Example University - Bachelor of Science in Computer Science
August 2018 - May 2022
Example Institute - Master of Science in Systems Engineering
August 2025 - Expected May 2027
Skills
Python, SQL, Git
'''
JOB='''Software Engineer - Example Company
Required qualifications:
Python and SQL programming.
At least 3 years of professional software engineering experience.
A completed bachelor's degree in Computer Science.
Must be authorized to work in the United States.
Preferred qualifications:
Experience with Docker and Kubernetes.
Responsibilities:
Build REST APIs and collaborate with product designers.
'''
handler=JobAgentStepHandler();state=AgentState(run_id='synthetic-quality',resume_text=RESUME,job_description=JOB)
started=time.monotonic()
with ThreadPoolExecutor(max_workers=2) as pool:
    r=pool.submit(handler.execute,Step.ANALYZE_RESUME,state);j=pool.submit(handler.execute,Step.ANALYZE_JOB,state)
    resume=r.result().updates['resume_analysis'];job=j.result().updates['job_analysis']
handler._validate_evidence(state.model_copy(update={'resume_analysis':resume}))
education=[e for e in resume.source_entries if e.entry_type=='education']
assert len(education)==2
assert {e.organization for e in education}=={'Example University','Example Institute'}
assert all(e.heading and e.start_date and e.end_date for e in education)
assert any('2027' in e.end_date for e in education)
assert any(r.minimum_years==3 and r.verification_mode.value=='years_experience' for r in job.requirements)
assert any(r.verification_mode.value=='user_confirmation' and 'authorized' in r.source_text for r in job.requirements)
assert sum(r.category.value=='responsibility' for r in job.requirements)>=2
assert {'python','sql','docker','kubernetes'}.issubset({r.canonical_name.lower() for r in job.requirements})
report={'seconds':round(time.monotonic()-started,3),'education_entries':len(education),
        'metadata_and_verbatim_quotes_valid':True,'explicit_years_preserved':True,'authorization_requires_confirmation':True,
        'responsibilities_preserved':True,'requirement_count':len(job.requirements)}
print(json.dumps(report))
