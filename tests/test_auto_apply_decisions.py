"""Site-independent interpretation, local assumptions and hierarchical controls."""
import copy
import os

import pytest

from eregion.runtime.auto_apply.agent import AgentTools
from eregion.runtime.auto_apply.autofill import autofill, desired_answer
from eregion.runtime.auto_apply.browser import BrowserBlocked
from eregion.runtime.auto_apply.decisions import active_decision
from test_auto_apply import FakeBrowser, field, request


def state(**extra):
    return {'profile':{**request().profile.model_dump(),'phone':'+1 (607) 555-0100'},'answers':{},'automation_mode':'hybrid',**extra}


def execute(session,name,key,**extra):
    snap=session.observe()
    return session.execute(name,{'observation_id':snap['observation_id'],'field_key':key,**extra})


def resolve(session,key,value,mode='format',refs=None):
    return execute(session,'resolve_field',key,mode=mode,value=value,
        source_refs=['profile:phone'] if refs is None else refs,reason='Adapt the confirmed source to the controls observed on this page.')


class DecisionBrowser(FakeBrowser):
    def __init__(self,labels=('Country Phone Code','Phone Number','Phone Device Type')):
        super().__init__('');self.writes=[]
        self.fields=[field('prefix',label=labels[0]),field('number',label=labels[1]),field('type','select',labels[2])]
        self.fields[2]['options']=[{'label':'Home','value':'home'},{'label':'Home Cellular','value':'cell'}]
    def fill(self,current,value):
        super().fill(current,value);self.writes.append((current['key'],value))
        next(f for f in self.fields if f['key']==current['key'])['invalid']=False
    def choose_option(self,key,label):self.fill(next(f for f in self.fields if f['key']==key),label)


@pytest.mark.parametrize('labels',[('Country Phone Code','Phone Number','Phone Device Type'),
    ('Dialling prefix','Subscriber line','Device classification'),('Calling region','Local telephone','Type of handset')])
def test_model_decisions_do_not_depend_on_platform_field_names(labels):
    b=DecisionBrowser(labels);data=state();b.fields[1].update(value=data['profile']['phone'],invalid=True)
    s=AgentTools(b,data,autofill=lambda:autofill(b,data,lambda:b''),active=lambda:True)
    resolve(s,'prefix','+1');resolve(s,'number','6075550100')
    resolve(s,'type','Home Cellular','default',[])
    assert [f['value'] for f in b.fields]==['+1','6075550100','Home Cellular']
    assert data['answers']=={} and data['profile']['phone']=='+1 (607) 555-0100'
    before=list(b.writes)
    for _ in range(2):
        resumed=AgentTools(b,data,autofill=lambda:autofill(b,data,lambda:b''),active=lambda:True)
        resumed.observe();resumed.execute('autofill',{})
    assert b.writes==before # Formatting/defaults survive another bulk fill.
    data['profile']['phone']='+44 7700 900123'
    assert active_decision(b.fields[1],data) is None


@pytest.mark.parametrize('label,kind',[('Do you require visa sponsorship?','select'),('Work authorization','select'),
    ('Salary expectations','select'),('I agree to data processing','checkbox'),('Veteran status','select'),
    ('Years of experience','select'),('Are you fluent in English?','select')])
def test_incidental_defaults_cannot_invent_material_answers(label,kind):
    b=DecisionBrowser();b.fields=[{**field('q',kind,label),'options':[{'label':'Other','value':'other'}]}]
    s=AgentTools(b,state(),autofill=lambda:{},active=lambda:True)
    with pytest.raises(BrowserBlocked):resolve(s,'q','Other','default',[])
    assert not b.writes


def test_formatting_cannot_invent_phone_digits_and_user_correction_invalidates_decision():
    b=DecisionBrowser();data=state();s=AgentTools(b,data,autofill=lambda:{},active=lambda:True)
    with pytest.raises(BrowserBlocked):resolve(s,'number','2129999999')
    resolve(s,'number','6075550100')
    data['answers']['number']='2065550100'
    assert desired_answer(b.fields[1],data)=='2065550100'


