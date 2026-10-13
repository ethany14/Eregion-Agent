"""Independent review sees only original evidence; contracts never infer meaning."""
import json
import pytest
from evals.search_semantic_audit import review,contract_checks,Audit,candidate_hash
from test_semantic_search_qualification import REQUEST,job,response
from eregion.domain.model import create_model


def audited(request,postings,personal=None):
    base=response(request,postings).model_dump()
    for d in base['decisions']:
        d['personal']=(personal or {}).get(d['posting_id'],{'status':'met','mandatory_gaps':[],
            'restricted_conditions':[],'reason':'No mandatory gap against the candidate facts.'})
    return Audit.model_validate(base)


def test_review_is_blind_bounded_and_bound_to_request_and_body(monkeypatch):
    from eregion.domain import model
    seen=[]
    def invoke(client,schema,system,content):
        payload=json.loads(content);seen.append(payload)
        assert all(set(p)=={'posting_id','title','location','description'} for p in payload['postings'])
        assert payload['candidate']=='Python SQL analyst'
        return audited(payload['request'],payload['postings'])
    monkeypatch.setattr(model,'invoke_structured',invoke)
    monkeypatch.setattr(model,'shared_model',lambda **_:object())
    jobs=[job(i,qualification={'qualified':True},match_score=100,recommendation='Do not send this') for i in range(5)]
    result=review(REQUEST,jobs,'Python SQL analyst')
    assert [len(p['postings']) for p in seen]==[4,1]
    assert all(contract_checks(jobs[0],result,REQUEST,candidate_hash('Python SQL analyst')).values())
    assert not contract_checks(jobs[0],result,REQUEST,candidate_hash('Another person'))['personal']
    assert not any(contract_checks({**jobs[0],'description':'Changed evidence'},result,REQUEST).values())
    assert not any(contract_checks(jobs[0],result,REQUEST+' Now Boston.').values())
    result[jobs[0]['url']]['checks']['seniority']['status']='unknown'
    assert not contract_checks(jobs[0],result,REQUEST)['seniority']


@pytest.mark.parametrize('settings,level', [({},'low'),({'LLM_EXTRACTION_REASONING':'medium'},'medium'),
    ({'LLM_EXTRACTION_REASONING':'high','LLM_REASONING_SEARCH_QUALIFICATION':'low'},'low')])
def test_qualification_uses_extraction_model_and_honors_reasoning_settings(tmp_path,settings,level):
    configured=create_model(env_path=tmp_path/'absent',purpose='search_qualification',environ={
        'LLM_MODEL_ID':'main','LLM_EXTRACTION_MODEL_ID':'reader',**settings},model_factory=lambda **kw:kw)
    assert configured['model']=='reader' and configured['reasoning_effort']==level


def test_personal_eligibility_is_judged_from_candidate_facts_with_exact_quotes(monkeypatch):
    from eregion.domain import model
    posting=job(1,description='Required: expert R programming. Candidates must hold French or EEA nationality. Data analysis duties.')
    gap={'requirement_quote':'Required: expert R programming.','reason':'The candidate facts show Python and SQL, not R.'}
    restricted={'requirement_quote':'Candidates must hold French or EEA nationality.','reason':'Nationality not provided.'}
    cases=[({'status':'unmet','mandatory_gaps':[gap],'restricted_conditions':[],'reason':'Mandatory R gap.'},'unmet'),
           ({'status':'unknown','mandatory_gaps':[],'restricted_conditions':[restricted],'reason':'Nationality unknown.'},'unknown'),
           # An "unmet" without a quote found in this posting is not a verified gap.
           ({'status':'unmet','mandatory_gaps':[{'requirement_quote':'Requires a PhD.','reason':'x'}],
             'restricted_conditions':[],'reason':'Unsupported.'},'unknown'),
           # "met" while listing a gap is contradictory, never a pass.
           ({'status':'met','mandatory_gaps':[gap],'restricted_conditions':[],'reason':'Contradiction.'},'unknown')]
    monkeypatch.setattr(model,'shared_model',lambda **_:object())
    for personal,expected in cases:
        monkeypatch.setattr(model,'invoke_structured',lambda c,s,p,content,personal=personal:
            audited(json.loads(content)['request'],json.loads(content)['postings'],{'0':personal}))
        row=review(REQUEST,[posting],'Python SQL analyst')[posting['url']]
        assert row['personal']['status']==expected
        assert not contract_checks(posting,{posting['url']:row},REQUEST,candidate_hash('Python SQL analyst'))['personal']
