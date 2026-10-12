"""R7 T0: LinkedIn MCP adapter against a fake server; zero real model or account requests.

Fake responses follow the pinned upstream contract
(stickerdaniel/linkedin-mcp-server @ 5bdef1c9, tools/job.py and tools/company.py).
"""
import json
import sys

import pytest
from mcp.types import CallToolResult, TextContent, Tool

from agent_runtime.career.linkedin_source import (BUSINESS_TOOLS, LinkedInMcpSource, LinkedInSourceStopped,
                                                  job_url)
from agent_runtime.mcp.config import McpRuntimeConfig, McpStdioServerConfig
from agent_runtime.mcp.errors import McpCallTimeoutError
from agent_runtime.mcp.manager import McpToolManager
from agent_runtime.registry import ToolRegistry

ANY = {'type': 'object', 'properties': {}, 'additionalProperties': True}
UPSTREAM_TOOLS = ['search_jobs', 'get_job_details', 'get_job_apply_url', 'get_saved_jobs', 'search_companies',
                  'get_company_profile', 'get_company_posts', 'get_company_employees', 'get_person_profile',
                  'send_message', 'close_session']


def result(payload=None, *, error=None, text=None):
    body = text if text is not None else (error if error is not None else json.dumps(payload))
    return CallToolResult(content=[TextContent(type='text', text=body)],
                          structuredContent=None if error is not None or text is not None else payload,
                          isError=error is not None)


class FakeLinkedIn:
    """Fake MCP client: records calls and answers from a script keyed by tool name."""

    def __init__(self, script=None):
        self.script, self.calls = dict(script or {}), []

    def connect(self):
        return None

    def list_tools(self):
        return [Tool(name=name, description=name, inputSchema=ANY) for name in UPSTREAM_TOOLS]

    def call_tool(self, name, arguments, *, timeout_seconds=None):
        self.calls.append((name, arguments, timeout_seconds))
        answer = self.script[name]
        answer = answer.pop(0) if isinstance(answer, list) else answer
        if isinstance(answer, Exception):
            raise answer
        return answer

    def close(self):
        return None


def manager_with(fake):
    config = McpRuntimeConfig(servers=[McpStdioServerConfig(
        server_id='linkedin', command=sys.executable, args=['-c', 'pass'], required=False,
        tool_allowlist=set(BUSINESS_TOOLS), read_only_tools=set(BUSINESS_TOOLS),
        startup_timeout_seconds=10, call_timeout_seconds=120)])
    manager = McpToolManager(config=config, registry=ToolRegistry(), client_factory=lambda _c: fake)
    manager.start()
    return manager


SEARCH = {'url': 'https://www.linkedin.com/jobs/search/?keywords=junior%20data%20analyst',
          'sections': {'search_results': 'Junior Data Analyst ...'},
          'job_ids': ['4475055219', '4472375348', '4475055219', 'not-an-id'], 'total': {'count': 1000, 'exact': False}}
DETAIL = {'url': job_url('4475055219'), 'sections': {'job_posting': 'About the job\n' + 'Analyse data. ' * 80}}


def test_only_business_tools_are_exposed_through_the_real_manager():
    fake = FakeLinkedIn({'search_jobs': result(SEARCH)})
    manager = manager_with(fake)
    try:
        exposed = {name.split('__')[-1] for name in manager.public_tool_names}
        assert exposed == BUSINESS_TOOLS          # no send_message / profiles / saved jobs / employees
        source = LinkedInMcpSource(manager.call_tool)
        found = source.search('junior data analyst', 'New York, NY', experience_level='entry,associate', max_pages=5)
    finally:
        manager.stop()
    name, args, timeout = fake.calls[0]
    assert name == 'search_jobs' and args['max_pages'] == 2 and args['experience_level'] == 'entry,associate'
    assert timeout == 120
    assert [j['provider_job_id'] for j in found['jobs']] == ['4475055219', '4472375348']   # deduped, identity only
    assert found['dropped_without_identity'] == 1 and found['total_exact'] is False
    assert all(j['completeness'] == 'card' and j['title'] is None for j in found['jobs'])  # unknown stays unknown


def test_no_match_is_empty_not_a_failure_and_partial_is_flagged():
    source = LinkedInMcpSource(FakeLinkedIn({'search_jobs': [
        result({'job_ids': [], 'section_errors': {'search_results': {'type': 'no_matching_jobs'}}}),
        result({**SEARCH, 'section_errors': {'page_2': {'type': 'timeout'}}})]}).call_tool_for())
    assert source.search('x')['status'] == 'no_match'
    partial = source.search('x')
    assert partial['status'] == 'partial' and partial['partial'] and partial['jobs']


