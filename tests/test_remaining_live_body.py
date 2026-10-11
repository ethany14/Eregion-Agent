"""Paid Jev check of the exact contaminated posting, with synthetic evidence."""
from dataclasses import replace
import hashlib
import json
import os

import pytest

from agent_runtime.career.discovery import JobDiscovery
from job_agent.jev_fit.service import JevFitService
from job_agent.jev_fit.settings import Settings
from scripts.e2e_repair_evaluation import APPLICANTS

pytestmark=pytest.mark.skipif(os.getenv('JOB_AGENT_LIVE_REMAINING')!='1',reason='Explicit paid Jev check')


def test_original_python_posting_scoring_is_isolated_from_related_companies(tmp_path):
    url='https://www.python.org/jobs/8113/'
    discovery=JobDiscovery()
    html,actual_url=discovery.read(url)
    (tmp_path/'source.html').write_text(html,encoding='utf-8')
    discovery.read=lambda _: (html,actual_url)
    clean=discovery.job(url)
    changed=html.replace('Fusionbox','Unrelated Company Requiring Ten Years of Rust').replace('Turing','Another Unrelated Employer')
    discovery.read=lambda _: (changed,actual_url)
    variant=discovery.job(url)
    assert clean['description']==variant['description']
    assert 'Fusionbox' not in clean['description'] and 'No Agencies Please' in clean['description']
    config=replace(Settings.load(cache_path=tmp_path/'isolated-fit.sqlite3'),resolve_unknowns=False)
    fit=JevFitService(config,owner='synthetic-body-audit')
    cold=fit.analyze_many(resume_text=APPLICANTS['backend'],jobs=[{'id':'original','job_description':clean['description']}])['original']
    # A new service instance proves persistent reuse, not a process-local shortcut.
    warm=JevFitService(config,owner='synthetic-body-audit').analyze_many(resume_text=APPLICANTS['backend'],
        jobs=[{'id':'variant','job_description':variant['description']}])['variant']
    result={'url':url,'source_sha256':hashlib.sha256(html.encode()).hexdigest(),'clean_job':clean,
        'cold':{k:v.model_dump(mode='json') if hasattr(v,'model_dump') else v for k,v in cold.items()},
        'variant':{k:v.model_dump(mode='json') if hasattr(v,'model_dump') else v for k,v in warm.items()}}
    (tmp_path/'real-jev-body-evidence.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'score':cold['skill_match'].overall_score,'calls':cold['model_calls'],
        'routing':cold['decision_routing'],'variant_calls':warm['model_calls']},ensure_ascii=True),flush=True)
    assert cold['main_model_calls']==warm['main_model_calls']==0
    assert warm['model_calls']==0
    assert cold['skill_match'].overall_score==warm['skill_match'].overall_score
    assert [r.original_text for r in cold['job_analysis'].requirements]==[r.original_text for r in warm['job_analysis'].requirements]
    assert not any('Fusionbox' in r.original_text or 'No Agencies' in r.original_text for r in cold['job_analysis'].requirements)
    assert any('Python' in r.original_text for r in cold['job_analysis'].requirements)
