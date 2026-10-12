"""Budget stops deliver local saved results without restarting paid work."""
import pytest

from agent_runtime.task_loop import TaskLoop
from agent_runtime.provider_usage import TaskProviderBudgetExceeded
from agent_runtime.career.repository import TaskRepository
from test_auto_apply import database
from test_career_flow import settled
from test_task_loop import Harness


@pytest.mark.parametrize('delivery_mode', ['saved', 'empty', 'absent'])
def test_provider_budget_stop_delivers_saved_results(database, delivery_mode):
    class Model:
        calls = 0

        def invoke(self, messages, tools):
            self.calls += 1
            raise TaskProviderBudgetExceeded('provider_attempts')

    model = Model()
    repo = TaskRepository(database.session_factory)
    harness = Harness()
    saved = '- Recommended: Data Analyst | score 43.46 | https://example.com/jobs/1'
    deliveries = []
    if delivery_mode != 'absent':
        def delivery(state):
            deliveries.append(state['task_id'])
            return [saved] if delivery_mode == 'saved' else []
        harness.terminal_delivery = delivery
    loop = TaskLoop(repo, harness, model_factory=lambda: model)
    try:
        task = loop.start('Find two matching jobs.', 'budget-delivery')
        result = settled(repo, task['task_id'])
        assert result['status'] == 'needs_input'
        assert result['error']['code'] == 'provider_budget'
        assert result['error']['reason'] == 'provider_attempts'
        assert result['error']['retryable'] is False
        messages = [m['text'] for m in result['messages'] if m['role'] == 'assistant']
        assert len(messages) == 1
        assert 'the requested work is not complete' in messages[0]
        assert ('Saved so far:' in messages[0]) == (delivery_mode == 'saved')
        assert (saved in messages[0]) == (delivery_mode == 'saved')
        assert deliveries == ([] if delivery_mode == 'absent' else [task['task_id']])
        assert model.calls == 1
        assert not result['history']
    finally:
        loop.close()