def test_unsupported_filter_is_reported_as_not_applied():
    fake = FakeLinkedIn({'search_jobs': result(SEARCH)})
    found = LinkedInMcpSource(fake.call_tool_for()).search('x', experience_level='junior')
    assert found['unapplied_filters'] == ['experience_level'] and 'experience_level' not in fake.calls[0][1]


def test_details_missing_description_and_closed_are_never_complete():
    fake = FakeLinkedIn({'get_job_details': [
        result(DETAIL),
        result({**DETAIL, 'section_errors': {'job_posting': {'type': 'description_missing'}}}),
        result({**DETAIL, 'apply': {'type': 'closed'}})]})
    source = LinkedInMcpSource(fake.call_tool_for())
    complete, missing, closed = (source.details('4475055219') for _ in range(3))
    assert complete['status'] == 'complete_jd' and complete['description']
    assert missing['status'] == 'description_missing' and missing['description'] is None and missing['evidence_text']
    assert closed['status'] == 'closed' and closed['description'] is None


def test_apply_url_only_for_external_postings():
    fake = FakeLinkedIn({'get_job_apply_url': [
        result({'url': 'u', 'apply': {'type': 'external', 'url': 'https://lnkd.in/x'}}),
        result({'url': 'u', 'apply': {'type': 'easy_apply'}})]})
    source = LinkedInMcpSource(fake.call_tool_for())
    assert source.apply_url('1')['url'] == 'https://lnkd.in/x'
    assert source.apply_url('1') == {'type': 'easy_apply', 'url': None, 'source': 'linkedin_mcp'}


@pytest.mark.parametrize('message,reason', [('HTTP 429 Too Many Requests', 'rate_limited'),
                                            ('Please sign in to continue: security checkpoint', 'auth_required')])
def test_rate_limit_or_login_challenge_stops_the_source(message, reason):
    fake = FakeLinkedIn({'search_jobs': result(error=message), 'get_job_details': result(DETAIL)})
    source = LinkedInMcpSource(fake.call_tool_for())
    with pytest.raises(LinkedInSourceStopped):
        source.search('x')
    with pytest.raises(LinkedInSourceStopped, match=reason):
        source.details('4475055219')           # no further call, no channel switch
    assert [c[0] for c in fake.calls] == ['search_jobs']


def test_timeout_blocks_the_next_call_until_cancellation_is_confirmed():
    fake = FakeLinkedIn({'get_job_details': [McpCallTimeoutError('slow'), result(DETAIL)]})
    source = LinkedInMcpSource(fake.call_tool_for())
    with pytest.raises(McpCallTimeoutError):
        source.details('1')
    with pytest.raises(LinkedInSourceStopped, match='timeout_cancel_unconfirmed'):
        source.details('1')
    source.confirm_cancelled()
    assert source.details('1')['status'] == 'complete_jd'
    assert len(fake.calls) == 2


def test_budget_counts_failures_and_survives_restart():
    store = {}
    fake = FakeLinkedIn({'get_job_details': [RuntimeError('transport')] + [result(DETAIL)] * 5})
    first = LinkedInMcpSource(fake.call_tool_for(), store=store, call_budget=3)
    with pytest.raises(RuntimeError):
        first.details('1')
    first.details('1')
    restarted = LinkedInMcpSource(fake.call_tool_for(), store=store, call_budget=3)   # same persisted store
    restarted.details('1')
    with pytest.raises(LinkedInSourceStopped, match='call_budget_exhausted'):
        restarted.details('1')
    assert store['calls_used'] == 3 and len(fake.calls) == 3


def test_oversized_response_is_not_parsed():
    fake = FakeLinkedIn({'get_job_details': result(text='x' * 3_000_000)})
    source = LinkedInMcpSource(fake.call_tool_for(), max_response_bytes=2_000_000)
    with pytest.raises(ValueError, match='size limit'):
        source.details('1')
    assert source.store['log'][-1]['outcome'] == 'oversized'


def test_out_of_scope_tools_are_refused_before_any_call():
    fake = FakeLinkedIn({})
    source = LinkedInMcpSource(fake.call_tool_for())
    with pytest.raises(ValueError):
        source._invoke('send_message', {'text': 'hi'})
    assert fake.calls == [] and source.store['calls_used'] == 0


def _call_tool_for(self):
    """Bind the fake as McpToolManager.call_tool would be: (server_id, tool, args, timeout_seconds=)."""
    return lambda server_id, tool, arguments, timeout_seconds=None: self.call_tool(
        tool, arguments, timeout_seconds=timeout_seconds)


FakeLinkedIn.call_tool_for = _call_tool_for
