"""Offline production-handler workflow gates."""
import copy
import hashlib
import json
import os
import subprocess
import types
from pathlib import Path

import pytest
from agent_runtime.request_context import encoded
from agent_runtime.provider_usage import current_scope, TaskProviderBudgetExceeded
from agent_runtime.career.harness import CareerHarness
from agent_runtime.career.repository import TaskRepository
from agent_runtime.task_host import TaskHost
from test_career_flow import career, execute
from test_b6_offline_replay import replay, frozen_web, offline_guard, ScriptedModel
import test_board_directory_replay as directory

BASE = '566f5642f921347df0446b7c40aa52d80ccbeaa9'
URL = 'https://jobs.lever.co/example/abc123'


def collapse(steps):
    steps = copy.deepcopy(steps)
    imports = {s['arguments']['url']: s for s in steps if s['tool'] == 'import_job'}
    removed = set()
    for i, step in enumerate(steps):
        if step['tool'] == 'read_job':
            url = step['arguments']['url']
            step['tool'] = 'verify_and_score'
            if url in imports:
                step['arguments'].update(imports[url]['arguments'])
        if step['tool'] in {'import_job', 'score_job'}:
            removed.add(i)
    # Body/context inspections used solely between mechanical steps become
    # redundant. Recommendation decisions and source recovery remain intact.
    for i, step in enumerate(steps):
        if (step['tool'] == 'read_context'
                and steps[step['context_step']]['tool'] in {'verify_and_score','import_job','score_job'}):
            removed.add(i)
    indices = {old:new for new,old in enumerate(i for i in range(len(steps)) if i not in removed)}
    result = [s for i, s in enumerate(steps) if i not in removed]
    for step in result:
        if 'context_step' in step:
            step['context_step'] = indices[step['context_step']]
    return result


@pytest.mark.parametrize('mode', ['granular', 'composite'])
@pytest.mark.parametrize('case', ['r1', 'r2', 'r3', 'correct', 'directory-positive', 'directory-negative'])
def test_replay_measurements(replay, frozen_web, career, monkeypatch, mode, case):
    monkeypatch.setenv('JOB_AGENT_OPT_VERIFY_AND_SCORE', '1' if mode == 'composite' else '0')
    rows, hashes = [], []
    invoke = ScriptedModel.invoke
    def capture(self, messages, tools):
        rows.append(copy.deepcopy(current_scope()['context_metrics']))
        return invoke(self, messages, tools)
    monkeypatch.setattr(ScriptedModel, 'invoke', capture)
    handler = career.harness.analysis._fit_service._handler
    analyze = handler._analyze
    def scoring(schema, system, content):
        hashes.append({'schema': schema.__name__, 'sha256': hashlib.sha256(encoded([system, content]).encode()).hexdigest()})
        return analyze(schema, system, content)
    monkeypatch.setattr(handler, '_analyze', scoring)
    results = []
    def run(name):
        if mode == 'composite':
            frozen_web['replays'][name]['steps'] = collapse(frozen_web['replays'][name]['steps'])
        result = replay(name)
        results.append(result)
        return result
    if case == 'directory-positive':
        directory.test_directory_blocked_recovery_two_qualified(run, frozen_web, monkeypatch)
    elif case == 'directory-negative':
        directory.test_directory_only_nonqualifying_finishes_honestly(run, frozen_web, monkeypatch)
    else:
        run(case)
    result = results[0]
    assert result.acceptance['qualified_count'] == {'r1':1, 'r2':0, 'r3':0, 'correct':2, 'directory-positive':2, 'directory-negative':0}[case]
    if case == 'r1':
        associate = next(j for j in result.state['recommendations'] if j['title'] == 'Associate Data Analyst')
        assert 'Level unverified' in associate['caveats']
    assert result.summary['provider_usage']['calls'] == 0
    if os.getenv('JOB_AGENT_OPT_SNAPSHOT_REFS') == '1':
        assert not any(r['protected_overflow'] for r in rows)
    output = os.getenv('OPT_STAGE4_OUTPUT')
    if output:
        target = Path(output); target.mkdir(parents=True, exist_ok=True)
        (target / f'{case}-{mode}.json').write_text(json.dumps({'case':case, 'mode':mode,
            'requests':rows, 'decisions':result.model.calls, 'scoring_inputs':hashes,
            'acceptance':result.acceptance, 'status':result.state['status']}, indent=2), encoding='utf-8')


