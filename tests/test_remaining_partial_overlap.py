"""Synthetic resolver decisions exercise a necessary relevance gate, not AUC."""
import re

import pytest

from eregion.domain.jev_fit import resolve
from test_e2e_followups import raw_with_unknowns


@pytest.fixture(autouse=True)
def offline_identity(monkeypatch):
    monkeypatch.setattr(resolve,'identity',lambda _: 'offline-partial-contract-v1')


def decision(rid,quote):
    return resolve.UnknownDecision(requirement_id=rid,is_candidate_requirement=True,
        level='required',personal_condition=False,status='partial',evidence_quote=quote,
        reason='Synthetic decision; relevant component only, remaining scope not demonstrated.')


@pytest.mark.parametrize('requirement,quote,status',[
    ('Financial forecasting','Built Python APIs.','missing'),
    ('5 years of production Python ownership','Built Python APIs for one year.','partial'),
    ('Operate Kubernetes clusters in production','Used k8s in a course prototype.','partial'),
    ('Advanced SQL optimization','Used Structured Query Language in a class.','partial'),
    ('Experience with financial forecasting tools','Experience with software tools and teams.','missing'),
    ('Work on financial forecasting systems','Worked on software systems.','missing'),
    ('Production C programming','Built C APIs for two years.','partial'),
    ('Advanced R analytics','Used R for two years.','partial'),
    ('Production C++ programming','Built C++ APIs for two years.','partial'),
    ('Production C# programming','Built C# APIs for two years.','partial'),
    ('Production C programming','Built C++ APIs for two years.','missing'),
    ('Production C# programming','Built C APIs for two years.','missing'),
    ('Financial forecasting A I X','Built Python APIs A I X.','missing'),
])
def test_single_resolver_partial_requires_content_or_listed_synonym(requirement,quote,status):
    result=resolve.resolve_unknowns(raw_with_unknowns(requirement),quote,model=None,
        invoke=lambda *_:resolve.UnknownResolution(decisions=[decision('j0',quote)]))
    match=result['matches'][0]
    assert match['status']==status and result['score']==(50 if status=='partial' else 0)
    assert match['citations'][0]['exact_text']==quote  # audit the rejected support too


@pytest.mark.parametrize('text,quote,status',[
    ('Financial forecasting','Built Python APIs.','missing'),
    ('Production Kubernetes ownership','Used k8s in a course prototype.','partial'),
])
def test_eight_job_fanout_and_new_store_cache_apply_identical_relevance_gate(tmp_path,text,quote,status):
    calls=[]
    def invoke(model,schema,prompt,payload):
        ids=re.findall(r'^- (\S+) \[',payload,re.M);calls.append(ids)
        return resolve.UnknownResolution(decisions=[decision(i,quote) for i in ids])
    path=tmp_path/'partial.sqlite3'
    def run(store):
        return resolve.resolve_unknowns_many({str(i):raw_with_unknowns(text) for i in range(8)},
            quote,model=None,invoke=invoke,store=store)
    cold=run(resolve.DecisionStore(path));warm=run(resolve.DecisionStore(path))
    assert calls==[['job0:j0']]
    assert all(v['matches'][0]['status']==status for v in [*cold.values(),*warm.values()])
    assert all(v['main_model_calls']==0 for v in warm.values())
    assert all(v['score']==(50 if status=='partial' else 0) for v in [*cold.values(),*warm.values()])


def test_quote_fabrication_stays_unknown_not_missing():
    result=resolve.resolve_unknowns(raw_with_unknowns('Financial forecasting'),'Built Python APIs.',model=None,
        invoke=lambda *_:resolve.UnknownResolution(decisions=[decision('j0','Built financial forecasts.')]))
    assert result['matches'][0]['status']=='unknown'


def test_transparent_inflection_and_no_arbitrary_single_letter_or_unlisted_alias():
    from eregion.domain.partial_support import partial_overlap
    assert partial_overlap('Financial forecasting','Built financial forecasts.')
    assert partial_overlap('Build REST APIs','Developed REST APIs.')
    assert not partial_overlap('Financial forecasting A I X','Python APIs A I X')
    assert not partial_overlap('Financial forecasting','Business modelling')
