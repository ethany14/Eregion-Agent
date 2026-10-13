import pytest
from eregion.runtime.career.search_strategy import variants
from eregion.runtime.career.search_filters import filter_cards
from eregion.runtime.career.qualification import assess
from eregion.runtime.career.posting_text import scope
from eregion.runtime.career.linkedin_source import LinkedInMcpSource
from fake_search_qualification import opening_level
from scripts.remaining_search_acceptance import constraints as acceptance_constraints
from test_career_flow import career,execute
from test_integrated_p3 import ask
from test_linkedin_default_route import setup
from test_linkedin_mcp_t0 import SEARCH,DETAIL,result

GOAL='Find 15 current junior data analyst positions in New York for my saved resume.'

def test_variants_preserve_role_and_do_not_expand_other_requests():
    state={'goal':GOAL};args={'query':'junior data analyst','location':'New York'}
    assert variants(state,args)==['"data analyst" AND (junior OR "entry level" OR graduate OR "new grad")',
                                 '"data analyst"','data analyst',
                                 '"analyst" AND (junior OR "entry level" OR graduate OR "new grad" OR "early career")']
    assert variants({'goal':GOAL.replace('15','2')},args)==['junior data analyst']
    assert variants(state,{**args,'query':'data analyst at Example'})==['data analyst at Example']


def test_cards_are_ordered_but_never_semantically_rejected_by_script():
    titles=['Investment Analyst','Data Scientist','Senior Data Analyst','Data Analyst',
            'Analyst','Data…','Data Driven Marketing Analyst','Junior Data Analyst']
    jobs=[{'url':str(i),'title':t,'location':'New York, NY'}for i,t in enumerate(titles)]
    kept,info=filter_cards(jobs,{'goal':GOAL})
    assert {j['title']for j in kept}==set(titles)
    assert info['excluded_count']==0 and not info['excluded']
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
    assert not q['qualified'] and q['review']['method']=='not_assessed'
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


def test_opening_header_recovers_metadata_with_bound_source_offsets():
    from eregion.runtime.career.posting_text import header
    raw='Example Inc\n\nData Analyst\n\nNew York, NY · Reposted 2 weeks ago · 15 applicants\n\nAbout the job\n'+'0-2 years of analytics experience. '*20
    extracted=header(raw)
    assert extracted['location']=='New York, NY' and extracted['company']=='Example Inc'
    for item in extracted['metadata_evidence'].values():
        assert raw[item['start']:item['end']]==item['quote']
    source=LinkedInMcpSource(lambda *a,**kw:result({**DETAIL,'sections':{'job_posting':raw}}))
    detail=source.details('4475055219')
    assert detail['location']=='New York, NY'
    assert assess({'goal':GOAL},{**detail,'title':detail['title']})['review']['method']=='not_assessed'
    assert not header('Example\nAbout the job\nOur office is in New York, NY\n'+raw)
    wrong=LinkedInMcpSource(lambda *a,**kw:result({**DETAIL,'url':'https://www.linkedin.com/jobs/view/9999999/',
                                               'sections':{'job_posting':raw}})).details('4475055219')
    assert wrong['status']=='incomplete' and 'metadata_evidence' not in wrong


def test_repeated_card_titles_keep_each_observed_location():
    from eregion.runtime.career.linkedin_source import search_cards
    payload={'sections':{'search_results':'Data Analyst\nExample A\nNew York, NY (Hybrid)\nPromoted\nData Analyst\nExample B\nBoston, MA (On-site)'},
             'references':{'search_results':[{'kind':'job','url':f'/jobs/view/{id}/','text':'Data Analyst'} for id in ('111111','222222')]}}
    cards=search_cards(payload)
    assert cards['111111']['company']=='Example A' and cards['222222']['location']=='Boston, MA (On-site)'
    # Partial evidence must not attach either ambiguous card to a URL by guessing.
    payload['sections']['search_results']+='\nData Analyst\nExample C\nChicago, IL'
    assert all(j['location'] is None for j in search_cards(payload).values())


