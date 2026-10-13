"""Owner/site-isolated browser login state, encrypted with the Windows user key."""
from __future__ import annotations
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4


def protect(data: bytes, *, decrypt=False) -> bytes:
    if os.name != "nt":
        raise OSError("Persistent login requires an OS-backed credential protector.")
    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    crypt = ctypes.windll.crypt32
    if decrypt:
        ok = crypt.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output))
    else:
        ok = crypt.CryptProtectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output))
    if not ok: raise OSError("Browser login state could not be protected.")
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        ctypes.windll.kernel32.LocalFree(output.data)


class BrowserSessionStore:
    def __init__(self, directory, *, codec=protect):
        self.directory = Path(directory)
        self.codec = codec

    def _path(self, owner, site):
        key = hashlib.sha256(f"{owner}\n{site}".encode()).hexdigest()
        return self.directory / f"{key}.session"

    def load(self, owner, site):
        try:
            data = json.loads(self.codec(self._path(owner, site).read_bytes(), decrypt=True))
            if data["owner"] != owner or data["site"] != site:
                return None
            return data["state"]
        except (OSError, ValueError, KeyError):
            return None

    def save(self, owner, site, state):
        if self.load(owner,site)==state:return
        # Encrypt before creating files: unsupported OSes never write plaintext.
        content = self.codec(json.dumps({"owner":owner, "site":site, "state":state}).encode())
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path(owner, site)
        temporary = path.with_suffix(f".{uuid4().hex}.tmp")
        try:
            temporary.write_bytes(content)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def revision(self,owner,site):
        try:return hashlib.sha256(self._path(owner,site).read_bytes()).hexdigest()
        except OSError:return None