def test_default_preserves_confirmed_or_already_valid_choice():
    b=DecisionBrowser();data=state();s=AgentTools(b,data,autofill=lambda:{},active=lambda:True)
    b.fields[2]['value']='Home'
    with pytest.raises(BrowserBlocked):resolve(s,'type','Home Cellular','default',[])
    b.fields[2]['value']='';data['answers']['type']='Home'
    with pytest.raises(BrowserBlocked):resolve(s,'type','Home Cellular','default',[])


@pytest.mark.parametrize('degree,option',[('M.Eng., Systems Engineering','Masters'),
    ('B.A., Economics','Bachelors'),('Master of Science, Computer Science','Graduate — Masters')])
def test_model_maps_supplied_degree_to_observed_level_without_default_or_alias_dictionary(degree,option):
    b=DecisionBrowser();b.fields=[{**field('degree','select','Degree*'),
        'options':[{'label':option,'value':'opaque-degree-id'}]}]
    data=state();data['profile']['degree']=degree
    s=AgentTools(b,data,autofill=lambda:autofill(b,data,lambda:b''),active=lambda:True)
    result=resolve(s,'degree',option,'equivalent',['profile:degree'])
    assert result['verified'] and b.fields[0]['value']==option
    assert data['answers']=={} and data['profile']['degree']==degree
    writes=list(b.writes)
    resumed=AgentTools(b,data,autofill=lambda:autofill(b,data,lambda:b''),active=lambda:True)
    resumed.observe();resumed.execute('autofill',{})
    assert b.writes==writes
    data['profile']['degree']='BSc, Physics'
    assert active_decision(b.fields[0],data) is None


def test_degree_mapping_honors_explicit_correction_over_profile_and_never_defaults():
    b=DecisionBrowser();b.fields=[{**field('degree','select','Degree*'),
        'options':[{'label':'Masters','value':'m'},{'label':'Bachelors','value':'b'}]}]
    data=state();data['profile']['degree']='M.Eng., Systems Engineering'
    data['answers']['degree']='Bachelor of Arts'
    s=AgentTools(b,data,autofill=lambda:{},active=lambda:True)
    with pytest.raises(BrowserBlocked,match='explicit answer'):
        resolve(s,'degree','Masters','equivalent',['profile:degree'])
    with pytest.raises(BrowserBlocked,match='default'):
        resolve(s,'degree','Masters','default',[])
    assert resolve(s,'degree','Bachelors','equivalent',['answer:degree'])['verified']


def test_material_equivalents_require_the_question_source_and_preserve_polarity():
    b=DecisionBrowser();b.fields=[{**field('sponsor','select','Do you require visa sponsorship?'),
        'options':[{'label':'Yes','value':'y'},{'label':'No','value':'n'},
                   {'label':'I will require sponsorship','value':'other-y'}]}]
    data=state();data['profile']['degree']='M.Eng.'
    s=AgentTools(b,data,autofill=lambda:{},active=lambda:True)
    with pytest.raises(BrowserBlocked):resolve(s,'sponsor','Yes','equivalent',['profile:degree'])
    data['answers']['another-question']='Yes'
    with pytest.raises(BrowserBlocked):resolve(s,'sponsor','Yes','equivalent',['answer:another-question'])
    data['answers']['sponsor']='Yes'
    with pytest.raises(BrowserBlocked,match='yes/no'):
        resolve(s,'sponsor','No','equivalent',['answer:sponsor'])
    assert resolve(s,'sponsor','I will require sponsorship','equivalent',['answer:sponsor'])['verified']


def test_consent_equivalence_still_requires_its_own_first_answer():
    b=DecisionBrowser();b.fields=[{**field('consent','select','Consent to recruitment data processing'),
        'options':[{'label':'I consent','value':'accept'}]}]
    data=state(answers={'authorization':'Yes'})
    s=AgentTools(b,data,autofill=lambda:{},active=lambda:True)
    with pytest.raises(BrowserBlocked):resolve(s,'consent','I consent','equivalent',['answer:authorization'])
    data['answers']['consent']=True
    assert resolve(s,'consent','I consent','equivalent',['answer:consent'])['verified']


