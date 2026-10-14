"""One-time interactive sign-in for a remote MCP server that uses OAuth (e.g. Indeed).

Registers this local client with the server's authorization server (dynamic client
registration, PKCE), opens the provider's sign-in page in the user's browser, receives the
authorization code on http://127.0.0.1:<port>/callback and stores the tokens encrypted for
this user (eregion.runtime.mcp.oauth_store). The user signs in themselves; this script never
sees a password. Afterwards it lists the server's tools and writes their schemas.

    python tools/scripts/mcp_oauth_login.py --config <mcp-config.json> --server indeed --tools-out <file>
"""
import argparse
import asyncio
import json
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from eregion.runtime.mcp.config import load_mcp_runtime_config
from eregion.runtime.mcp.client import oauth_provider


async def register_without_scopes(config):
    """Indeed refuses scopes in dynamic client registration ('Requested scopes are invalid or
    not supported') but the scopes can be requested at sign-in. Register once without scopes
    and store the client record, so the SDK reuses it and asks for the scopes in the
    authorization request, where the user approves them."""
    import httpx
    from mcp.shared.auth import OAuthClientInformationFull
    from eregion.runtime.mcp.oauth_store import FileTokenStorage
    storage = FileTokenStorage(config.server_id)
    if await storage.get_client_info():
        return
    parts = urlsplit(config.url)
    async with httpx.AsyncClient(timeout=30) as http:
        resource = (await http.get(f'{parts.scheme}://{parts.netloc}/.well-known/oauth-protected-resource{parts.path}')).json()
        issuer = resource['authorization_servers'][0].rstrip('/')
        server = (await http.get(issuer + '/.well-known/oauth-authorization-server')).json()
        response = await http.post(server['registration_endpoint'], json={
            'client_name': 'Eregion job search (local)',
            'redirect_uris': [f'http://127.0.0.1:{config.oauth_redirect_port}/callback'],
            'grant_types': ['authorization_code', 'refresh_token'], 'response_types': ['code'],
            'token_endpoint_auth_method': 'none'})
        response.raise_for_status()
    await storage.set_client_info(OAuthClientInformationFull.model_validate(response.json()))


def wait_for_code(port, timeout=600):
    received = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            query = parse_qs(urlsplit(self.path).query)
            if urlsplit(self.path).path != '/callback':
                self.send_response(404); self.end_headers(); return
            received.update({k: v[0] for k, v in query.items()})
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write('Sign-in received. You can close this tab and return to Eregion.'.encode())

        def log_message(self, *args):
            pass   # never log the authorization code

    server = HTTPServer(('127.0.0.1', port), Handler)
    server.timeout = 1
    stop = threading.Event()

    def serve():
        for _ in range(timeout):
            if received or stop.is_set():
                return
            try:
                server.handle_request()
            except (OSError, ValueError):
                return   # the socket was closed after a failed flow
    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    server.stop = stop
    return server, thread, received


async def main_async(config, tools_out):
    from mcp import Client
    from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client
    from mcp.shared.auth import AuthorizationCodeResult
    server, thread, received = wait_for_code(config.oauth_redirect_port)

    async def redirect(url):
        print('Opening the sign-in page in your browser. If it does not open, visit:\n' + url, flush=True)
        webbrowser.open(url)

    async def callback():
        await asyncio.to_thread(thread.join)
        if received.get('error'):
            raise RuntimeError('Sign-in was not completed: ' + received.get('error_description', received['error']))
        if not received.get('code'):
            raise RuntimeError('No authorization code was received before the timeout.')
        return AuthorizationCodeResult(code=received['code'], state=received.get('state'), iss=received.get('iss'))

    await register_without_scopes(config)
    provider = oauth_provider(config, interactive=True, redirect_handler=redirect, callback_handler=callback)
    try:
        async with create_mcp_http_client(auth=provider) as http:
            async with Client(streamable_http_client(config.url, http_client=http), read_timeout_seconds=60) as client:
                tools = (await client.list_tools()).tools
    finally:
        server.stop.set()
        thread.join(timeout=3)
        server.server_close()
    rows = [{'name': t.name, 'description': t.description, 'input_schema': t.inputSchema} for t in tools]
    if tools_out:
        Path(tools_out).write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding='utf-8')
    print('Signed in. Tools:', ', '.join(r['name'] for r in rows))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--server', required=True)
    parser.add_argument('--tools-out')
    args = parser.parse_args()
    config = next(s for s in load_mcp_runtime_config(args.config.resolve()).servers if s.server_id == args.server)
    if config.transport != 'streamable_http' or not config.oauth:
        raise SystemExit('This server does not use OAuth over streamable HTTP.')
    asyncio.run(main_async(config, args.tools_out))


if __name__ == '__main__':
    main()
