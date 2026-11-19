"""A NOBAD process talking to the running engine over its pipe: the single-instance hand-off (a second launch asks the
running copy to show its window) and the Start-menu "Restore internet" / "Repair network" forwarding.

Same checks as the Flutter window's client: identification-level impersonation only, and the pipe's owner must be
Administrators or SYSTEM (made by an elevated engine), so a program running as the user can't take the name and
answer in the engine's place. One request, one answer, then the pipe is closed.
"""
import ctypes
import json
import os
import threading
from ctypes import wintypes

from . import security

ADMINS_OR_SYSTEM = (security.ADMINS, security.SYSTEM)


class PipeError(Exception):
    pass


def _k():
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateFileW.restype = wintypes.HANDLE
    k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                              wintypes.DWORD, wintypes.HANDLE]
    k.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    return k


def pipe_owner(handle):
    """The string SID that owns the pipe, or None."""
    a = ctypes.WinDLL("advapi32", use_last_error=True)
    k = ctypes.WinDLL("kernel32")
    owner, sd = ctypes.c_void_p(), ctypes.c_void_p()
    a.GetSecurityInfo.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p),
                                  ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    if a.GetSecurityInfo(handle, 6, 1, ctypes.byref(owner), None, None, None, ctypes.byref(sd)) != 0:
        return None
    try:
        s = wintypes.LPWSTR()
        a.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
        if not a.ConvertSidToStringSidW(owner, ctypes.byref(s)):
            return None
        out = s.value
        k.LocalFree(s)
        return out
    finally:
        k.LocalFree(sd)


def call(method, params=None, timeout=3.0, name=None, owners=ADMINS_OR_SYSTEM):
    """Send one request to the engine and return its `result`. PipeError when there's no engine, the pipe isn't
    an elevated engine's, the engine refused, or it didn't answer within `timeout` seconds."""
    if os.name != "nt":
        raise PipeError("Windows only")
    name = name or security.pipe_name(security.session_user_sid())
    k = _k()
    h = k.CreateFileW(name, 0xC0000000, 0, None, 3, 0x00100000 | 0x00010000, None)   # SQOS: identification
    if not h or h == ctypes.c_void_p(-1).value:
        if not k.WaitNamedPipeW(name, int(timeout * 1000)):
            raise PipeError("no engine")
        h = k.CreateFileW(name, 0xC0000000, 0, None, 3, 0x00100000 | 0x00010000, None)
        if not h or h == ctypes.c_void_p(-1).value:
            raise PipeError("no engine")
    try:
        if owners is not None and pipe_owner(h) not in owners:
            raise PipeError("the pipe isn't the engine's")
        import msvcrt
        fd = msvcrt.open_osfhandle(h, 0)
        h = None                                    # owned by the file object now
        with os.fdopen(fd, "r+b", buffering=0) as f:
            req = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
            f.write((json.dumps(req) + "\n").encode("ascii"))
            got, done = bytearray(), threading.Event()

            def read():
                try:
                    while not got.endswith(b"\n"):
                        c = f.read(4096)
                        if not c:
                            break
                        got.extend(c)
                finally:
                    done.set()
            t = threading.Thread(target=read, daemon=True)
            t.start()
            if not done.wait(timeout):
                raise PipeError("the engine didn't answer")
        try:
            msg = json.loads(bytes(got).decode("utf-8"))
        except ValueError:
            raise PipeError("no answer") from None
        if "error" in msg:
            raise PipeError(str((msg.get("error") or {}).get("message", "refused")))
        return msg.get("result")
    finally:
        if h:
            k.CloseHandle(h)