browser_test=pytest.mark.skipif(os.getenv('JOB_AGENT_BROWSER_TESTS')!='1',reason='Offline Chrome opt-in')
DEGREE_FORM='''<main><h1>My Experience</h1><form id="application">
<fieldset><legend>From</legend><label id="degree-label">Degree*</label>
<button type="button" role="combobox" id="degree" name="degree" aria-labelledby="degree-label" aria-controls="degrees" aria-required="true">Select One</button>
<div id="degrees" role="listbox" hidden><div role="option" aria-disabled="true">Select One</div>
<div role="option" data-value="mtech">MTECH</div><div role="option" data-value="mba">MBA</div>
<div role="option" data-value="opaque-master-id">Masters</div><div role="option" data-value="opaque-bachelor-id">Bachelors</div></div>
</fieldset><button type="button">Submit Application</button></form></main>
<script>window.degreeWrites=0;const degree=document.querySelector('#degree'),menu=document.querySelector('#degrees');
degree.onclick=()=>{menu.hidden=false;degree.setAttribute('aria-expanded','true')};
menu.querySelectorAll('[data-value]').forEach(o=>o.onclick=()=>{degree.textContent=o.textContent;menu.hidden=true;degree.setAttribute('aria-expanded','false');window.degreeWrites++});</script>'''


@browser_test
def test_workday_style_degree_mapping_uses_confirmed_profile_then_survives_autofill():
    from test_auto_apply_browser import FixtureBrowser
    b=FixtureBrowser('https://job-boards.greenhouse.io/example/jobs/123')
    try:
        b.page.set_content(DEGREE_FORM);data=state();data['profile']['degree']='M.Eng., Systems Engineering'
        key=b.observe()[0]['key'];s=AgentTools(b,data,autofill=lambda:autofill(b,data,lambda:b''),active=lambda:True)
        execute(s,'inspect_field',key)
        assert resolve(s,key,'Masters','equivalent',['profile:degree'])['verified']
        for _ in range(2):
            s.observe();s.execute('autofill',{})
        assert b.field(key)['value']=='Masters' and b.page.evaluate('degreeWrites')==1
        assert s.execute('ready_for_review',{})['host_validation_required']
    finally:b.close()


PHONE_FORM='''<main><h1>Contact details</h1><form id="application" onsubmit="validate();return false">
<fieldset><legend>Telephone</legend><label for="prefix">Calling prefix*</label><input id="prefix" required value="+1">
<div class="form-field"><label for="number">Phone Number*</label><input id="number" required aria-describedby="number-error" value="+16075550100">
<div id="number-error" role="alert">Do not include the country calling code in the local number.</div></div></fieldset>
<button>Next</button></form></main><script>
window.nextClicks=0;document.querySelector('#number').setAttribute('aria-invalid','true');
function validate(){window.nextClicks++;const n=document.querySelector('#number');if(n.value==='6075550100'){
document.querySelector('#number-error').hidden=true;n.setAttribute('aria-invalid','false');document.querySelector('h1').textContent='Review';
document.querySelector('button').textContent='Submit Application';}}
</script>'''


@browser_test
def test_browser_exposes_relationships_errors_and_can_revalidate_after_correction():
    from test_auto_apply_browser import FixtureBrowser
    b=FixtureBrowser('https://job-boards.greenhouse.io/example/jobs/123')
    try:
        b.page.set_content(PHONE_FORM);data=state();s=AgentTools(b,data,autofill=lambda:{},active=lambda:True)
        snap=s.observe();number=next(f for f in snap['fields'] if f['label']=='Phone Number*')
        assert number['group']=='Telephone' and 'country calling code' in number['errors'][0]
        assert snap['page']['errors']
        result=resolve(s,number['key'],'6075550100')
        assert not result['verified'] # This website clears errors only on Next.
        snap=s.observe();control=next(c for c in snap['page']['controls'] if c['kind']=='next')
        s.execute('click_page_action',{'observation_id':snap['observation_id'],'control_id':control['id']})
        snap=s.observe();assert not next(f for f in snap['fields'] if f['key']==number['key']).get('invalid',False)
        assert b.page.evaluate('window.nextClicks')==1
        assert snap['page']['can_submit']
    finally:b.close()


