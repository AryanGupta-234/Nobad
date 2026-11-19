"""Who may talk to the elevated engine over its pipe, and how that is checked.

The engine runs elevated; its UI runs as the signed-in user (never elevated). Four layers, each enough to stop a
class of caller on its own:

1. The pipe's security descriptor (sddl_for): a protected DACL that allows only the interactive user of the
   engine's session, SYSTEM and Administrators, denies network logons, and carries an explicit Medium mandatory
   label (no-write-up), so Low-integrity and AppContainer processes (sandboxed browser tabs, store apps) can't
   even open it, and the UI at Medium can.
2. PIPE_REJECT_REMOTE_CLIENTS and FILE_FLAG_FIRST_PIPE_INSTANCE (server.py): nothing from another machine, and
   the engine refuses to serve a name someone else created first.
3. The caller check (check_client), on the connection's first bytes and before any request is read: the client's
   token (through identification-level impersonation) must belong to that same user, or SYSTEM; it must be in
   the engine's own Windows session; its integrity must be at least Medium. In an installed build its program
   must be NOBAD's own UI (or NobadVPN.exe itself), from the install folder, which only administrators can change.
4. Every request is checked against params.SPEC (an allowlist of methods and parameter shapes), then the
   existing handler checks run as they do for the WebView UI. No parameter is ever a path or a command line.

The client checks the other way round too (ui_flutter pipe_client.dart): the pipe's owner must be Administrators
or SYSTEM, i.e. created by an elevated process, so a program running as the user can't pose as the engine.

What this does NOT stop (docs/UI-PIPE.md, "Residual risk"): a program already running as the signed-in user can
drive the UI window itself (send it input, inject code into it, start it with a debugger). The WebView UI ran
elevated and was out of reach of such programs; a UI that runs as the user, as required, can't be. Calls that
lower protection are written to the log with the calling program, so they're visible afterwards.
"""
import ctypes
import os
import re
import sys
from ctypes import wintypes

SYSTEM, ADMINS = "S-1-5-18", "S-1-5-32-544"
MEDIUM_RID = 0x2000
_SID = re.compile(r"S-1-[0-9]+(-[0-9]+){1,14}")


def sddl_for(user_sid):
    """Protected DACL (no inheritance): network logons denied; full access for the session's user, SYSTEM and
    Administrators. SACL: Medium mandatory label, no-write-up."""
    if not isinstance(user_sid, str) or not _SID.fullmatch(user_sid):
        raise ValueError("not a SID")
    return f"D:P(D;;GA;;;NU)(A;;GA;;;{user_sid})(A;;GA;;;SY)(A;;GA;;;BA)S:(ML;;NW;;;ME)"


def pipe_name(user_sid, dev=False):
    """\\\\.\\pipe\\NOBADVPN-<user SID>. The development name (an unelevated demo engine) is a different name, so a
    UI built for real use never connects to a non-elevated engine by accident."""
    if not isinstance(user_sid, str) or not _SID.fullmatch(user_sid):
        raise ValueError("not a SID")
    return "\\\\.\\pipe\\NOBADVPN-" + ("dev-" if dev else "") + user_sid


def decide(client, engine, allowed_images=None):
    """The caller check as a pure function. `client`: {sid, session, integrity, image, appcontainer}; `engine`:
    {user_sid, session}. `allowed_images`: lower-case full paths the client's program must be one of (None: not
    checked, a source run). Returns None (allowed) or the reason it isn't."""
    sid = client.get("sid")
    if sid not in (engine.get("user_sid"), SYSTEM):
        return "another account"
    if client.get("session") != engine.get("session") and sid != SYSTEM:
        return "another Windows session"
    if client.get("appcontainer"):
        return "an app container"
    if not isinstance(client.get("integrity"), int) or client["integrity"] < MEDIUM_RID:
        return "low integrity"
    if allowed_images is not None:
        img = os.path.normcase(os.path.normpath(client.get("image") or ""))
        if img not in {os.path.normcase(os.path.normpath(p)) for p in allowed_images}:
            return "not NOBAD's own program"
    return None


