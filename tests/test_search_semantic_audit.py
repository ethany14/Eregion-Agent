"""Independent review sees only original evidence; contracts never infer meaning."""
import json
import pytest
from evals.search_semantic_audit import review,contract_checks
from test_semantic_search_qualification import REQUEST,job,response
from eregion.domain.model import create_model


def test_review_is_blind_bounded_and_bound_to_request_and_body(monkeypatch):
    from eregion.domain import model
    seen=[]
    def invoke(client,schema,system,content):
        payload=json.loads(content);seen.append(payload)
        assert all(set(p)=={'posting_id','title','location','description'} for p in payload['postings'])
        return response(payload['request'],payload['postings'])
    monkeypatch.setattr(model,'invoke_structured',invoke)
    monkeypatch.setattr(model,'shared_model',lambda **_:object())
    jobs=[job(i,qualification={'qualified':True},match_score=100,recommendation='Do not send this') for i in range(5)]
    result=review(REQUEST,jobs)
    assert [len(p['postings']) for p in seen]==[4,1]
    assert all(contract_checks(jobs[0],result,REQUEST).values())
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
