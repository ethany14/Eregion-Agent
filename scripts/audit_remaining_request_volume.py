"""Offline reconstruction of a synthetic paid search's final pre-finish request.

Never invoke providers or mutate the original task. This is a reconstruction,
not a claim that final persisted context can recover all 58 earlier requests.
"""
import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def reconstruct(case, rejected_job=None, *, stopped=False):
    from api.db import create_database
    from agent_runtime.career.harness import CareerHarness
    from agent_runtime.career.repository import TaskRepository
    from agent_runtime.career.alerts import AlertRepository
    from agent_runtime.auto_apply.repository import ApplyRepository
    from agent_runtime.workspace.repository import JobWorkspaceRepository
    from agent_runtime.evidence.repository import CareerEvidenceRepository
    from agent_runtime.application_pack.repository import PackRepository
    from agent_runtime.loop_context import ConversationWindow
    from agent_runtime.request_context import ContextArchive,prepare_request,encoded
    from agent_runtime.task_loop import CONTROL_TOOLS
    state=json.loads((case/'transcript.json').read_text(encoding='utf-8'))
    runtime_state=state['loop_runtime']
    # URI read-only mode also prevents accidental writes by a repository.
    uri=(case/'career.db').resolve().as_posix()
    db=create_database('sqlite:///file:'+uri+'?mode=ro&uri=true')
    runtime=SimpleNamespace(database=db,workspace=JobWorkspaceRepository(db.session_factory),
        evidence=CareerEvidenceRepository(db.session_factory),packs=PackRepository(db.session_factory),
        pack_workflow=SimpleNamespace())
    harness=CareerHarness(runtime,SimpleNamespace(repository=ApplyRepository(db.session_factory)),
        TaskRepository(db.session_factory),fit_service=SimpleNamespace())
    harness.alerts=AlertRepository(db.session_factory)
    try:
        # Remove the just-completed finish exchange from the terminal state.
        if state['history'] and state['history'][-1]['tool']=='finish_task':state['history'].pop()
        if state['messages'] and state['messages'][-1]['role']=='assistant':state['messages'].pop()
        if rejected_job:
            from agent_runtime.career.candidate_health import validate_and_record
            from agent_runtime.career.posting_qualification import PostingRejected
            # Replay the production classification into an isolated in-memory
            # state. The original database remains read-only and unchanged.
            def change(_, update):state.update(update(state))
            try:validate_and_record(SimpleNamespace(change=change),state['task_id'],rejected_job)
            except PostingRejected:pass
            else:raise AssertionError('The rejection fixture must actually be rejected')
        observed=harness.observe(state)
        if stopped:
            # Preserve the live browser-dependent tool group without starting
            # Chrome. Omitting this cache would undercount the request schema.
            harness._browsing=SimpleNamespace(inspect=lambda _:state.get('browser'),close=lambda:None)
        latest=next(m for m in reversed(state['messages']) if m['role']=='user')
        snapshot={'goal':latest['text'],'initial_goal':state['goal'],
            'current_request':{'revision':state['chat_revision'],'message':latest},
            'messages':state['messages'][-60:],'plan':state['plan'],'history':state['history'][-16:],
            'pending_question':state.get('input_request'),'visual_fallback':state.get('visual_fallback',False),
            'budget_remaining':3,**observed}
        if stopped:
            snapshot['budget_remaining']=state.get('model_budget',60)-state['model_calls']+state['budget_base']
            snapshot.update(must_decide=True,decision_reason='Repeated reads added no evidence. Use saved results to finish honestly, ask for essential missing input, or take a different action/source. Do not claim unfinished work is complete.')
            reads={'read_context','browser_read','browser_screenshot','list_jobs','inspect_job','inspect_materials',
                'inspect_interview','inspect_application','browser_scroll','browser_wait','screen_jobs'}
            tools=[t for t in CONTROL_TOOLS if t['function']['name'] in {'finish_task','ask_user','pause_task'}]+[
                t for t in harness.available_tools(state) if t['function']['name'] not in reads]
        else:
            snapshot.update(completion_required=True,completion_reason='Use the remaining decisions to report the observed results and explicit unfinished work. No additional research or rereading. Do not claim requested constraints were met when they were not. Ask only for genuinely essential missing user input.')
            tools=[t for t in CONTROL_TOOLS if t['function']['name'] in {'finish_task','ask_user'}]
        groups=list(runtime_state['transcript'])
        if groups and any(c['name']=='finish_task' for c in groups[-1]['assistant']['tool_calls']):groups.pop()
        fixture={'prompt':harness.prompt,'tools':tools,'snapshot':snapshot,'groups':groups,
            'archive_values':runtime_state['context_archive'],'archive_reads':runtime_state['context_read_progress'],
            'archive_resources':runtime_state['context_resources']}
        messages,metrics=prepare_request(fixture['prompt'],tools,ConversationWindow(groups),snapshot,
            ContextArchive(fixture['archive_values'],fixture['archive_reads'],fixture['archive_resources']),max_chars=48000)
        live=json.loads(messages[-1].content)
        audit={'scope':'Offline read-only terminal-state counterfactual request reconstruction; not an exact recovery of earlier requests',
            'recorded_final_metrics':runtime_state['context_metrics'],'reconstructed_metrics':metrics,
            'field_chars':{k:len(encoded(v)) for k,v in live.items()},
            'message_chars':[len(m.content) for m in messages],
            'preserved_job_facts':snapshot['jobs'],'preserved_recommendations':snapshot['recommended_jobs'],
            'earlier_request_limit':'Only the bounded final transcript/archive is persisted. Per-call ledger context_chars gives sizes, not original messages; reconstructing every earlier prompt exactly would fabricate missing state.'}
        with sqlite3.connect('file:'+uri+'?mode=ro',uri=True) as connection:
            rows=[json.loads(row[0]) for row in connection.execute(
                'select details_json from provider_usage where task_id=? order by created_at',(state['task_id'],))]
        main=[row for row in rows if row.get('purpose')=='agent']
        audit['actual_main_request_sizes']=[{'call':i+1,**{key:row.get(key) for key in
            ('context_chars','tool_schema_chars','input_tokens','output_tokens')},
            'combined_text_chars':row.get('context_chars',0)+row.get('tool_schema_chars',0)} for i,row in enumerate(main)]
        audit['actual_size_summary']={'calls':len(main),'over_48000':sum(
            row['combined_text_chars']>48000 for row in audit['actual_main_request_sizes']),
            'main_input_tokens':sum(row.get('input_tokens',0) for row in main),
            'all_task_input_tokens':sum(row.get('input_tokens',0) for row in rows),
            'archive_storage_chars':len(encoded(runtime_state['context_archive'])),
            'counterfactual_scope':'Only the final request is reconstructed after the fix. Earlier sizes are actual ledger observations, not after-fix estimates.'}
        audit['excluded_candidates']=live.get('known_results',{}).get('excluded_candidates',[])
        return fixture,audit
    finally:harness.close();db.close()


if __name__=='__main__':
    case=Path(sys.argv[1]);destination=Path(sys.argv[2]);destination.mkdir(parents=True,exist_ok=True)
    stopped='--no-progress' in sys.argv
    rejected_job=json.loads(Path(sys.argv[3]).read_text(encoding='utf-8'))['jobs'][0] if len(sys.argv)>3 and sys.argv[3]!='--no-progress' else None
    fixture,audit=reconstruct(case,rejected_job,stopped=stopped)
    (destination/'request-replay-input.json').write_text(json.dumps(fixture,ensure_ascii=False),encoding='utf-8')
    (destination/'request-volume.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:audit[k] for k in ('recorded_final_metrics','reconstructed_metrics','field_chars')},ensure_ascii=False))
