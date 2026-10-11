"""F3 audit contracts. Synthetic files only, no product/provider/rebuild calls."""
import re

import pytest

from scripts import audit_tmp_cleanup as audit


def entry(path, size=12):
    return {'path': path, 'bytes': size, 'mtime_ns': 1, 'group': audit.group_for(path)}


def recipe():
    return {'recipe_id': 'synthetic-reviewed-recipe', 'group': audit.RECIPE_GROUP,
        'result_xml': {'path': audit.RECIPE_XML}, 'passed_nodes': [
            {'classname': 'tests.test_remaining_cover_style', 'name': 'test_simple_style_context', 'status': 'passed'}]}


def candidate_path():
    return f'tmp/{audit.RECIPE_GROUP}/test_simple_style_context0/career.db'


def test_directory_reference_protects_all_descendants_not_similar_siblings():
    refs=[{'path':'tmp/original-run','exists':True,'protect_descendants':True}]
    assert audit.reference_hits('tmp/original-run/nested/career.db',refs)==['tmp/original-run']
    assert audit.reference_hits('tmp/original-run-other/career.db',refs)==[]


def test_missing_reference_does_not_protect_unrelated_path_or_grant_deletion():
    refs=[{'path':'tmp/missing','exists':False,'protect_descendants':False}]
    value=audit.classify(entry('tmp/unreferenced/value.bin'),refs,set(),None)
    assert value['classification']=='unproven_keep_review_required'
    assert value['deletion_eligible'] is False and value['regeneration'] is None


def test_matching_passed_case_and_source_recipe_are_required_for_review_candidate():
    value=audit.classify(entry(candidate_path()),[],set(),recipe())
    assert value['classification']=='reproducible_success_fixture_review_candidate'
    assert value['regeneration']['node']=='tests/test_remaining_cover_style.py::test_simple_style_context'
    assert not value['deletion_eligible'] and not value['database_opened']
    without=audit.classify(entry(candidate_path()),[],set(),None)
    assert without['classification']=='protected_keep'
    assert 'database_or_sidecar_ownership_unproven_preserve' in without['protection_tags']


@pytest.mark.parametrize('protection',['directory','exact','failed'])
def test_reference_or_failed_run_overrides_regeneration_recipe(protection):
    refs=[];failed=set()
    if protection=='directory':refs=[{'path':f'tmp/{audit.RECIPE_GROUP}','exists':True,'protect_descendants':True}]
    elif protection=='exact':refs=[{'path':candidate_path(),'exists':True,'protect_descendants':False}]
    else:failed={audit.RECIPE_GROUP}
    value=audit.classify(entry(candidate_path()),refs,failed,recipe())
    assert value['classification']=='protected_keep' and value['regeneration']


def test_ambiguous_prefix_unknown_file_or_skipped_case_cannot_be_candidate():
    data=recipe();data['passed_nodes'].append(dict(data['passed_nodes'][0],name='test_simple_style_context[other]'))
    # Same sanitized first30-character prefix is not a unique original owner.
    data['passed_nodes'][0]['name']='test_same_prefix_abcdefghijklmnopqrstuvwxyz[A]'
    data['passed_nodes'][1]['name']='test_same_prefix_abcdefghijklmnopqrstuvwxyz[B]'
    prefix=re.sub(r'[\W]','_',data['passed_nodes'][0]['name'])[:30]
    assert prefix==re.sub(r'[\W]','_',data['passed_nodes'][1]['name'])[:30]
    assert audit.recipe_for_file(f'tmp/{audit.RECIPE_GROUP}/{prefix}0/career.db',data) is None
    assert audit.recipe_for_file(candidate_path().replace('career.db','usage.json'),recipe()) is None
    assert audit.recipe_for_file(candidate_path().replace(audit.RECIPE_GROUP,'other'),recipe()) is None
    skipped=recipe();skipped['passed_nodes'][0]['status']='skipped'
    assert audit.recipe_for_file(candidate_path(),skipped) is None