def test_detail_metadata_replaces_missing_card_fields_and_stale_location(career,monkeypatch):
    raw='Example Inc\nData Analyst\nBoston, MA · 2 days ago · 12 applicants\nAbout the job\n'+'0-2 years of analytics experience. '*20
    c=career;fake,manager=setup(c,monkeypatch,{'get_job_details':result({**DETAIL,'sections':{'job_posting':raw}})})
    try:
        ask(c,GOAL)
        c.repository.change(c.state['task_id'],search_candidates={DETAIL['url']:{'url':DETAIL['url'],'title':'Data Analyst','location':'New York, NY'}})
        job=execute(c,'read_job',url=DETAIL['url'])
        assert job['location']=='Boston, MA' and job['company']=='Example Inc'
        assert not assess({'goal':GOAL},job)['qualified']
        saved=next(iter(c.repository.get(c.state['task_id'])['retrieved_jobs'].values()))
        assert saved['metadata_evidence']['location']['quote'].startswith('Boston')
        assert saved['discovery_card']['location']=='New York, NY'
    finally:manager.stop()


def test_official_mcp_error_type_does_not_return_unrelated_recommendations():
    payload={**SEARCH,'section_errors':{'search_results':{'error_type':'no_matching_jobs','error_message':'No matches'}}}
    value=LinkedInMcpSource(lambda *a,**kw:result(payload)).search('data analyst')
    assert value['status']=='no_match' and value['jobs']==[]


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
        found=execute(c,'search_jobs',query='junior data analyst',location='New York',limit=20,work_type='onsite_or_hybrid')
        assert len(fake.calls)==4 and len({args['keywords']for _,args,_ in fake.calls})==4
        assert all(args['experience_level']=='entry' and args['location']=='New York'
                   and args['work_type']=='on_site,hybrid' for _,args,_ in fake.calls)
        assert [args['max_pages'] for _,args,_ in fake.calls]==[4,8,8,4]
        assert c.repository.get(c.state['task_id'])['linkedin_mcp_state']['call_limit']==50
        again=execute(c,'search_jobs',query='entry level data analyst',location='New York',limit=20,use_directory=True,
                      work_type='onsite_or_hybrid')
        assert again['no_new_evidence'] and len(fake.calls)==4 and len(found['jobs'])==2
        # City expansion defaults to onsite_or_hybrid, so omitting it reuses the cache.
        execute(c,'search_jobs',query='entry level data analyst',location='New York',limit=20)
        assert len(fake.calls)==4
        # An explicit remote request is a different upstream query, never a cached answer.
        execute(c,'search_jobs',query='entry level data analyst',location='New York',limit=20,work_type='remote')
        assert len(fake.calls)==8 and fake.calls[-1][1]['work_type']=='remote'
    finally:manager.stop()


def test_query_plan_stops_on_auth_failure(career,monkeypatch):
    c=career;fake,manager=setup(c,monkeypatch,{'search_jobs':result(error='Sign in required')})
    try:
        ask(c,GOAL+' Only search LinkedIn.')
        found=execute(c,'search_jobs',query='junior data analyst',location='New York',limit=20)
        assert found['status']=='blocked' and len(fake.calls)==1
    finally:manager.stop()


def test_card_title_does_not_block_model_from_reading_actual_posting(career,monkeypatch):
    c=career;fake,manager=setup(c,monkeypatch,{'get_job_details':result(DETAIL)})
    try:
        ask(c,GOAL)
        c.repository.change(c.state['task_id'],search_candidates={DETAIL['url']:{'url':DETAIL['url'],'title':'Investment Analyst'}})
        execute(c,'read_job',url=DETAIL['url'])
        assert len(fake.calls)==1
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


def test_large_discovery_retains_actionable_cards_without_nested_refs():
    from eregion.runtime.request_context import ContextArchive
    archive=ContextArchive()
    jobs=[{'url':f'https://example.com/jobs/{i}','title':'Data Analyst','location':'New York','company':'Example'} for i in range(60)]
    summary=archive.tool_result({'jobs':jobs,'linkedin_mcp':{'status':'ok'},'sources_checked':['x'*2000]})
    assert isinstance(summary['jobs'],list) and len(summary['jobs'])==8
    assert all('context_ref' not in j for j in summary['jobs'])
    assert summary['discovery_count']==60
    assert archive.read(summary['context_ref'],path=['jobs','40'])['content']