@pytest.mark.parametrize('boundary', ['read_job', 'import_job', 'score_job'])
@pytest.mark.parametrize('when', ['after_effect', 'after_checkpoint'])
def test_crash_resume(career, monkeypatch, boundary, when):
    c = career
    monkeypatch.setenv('JOB_AGENT_OPT_VERIFY_AND_SCORE', '1')
    original = c.harness.execute
    class Crash(BaseException): pass
    hit = []
    analyses, reads = [], []
    read = c.harness.discovery.job
    def count_read(url):
        reads.append(url)
        return read(url)
    monkeypatch.setattr(c.harness.discovery, 'job', count_read)
    analyze = c.harness.analysis.analyze
    async def count_analysis(*args, **kwargs):
        analyses.append(args)
        return await analyze(*args, **kwargs)
    monkeypatch.setattr(c.harness.analysis, 'analyze', count_analysis)
    if when == 'after_effect':
        def crash(tid, name, args, **kw):
            result = original(tid, name, args, **kw)
            if name == boundary and not hit:
                hit.append(name); raise Crash()
            return result
        monkeypatch.setattr(c.harness, 'execute', crash)
    else:
        change = c.repository.change
        def crash(tid, mutation=None, **kw):
            result = change(tid, mutation, **kw)
            records = list(result.get('verification_workflows', {}).values())
            if records and boundary in records[-1].get('completed_steps', []) and not hit:
                hit.append(boundary); raise Crash()
            return result
        monkeypatch.setattr(c.repository, 'change', crash)
    with pytest.raises(Crash):
        original(c.state['task_id'], 'verify_and_score', {'url':URL}, call_id='crash')
    assert hit
    repo = TaskRepository(c.runtime.database.session_factory)
    h = CareerHarness(c.runtime, c.applications, repo, discovery=c.harness.discovery,
                      fit_service=c.harness.analysis._fit_service)
    monkeypatch.setattr(h.analysis, 'analyze', count_analysis)
    result = h.execute(c.state['task_id'], 'verify_and_score', {'url':URL}, call_id='restart')
    app = c.runtime.workspace.get_application(result['application_id'])
    repeated = h.execute(c.state['task_id'], 'verify_and_score', {'url':URL}, call_id='repeat')
    assert repeated['no_new_evidence']
    assert repeated['application_id'] == result['application_id']
    assert c.runtime.workspace.get_application(result['application_id']).version == app.version
    assert len(analyses) == 1
    assert reads == [URL]
    assert len(c.runtime.workspace.list_applications()) == 1
    assert result['completed_steps'] == ['read_job','import_job','score_job']
    assert 'opening_level' in result and 'qualification_evidence' in result
    assert result['location'] == 'Remote'
    assert not repo.get(c.state['task_id']).get('recommendations')


@pytest.mark.parametrize('kind', ['blocked','vacancy','unreadable','scoring','budget'])
def test_failure_parity(career, monkeypatch, kind):
    from agent_runtime.career.source_health import SourceBlocked
    from agent_runtime.career.posting_qualification import PostingRejected
    c = career; monkeypatch.setenv('JOB_AGENT_OPT_VERIFY_AND_SCORE', '1')
    errors = {'blocked':SourceBlocked('browser:example.com'),
              'vacancy':PostingRejected('Not a current vacancy',code='not_current_vacancy'),
              'unreadable':ValueError('Unreadable body'), 'scoring':RuntimeError('Scoring failed'),
              'budget':TaskProviderBudgetExceeded('provider_attempts')}
    original = c.harness.execute
    failing = 'score_job' if kind in {'scoring','budget'} else 'read_job'
    def fail(tid, name, args, **kw):
        if name == failing: raise errors[kind]
        return original(tid, name, args, **kw)
    monkeypatch.setattr(c.harness, 'execute', fail)
    host = object.__new__(TaskHost)
    if kind != 'budget': expected = host.action_error(errors[kind])
    with pytest.raises(type(errors[kind])) as caught:
        original(c.state['task_id'],'verify_and_score',{'url':URL},call_id='failure')
    if kind == 'budget':
        assert caught.value is errors[kind]
        assert caught.value.workflow_detail == {'completed_steps':['read_job','import_job'], 'failed_step':'score_job'}
    else:
        outcome = host.action_error(caught.value)
        assert all(outcome[k] == v for k,v in expected.items())
        assert outcome['failed_step'] == failing
        assert outcome['completed_steps'] == ([] if failing == 'read_job' else ['read_job','import_job'])
        assert ('fallback' in outcome) == (kind in {'unreadable','scoring'})
        assert next(iter(c.repository.get(c.state['task_id'])['verification_workflows'].values()))['failure']


