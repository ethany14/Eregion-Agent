"""Preflight the whole batch before any scheduled provider work; offline spies."""
import asyncio
from dataclasses import replace
import hashlib
from types import SimpleNamespace

import pytest

from eregion.api.services.fit_analysis_service import FitAnalysisService
from eregion.domain.requirement_catalog import FrozenRequirementCatalog
from test_remaining_catalog_identity import job, BODY
from test_jev_fit_production import NoMainModel


def frozen():
    target=job()
    match=SimpleNamespace(algorithm='jev-only',decision_details={
        'jd_sha256':hashlib.sha256(BODY.encode()).hexdigest(),
        'extraction':[{'id':'REQ-python','start':0,'end':len('Requires Python.')}]},
        matches=[SimpleNamespace(requirement_id='REQ-python',requirement_level='required')])
    return FrozenRequirementCatalog.from_jev_result(SimpleNamespace(job_analysis=target,skill_match=match),
        BODY,producer_signature='offline-batch-v1',provenance='Synthetic local factory, no provider')


@pytest.mark.parametrize('kind',['valid','invalid_type','stale','wrong_body'])
def test_jev_batch_rejects_every_fixed_catalogue_before_scheduler_like_single(monkeypatch,kind):
    catalog=frozen()
    if kind=='invalid_type':catalog={'catalogue':'untrusted'}
    elif kind=='stale':catalog=replace(catalog,catalogue_version='old')
    calls=[]
    service=FitAnalysisService(NoMainModel(),jev_enabled=True)
    monkeypatch.setattr(service,'_jev_many_sync',lambda **kwargs:calls.append(kwargs) or {})
    body=BODY+' changed' if kind=='wrong_body' else BODY
    with pytest.raises(ValueError):
        asyncio.run(service.analyze_many(resume_text='Candidate',jobs=[
            {'id':'plain','job_description':BODY},
            {'id':'fixed','job_description':body,'fixed_job_catalog':catalog}]))
    assert calls==[]
    with pytest.raises(ValueError):
        asyncio.run(service.analyze(resume_text='Candidate',job_description=body,fixed_job_catalog=catalog))
    assert calls==[]


@pytest.mark.parametrize('kind',['invalid_type','stale','wrong_body'])
def test_main_batch_mixed_valid_invalid_is_rejected_before_any_worker(monkeypatch,kind):
    catalog=frozen();invalid=catalog
    if kind=='invalid_type':invalid={'catalogue':'untrusted'}
    elif kind=='stale':invalid=replace(catalog,catalogue_version='old')
    calls=[]
    service=FitAnalysisService(NoMainModel(),jev_enabled=False)
    monkeypatch.setattr(service,'_analyze_sync',lambda **kwargs:calls.append(kwargs) or None)
    with pytest.raises(ValueError):
        asyncio.run(service.analyze_many(resume_text='Candidate',jobs=[
            {'id':'valid','job_description':BODY,'fixed_job_catalog':catalog},
            {'id':'invalid','job_description':BODY+' changed' if kind=='wrong_body' else BODY,'fixed_job_catalog':invalid}]))
    assert calls==[]
