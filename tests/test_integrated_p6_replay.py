"""Single-variable frozen B6 comparisons; no paid provider calls."""
import copy
import hashlib
import json
import os
from pathlib import Path
import pytest
from langchain_core.messages import ToolMessage
from eregion.domain.model import ProviderCompatibleChatOpenAI
from eregion.runtime import wire_metrics
from eregion.runtime.provider_usage import current_scope
from eregion.runtime.request_context import encoded
from test_b6_offline_replay import replay, offline_guard, frozen_web, ScriptedModel
from test_career_flow import career

VARIANTS = ['B0', 'STABLE_TOOLS', 'PROMPT_TRIM', 'SCOPED_CONTEXT', 'STATE_DELTAS', 'structured_checkpoint']

@pytest.mark.parametrize('variant', VARIANTS + ['trim_checkpoint'])
def test_frozen_context_single_variable(replay, career, monkeypatch, variant):
    for flag in VARIANTS[1:-1] + ['SNAPSHOT_REFS', 'VERIFY_AND_SCORE']:
        monkeypatch.setenv('JOB_AGENT_OPT_' + flag, '0')
    monkeypatch.setenv('JOB_AGENT_OPT_HISTORY_POLICY', 'current')
    if variant == 'trim_checkpoint':
        monkeypatch.setenv('JOB_AGENT_OPT_PROMPT_TRIM', '1')
        monkeypatch.setenv('JOB_AGENT_OPT_HISTORY_POLICY', 'structured_checkpoint')
    elif variant == 'structured_checkpoint': monkeypatch.setenv('JOB_AGENT_OPT_HISTORY_POLICY', variant)
    elif variant != 'B0': monkeypatch.setenv('JOB_AGENT_OPT_' + variant, '1')
    serializer = ProviderCompatibleChatOpenAI(model='offline', api_key='offline', base_url='https://offline.invalid/v1', max_retries=0)
    rows, scoring = [], []
    original = ScriptedModel.invoke
    wire_metrics.reset()
    def invoke(self, messages, tools):
        payload = serializer._get_request_payload(messages, tools=tools)
        metrics = copy.deepcopy(current_scope()['context_metrics'])
        measured = wire_metrics.measure(payload, variant)
        calls = {c['id'] for m in messages for c in getattr(m, 'tool_calls', [])}
        assert all(m.tool_call_id in calls for m in messages if isinstance(m, ToolMessage))
        live = json.loads(messages[-1].content)
        assert live['current_request']['message']['role'] == 'user'
        rows.append({'context': metrics, 'wire': measured,
                     'wire_bytes': len(encoded(payload).encode()),
                     'read_context': self.steps[self.calls]['tool'] == 'read_context'})
        return original(self, messages, tools)
    monkeypatch.setattr(ScriptedModel, 'invoke', invoke)
    handler = career.harness.analysis._fit_service._handler
    analyze = handler._analyze
    def capture(schema, system, content):
        scoring.append({'schema': schema.__name__, 'sha256': hashlib.sha256(encoded([system, content]).encode()).hexdigest()})
        return analyze(schema, system, content)
    monkeypatch.setattr(handler, '_analyze', capture)
    result = replay('correct')
    assert result.acceptance['status'] == 'passed'
    assert result.acceptance['qualified_count'] == 2
    assert not any(r['context']['protected_overflow'] for r in rows)
    output = os.getenv('OPT_P6_OUTPUT')
    if output:
        target = Path(output)
        target.mkdir(parents=True, exist_ok=True)
        (target / (variant + '.json')).write_text(json.dumps({
            'variant': variant, 'measurement': 'production request serializer, scripted model; no provider tokens',
            'acceptance': result.acceptance, 'scoring_inputs': scoring,
            'router_calls': len(rows), 'requests': rows}, indent=2), encoding='utf-8')
