import pytest
from eregion.runtime.career.search_strategy import variants
from eregion.runtime.career.search_filters import filter_cards
from eregion.runtime.career.qualification import assess
from eregion.runtime.career.posting_text import scope
from eregion.runtime.career.linkedin_source import LinkedInMcpSource
from eregion.runtime.career.search_policy import opening_level
from scripts.remaining_search_acceptance import constraints as acceptance_constraints
from test_career_flow import career,execute
from test_integrated_p3 import ask
from test_linkedin_default_route import setup
from test_linkedin_mcp_t0 import SEARCH,DETAIL,result

GOAL='Find 15 current junior data analyst positions in New York for my saved resume.'

def test_variants_preserve_role_and_do_not_expand_other_requests():
    state={'goal':GOAL};args={'query':'junior data analyst','location':'New York'}
    assert variants(state,args)==['junior data analyst','entry level data analyst','graduate data analyst','"data analyst"']
    assert variants({'goal':GOAL.replace('15','2')},args)==['junior data analyst']
    assert variants(state,{**args,'query':'data analyst at Example'})==['data analyst at Example']


def test_cards_exclude_only_explicit_alternative_occupations():
    titles=['Investment Analyst','Data Scientist','Senior Data Analyst','Data Analyst',
            'Analyst','Data…','Data Driven Marketing Analyst','Junior Data Analyst']
    jobs=[{'url':str(i),'title':t,'location':'New York, NY'}for i,t in enumerate(titles)]
    kept,info=filter_cards(jobs,{'goal':GOAL})
    assert {j['title']for j in kept}=={'Data Analyst','Analyst','Data…','Junior Data Analyst'}
    assert info['excluded_count']==4
    assert all(x.get('quote') or x.get('actual') for x in info['excluded'])
    # Matching title but broad remote location stays unknown, never presumed NYC.
    remote={'url':'https://example.com/jobs/1','title':'Junior Data Analyst','location':'United States (Remote)'}
    assert filter_cards([remote],{'goal':GOAL})[0]==[remote]
    assert not assess({'goal':GOAL},remote)['qualified']


def test_scattered_title_terms_cannot_pass_occupation():
    q=assess({'goal':GOAL},{'url':'https://example.com/jobs/1','title':'Junior Data Driven Marketing Analyst',
                           'location':'New York','description':'0-2 years of experience.'})
    assert not q['qualified'] and q['checks']['role']['status']=='unknown'


@pytest.mark.parametrize('prefix',['You have','You bring','The ideal candidate has','Experience:'])
def test_explicit_bounded_years_with_requirement_prefix(prefix):
    body=f'{prefix} 1–2 years of data analysis experience.'
    assert opening_level(body)=='junior'
    assert acceptance_constraints('analyst',{'title':'Data Analyst','location':'New York','description':body})['seniority']
    for other in ['You have 2+ years of experience.','Mentor colleagues with 1-2 years of experience.',
                  'Our junior team members have 1-2 years of experience.']:
        assert opening_level(other) is None
    assert opening_level(body+'\nYou have 5 years of professional experience.')=='senior'


def test_unknown_location_uses_only_explicit_opening_evidence():
    job={'url':'https://example.com/jobs/1','title':'Junior Data Analyst','location':'United States (Remote)'}
    q=assess({'goal':GOAL},{**job,'description':'This role is based in New York.'})
    assert q['qualified'] and q['checks']['location']['quote']=='This role is based in New York'
    assert acceptance_constraints('analyst',{**job,'description':'This role is based in New York.'})['location']
    assert not acceptance_constraints('analyst',{**job,'description':'Our company has offices in New York.'})['location']
    assert not assess({'goal':GOAL},{**job,'description':'Our company has offices in New York.'})['qualified']
    assert not assess({'goal':GOAL},{**job,'location':'Boston, MA','description':'This role is based in New York.'})['qualified']


def test_employer_explicitly_seeking_entry_level_professional():
    body='A financial services organization is seeking an entry-level professional to support AML transaction monitoring.'
    assert opening_level(body)=='junior'
    assert acceptance_constraints('analyst',{'title':'Compliance Data Analyst','location':'New York','description':body})['seniority']
    for negative in ['You will mentor entry-level professionals.',
                     'We are not seeking an entry-level professional.',
                     'We are not currently hiring a junior analyst.']:
        assert opening_level(negative) is None
    assert opening_level(body+'\nRequires 5 years of experience.')=='senior'


