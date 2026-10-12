"""Unified loop M6: restart dry-run on database copies built at the current schema head."""
import importlib.util
import json
import os
from pathlib import Path

import pytest

from agent_runtime.auto_apply.repository import ApplyRepository
from agent_runtime.career.repository import TaskRepository
from agent_runtime.sessions.events import SessionEvent, SessionEventType
from agent_runtime.sessions.repository import SessionRepository
from agent_runtime.sessions.state import SessionMessageDraft, SessionState, SessionStatus
from agent_runtime.tools.messages import AgentMessage, NormalizedToolCall
from api.db import create_database, upgrade_database
from test_auto_apply import request
from test_multi_agent import make_plan, validate

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('unified_loop_dry_run', ROOT / 'scripts/unified_loop_dry_run.py')
dry = importlib.util.module_from_spec(spec); spec.loader.exec_module(dry)


def _session(repo, session_id, status, **extra):
    state = repo.create(SessionState(session_id=session_id, allowed_tools=frozenset({'read'})),
                        SessionEvent(session_id=session_id, event_type=SessionEventType.SESSION_CREATED),
                        messages=[SessionMessageDraft(message=AgentMessage(
                            message_id=f'{session_id}-system', role='system', content='policy'))])
    if status == SessionStatus.ACTIVE and not extra:
        return state
    messages = extra.pop('messages', [])
    return repo.save_transition(SessionState.model_validate({**state.model_dump(), 'status': status, **extra}),
        SessionEvent(session_id=session_id, event_type=SessionEventType.SESSION_RESUMED),
        expected_version=state.version, messages=[SessionMessageDraft(message=m) for m in messages])


def build_source(path: Path) -> Path:
    url = f"sqlite:///{path.as_posix()}"
    upgrade_database(url)  # real migrations, not create_all
    db = create_database(url)
    try:
        tasks = TaskRepository(db.session_factory)
        for key, status in [('queued', 'queued'), ('running', 'running'), ('waiting', 'waiting'),
                            ('asking', 'needs_input'), ('done', 'completed'), ('paused', 'running')]:
            state, _ = tasks.create(f'goal {key}', key)
            tasks.change(state['task_id'], status=status, **({'pause_requested': True} if key == 'paused' else {}))
        applications = ApplyRepository(db.session_factory)
        for n, (status, mode) in enumerate([('running', 'hybrid'), ('submitting', 'hybrid'),
                                            ('submitted', 'hybrid'), ('awaiting_review', 'autofill')]):
            state, _ = applications.create(request(automation_mode=mode, idempotency_key=f'req-{n:04d}',
                                                   url=f'https://jobs.lever.co/example/job{n}'))
            applications.save(state, status=status)
        sessions = SessionRepository(db.session_factory)
        _session(sessions, 'parent', SessionStatus.ACTIVE)
        _session(sessions, 's-done', SessionStatus.COMPLETED, terminal_reason='completed')
        call = NormalizedToolCall(tool_call_id='c1', tool_name='read', arguments={'text': 'x'})
        assistant = AgentMessage(message_id='s-run-a1', role='assistant', tool_calls=[call])
        _session(sessions, 's-running', SessionStatus.RUNNING, messages=[assistant],
                 pending_assistant_message_id='s-run-a1', pending_tool_call_ids=['c1'])
        from agent_runtime.multi_agent.repository import AgentTaskRepository
        agent_tasks = AgentTaskRepository(db.session_factory)
        plan = make_plan(); agent_tasks.create_plan(plan, validate(plan))
    finally:
        db.close()
    return path


@pytest.fixture
def source(tmp_path):
    return build_source(tmp_path / 'source.db')


def test_restart_dry_run_resumes_each_in_flight_object_once_and_keeps_history(source, tmp_path):
    first = dry.dry_run(source, tmp_path / 'run-1')
    second = dry.dry_run(source, tmp_path / 'run-2')
    assert first == second  # repeatable on fresh copies
    assert first['source_unchanged'] and first['history_unchanged'] and first['single_owner']
    assert first['schema_head'] and first['schema_head'].startswith('0037')
    assert len(first['career_task']['resumed']) == 2          # queued + running; paused is not resumed
    assert len(first['career_task']['waiting']) == 1 and len(first['career_task']['needs_input']) == 1
    app = first['application_run']
    assert len(app['resumed_on_browser_owner']) == 1           # hybrid running only
    assert len(app['submission_unknown_manual']) == 1          # never auto-resubmitted
    assert first['session'] == {'in_flight': ['s-running'], 'legacy_drain_registered': [],
                                'shared_kernel': ['s-running'], 'pending_calls': {'s-running': ['c1']}}
    assert len(first['agent_task']['ready']) == 1
    assert first['execution_inventory'] == {'career_task': {'recovered': True},
                                            'application_run': {'recovered': True}}
    if os.getenv('UNIFIED_LOOP_DRY_RUN_REPORT'):
        Path(os.environ['UNIFIED_LOOP_DRY_RUN_REPORT']).write_text(json.dumps(first, indent=2, sort_keys=True))


def test_second_restart_on_the_same_copy_keeps_unknown_submissions_unknown(source, tmp_path):
    first = dry.dry_run(source, tmp_path / 'once')
    copy = tmp_path / 'once' / 'dry-run-copy.db'
    again = dry.dry_run(copy, tmp_path / 'twice')
    assert again['history_unchanged'] and again['single_owner']
    assert again['application_run']['submission_unknown_manual'] == first['application_run']['submission_unknown_manual']
    assert again['application_run']['transitions'] == {}       # no further state change on re-run


def test_the_user_database_is_refused(monkeypatch, capsys):
    monkeypatch.setattr('sys.argv', ['dry', '--source', str(dry.USER_DATABASE), '--work', 'unused'])
    assert dry.main() == 2
