"""Offline request optimization gates; unchanged frozen decisions and acceptance."""
import copy
import json
import os
import subprocess
import types
from pathlib import Path

import pytest
from scripts.baseline_imports import relocate_imports
from langchain_core.messages import HumanMessage, ToolMessage
from eregion.runtime.request_context import ContextArchive, prepare_request, encoded
from eregion.runtime.core.context import ConversationWindow
from eregion.runtime.request_options import snapshot_refs, slim_tools
from eregion.runtime.provider_usage import current_scope
from test_b6_offline_replay import replay, offline_guard, frozen_web, ScriptedModel
from test_career_flow import career
from test_auto_apply import database

# Byte-identical comparisons with commit 6691b0b were removed: request assembly and
# the prompt have changed by design since that experiment.


def test_body_refs_and_protected_facts():
    archive = ContextArchive()
    original = {'current_request':{'text':'x'*5000}, 'resume_text':'resume'*1000,
        'search_constraints':{'only':'junior'}, 'jobs':[{'application_id':'job', 'description':'JD '*1000,
        'qualification_evidence':[{'quote':'4+ years'}], 'match_score':42}],
        'research_pages':[{'url':'https://example.com','text':'page '*1000,'blocked':False}],
        'must_decide':True, 'completion_required':True}
    result = snapshot_refs(original, archive)
    for key in ('current_request','resume_text','search_constraints','must_decide','completion_required'):
        assert result[key] == original[key]
    for key, field in [('jobs','description'),('research_pages','text')]:
        ref = result[key][0][field]['context_ref']
        assert json.loads(archive.values[ref])['value'] == original[key][0][field]
        assert archive.read(ref)['content'] == encoded(original[key][0][field])[:3000]
    assert result['jobs'][0]['qualification_evidence'] == original['jobs'][0]['qualification_evidence']
    assert original['jobs'][0]['description'] == 'JD '*1000


@pytest.mark.parametrize('name', ['write_item', 'read_context'])
def test_stable_disallowed_has_no_effect_and_breaks_loop(database, monkeypatch, name):
    from test_shared_agent_loop import Harness, Model, call, settled
    from eregion.runtime.career.repository import TaskRepository
    from eregion.runtime.tasks.loop import TaskLoop
    from langchain_core.messages import AIMessage
    monkeypatch.setenv('JOB_AGENT_OPT_STABLE_TOOLS', '1')
    harness = Harness()
    harness.stable_tools = lambda state: harness.tools
    harness.available_tools = lambda state: []
    # must_decide also removes read_context; repeated forbidden calls must stop.
    args = {'value':'never'} if name == 'write_item' else {'ref':'missing'}
    model = Model([AIMessage(content='', tool_calls=[call(name,args,str(i))]) for i in range(6)])
    repo = TaskRepository(database.session_factory)
    loop = TaskLoop(repo, harness, model_factory=lambda:model)
    try:
        state = loop.start('Help', 'stable-rejection')
        result = settled(repo, state['task_id'])
        assert result['error']['code'] == 'no_progress'
        assert harness.writes == []
        assert any(h['result'].get('error_code') == 'tool_arguments' for h in result['history'])
        assert result['model_calls'] <= 5
    finally:
        loop.close()


@pytest.mark.parametrize('policy', ['current','checkpoint','aligned'])
def test_history_protects_current_user_and_original_evidence(monkeypatch, policy):
    monkeypatch.setenv('JOB_AGENT_OPT_HISTORY_POLICY', policy)
    archive = ContextArchive()
    ref = archive.reference('evidence'*300)['context_ref']
    archive.read(ref)
    window = ConversationWindow(max_groups=8)
    for i in range(12):
        window.append({}, '', [{'id':str(i),'name':'read_job','args':{}}], [{'text':'x'*500}], 0)
    snapshot = {'messages':[{'role':'user','text':'latest instruction'}], 'current_request':{'message':{'text':'latest instruction'}}}
    messages, metrics = prepare_request('system', [], window, snapshot, archive, max_chars=6000)
    live = json.loads(messages[-1].content)
    assert live['messages'] == snapshot['messages']
    assert live['current_request'] == snapshot['current_request']
    assert 'evidence' in encoded(live['context_evidence'])
    assert not metrics['protected_overflow']
    if policy != 'current':
        assert metrics['history_group_id'] == (metrics['persistent_group_ids'][0] if window.groups else None)