@pytest.mark.parametrize('optimized', [False, True])
def test_flag_off_base_arrays_and_requests(career, monkeypatch, optimized):
    from test_remaining_search_runtime import host_for
    from agent_runtime.request_context import prepare_request, ContextArchive
    from agent_runtime.loop_context import ConversationWindow
    monkeypatch.setenv('JOB_AGENT_OPT_VERIFY_AND_SCORE','0')
    for flag in ('STABLE_TOOLS','PROMPT_TRIM','SNAPSHOT_REFS'):
        monkeypatch.setenv('JOB_AGENT_OPT_'+flag,'1' if optimized else '0')
    monkeypatch.setenv('JOB_AGENT_OPT_HISTORY_POLICY','checkpoint' if optimized else 'current')
    source = subprocess.check_output(['git','show',BASE+':agent_runtime/career/harness.py']).decode()
    module = types.ModuleType('agent_runtime.career._stage4_base')
    exec(compile(source,'base/harness.py','exec'), module.__dict__)
    state=career.repository.get(career.state['task_id'])
    assert career.harness.available_tools(state) == module.CareerHarness.available_tools(career.harness,state)
    assert career.harness.stable_tools(state) == module.CareerHarness.available_tools(career.harness,state,stable=True)
    with pytest.raises(ValueError,match='disabled'):
        execute(career,'verify_and_score',url=URL)
    host=host_for(career); turn=host.observe()
    base=types.ModuleType('agent_runtime._stage4_host')
    exec(subprocess.check_output(['git','show',BASE+':agent_runtime/task_host.py']).decode(),base.__dict__)
    old=base.TaskHost.observe(host)
    assert turn.tools == old.tools and turn.prompt == old.prompt
    assert turn.allowed_tools == old.allowed_tools
    a,_=prepare_request(turn.prompt,turn.tools,ConversationWindow(),turn.snapshot,ContextArchive())
    b,_=prepare_request(old.prompt,old.tools,ConversationWindow(),turn.snapshot,ContextArchive())
    assert encoded([m.model_dump() for m in a]) == encoded([m.model_dump() for m in b])


@pytest.mark.parametrize('stable', ['0', '1'])
@pytest.mark.parametrize('restriction', ['search', 'recommendation', 'completion', 'must_decide'])
def test_execution_masks(career, monkeypatch, stable, restriction):
    from test_remaining_search_runtime import host_for
    from agent_runtime.loop_engine import validate_call, ToolArgumentsError
    monkeypatch.setenv('JOB_AGENT_OPT_VERIFY_AND_SCORE', '1')
    monkeypatch.setenv('JOB_AGENT_OPT_STABLE_TOOLS', stable)
    c = career
    if restriction == 'search':
        c.repository.change(c.state['task_id'], messages=[{'id':'search','role':'user','text':'Find junior data analyst jobs'}])
    elif restriction == 'recommendation':
        monkeypatch.setattr(c.harness, 'recommendation_run', lambda _: {'status':'running'})
        c.harness.alerts = types.SimpleNamespace(recommended=lambda: [])
    elif restriction == 'completion':
        c.repository.change(c.state['task_id'], model_calls=57)
    else:
        c.repository.change(c.state['task_id'], progress_guard={'revision':0,'count':2})
    turn = host_for(c).observe()
    allowed = turn.allowed_tools if turn.allowed_tools is not None else turn.tools
    names = {t['function']['name'] for t in allowed}
    assert ('verify_and_score' in names) == all(n in names for n in ('read_job','import_job','score_job'))
    call = {'name':'verify_and_score','args':{'url':URL}}
    if restriction == 'completion':
        with pytest.raises(ToolArgumentsError): validate_call(call, allowed)
    else:
        validate_call(call, allowed)