def allowed_images():
    """Programs that may use the pipe in an installed build: NOBAD's Flutter UI and NobadVPN.exe itself, both in
    the install folder (Program Files: only administrators can change it). None for a source run (the build folder
    there is the developer's own, so pinning it would prove nothing)."""
    if not getattr(sys, "frozen", False):
        return None
    app = os.path.dirname(os.path.abspath(sys.executable))
    return [os.path.join(app, "ui", "nobad_vpn_ui.exe"), os.path.abspath(sys.executable)]


# ---------------------------------------------------------------- Win32 (ctypes)
class _SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]


_dll = {}


def _dlls():
    if not _dll:
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        a = ctypes.WinDLL("advapi32", use_last_error=True)
        w = ctypes.WinDLL("wtsapi32", use_last_error=True)
        H, D, B, P = wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, ctypes.c_void_p
        for dll, specs in ((k, (("GetCurrentProcess", H, []), ("GetCurrentProcessId", D, []),
                                ("ProcessIdToSessionId", B, [D, ctypes.POINTER(D)]),
                                ("OpenProcess", H, [D, B, D]), ("CloseHandle", B, [H]), ("LocalFree", P, [P]),
                                ("GetCurrentThread", H, []),
                                ("QueryFullProcessImageNameW", B, [H, D, wintypes.LPWSTR, ctypes.POINTER(D)]))),
                           (a, (("OpenProcessToken", B, [H, D, ctypes.POINTER(H)]),
                                ("OpenThreadToken", B, [H, D, B, ctypes.POINTER(H)]),
                                ("ImpersonateNamedPipeClient", B, [H]), ("RevertToSelf", B, []),
                                ("GetTokenInformation", B, [H, ctypes.c_int, P, D, ctypes.POINTER(D)]),
                                ("GetSidSubAuthorityCount", ctypes.POINTER(ctypes.c_ubyte), [P]),
                                ("GetSidSubAuthority", ctypes.POINTER(D), [P, D]),
                                ("ConvertSidToStringSidW", B, [P, ctypes.POINTER(wintypes.LPWSTR)]),
                                ("LookupAccountNameW", B, [wintypes.LPCWSTR, wintypes.LPCWSTR, P, ctypes.POINTER(D),
                                                           wintypes.LPWSTR, ctypes.POINTER(D), ctypes.POINTER(D)]))),
                           (w, (("WTSQuerySessionInformationW", B, [H, D, ctypes.c_int,
                                                                    ctypes.POINTER(wintypes.LPWSTR),
                                                                    ctypes.POINTER(D)]),
                                ("WTSFreeMemory", None, [P])))):
            for name, res, args in specs:
                f = getattr(dll, name)
                f.restype, f.argtypes = res, args
        _dll.update(k=k, a=a, w=w)
    return _dll["k"], _dll["a"], _dll["w"]


def _sid_str(psid):
    k, a, _w = _dlls()
    s = wintypes.LPWSTR()
    if not a.ConvertSidToStringSidW(psid, ctypes.byref(s)):
        return None
    try:
        return s.value
    finally:
        k.LocalFree(s)


def _token_info(tok, cls):
    _k, a, _w = _dlls()
    need = wintypes.DWORD()
    a.GetTokenInformation(tok, cls, None, 0, ctypes.byref(need))
    if not need.value:
        return None
    buf = ctypes.create_string_buffer(need.value)
    if not a.GetTokenInformation(tok, cls, buf, need, ctypes.byref(need)):
        return None
    return buf


