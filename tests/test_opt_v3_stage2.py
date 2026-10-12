"""Offline request optimization gates; unchanged frozen decisions and acceptance."""
import copy
import json
import os
import subprocess
import types
from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage, ToolMessage
from agent_runtime.request_context import ContextArchive, prepare_request, encoded
from agent_runtime.loop_context import ConversationWindow
from agent_runtime.request_options import snapshot_refs, slim_tools
from agent_runtime.provider_usage import current_scope
from test_b6_offline_replay import replay, offline_guard, frozen_web, ScriptedModel
from test_career_flow import career
from test_auto_apply import database

BASE = "6691b0bb75651aa71d40b8287f086411623025a9"


def test_off_requests_equal_fixed_base(monkeypatch):
    for name in ('SNAPSHOT_REFS', 'STABLE_TOOLS', 'PROMPT_TRIM'):
        monkeypatch.setenv('JOB_AGENT_OPT_' + name, '0')
    monkeypatch.setenv('JOB_AGENT_OPT_HISTORY_POLICY', 'current')
    source = subprocess.check_output(['git', 'show', BASE + ':agent_runtime/request_context.py']).decode()
    legacy = types.ModuleType('legacy_request')
    exec(compile(source, 'base/request_context.py', 'exec'), legacy.__dict__)
    old_window_module = types.ModuleType('legacy_window')
    exec(subprocess.check_output(['git','show',BASE+':agent_runtime/loop_context.py']).decode(), old_window_module.__dict__)
    legacy.ConversationWindow = old_window_module.ConversationWindow
    old_prompt = {}
    exec(subprocess.check_output(['git','show',BASE+':agent_runtime/career/prompt.py']).decode(), old_prompt)
    from agent_runtime.career.prompt import SYSTEM
    assert SYSTEM == old_prompt['SYSTEM']
    from agent_runtime.career.harness import TOOLS
    for budget in (48000, 8000):
        window = ConversationWindow()
        old_window = old_window_module.ConversationWindow()
        for i in range(9):
            for target in (window, old_window):
                target.append({}, '', [{'id':str(i),'name':'read_job','args':{'url':'https://example.com'}}], [{'text':'body ' * 1000}], 0)
        snapshot = {'current_request':{'message':{'text':'Find junior jobs'}}, 'messages':[{'role':'user','text':'Find junior jobs'}],
                    'research_pages':[{'url':'https://example.com','excerpt':'x'*2000}], 'history':[]}
        a, _ = prepare_request(SYSTEM, TOOLS, copy.deepcopy(window), snapshot, ContextArchive(), max_chars=budget)
        b, _ = legacy.prepare_request(old_prompt['SYSTEM'], TOOLS, old_window, snapshot, legacy.ContextArchive(), max_chars=budget)
        assert encoded([m.model_dump() for m in a]) == encoded([m.model_dump() for m in b])


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