def test_granular_then_composite_has_no_new_evidence(career, monkeypatch):
    from test_remaining_search_runtime import host_for
    monkeypatch.setenv('JOB_AGENT_OPT_VERIFY_AND_SCORE','1')
    c = career
    execute(c,'read_job',url=URL)
    job = execute(c,'import_job',url=URL)
    execute(c,'score_job',application_id=job['application_id'])
    host = host_for(c)
    for i in range(3):
        turn = host.observe()
        call = {'name':'verify_and_score','args':{'url':URL},'id':str(i)}
        result = host.execute(call,turn)
        assert result['no_new_evidence']
        host.after_action(call,result,turn)
    assert c.repository.get(c.state['task_id'])['error']['code'] == 'no_progress'


def test_real_blocked_and_rejected_source_guards(career, monkeypatch):
    from agent_runtime.career.source_health import record_browser
    from agent_runtime.career.posting_qualification import PostingRejected
    monkeypatch.setenv('JOB_AGENT_OPT_VERIFY_AND_SCORE','1')
    c = career; host = object.__new__(TaskHost)
    record_browser(c.repository,c.state['task_id'],{'url':URL,'blocked':True})
    outcomes=[]
    for name in ('read_job','verify_and_score'):
        try: execute(c,name,url=URL)
        except Exception as exc: outcomes.append(host.action_error(exc))
    assert all(outcomes[1][k] == v for k,v in outcomes[0].items())
    assert outcomes[1]['error_code'] == 'source_blocked'
    c.repository.change(c.state['task_id'],search_source_health={})
    monkeypatch.setattr(c.harness.discovery,'job',lambda url: {'url':url,'title':'Analyst',
        'description':'Apply to our talent network for future opportunities.'})
    with pytest.raises(PostingRejected): execute(c,'verify_and_score',url=URL)
    state = c.repository.get(c.state['task_id'])
    assert state['candidate_rejections'] and not state['jobs']


def test_saved_body_survives_eviction_restart(career, monkeypatch):
    monkeypatch.setenv('JOB_AGENT_OPT_VERIFY_AND_SCORE','1')
    c = career
    execute(c,'verify_and_score',url=URL)
    c.repository.change(c.state['task_id'],retrieved_jobs={})
    monkeypatch.setattr(c.harness.discovery,'job',lambda _: pytest.fail('completed read repeated'))
    result = execute(c,'verify_and_score',url=URL)
    assert result['no_new_evidence'] and result['match_score'] is not None


@pytest.mark.parametrize('mode',['granular','composite'])
def test_actual_provider_budget_stops_before_attempt(career, monkeypatch, mode):
    from agent_runtime.provider_usage import usage_scope, UsageLedger, provider_call
    c = career
    monkeypatch.setenv('JOB_AGENT_OPT_VERIFY_AND_SCORE','1')
    monkeypatch.setenv('JOB_AGENT_TASK_MAX_PROVIDER_ATTEMPTS','0')
    attempted=[]
    async def analyze(*args, **kwargs):
        with provider_call('offline-never-invoked'):
            attempted.append(True)
    monkeypatch.setattr(c.harness.analysis,'analyze',analyze)
    ledger=UsageLedger(c.runtime.database.session_factory)
    with usage_scope(task_id=c.state['task_id'],ledger=ledger):
        with pytest.raises(TaskProviderBudgetExceeded,match='provider_attempts'):
            if mode == 'composite': execute(c,'verify_and_score',url=URL)
            else:
                execute(c,'read_job',url=URL)
                job=execute(c,'import_job',url=URL)
                execute(c,'score_job',application_id=job['application_id'])
    assert not attempted and ledger.summary(task_id=c.state['task_id'])['calls']==0
    state=c.repository.get(c.state['task_id'])
    assert len(state['jobs'])==1 and not state.get('analyses')
    if mode=='composite':
        record=next(iter(state['verification_workflows'].values()))
        assert record['pending_step']=='score_job'
        assert record['completed_steps']==['read_job','import_job']