def test_linkedin_scope_excludes_other_jobs_and_keeps_original_offsets():
    raw='Example\nData Analyst\nNew York, NY\nAbout the job\n'+'We analyse data. '*35+'\nMore jobs\nJunior role: 0-2 years of experience.'
    body=scope(raw)
    assert raw[body['start']:body['end']]==body['text'] and opening_level(body['text']) is None
    source=LinkedInMcpSource(lambda *a,**kw:result({**DETAIL,'sections':{'job_posting':raw}}))
    detail=source.details('4475055219')
    assert detail['status']=='complete_jd' and detail['raw_posting']==raw
    assert 'More jobs' not in detail['description']
    tiny=raw.replace('We analyse data. '*35,'Tiny JD')
    source=LinkedInMcpSource(lambda *a,**kw:result({**DETAIL,'sections':{'job_posting':tiny}}))
    assert source.details('4475055219')['status']=='incomplete'


def test_effective_query_cache_ignores_local_flags_and_default_filter(career,monkeypatch):
    c=career;fake,manager=setup(c,monkeypatch,{'search_jobs':result(SEARCH)})
    try:
        ask(c,'Find two junior data analyst jobs in New York; only search LinkedIn')
        execute(c,'search_jobs',query='junior data analyst',location='New York',limit=20)
        again=execute(c,'search_jobs',query='junior data analyst',location='New York',limit=15,
                      experience_level='entry',use_directory=True)
        assert again['cached'] and len(fake.calls)==1
    finally:manager.stop()


def test_large_search_uses_four_distinct_queries_once(career,monkeypatch):
    c=career;fake,manager=setup(c,monkeypatch,{'search_jobs':result(SEARCH)})
    try:
        ask(c,GOAL+' Only search LinkedIn.')
        found=execute(c,'search_jobs',query='junior data analyst',location='New York',limit=20)
        assert len(fake.calls)==4 and len({args['keywords']for _,args,_ in fake.calls})==4
        assert all(args['experience_level']=='entry' and args['location']=='New York' for _,args,_ in fake.calls)
        again=execute(c,'search_jobs',query='entry level data analyst',location='New York',limit=20,use_directory=True)
        assert again['no_new_evidence'] and len(fake.calls)==4 and len(found['jobs'])==2
    finally:manager.stop()


def test_query_plan_stops_on_auth_failure(career,monkeypatch):
    c=career;fake,manager=setup(c,monkeypatch,{'search_jobs':result(error='Sign in required')})
    try:
        ask(c,GOAL+' Only search LinkedIn.')
        found=execute(c,'search_jobs',query='junior data analyst',location='New York',limit=20)
        assert found['status']=='blocked' and len(fake.calls)==1
    finally:manager.stop()


def test_list_mismatch_cannot_bypass_filter_via_direct_detail(career,monkeypatch):
    c=career;fake,manager=setup(c,monkeypatch,{'get_job_details':result(DETAIL)})
    try:
        ask(c,GOAL)
        c.repository.change(c.state['task_id'],search_candidates={DETAIL['url']:{'url':DETAIL['url'],'title':'Investment Analyst'}})
        with pytest.raises(ValueError,match='card explicitly conflicts'):
            execute(c,'read_job',url=DETAIL['url'])
        assert not fake.calls
    finally:manager.stop()


@pytest.mark.parametrize('value',[
    {'error_code':'qualification_needed','issues':['Opening level not established'],
     'triage_evidence':[{'quote':'2+ years of experience.'}], 'source':'x'*6000},
    {'jobs':[{'url':'https://example.com/jobs/1','title':'Data Analyst'}],
     'linkedin_mcp':{'query_variants':['x'*6000]}},
])
def test_known_search_and_qualification_summaries_are_not_bulk_paged(value):
    from eregion.runtime.request_context import ContextArchive
    archive=ContextArchive();ref=archive.tool_result(value)['context_ref']
    for offset in (0,3000):
        read=archive.read(ref,offset)
        assert read['no_new_evidence'] and read['content']==''
    key='issues' if 'issues' in value else 'jobs'
    assert archive.read(ref,path=[key])['content']
    assert archive.read(ref,historical=True)['content']