@pytest.mark.parametrize('case', ['r1','r2','r3','correct'])
def test_stage2_b6_measurement(replay, career, monkeypatch, case):
    rows = []
    byte_checks = []
    if (all(os.getenv('JOB_AGENT_OPT_' + name, '0') != '1'
            for name in ('SNAPSHOT_REFS','STABLE_TOOLS','PROMPT_TRIM'))
            and os.getenv('JOB_AGENT_OPT_HISTORY_POLICY', 'current') == 'current'):
        import agent_runtime.loop_engine as engine
        legacy = types.ModuleType('legacy_request')
        exec(subprocess.check_output(['git','show',BASE+':agent_runtime/request_context.py']).decode(), legacy.__dict__)
        old_window = types.ModuleType('legacy_window')
        exec(subprocess.check_output(['git','show',BASE+':agent_runtime/loop_context.py']).decode(), old_window.__dict__)
        legacy.ConversationWindow = old_window.ConversationWindow
        original_prepare = engine.prepare_request
        def compare_request(prompt, tools, window, snapshot, archive, **kwargs):
            expected, _ = legacy.prepare_request(prompt, tools, copy.deepcopy(window),
                copy.deepcopy(snapshot), legacy.ContextArchive(copy.deepcopy(archive.values),
                    copy.deepcopy(archive.reads), copy.deepcopy(archive.resources)), **kwargs)
            actual = original_prepare(prompt, tools, window, snapshot, archive, **kwargs)
            assert encoded([m.model_dump() for m in actual[0]]) == encoded([m.model_dump() for m in expected])
            byte_checks.append(True)
            return actual
        monkeypatch.setattr(engine, 'prepare_request', compare_request)
    scoring_inputs = []
    handler = career.harness.analysis._fit_service._handler
    analyze = handler._analyze
    def capture(schema, system, content):
        import hashlib
        scoring_inputs.append({'schema':schema.__name__, 'sha256':hashlib.sha256(encoded([system,content]).encode()).hexdigest()})
        return analyze(schema, system, content)
    monkeypatch.setattr(handler, '_analyze', capture)
    original = ScriptedModel.invoke
    def invoke(self, messages, tools):
        metrics = copy.deepcopy(current_scope()['context_metrics'])
        snapshot = json.loads(messages[-1].content)
        metrics['latest_user_protected'] = snapshot['current_request']['message']['role'] == 'user'
        # Every result must have an earlier matching assistant call in this request.
        calls = {c['id'] for m in messages for c in getattr(m, 'tool_calls', [])}
        metrics['orphan_free'] = all(m.tool_call_id in calls for m in messages if isinstance(m, ToolMessage))
        if 'allowed_tools' in snapshot:
            metrics['script_allowed'] = self.steps[self.calls]['tool'] in snapshot['allowed_tools']
        rows.append(metrics)
        return original(self, messages, tools)
    monkeypatch.setattr(ScriptedModel, 'invoke', invoke)
    result = replay(case)
    expected = {'r1':1,'r2':0,'r3':0,'correct':2}
    assert result.acceptance['qualified_count'] == expected[case]
    output = os.getenv('OPT_STAGE2_OUTPUT')
    if output:
        target = Path(output); target.mkdir(parents=True, exist_ok=True)
        (target / (case+'.json')).write_text(json.dumps({'case':case,'requests':rows,
            'acceptance':result.acceptance,'status':result.state['status'],
            'scoring_calls':result.scoring_calls, 'scoring_inputs':scoring_inputs,
            'fixed_base_byte_checks':len(byte_checks)}, indent=2, default=str), encoding='utf-8')

    assert all(r['orphan_free'] and r['latest_user_protected'] for r in rows)
    assert all(r.get('script_allowed', True) for r in rows)
    if os.getenv('JOB_AGENT_OPT_STABLE_TOOLS') == '1':
        assert len({r['tools_hash'] for r in rows}) == 1
    assert os.getenv('JOB_AGENT_OPT_SNAPSHOT_REFS') != '1' or not any(r['protected_overflow'] for r in rows), [(i,r['request_text_chars']) for i,r in enumerate(rows) if r['protected_overflow']]


@pytest.mark.parametrize('name', ['write_item', 'read_context'])
def test_stable_disallowed_has_no_effect_and_breaks_loop(database, monkeypatch, name):
    from test_shared_agent_loop import Harness, Model, call, settled
    from agent_runtime.career.repository import TaskRepository
    from agent_runtime.task_loop import TaskLoop
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
    from agent_runtime.task_host import TaskHost
    from agent_runtime.loop_engine import validate_call, ToolArgumentsError
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
    from agent_runtime.career.harness import TOOLS
    from agent_runtime.loop_engine import validate_call, ToolArgumentsError
    slim = slim_tools(TOOLS)
    valid = {'name':'import_job', 'args':{'url':'https://example.com','title':'Junior Analyst'}}
    validate_call(valid, slim)
    with pytest.raises(ToolArgumentsError):
        validate_call({'name':'score_jobs','args':{'application_ids':[]}}, slim)
    assert len(encoded(slim)) < len(encoded(TOOLS))

    from agent_runtime.career.harness import CareerHarness
    from agent_runtime.task_loop import CONTROL_TOOLS
    from agent_runtime.request_context import READ_CONTEXT
    from agent_runtime.career.prompt import SYSTEM, TRIMMED_SYSTEM
    tools = [*CONTROL_TOOLS, *CareerHarness.tools, READ_CONTEXT]
    output = os.getenv('OPT_STAGE2_OUTPUT')
    if output:
        Path(output).mkdir(parents=True, exist_ok=True)
        (Path(output)/'static-sizes.json').write_text(json.dumps({
            'all_tools_before':len(encoded(tools)), 'all_tools_after':len(encoded(slim_tools(tools))),
            'prompt_before':len(SYSTEM), 'prompt_after':len(TRIMMED_SYSTEM)}, indent=2))
