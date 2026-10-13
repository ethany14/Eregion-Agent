"""Complete catalogue identity and trusted binding; all inputs are offline."""
import pytest

from evals.audit_fit_catalog import freeze_catalog, compare_catalog
from eregion.domain.schemas import JobAnalysis

BODY='Requires Python. Requires Rust.'


def job():
    return JobAnalysis(title='Engineer',summary='Build APIs',responsibilities=['Build APIs'],requirements=[{
        'requirement_id':'REQ-python','canonical_name':'python','display_name':'Python',
        'original_text':'Requires Python.','source_text':'Requires Python.','atomic_text':'Python','level':'required'}])


@pytest.mark.parametrize('field,value',[
    ('canonical_name','rust'),('display_name','Rust'),('original_text','Requires Rust.'),
    ('requirement_id','REQ-new'),('requirement_group_id','group-new'),
    ('source_text','Requires Rust.'),('atomic_text','Rust'),('minimum_years',5),
    ('verification_mode','years_experience'),('category','experience'),('level','preferred')])
def test_every_requirement_field_affects_identity(field,value):
    a=job();b=a.model_copy(deep=True)
    b.requirements[0]=type(b.requirements[0]).model_validate({**b.requirements[0].model_dump(),field:value})
    left=freeze_catalog(a,BODY,provenance='offline')
    right=freeze_catalog(b,BODY,provenance='offline')
    assert left['catalogue_sha256']!=right['catalogue_sha256']
    assert not compare_catalog(left,right)['exact_catalogue_agreement']


@pytest.mark.parametrize('field,value',[('title','Other Engineer'),('summary','Other'),('responsibilities',['Other'])])
def test_job_payload_metadata_is_also_frozen(field,value):
    a=job();b=a.model_copy(deep=True);setattr(b,field,value)
    left=freeze_catalog(a,BODY,provenance='offline');right=freeze_catalog(b,BODY,provenance='offline')
    assert left['catalogue_sha256']!=right['catalogue_sha256']
    assert not compare_catalog(left,right)['exact_catalogue_agreement']


def test_descriptive_provenance_does_not_change_semantic_identity():
    a=freeze_catalog(job(),BODY,provenance='saved artifact')
    b=freeze_catalog(job(),BODY,provenance='restart replay')
    assert a['catalogue_sha256']==b['catalogue_sha256']
    assert compare_catalog(a,b)['exact_catalogue_agreement']


def test_incomplete_legacy_or_mutated_audit_payload_cannot_claim_agreement():
    from copy import deepcopy
    frozen=freeze_catalog(job(),BODY,provenance='offline')
    old={'requirements':frozen['requirements'],'body_sha256':frozen['body_sha256']}
    with pytest.raises(ValueError,match='historical'):compare_catalog(old,old)
    changed=deepcopy(frozen);changed['requirements'][0]['canonical_name']='rust'
    with pytest.raises(ValueError,match='identity'):compare_catalog(frozen,changed)


def test_full_field_set_and_duplicate_source_ids_are_explicit():
    a=job();frozen=freeze_catalog(a,BODY,provenance='offline')
    assert frozen['requirements'][0]==a.requirements[0].model_dump(mode='json')
    assert frozen['job_analysis']==a.model_dump(mode='json')
    a.requirements.append(a.requirements[0].model_copy(deep=True))
    with pytest.raises(ValueError,match='Duplicate'):freeze_catalog(a,BODY,provenance='offline')
