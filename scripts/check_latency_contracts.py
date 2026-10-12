"""Performance invariants: no pytest, no provider or production writes."""
import copy, importlib.util, json, sys, time
from pathlib import Path
from threading import Event, Timer
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from agent_runtime.loop_context import ConversationWindow, trace_value
from agent_runtime.loop_model import ModelRequests, ModelInterrupted
from agent_runtime.telemetry import model_metrics
from job_agent.job_extraction import JobExtraction
from job_agent.resume_extraction import ResumeExtraction
from job_agent.domain import normalize_job_analysis, normalize_resume_analysis
from job_agent.workflow.handlers import JobAgentStepHandler
from job_agent.workflow.state import AgentState

def context_checks():
    window=ConversationWindow();history=[];snapshot={'goal':'Inspect fixtures','messages':[{'role':'user','text':'Read all items','id':'request'}]}
    for index in range(4):
        call={'id':str(index),'name':'read_item','args':{'id':index}}
        result={'text':'Synthetic unique evidence '+str(index)+' '+'details '*250}
        window.append(snapshot,'',[call],[result],0)
        history.append({'call_id':str(index),'tool':'read_item','arguments':call['args'],'result':trace_value(result)})
    state={**snapshot,'history':history};before=copy.deepcopy(state);compacted=window.snapshot(state)
    assert state==before
    assert all('result_in_tool_message' in r for r in compacted['history'])
    assert len([m for m in window.messages() if m.type=='tool'])==4
    assert len([m for m in window.messages() if m.type=='human'])==1
    altered=copy.deepcopy(state);altered['history'][0]['result']={'error':'changed'}
    assert window.snapshot(altered)['history'][0]['result']=={'error':'changed'}
    legacy=copy.deepcopy(state);del legacy['history'][0]['call_id']
    assert 'result' in window.snapshot(legacy)['history'][0]
    trimmed=ConversationWindow(window.groups,max_groups=1)
    assert 'result' in trimmed.snapshot(state)['history'][0]
    return {'snapshot_before_chars':len(json.dumps(state)),'snapshot_after_chars':len(json.dumps(compacted)),
            'intact_tool_results':4,'legacy_and_changed_outcomes_preserved':True}

def extraction_checks():
    job=JobExtraction(title='Engineer',summary='',responsibilities=[],statements=[{'source_text':'Required: Python and SQL.',
        'requirements':[{'canonical_name':s.lower(),'display_name':s,'atomic_text':s,'category':'skill',
         'verification_mode':'resume_evidence','level':'required'} for s in ['Python','SQL']]}])
    expanded=job.expand();normalized=normalize_job_analysis(expanded,'Required: Python and SQL.')
    assert len(normalized.requirements)==2
    assert normalized.requirements[0].requirement_group_id==normalized.requirements[1].requirement_group_id
    assert all(r.original_text==r.atomic_text for r in normalized.requirements)
    quotes=['Example A - Bachelor of Science, 2020-2024.','Example B - Master of Science, 2024-2026.']
    resume=ResumeExtraction(summary='',skills=[],education=quotes,entries=[{'entry_type':'education',
        'source_section':'Education','heading':degree,'organization':org,'start_date':start,'end_date':end,'evidence':[quote]}
        for degree,org,start,end,quote in [('Bachelor of Science','Example A','2020','2024',quotes[0]),
                                        ('Master of Science','Example B','2024','2026',quotes[1])]])
    analyzed=normalize_resume_analysis(resume.expand())
    state=AgentState(run_id='check',resume_text='\n'.join(quotes),job_description='Required: Python and SQL.',resume_analysis=analyzed)
    JobAgentStepHandler._validate_evidence(state)
    assert len(analyzed.source_entries)==2 and len({e.source_entry_id for e in analyzed.evidence})==2
    invalid=state.model_copy(deep=True);invalid.resume_analysis.evidence[0].exact_text='Invented degree'
    try:JobAgentStepHandler._validate_evidence(invalid)
    except ValueError:pass
    else:raise AssertionError('Ungrounded evidence accepted')
    return {'two_education_entries_retained':True,'ungrounded_evidence_rejected':True,
        'job_wire_chars':len(job.model_dump_json()),'expanded_job_chars':len(expanded.model_dump_json()),
        'resume_wire_chars':len(resume.model_dump_json()),'expanded_resume_chars':len(resume.expand().model_dump_json())}

def polling_checks():
    request=ModelRequests();reads=[0]
    def active():reads[0]+=1;return True
    try:
        assert request.call(lambda:(time.sleep(.45),'done')[1],active=active,timeout=2)=='done'
        assert reads[0]<=7,reads
        stop=Event();finished=Event();timer=Timer(.05,stop.set);timer.start();started=time.monotonic()
        try:request.call(lambda:finished.wait(.6),active=lambda:not stop.is_set(),timeout=2)
        except ModelInterrupted:pass
        else:raise AssertionError('Stale result accepted')
        elapsed=time.monotonic()-started;finished.set();timer.join();assert elapsed<.3,elapsed
        fired=[]
        try:request.call(lambda:fired.append(True),active=lambda:False)
        except ModelInterrupted:pass
        assert not fired
        return {'checks_during_450ms_request':reads[0],'interruption_seconds':round(elapsed,3),'inactive_request_not_sent':True}
    finally:request.close()

report={'context':context_checks(),'extractions':extraction_checks(),'polling':polling_checks()}
print(json.dumps(report))
