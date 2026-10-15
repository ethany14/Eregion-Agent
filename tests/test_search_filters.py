import json
from eregion.runtime.career.search_filters import effective_filters, filter_cards
from eregion.runtime.career.treg_jobs import search_body
from test_career_flow import career, execute
from test_integrated_p3 import treg_env, install_treg, ok, ask, CRAWL_ROWS
from test_remaining_search_completion import prepare

def test_provider_filters_and_unknowns():
    state={'goal':'Find junior data analyst jobs in New York'}
    filters=effective_filters(state,{'work_type':'remote','posted':'week'})
    assert search_body('anyapi','data analyst','New York',**filters)=={
        'query':'data analyst','location':'New York','postedLimit':'week',
        'experienceLevel':'entry','workplaceType':'remote'}
    assert search_body('crawl4ai','data analyst',**filters,limit=20)=={'query':'data analyst','posted':'week','limit':20}
    jobs=[{'title':t,'url':str(i)} for i,t in enumerate(['Senior Data Analyst','Junior Data Analyst','Data Analyst','Graduate Data Analyst'])]
    kept,info=filter_cards(jobs,state)
    # Cards are only ordered; the model rejects a level mismatch after reading the posting.
    assert sorted(j['url'] for j in kept)==sorted(j['url'] for j in jobs) and info['excluded_count']==0
    assert sorted(j['url'] for j in filter_cards(jobs,{'goal':'Find data analyst jobs'})[0])==sorted(j['url'] for j in jobs)

def test_linkedin_only_filters_cache_and_candidates(career,monkeypatch):
    treg_env(monkeypatch,JOB_AGENT_TREG_SEARCH_PROVIDER='anyapi')
    c=career;prepare(c);ask(c,'Find junior data analyst jobs; only search LinkedIn')
    bodies=[]
    def handler(r):
        bodies.append(json.loads(r.content))
        return ok({'output':{'data':{'items':[{'id':'4468908584','url':CRAWL_ROWS['rows'][0]['url'],
            'title':'Junior Data Analyst','location':'New York'}]}}})
    seen=install_treg(c,handler)
    first=execute(c,'search_jobs',query='data analyst',location='New York',work_type='remote')
    assert bodies[0]['experienceLevel']=='entry' and bodies[0]['workplaceType']=='remote'
    assert first['treg']['unapplied_filters']==[]
    assert c.repository.get(c.state['task_id'])['search_candidates']
    second=execute(c,'search_jobs',query='data analyst',location='New York',work_type='remote')
    assert second['cached'] and second['no_new_evidence'] and len(seen)==1
    execute(c,'search_jobs',query='data analyst',location='New York',work_type='hybrid')
    assert len(seen)==2
    ask(c,'Please search again')
    # Source-only restriction ends with the new instruction; exercise the helper with fresh task state.
    c.harness._treg_search(c.state['task_id'],c.repository.get(c.state['task_id']),{'query':'data analyst','location':'New York','work_type':'remote'})
    assert len(seen)>=3