TREE_FORM='''<form id="application"><label for="source">How Did You Hear About Us?*</label>
<div data-automation-id="multiSelectContainer"><input id="source" aria-controls="choices" aria-haspopup="tree" required></div>
<div id="choices" role="tree" hidden></div><button type="button">Submit Application</button></form>
<script>
const input=document.querySelector('#source'),menu=document.querySelector('#choices');window.path=[];
input.onclick=()=>{if(!menu.hidden)return;menu.hidden=false;menu.innerHTML='<div role="treeitem" aria-expanded="false" onclick="branch()">Job Board</div><div role="treeitem">Events</div>';};
function branch(){window.path.push('Job Board');menu.innerHTML='<div role="treeitem" aria-label="LinkedIn" onclick="leaf()"><span>LinkedIn</span><span aria-hidden="true">Select</span></div>';}
function leaf(){window.path.push('LinkedIn');input.value='LinkedIn';menu.hidden=true;}
</script>'''


@browser_test
@pytest.mark.parametrize('search_first',[False,True])
def test_text_shaped_hierarchical_picker_category_then_leaf_without_reasking(search_first):
    from test_auto_apply_browser import FixtureBrowser
    b=FixtureBrowser('https://job-boards.greenhouse.io/example/jobs/123')
    try:
        b.page.set_content(TREE_FORM);f=b.observe()[0];key=f['key']
        assert f['kind']=='text' and f['choice_control']
        data=state(answers={key:'linkedin'});s=AgentTools(b,data,autofill=lambda:autofill(b,data,lambda:b''),active=lambda:True)
        s.execute('autofill',{});assert b.page.evaluate('window.path')==[]
        s.autofill_called=False # A fresh decision slice may explore before bulk filling.
        if search_first:execute(s,'search_options',key,source_ref='answer:'+key)
        else:execute(s,'inspect_field',key)
        result=execute(s,'explore_option',key,source_ref='answer:'+key,option_label='Job Board',reason='The named service belongs to this source category; inspect its children.')
        assert result['options'][0]['label']=='LinkedIn'
        snap=s.observe();assert snap['fields'][0]['value']==''
        with pytest.raises(BrowserBlocked):s.execute('ready_for_review',{})
        execute(s,'choose_option',key,source_ref='answer:'+key,option_label='LinkedIn')
        snap=s.observe();assert snap['option_paths'][key]['complete']
        s.execute('ready_for_review',{})
        assert b.page.evaluate('window.path')==['Job Board','LinkedIn']
        before=b.page.evaluate('window.path')
        s.execute('autofill',{});assert b.page.evaluate('window.path')==before
    finally:b.close()


@browser_test
def test_category_selection_can_reveal_a_separate_dependent_field():
    from test_auto_apply_browser import FixtureBrowser
    b=FixtureBrowser('https://job-boards.greenhouse.io/example/jobs/123')
    try:
        b.page.set_content('''<form><label>How did you hear about us?<select id="source" required onchange="document.querySelector('#child').hidden=false"><option value="">Choose</option><option value="board">Job Board</option></select></label>
          <div id="child" hidden><label>Which service?<select id="service" required><option value="">Choose</option><option value="li">LinkedIn</option></select></label></div><button type="button">Submit Application</button></form>''')
        key=b.observe()[0]['key'];data=state(answers={key:'LinkedIn'});s=AgentTools(b,data,autofill=lambda:autofill(b,data,lambda:b''),active=lambda:True)
        execute(s,'inspect_field',key)
        execute(s,'explore_option',key,source_ref='answer:'+key,option_label='Job Board',reason='Open the service list for the confirmed referral source.')
        child=next(f for f in s.observe()['fields'] if f['key']!=key)
        resolve(s,child['key'],'LinkedIn','equivalent',['answer:'+key])
        snap=s.observe();assert snap['option_paths'][key]['complete']
        s.execute('autofill',{});assert [f['value'] for f in b.observe()]==['board','li']
        s.execute('ready_for_review',{})
    finally:b.close()
