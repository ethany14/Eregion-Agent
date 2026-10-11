"""Evaluation math/coverage contracts only; synthetic test labels are NOT human gold."""
from copy import deepcopy
import json
from pathlib import Path
import pytest

from evals.run_fit_labels import evaluate, validate, validate_predictions, metrics, auc, freeze_manifest, validate_manifest


@pytest.fixture
def dataset():
    return json.loads(Path('evals/fit_labels_v1.json').read_text(encoding='utf-8'))


def test_real_source_cohort_is_complete_but_no_human_quality_is_claimed(dataset):
    report=evaluate(dataset,[])
    assert not report['validation']['errors']
    assert report['status']=='pending_human_review'
    assert report['coverage']['actual_pairs']==72
    assert report['coverage']['missing_rows']==288
    assert report['coverage']['human_reviews_pending']==96  # 12 source + 12 requirement + 72 pair
    assert all(value is None for group in report['quality_metrics'].values() for value in group.values())
    assert all(value['acceptance']=='not_evaluable' for value in report['format_delta'].values())
    assert report['overall_acceptance']=='not_passed'
    assert dataset['read_errors'][0]['status']=='source_read_failed_not_empty'


def reviewed_for_math(data):
    """In-memory invented labels for unit tests; never written into the cohort."""
    data=deepcopy(data)
    review={'status':'confirmed','reviewer':{'kind':'human','name':'SYNTHETIC TEST REVIEWER','confirmed_at':'2026-10-11T00:00:00Z'}}
    for j in data['jobs']:
        j['source']['human_review']=review
        j['requirements_review']={'status':review['status'],'reviewer':review['reviewer'],
            'requirements':[{'requirement_id':'human-r1','quote':j['structured'][:30],
                'source_start':0,'source_end':30,'atomic_text':'Synthetic math requirement','level':'required'}]}
    people={a['applicant_id']:a for a in data['applicants']}
    fits={a['applicant_id'] for a in data['applicants'][:3]}
    for p in data['pairs']:
        p['review']=review;p['labelled_score']=80 if p['applicant_id'] in fits else 20
        p['fit_label']='fit' if p['applicant_id'] in fits else 'mismatch'
        p['requirement_statuses']=[{'requirement_id':'human-r1','status':'matched',
            'resume_quotes':[people[p['applicant_id']]['resume'].splitlines()[0]],'rationale':'Synthetic test fixture only'}]
    return data


def prediction(data,pair,algorithm='main',form='structured'):
    from api.services.fit_analysis_service import FitAnalysisResult
    people={a['applicant_id']:a for a in data['applicants']};jobs={j['job_id']:j for j in data['jobs']}
    j=jobs[pair['job_id']];quote=j['structured'][:30]
    result=FitAnalysisResult.model_validate({'analysis_id':'synthetic-math-fixture','latency_seconds':0,
        'resume_analysis':{'summary':'Synthetic','skills':[],'evidence':[],'education':[]},
        'job_analysis':{'title':j['title'],'summary':'Synthetic','responsibilities':[],
            'requirements':[{'requirement_id':'predicted-r1','canonical_name':'test','original_text':quote,
                'atomic_text':'Synthetic math requirement','level':'required'}]},
        'skill_match':{'matches':[{'requirement_id':'predicted-r1','job_skill':'test','requirement_level':'required',
            'match_status':'matched','resume_evidence':[],'confidence':1}],
            'explanation':'Synthetic math fixture','recommendations':[],
            'missing_required_requirements':[],'missing_preferred_requirements':[],'overall_score':pair['labelled_score']}})
    manifest=math_manifest(data)
    return {'pair_id':pair['pair_id'],'applicant_id':pair['applicant_id'],'job_id':pair['job_id'],
        'run_id':manifest['run_id'],'manifest_sha256':manifest['manifest_sha256'],
        'scoring_signature':manifest['algorithms'][algorithm]['production_cache_signature'],
        'algorithm':algorithm,'format':form,'resume_sha256':people[pair['applicant_id']]['resume_sha256'],
        'job_sha256':j[form+'_sha256'],'result':result.model_dump(mode='json')}


def math_manifest(data,main='synthetic-main-v1'):
    return freeze_manifest(data,{'main':main,'jev':'synthetic-jev-v1'},
        run_id='synthetic-math-only',created_at='2026-10-11T00:00:00Z')


