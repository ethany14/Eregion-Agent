"""The model owns semantics; the harness owns source binding, reuse and execution safety."""
from copy import deepcopy
import pytest
from test_career_flow import career
from eregion.domain.search_qualification import SearchQualification
from eregion.runtime.career import qualification as q
from eregion.runtime.core.engine import LoopStop
from eregion.runtime.provider_usage import TaskProviderBudgetExceeded

REQUEST='Find 15 junior data analyst jobs in New York. Keep all my conditions.'


def job(i=1,**changes):
    return {'url':f'https://example.com/jobs/{i}','title':'Data Analyst','location':'New York, NY',
            'description':'This opening welcomes recent university graduates. You will work under supervision.',**changes}


def setup(c):
    c.repository.change(c.state['task_id'],goal=REQUEST,messages=[])
    return c.repository,c.state['task_id']


def response(request,postings):
    return SearchQualification.model_validate({'decisions':[
        {'posting_id':j['posting_id'],**{field:{'status':'met','request_quote':request,
            'reason':'Scripted semantic conclusion based on the supplied opening.',
            'evidence':[{'source':source,'quote':j[source]}]}
            for field,source in [('role','title'),('location','location'),('seniority','description'),('vacancy','description')]}}
        for j in postings]})


def test_no_rules_can_qualify_a_job_without_a_model_verdict():
    result=q.assess({'goal':REQUEST},job(title='Junior Data Analyst',description='0-2 years experience.'))
    assert not result['qualified'] and result['review']['method']=='not_assessed'


def test_model_decides_semantics_once_per_batch_not_per_phrase(career,monkeypatch):
    repo,tid=setup(career);calls=[]
    jobs=[job(),job(2,description='Un début de carrière avec accompagnement quotidien.')]
    def judge(request,postings):calls.append(deepcopy(postings));return response(request,postings)
    monkeypatch.setattr(q,'judge',judge)
    results=q.record_many(repo,tid,jobs)
    assert len(calls)==1 and all(r['qualified'] for r in results)
    assert calls[0][1]['description']==jobs[1]['description']
    assert q.record_many(repo,tid,list(reversed(jobs)))==list(reversed(results)) and len(calls)==1
    for result,j in zip(results,jobs):
        for check in result['checks'].values():
            for e in check['evidence']:assert j[e['source']][e['start']:e['end']]==e['quote']
    q.record(repo,tid,{**jobs[0],'description':jobs[0]['description']+' New duties.'})
    assert len(calls)==2
    repo.change(tid,goal=REQUEST.replace('New York','Boston'))
    assert not q.assess(repo.get(tid),jobs[1])['qualified']
    q.record(repo,tid,jobs[1]);assert len(calls)==3


def test_unknown_or_negative_model_decision_is_not_overridden_by_junior_title(career,monkeypatch):
    repo,tid=setup(career)
    def judge(request,postings):
        value=response(request,postings)
        value.decisions[0].seniority.status='unmet'
        value.decisions[1].location.status='unknown'
        return value
    monkeypatch.setattr(q,'judge',judge)
    result=q.record_many(repo,tid,[job(title='Junior Data Analyst'),job(2)])
    assert [r['checks'][f]['status'] for r,f in zip(result,['seniority','location'])]==['unmet','unknown']
    # A clear mismatch keeps the posting out; an unknown is shown as unconfirmed (handoff 12.22).
    assert not result[0]['qualified'] and result[1]['qualified']
    assert result[1]['near_misses']==[{'field':'location','status':'unknown','quote':result[1]['checks']['location']['quote'],
                                       'reason':result[1]['checks']['location']['reason']}]


@pytest.mark.parametrize('status',['unmet','not_requested'])
def test_vacancy_must_be_established_by_the_model(career,monkeypatch,status):
    repo,tid=setup(career)
    def judge(request,postings):
        value=response(request,postings)
        value.decisions[0].vacancy.status=status
        if status=='not_requested':value.decisions[0].vacancy.request_quote=''
        return value
    monkeypatch.setattr(q,'judge',judge)
    result=q.record(repo,tid,job(title='Junior Data Analyst'))
    assert result['checks']['vacancy']['status']==('unknown' if status=='not_requested' else 'unmet')
    # A closed opening (unmet) stays out; an unestablished vacancy is shown as unconfirmed.
    assert result['qualified']==(status=='not_requested')
    if status=='not_requested':assert [m['field'] for m in result['near_misses']]==['vacancy']


@pytest.mark.parametrize('invalid',['other_job_quote','invented_quote','missing_quote','wrong_request','duplicate_id'])
def test_unbound_model_evidence_cannot_qualify(career,monkeypatch,invalid):
    repo,tid=setup(career);calls=[]
    def judge(request,postings):
        calls.append(1);value=response(request,postings);d=value.decisions[0]
        if invalid=='other_job_quote':d.seniority.evidence[0].quote=postings[1]['description']
        elif invalid=='invented_quote':d.seniority.evidence[0].quote='This sentence is not in the source.'
        elif invalid=='missing_quote':d.seniority.evidence=[]
        elif invalid=='wrong_request':d.seniority.request_quote='Find senior engineers.'
        else:value.decisions[1].posting_id=d.posting_id
        return value
    monkeypatch.setattr(q,'judge',judge)
    jobs=[job(),job(2,description='A distinct posting with a different source sentence.')]
    results=q.record_many(repo,tid,jobs)
    # An unverified claim never counts as confirmed: the field is unknown, so the posting is
    # at most shown as unconfirmed (never priority); an unusable reply never passes.
    if invalid=='duplicate_id':
        assert not results[0]['qualified']
    else:
        assert results[0]['checks']['seniority']['status']=='unknown'
        assert 'seniority' in [m['field'] for m in results[0]['near_misses']]
    # An unusable reply (duplicate identities) gets exactly one bounded retry; the
    # cached result then prevents further calls.
    again=q.record_many(repo,tid,jobs)[0]
    assert again['qualified']==results[0]['qualified'] and len(calls)==(2 if invalid=='duplicate_id' else 1)


def test_steering_during_judgment_discards_result(career,monkeypatch):
    repo,tid=setup(career)
    def judge(request,postings):
        repo.change(tid,chat_revision=1)
        return response(request,postings)
    monkeypatch.setattr(q,'judge',judge)
    with pytest.raises(LoopStop):q.record(repo,tid,job())
    assert not repo.get(tid).get('candidate_qualifications')


def test_provider_budget_stop_is_not_swallowed_or_replaced_by_rules(career,monkeypatch):
    repo,tid=setup(career)
    def judge(*_):raise TaskProviderBudgetExceeded('test limit')
    monkeypatch.setattr(q,'judge',judge)
    with pytest.raises(TaskProviderBudgetExceeded):q.record(repo,tid,job())
    assert not repo.get(tid).get('candidate_qualifications')


def test_bounded_groups_keep_full_text_and_all_identities(career,monkeypatch):
    repo,tid=setup(career);calls=[]
    def judge(request,postings):calls.append(deepcopy(postings));return response(request,postings)
    monkeypatch.setattr(q,'judge',judge)
    jobs=[job(i) for i in range(12)]
    assert all(r['qualified'] for r in q.record_many(repo,tid,jobs))
    assert [len(batch) for batch in calls]==[6,6]
    too_large=job(99,description='Complete evidence. '*5000)
    result=q.record(repo,tid,too_large)
    assert not result['qualified'] and len(calls)==2