@pytest.mark.parametrize('restriction', ['no_page','must_decide','completion','search_only','recommendation'])
def test_stable_capabilities_keep_legacy_execution_mask(career, monkeypatch, restriction):
    from types import SimpleNamespace
    from eregion.runtime.tasks.host import TaskHost
    from eregion.runtime.core.engine import validate_call, ToolArgumentsError
    c = career
    if restriction == 'must_decide':
        c.repository.change(c.state['task_id'], progress_guard={'revision':0,'count':2})
    elif restriction == 'completion':
        c.repository.change(c.state['task_id'], model_calls=57)
    elif restriction == 'search_only':
        c.repository.change(c.state['task_id'], messages=[{'id':'user','role':'user','text':'Find two junior data analyst jobs'}])
    elif restriction == 'recommendation':
        monkeypatch.setattr(c.harness, 'recommendation_run', lambda state: {'status':'running'})
        c.harness.alerts = SimpleNamespace(recommended=lambda:[])
    loop = SimpleNamespace(repository=c.repository, harness=c.harness, _budget=lambda _:60, _timing=lambda *a,**k:None)
    monkeypatch.setenv('JOB_AGENT_OPT_STABLE_TOOLS','0')
    old = TaskHost(loop,c.state['task_id'],None).observe()
    monkeypatch.setenv('JOB_AGENT_OPT_STABLE_TOOLS','1')
    new = TaskHost(loop,c.state['task_id'],None).observe()
    assert new.allowed_tools == old.tools
    denied = {'no_page':'browser_read','must_decide':'inspect_job','completion':'search_jobs',
              'search_only':'start_application','recommendation':'start_application'}[restriction]
    with pytest.raises(ToolArgumentsError, match='advertised in the current observation'):
        validate_call({'name':denied,'args':{}}, new.allowed_tools)
    # Browser/progress/budget changes preserve definitions for this task kind.
    state = c.repository.get(c.state['task_id'])
    before = c.harness.stable_tools(state)
    state.update(model_calls=59, progress_guard={'revision':0,'count':3})
    assert c.harness.stable_tools(state) == before


def test_slim_schema_retains_title_parameter_and_constraints():
    from eregion.runtime.career.harness import TOOLS
    from eregion.runtime.core.engine import validate_call, ToolArgumentsError
    slim = slim_tools(TOOLS)
    valid = {'name':'import_job', 'args':{'url':'https://example.com','title':'Junior Analyst'}}
    validate_call(valid, slim)
    with pytest.raises(ToolArgumentsError):
        validate_call({'name':'score_jobs','args':{'application_ids':[]}}, slim)
    assert len(encoded(slim)) < len(encoded(TOOLS))

    from eregion.runtime.career.harness import CareerHarness
    from eregion.runtime.tasks.loop import CONTROL_TOOLS
    from eregion.runtime.request_context import READ_CONTEXT
    from eregion.runtime.career.prompt import SYSTEM, TRIMMED_SYSTEM
    tools = [*CONTROL_TOOLS, *CareerHarness.tools, READ_CONTEXT]
    output = os.getenv('OPT_STAGE2_OUTPUT')
    if output:
        Path(output).mkdir(parents=True, exist_ok=True)
        (Path(output)/'static-sizes.json').write_text(json.dumps({
            'all_tools_before':len(encoded(tools)), 'all_tools_after':len(encoded(slim_tools(tools))),
            'prompt_before':len(SYSTEM), 'prompt_after':len(TRIMMED_SYSTEM)}, indent=2))
