"""OAuth token storage for remote MCP servers, outside the repository and encrypted at rest.

Tokens and the dynamically registered client record are kept per server in
%LOCALAPPDATA%/Eregion/mcp-oauth/<server_id>.bin (or EREGION_MCP_OAUTH_DIR). On Windows the
file is protected with DPAPI for the current user; elsewhere it is written with owner-only
permissions. Nothing here is logged, and values never enter task state or provider usage.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from mcp.shared.auth import OAuthClientInformationFull, OAuthToken


def oauth_directory() -> Path:
    configured = os.getenv("EREGION_MCP_OAUTH_DIR", "").strip()
    if configured:
        return Path(configured)
    base = os.getenv("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / "Eregion" / "mcp-oauth"


def _dpapi(data: bytes, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    source = Blob(len(data), ctypes.cast(ctypes.create_string_buffer(data, len(data)), ctypes.POINTER(ctypes.c_char)))
    target = Blob()
    crypt32 = ctypes.windll.crypt32
    call = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    if not call(ctypes.byref(source), None, None, None, None, 0x1, ctypes.byref(target)):  # UI_FORBIDDEN
        raise OSError("The OAuth token store could not be protected or opened for this user.")
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(target.pbData)


class FileTokenStorage:
    """mcp.client.auth.TokenStorage for one server."""

    def __init__(self, server_id: str, directory: Path | None = None) -> None:
        self._path = (directory or oauth_directory()) / f"{server_id}.bin"

    def _read(self) -> dict:
        if not self._path.is_file():
            return {}
        raw = self._path.read_bytes()
        if sys.platform == "win32":
            raw = _dpapi(raw, protect=False)
        return json.loads(raw.decode("utf-8"))

    def _write(self, value: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(value).encode("utf-8")
        if sys.platform == "win32":
            raw = _dpapi(raw, protect=True)
        temporary = self._path.with_suffix(".tmp")
        temporary.write_bytes(raw)
        if sys.platform != "win32":
            os.chmod(temporary, 0o600)
        os.replace(temporary, self._path)

    @property
    def signed_in(self) -> bool:
        try:
            return bool(self._read().get("tokens"))
        except (OSError, ValueError):
            return False

    async def get_tokens(self) -> OAuthToken | None:
        tokens = self._read().get("tokens")
        return OAuthToken.model_validate(tokens) if tokens else None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self._write({**self._read(), "tokens": tokens.model_dump(mode="json", exclude_none=True)})

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        info = self._read().get("client_info")
        return OAuthClientInformationFull.model_validate(info) if info else None

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self._write({**self._read(), "client_info": client_info.model_dump(mode="json", exclude_none=True)})

    def clear(self) -> None:
        if self._path.exists():
            self._path.unlink()
