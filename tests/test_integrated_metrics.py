"""P1: final-request (wire) measurement. Synthetic requests only; no provider calls."""
import pytest

from agent_runtime import wire_metrics


@pytest.fixture(autouse=True)
def _fresh():
    wire_metrics.reset()
    yield
    wire_metrics.reset()


def payload(messages, tools=('search_jobs',)):
    return {'model': 'm', 'tools': [{'type': 'function', 'function': {'name': t, 'parameters': {}}} for t in tools],
            'messages': messages}


SYSTEM = {'role': 'system', 'content': 'You are a job agent. ' * 50}
USER = {'role': 'user', 'content': 'Find two junior data analyst jobs in New York.'}


def test_first_request_has_unknown_previous_and_no_text_is_returned():
    result = wire_metrics.measure(payload([SYSTEM, USER]), 'task|run|agent|m')
    assert result['wire_common_prefix_chars'] is None and result['wire_first_change'] == 'unknown_no_previous'
    assert 'You are a job agent' not in str(result)  # lengths and hashes only


def test_identical_retry_and_appended_tail():
    key = 'task|run|agent|m'
    first = wire_metrics.measure(payload([SYSTEM, USER]), key)
    retry = wire_metrics.measure(payload([SYSTEM, USER]), key)
    assert retry['wire_first_change'] == 'identical' and retry['wire_common_prefix_chars'] == first['wire_chars']
    appended = wire_metrics.measure(payload([SYSTEM, USER, {'role': 'assistant', 'content': 'ok'}]), key)
    assert appended['wire_first_change'] == 'message:2'
    assert appended['wire_common_prefix_chars'] >= first['wire_chars']


def test_tool_change_and_front_trim_are_located():
    key = 'task|run|agent|m'
    wire_metrics.measure(payload([SYSTEM, USER, {'role': 'assistant', 'content': 'old'}]), key)
    tools = wire_metrics.measure(payload([SYSTEM, USER, {'role': 'assistant', 'content': 'old'}],
                                         tools=('search_jobs', 'decide_job')), key)
    assert tools['wire_first_change'] == 'tools'
    trimmed = wire_metrics.measure(payload([SYSTEM, {'role': 'assistant', 'content': 'old'}],
                                           tools=('search_jobs', 'decide_job')), key)
    assert trimmed['wire_first_change'] == 'message:1'  # history trimmed right after the system prompt


def test_model_switch_and_restart_do_not_compare_unrelated_requests():
    wire_metrics.measure(payload([SYSTEM, USER]), 'task|run|agent|model-a')
    other = wire_metrics.measure(payload([SYSTEM, USER]), 'task|run|agent|model-b')
    assert other['wire_common_prefix_chars'] is None
    wire_metrics.reset()  # process restart: no previous request material
    assert wire_metrics.measure(payload([SYSTEM, USER]), 'task|run|agent|model-a')['wire_common_prefix_chars'] is None


def test_adapter_records_wire_metrics_without_changing_the_request(monkeypatch):
    from langchain_core.messages import HumanMessage, SystemMessage
    from job_agent.model import ProviderCompatibleChatOpenAI
    model = ProviderCompatibleChatOpenAI(model='m', api_key='k', base_url='https://provider.test/v1', max_retries=0)
    sent = []
    def fake(self, messages, stop=None, run_manager=None, **kwargs):
        from langchain_core.outputs import ChatGeneration, ChatResult
        from langchain_core.messages import AIMessage
        sent.append(self._get_request_payload(messages, stop=stop, **kwargs))
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content='ok'))])
    monkeypatch.setattr('langchain_openai.ChatOpenAI._generate', fake)
    from agent_runtime.provider_usage import capture_provider_attempts
    with capture_provider_attempts() as attempts:
        model._generate([SystemMessage(content='sys'), HumanMessage(content='hi')])
        model._generate([SystemMessage(content='sys'), HumanMessage(content='hi')])
    assert attempts[0]['wire_common_prefix_chars'] is None and attempts[1]['wire_first_change'] == 'identical'
    assert sent[0] == sent[1] and 'wire_chars' not in str(sent[0])