def test_raw_ledger_screenshot_and_unproven_database_are_kept():
    for name in ['tmp/unknown/career.db','tmp/unknown/career.db-wal','tmp/unknown/usage.json','tmp/unknown/view.png']:
        value=audit.classify(entry(name),[],set(),None)
        assert value['classification']!='reproducible_success_fixture_review_candidate'
        assert value['deletion_eligible'] is False
        assert value['classification']=='protected_keep'


def test_actual_reference_types_are_derived_not_trusted_from_independent_flags(tmp_path):
    directory=tmp_path/'tmp/original';directory.mkdir(parents=True)
    source=tmp_path/'report.md';source.write_text('Evidence: `tmp/original`.',encoding='utf-8')
    independent={'references':{'tmp/missing':{'exists':True,'directory':True,'sources':['report.md']}}}
    refs,_,errors=audit.scan_references(tmp_path,[source],independent)
    values={r['path']:r for r in refs}
    assert not errors and values['tmp/original']['protect_descendants']
    assert not values['tmp/missing']['exists'] and not values['tmp/missing']['protect_descendants']


def test_report_prose_suffix_does_not_hide_existing_reference(tmp_path):
    (tmp_path/'tmp').mkdir()
    (tmp_path/'tmp/result.xml').write_text('<testsuite/>')
    source=tmp_path/'report.md';source.write_text('tmp/result.xml:107\ntmp/result.xml保留历史。',encoding='utf-8')
    refs,_,errors=audit.scan_references(tmp_path,[source],{})
    assert not errors and len(refs)==1 and refs[0]['path']=='tmp/result.xml'
    assert len(refs[0]['locations'])==2


def test_existing_unicode_filename_is_not_truncated_to_another_file(tmp_path):
    (tmp_path/'tmp').mkdir()
    (tmp_path/'tmp/result.xml').write_text('older')
    (tmp_path/'tmp/result.xml附录').write_text('separate actual file',encoding='utf-8')
    assert audit.existing_prefix(tmp_path,'tmp/result.xml附录')=='tmp/result.xml附录'


def test_failure_xml_protects_exact_case_directory_stem(tmp_path):
    directory=tmp_path/'tmp/run-before-cases-20261011';directory.mkdir(parents=True)
    xml=tmp_path/'tmp/run-before-20261011.xml'
    xml.write_text('<testsuite tests="1" failures="1" errors="0" skipped="0"><testcase name="x"><failure/></testcase></testsuite>')
    files,errors,_=audit.inventory(tmp_path)
    # Add an actual generated file so its parent group enters the inventory.
    (directory/'state.db').write_bytes(b'synthetic, not opened as SQLite')
    files,errors,_=audit.inventory(tmp_path)
    failures,read_errors=audit.failed_run_groups(tmp_path,files)
    assert not errors and not read_errors
    assert failures[0]['protected_groups']==['run-before-cases-20261011']


def test_inventory_does_not_read_database_contents(tmp_path):
    base=tmp_path/'tmp';base.mkdir()
    raw=b'not SQLite: must never be opened or rewritten'
    path=base/'recovery.db';path.write_bytes(raw)
    files,errors,_=audit.inventory(tmp_path)
    assert not errors and files[0]['bytes']==len(raw) and path.read_bytes()==raw


def test_output_refuses_overwrite(tmp_path):
    path=tmp_path/'audit.json';path.write_text('original')
    with pytest.raises(FileExistsError):audit.write_new(path,{'replacement':True})
    assert path.read_text()=='original'


def test_audit_read_errors_fail_closed_for_otherwise_reproducible_files(tmp_path,monkeypatch):
    monkeypatch.setattr(audit,'inventory',lambda root:([entry(candidate_path())],[{'error':'PermissionError'}],[]))
    monkeypatch.setattr(audit,'scan_references',lambda *args:([],[],[]))
    monkeypatch.setattr(audit,'failed_run_groups',lambda *args:([],[]))
    monkeypatch.setattr(audit,'regeneration_recipe',lambda root:recipe())
    result=audit.build_audit(tmp_path,{'files':1,'bytes':12,'groups':{}},{},sources=[])
    assert result['summary']['candidate_files']==0
    assert result['files'][0]['classification']=='unproven_keep_review_required'
    assert 'audit_errors_fail_closed' in result['files'][0]['protection_tags']