def test_all_metric_math_and_format_delta_on_complete_synthetic_labels(dataset):
    data=reviewed_for_math(dataset)
    rows=[prediction(data,p,a,f) for p in data['pairs'] for a in ('main','jev') for f in ('structured','flat')]
    manifest=math_manifest(data)
    report=evaluate(data,rows,manifest)
    assert report['status']=='evaluated' and not report['prediction_errors']
    for groups in report['quality_metrics'].values():
        for m in groups.values():
            assert m['requirement_precision']==m['requirement_recall']==m['status_accuracy']==m['level_accuracy']==1
            assert m['score_mae']==0 and m['mismatch_fit_auc']==1
    assert all(v['within_10_fraction']==1 for v in report['format_delta'].values())
    assert report['overall_acceptance']=='not_passed'  # A1 concurrency/baseline gates remain unmeasured.
    rows.pop()
    missing=evaluate(data,rows,manifest)
    assert missing['status']=='incomplete_predictions' and missing['quality_metrics']['main']['flat'] is None


@pytest.mark.parametrize('mutate',[
    lambda d:d['pairs'].pop(),
    lambda d:d['pairs'].append(d['pairs'][0]),
    lambda d:d['jobs'][0].update(flat=d['jobs'][0]['flat']+' added skill'),
    lambda d:d['thresholds'].update(format_delta_max=20),
    lambda d:d['jobs'][0]['source']['boundary_checks'].update(single_record_body=False),
])
def test_strict_cohort_scope_source_and_threshold_validation(dataset,mutate):
    mutate(dataset)
    assert validate(dataset)['errors']


@pytest.mark.parametrize('mutation',[
    lambda d:d['pairs'][0]['review']['reviewer'].update(kind='model'),
    lambda d:d['pairs'][0].update(requirement_statuses=[]),
    lambda d:d['pairs'][0].update(labelled_score=None),
    lambda d:d['pairs'][0]['requirement_statuses'][0].update(resume_quotes=['invented experience']),
    lambda d:d['jobs'][0]['requirements_review']['requirements'][0].update(source_end=31),
])
def test_no_model_gold_or_missing_gold_or_forged_citations(dataset,mutation):
    data=reviewed_for_math(dataset);mutation(data)
    assert validate(data)['errors']
    assert evaluate(data,[])['status']=='invalid'


def test_duplicate_stale_and_malformed_cached_results_fail_closed(dataset):
    data=reviewed_for_math(dataset);row=prediction(data,data['pairs'][0])
    manifest=math_manifest(data)
    assert validate_predictions(data,[row,row],manifest)
    stale=deepcopy(row);stale['job_sha256']='old-polluted-body'
    assert validate_predictions(data,[stale],manifest)
    malformed=deepcopy(row);malformed['result']['job_analysis']['requirements'][0].pop('requirement_id')
    assert validate_predictions(data,[malformed],manifest)


def test_unsigned_mixed_and_old_same_text_signature_are_rejected_but_history_is_offline_valid(dataset):
    data=reviewed_for_math(dataset);row=prediction(data,data['pairs'][0]);manifest=math_manifest(data)
    assert validate_predictions(data,[row])  # Missing frozen run.
    unsigned=deepcopy(row);unsigned.pop('scoring_signature')
    assert validate_predictions(data,[unsigned],manifest)
    mixed=deepcopy(row);mixed['scoring_signature']='synthetic-main-v2'
    assert validate_predictions(data,[mixed],manifest)
    mixed_id=deepcopy(row);mixed_id['run_id']='another-run'
    assert validate_predictions(data,[mixed_id],manifest)
    changed=math_manifest(data,main='synthetic-main-v2')
    assert validate_manifest(data,manifest,changed)  # Exact same JD/resume, changed prompt/model/schema signature.
    assert not validate_manifest(data,manifest)
    assert not validate_predictions(data,[row],manifest)
    report=evaluate(data,[row],manifest)
    assert not report['prediction_errors'] and report['run_manifest']==manifest
    assert 'Historical frozen run' in report['version_scope']
    assert report['status']=='incomplete_predictions'


def test_omissions_duplicates_wrong_level_status_and_interval_are_not_free_passes(dataset):
    data=reviewed_for_math(dataset)
    rows=[prediction(data,p) for p in data['pairs']]
    r=rows[0]['result'];r['job_analysis']['requirements'].append(deepcopy(r['job_analysis']['requirements'][0]))
    r['skill_match']['matches'][0]['match_status']='missing'
    r['job_analysis']['requirements'][0]['level']='preferred'
    r['skill_match']['overall_score']=None;r['skill_match']['score_range']=[20,60]
    m=metrics(data,rows,'main','structured')
    assert m['requirement_precision']<1 and m['status_accuracy']<1 and m['level_accuracy']<1
    assert m['score_mae'] is None and m['missing_or_interval_only_scores']==1
    assert auc(['fit','mismatch'],[50,50])==.5
    assert auc(['fit'],[90]) is None


