"""R8: initialization and routing for each credential combination, offline (no paid call).

LinkedIn MCP is not wired into career source selection (R7 T1/T2 deferred), so a
configured MCP server changes nothing in career routing; its optional-server
startup and degraded health are covered by tests/test_mcp_app.py
(test_optional_failure_produces_sanitized_degraded_health).
"""
import pytest

from test_career_flow import career, execute  # noqa: F401
from test_integrated_p3 import CRAWL_ROWS, Discovery, install_treg, ok
from test_remaining_search_completion import prepare

GH = {'url': 'https://job-boards.greenhouse.io/acme/jobs/1', 'title': 'Junior Data Analyst', 'company': 'Acme',
      'location': 'New York, NY'}
NONE = {'TREG_TOKEN': '', 'JOB_AGENT_TREG_ENABLED': '0', 'JOB_AGENT_JOB_API_FIRST': '0'}
TREG = {'TREG_TOKEN': 'fake-test-token', 'JOB_AGENT_TREG_ENABLED': '1', 'JOB_AGENT_JOB_API_FIRST': '1',
        'JOB_AGENT_TREG_SEARCH_PROVIDER': 'crawl4ai'}
# A LinkedIn MCP server lives in the MCP config file, not in these variables, and has
# no effect on career routing until adopted: MCP-only routes like NONE, both like TREG.
MCP_ONLY, BOTH = NONE, TREG


@pytest.mark.parametrize('name,env,treg_calls', [('none', NONE, 0), ('linkedin_mcp_only', MCP_ONLY, 0),
                                                 ('treg_only', TREG, 1), ('both', BOTH, 1)])
def test_each_credential_combination_starts_and_routes(career, monkeypatch, name, env, treg_calls):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    c = career; prepare(c)
    seen = install_treg(c, lambda r: ok(CRAWL_ROWS)) if env['TREG_TOKEN'] else []
    c.harness.discovery = Discovery(directory=[GH])
    result = execute(c, 'search_jobs', query='junior data analyst', location='New York, NY', use_directory=True)
    assert 'error' not in result                      # no crash without credentials
    assert len(seen) == treg_calls                    # Treg only when configured and enabled
    assert (c.harness._treg() is None) == (treg_calls == 0)
    assert any(j['url'] == GH['url'] for j in result['jobs'])   # free boards always used
