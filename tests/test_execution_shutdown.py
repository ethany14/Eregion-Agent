"""M45-SHUTDOWN-001: owners drain their in-flight work before their resources close."""
import threading
import time
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

from agent_runtime.career.interview_queue import InterviewQueue
from agent_runtime.career.repository import TaskRepository
from agent_runtime.career.service import CareerService
from agent_runtime.execution import ExecutionClosed, ExecutionService
from api.db import create_database
from test_shared_agent_loop import Harness, Model, call, finish


class BlockingHarness(Harness):
    """A career harness whose tool blocks on an Event and whose close records order."""

    def __init__(self):
        super().__init__()
        self.entered, self.release, self.events = threading.Event(), threading.Event(), []

    def execute(self, task_id, name, args, **kwargs):
        self.events.append('tool_enter')
        self.entered.set()
        assert self.release.wait(10)
        self.events.append('tool_exit')
        return super().execute(task_id, name, args, **kwargs)

    def close(self):
        self.events.append('resource_close')  # discovery / Treg / browser in production


@pytest.fixture
def database(tmp_path):
    db = create_database('sqlite:///' + (tmp_path / 'shutdown.db').as_posix(), create_schema_for_tests=True)
    yield db
    db.close()  # the database closes last


def test_career_close_waits_for_the_running_tool_before_closing_resources(database):
    harness = BlockingHarness()
    model = Model([AIMessage(content='', tool_calls=[call('write_item', {'value': 'x'}, 'w1')]), finish('done')])
    execution = ExecutionService()
    service = CareerService(SimpleNamespace(database=database), None, harness=harness,
                            model_factory=lambda: model, start_alert_scheduler=False, execution=execution)
    task = service.loop.start('write one item', 'shutdown-1')
    assert harness.entered.wait(10)

    closer = threading.Thread(target=service.close)
    closer.start()
    time.sleep(0.3)
    assert 'resource_close' not in harness.events  # close is waiting for the in-flight tool
    harness.release.set()
    closer.join(10)
    assert not closer.is_alive()
    assert harness.events[:3] == ['tool_enter', 'tool_exit', 'resource_close']

    # After close nothing new is scheduled or executed, even though the shared
    # service itself is still open for other kinds.
    service.loop.schedule(task['task_id'])
    with pytest.raises(ExecutionClosed):
        execution.submit('career_task', None, lambda: None)
    time.sleep(0.2)
    assert harness.events.count('tool_enter') == 1
    assert not execution.closed
    execution.close(wait=True)


def test_interview_close_drains_inputs_and_refuses_new_ones():
    execution = ExecutionService()
    queue = InterviewQueue(harness=None, execution=execution)
    entered, release, events = threading.Event(), threading.Event(), []

    def run(task_id):
        events.append(('enter', task_id)); entered.set()
        assert release.wait(10)
        events.append(('exit', task_id))
        with queue.lock:
            queue.running.pop(task_id, None)

    queue._run = run
    queue.start('t1')
    assert entered.wait(5)
    closer = threading.Thread(target=lambda: (queue.close(), events.append(('closed', None))))
    closer.start()
    time.sleep(0.2)
    assert ('closed', None) not in events
    release.set()
    closer.join(10)
    assert events == [('enter', 't1'), ('exit', 't1'), ('closed', None)]
    queue.start('t2')  # refused after close: no new external work
    time.sleep(0.1)
    assert ('enter', 't2') not in events
    execution.close(wait=True)


def test_stopping_one_kind_cancels_its_queued_jobs_and_leaves_other_kinds_running():
    execution = ExecutionService()
    execution.register_kind('a', max_workers=1)
    execution.register_kind('b', max_workers=1)
    gate, ran = threading.Event(), []
    first = execution.submit('a', 'x', lambda: (gate.wait(5), ran.append('x')))
    queued = execution.submit('a', 'y', lambda: ran.append('y'))
    threading.Timer(0.2, gate.set).start()
    assert execution.stop_kind('a', timeout=5)
    assert first.done() and queued.cancelled() and ran == ['x']
    assert execution.inventory()['kinds']['a']['active'] == []
    assert execution.submit('b', 'z', lambda: 'ok').result(5) == 'ok'
    execution.close(wait=True)