@pytest.mark.parametrize('mode,precision,recall',[
    ('unique_atomic',1,1),('approved_alias',1,1),('alias_collision',0,0),
    ('shared_quote_only',0,0),('duplicate_atomic',.5,.5),('missing_atomic',1,.5)])
def test_shared_quote_is_not_atomic_identity_or_duplicate_permission(dataset,mode,precision,recall):
    # Invented in-memory math labels only, never real cohort human gold.
    data=reviewed_for_math(dataset)
    for job in data['jobs']:
        first=job['requirements_review']['requirements'][0]
        first['atomic_text']='Synthetic Python requirement'
        job['requirements_review']['requirements'].append({**first,'requirement_id':'human-r2',
            'atomic_text':'Synthetic SQL requirement'})
        if mode=='approved_alias':job['requirements_review']['requirements'][1]['accepted_prediction_texts']=['Synthetic approved SQL alias']
        if mode=='alias_collision':
            for r in job['requirements_review']['requirements']:r['accepted_prediction_texts']=['Synthetic ambiguous alias']
    rows=[]
    for pair in data['pairs']:
        pair['requirement_statuses'].append({**pair['requirement_statuses'][0],'requirement_id':'human-r2'})
        row=prediction(data,pair);requirements=row['result']['job_analysis']['requirements']
        requirements[0]['atomic_text']='Synthetic Python requirement'
        requirements.append({**requirements[0],'requirement_id':'predicted-r2','atomic_text':'Synthetic SQL requirement'})
        row['result']['skill_match']['matches'].append({**row['result']['skill_match']['matches'][0],'requirement_id':'predicted-r2'})
        if mode=='shared_quote_only':
            for r in requirements:r['atomic_text']=r['original_text']
        elif mode=='duplicate_atomic':requirements[1]['atomic_text']=requirements[0]['atomic_text']
        elif mode=='missing_atomic':requirements.pop()
        elif mode=='approved_alias':requirements[1]['atomic_text']='Synthetic approved SQL alias'
        elif mode=='alias_collision':
            for r in requirements:r['atomic_text']='Synthetic ambiguous alias'
        rows.append(row)
    assert not validate(data)['errors']
    assert not validate_predictions(data,rows,math_manifest(data))
    result=metrics(data,rows,'main','structured')
    assert result['gold_requirements']==144
    assert result['requirement_precision']==precision and result['requirement_recall']==recall
    assert result['status_accuracy']==recall and result['level_accuracy']==recall


def test_live_pipeline_attribution_checkpoint_and_no_silent_failure_retry(dataset,tmp_path,monkeypatch):
    """Exercise live orchestration with explicit offline providers, not paid accuracy."""
    import api.services.fit_analysis_service as module
    from evals.run_fit_labels import live_rows
    calls=[]
    class OfflineService:
        def __init__(self,*a,**kw):pass
        def cache_signature(self):return 'offline-contract-test'
        def _analyze_sync(self,**kwargs):
            calls.append(kwargs);raise RuntimeError('synthetic provider outage')
    monkeypatch.setattr(module,'FitAnalysisService',OfflineService)
    output=tmp_path/'predictions.json'
    cache=live_rows(dataset,{'manifest':None,'rows':[]},output,limit=1)
    rows=cache['rows']
    assert len(calls)==1 and len(rows)==1 and rows[0]['error_type']=='RuntimeError'
    assert rows[0]['task_id'] and rows[0]['usage']['pending']==0
    assert json.loads(output.read_text(encoding='utf-8'))==cache
    # Prior failure remains intact; only the next format is attempted.
    second=live_rows(dataset,cache,output,limit=1)['rows']
    assert len(calls)==2 and second[0]==rows[0] and second[1]['format']=='flat'
    prior=output.read_bytes()
    monkeypatch.setattr(OfflineService,'cache_signature',lambda self:'offline-contract-v2')
    with pytest.raises(ValueError,match='new run path'):
        live_rows(dataset,cache,output,limit=1)
    assert len(calls)==2 and output.read_bytes()==prior