def test_unreadable_rendered_body_exact_failure(career, monkeypatch):
    c=career; monkeypatch.setenv('JOB_AGENT_OPT_VERIFY_AND_SCORE','1')
    page={'url':URL,'primary_heading':'Python Engineer','text':'too short', 'controls':[]}
    c.harness._browsing=types.SimpleNamespace(inspect=lambda _:page,call=lambda *a,**kw:page)
    host=object.__new__(TaskHost)
    outcomes=[]
    for name in ('read_job','verify_and_score'):
        try: execute(c,name,url=URL)
        except ValueError as exc: outcomes.append(host.action_error(exc))
    assert len(outcomes)==2
    assert all(outcomes[1][k]==v for k,v in outcomes[0].items())
    assert outcomes[1]['failed_step']=='read_job'
    assert not c.repository.get(c.state['task_id'])['jobs']



def test_saved_body_local_import_on_blocked_source_and_tracking_identity(career, monkeypatch):
    from agent_runtime.career.source_health import record_browser
    monkeypatch.setenv('JOB_AGENT_OPT_VERIFY_AND_SCORE','1')
    c=career
    execute(c,'read_job',url=URL)
    record_browser(c.repository,c.state['task_id'],{'url':URL,'blocked':True})
    monkeypatch.setattr(c.harness.discovery,'job',lambda _:pytest.fail('saved body was fetched again'))
    first=execute(c,'verify_and_score',url=URL)
    second=execute(c,'verify_and_score',url=URL+'?msockid=tracking-only')
    assert first['application_id']==second['application_id']
    assert second['no_new_evidence']
    assert len(c.runtime.workspace.list_applications())==1
    assert not c.repository.get(c.state['task_id']).get('recommendations')



def test_changed_resume_failure_does_not_claim_old_score_completed(career, monkeypatch):
    monkeypatch.setenv('JOB_AGENT_OPT_VERIFY_AND_SCORE','1')
    c=career
    execute(c,'verify_and_score',url=URL)
    monkeypatch.setattr(c.harness,'candidate',lambda: ({},''))
    with pytest.raises(ValueError,match='Attach a resume') as caught:
        execute(c,'verify_and_score',url=URL)
    outcome=object.__new__(TaskHost).action_error(caught.value)
    assert outcome['completed_steps']==['read_job','import_job']
    assert outcome['failed_step']=='score_job' and outcome['fallback']
    assert len(c.runtime.workspace.list_applications())==1



@pytest.mark.parametrize('mode',['granular','composite'])
def test_loop_budget_outcome_keeps_completed_steps(career, monkeypatch, mode):
    from agent_runtime.career.service import CareerService
    from agent_runtime.provider_usage import provider_call
    from test_career_flow import ToolModel, settled
    c=career
    # The service restores queued tasks; this fixture's seed is not this replay.
    c.repository.change(c.state['task_id'],status='cancelled',pause_requested=True)
    monkeypatch.setenv('JOB_AGENT_OPT_VERIFY_AND_SCORE','1' if mode=='composite' else '0')
    monkeypatch.setenv('JOB_AGENT_TASK_MAX_PROVIDER_ATTEMPTS','0')
    async def analyze(*a,**kw):
        with provider_call('offline-budget-probe'):
            pytest.fail('An exhausted budget permitted provider work')
    monkeypatch.setattr(c.harness.analysis,'analyze',analyze)
    names=iter(['verify_and_score'] if mode=='composite' else ['read_job','import_job','score_job'])
    def decide(snapshot):
        name=next(names)
        return name, ({'application_id':snapshot['jobs'][0]['application_id']} if name=='score_job' else {'url':URL})
    model=ToolModel(decide)
    service=CareerService(c.runtime,c.applications,harness=c.harness,
        model_factory=lambda:model,start_alert_scheduler=False)
    try:
        started=service.start('Find and score Python jobs','stage4-budget-'+mode)
        state=settled(service.repository,started['run_id'])
        assert state['status']=='needs_input'
        assert state['error']['code']=='provider_budget'
        assert state['error']['reason']=='provider_attempts'
        assert state['error']['retryable'] is False
        assert len(state['jobs'])==1 and not state.get('analyses')
        if mode=='composite':
            assert state['error']['completed_steps']==['read_job','import_job']
            assert state['error']['failed_step']=='score_job'
        else: assert 'completed_steps' not in state['error']
    finally: service.close()