def token_facts(tok):
    """{sid, session, integrity, appcontainer} of an open token."""
    out = {"sid": None, "session": None, "integrity": None, "appcontainer": None}
    b = _token_info(tok, 1)                                             # TokenUser
    if b is not None:
        out["sid"] = _sid_str(_SID_AND_ATTRIBUTES.from_buffer(b).Sid)
    b = _token_info(tok, 12)                                            # TokenSessionId
    if b is not None:
        out["session"] = wintypes.DWORD.from_buffer(b).value
    b = _token_info(tok, 25)                                            # TokenIntegrityLevel
    if b is not None:
        _k, a, _w = _dlls()
        psid = _SID_AND_ATTRIBUTES.from_buffer(b).Sid
        n = a.GetSidSubAuthorityCount(psid)[0]
        out["integrity"] = a.GetSidSubAuthority(psid, n - 1)[0] if n else None
    b = _token_info(tok, 29)                                            # TokenIsAppContainer
    if b is not None:
        out["appcontainer"] = bool(wintypes.DWORD.from_buffer(b).value)
    return out


def own_session():
    k, _a, _w = _dlls()
    s = wintypes.DWORD()
    return s.value if k.ProcessIdToSessionId(k.GetCurrentProcessId(), ctypes.byref(s)) else None


def own_user_sid():
    k, a, _w = _dlls()
    tok = wintypes.HANDLE()
    if not a.OpenProcessToken(k.GetCurrentProcess(), 0x8, ctypes.byref(tok)):          # TOKEN_QUERY
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return token_facts(tok)["sid"]
    finally:
        k.CloseHandle(tok)


def session_user_sid(session=None):
    """The SID of the user signed in to `session` (the engine's own by default). An elevated engine usually runs as
    that same user, but not always: a standard user who typed an administrator's password at the UAC prompt runs
    the engine as the administrator, while the UI runs as the standard user. Falls back to the engine's own SID."""
    k, a, w = _dlls()
    session = own_session() if session is None else session
    try:
        def q(cls):
            p, n = wintypes.LPWSTR(), wintypes.DWORD()
            if not w.WTSQuerySessionInformationW(None, session, cls, ctypes.byref(p), ctypes.byref(n)):
                return ""
            try:
                return p.value or ""
            finally:
                w.WTSFreeMemory(p)
        user, domain = q(5), q(7)                                       # WTSUserName, WTSDomainName
        if user:
            sid = ctypes.create_string_buffer(68)
            cb, cch, use = wintypes.DWORD(68), wintypes.DWORD(256), wintypes.DWORD()
            dom = ctypes.create_unicode_buffer(256)
            acct = f"{domain}\\{user}" if domain else user
            if a.LookupAccountNameW(None, acct, sid, ctypes.byref(cb), dom, ctypes.byref(cch), ctypes.byref(use)):
                s = _sid_str(sid)
                if s:
                    return s
    except OSError:
        pass
    return own_user_sid()


def client_facts(pipe_handle, pid):
    """What the engine knows about the program at the other end of `pipe_handle`: its token (by impersonating it
    at identification level, which the UI asks for) and its program file (by pid)."""
    k, a, _w = _dlls()
    out = {"sid": None, "session": None, "integrity": None, "appcontainer": None, "image": None}
    if a.ImpersonateNamedPipeClient(pipe_handle):
        try:
            tok = wintypes.HANDLE()
            if a.OpenThreadToken(k.GetCurrentThread(), 0x8, True, ctypes.byref(tok)):    # TOKEN_QUERY, as self
                try:
                    out.update(token_facts(tok))
                finally:
                    k.CloseHandle(tok)
        finally:
            if not a.RevertToSelf():                    # never keep running as the client
                raise SystemExit("RevertToSelf failed")
    if pid:
        h = k.OpenProcess(0x1000, False, pid)                                            # QUERY_LIMITED_INFORMATION
        if h:
            try:
                buf, n = ctypes.create_unicode_buffer(1024), wintypes.DWORD(1024)
                if k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                    out["image"] = buf.value
            finally:
                k.CloseHandle(h)
    return out
