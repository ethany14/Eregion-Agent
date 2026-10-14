"""Remote (streamable HTTP) MCP servers: configuration, client selection and token storage."""
import asyncio
import pytest
from eregion.runtime.mcp.config import McpStdioServerConfig
from eregion.runtime.mcp.client import HttpMcpClient, StdioMcpClient, create_client


def remote(**changes):
    return McpStdioServerConfig(**{'server_id': 'indeed', 'transport': 'streamable_http',
                                   'url': 'https://mcp.example.com/mcp', 'oauth': True, **changes})


def test_remote_server_needs_https_and_stdio_still_needs_a_command():
    assert remote().url == 'https://mcp.example.com/mcp'
    for bad in ('http://mcp.example.com/mcp', 'https://user:pw@mcp.example.com/mcp', ''):
        with pytest.raises(ValueError):
            remote(url=bad)
    with pytest.raises(ValueError):
        McpStdioServerConfig(server_id='local')                      # stdio without command
    with pytest.raises(ValueError):
        McpStdioServerConfig(server_id='local', command='x', url='https://a.example/mcp')
    assert McpStdioServerConfig(server_id='local', command='x').transport == 'stdio'


def test_client_factory_picks_the_transport():
    assert isinstance(create_client(remote()), HttpMcpClient)
    assert type(create_client(McpStdioServerConfig(server_id='local', command='x'))) is StdioMcpClient


def test_tokens_round_trip_encrypted_outside_the_repository(tmp_path):
    from mcp.shared.auth import OAuthToken
    from eregion.runtime.mcp.oauth_store import FileTokenStorage
    storage = FileTokenStorage('indeed', tmp_path)
    assert not storage.signed_in
    asyncio.run(storage.set_tokens(OAuthToken(access_token='secret-access-value', token_type='Bearer')))
    assert storage.signed_in and asyncio.run(storage.get_tokens()).access_token == 'secret-access-value'
    assert b'secret-access-value' not in (tmp_path / 'indeed.bin').read_bytes()   # protected at rest (DPAPI)


def test_a_task_never_starts_an_interactive_sign_in():
    from eregion.runtime.mcp.client import oauth_provider
    from eregion.runtime.mcp.errors import McpAuthorizationRequired
    provider = oauth_provider(remote(), interactive=False)
    with pytest.raises(McpAuthorizationRequired):
        asyncio.run(provider.context.redirect_handler('https://secure.example/authorize'))
