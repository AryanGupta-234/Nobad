"""Where the Flutter UI lives, which UI a launch uses, and starting the UI as the signed-in user (never elevated).

The engine never starts the UI with its own (administrator) token. It starts it with a copy of the desktop shell's
token (explorer.exe of the signed-in user, normal rights) through CreateProcessWithTokenW; if that fails, a one-shot
scheduled task with an interactive, limited principal starts it, the route syscmd.open_url_as_user takes for links.
The program is a fixed file (the install folder's ui\\nobad_vpn_ui.exe, or the developer's build) and the only argument is
`--mini` or nothing; nothing from the UI or the network ever reaches this command line.
"""
import ctypes
import os
import re
import subprocess
import sys

from ..logbus import log

UI_EXE = "nobad_vpn_ui.exe"
ARGS = {"main": "", "mini": "--mini"}
MODES = ("webview", "flutter", "both")


def ui_exe():
    """The Flutter UI program, or None. Installed: {app}\\ui\\nobad_vpn_ui.exe. Source run: the release (else
    debug) build in apps/vpn/ui_flutter."""
    if getattr(sys, "frozen", False):
        p = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "ui", UI_EXE)
        return p if os.path.isfile(p) else None
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        "ui_flutter", "build", "windows", "x64", "runner")
    for kind in ("Release", "Debug"):
        p = os.path.join(root, kind, UI_EXE)
        if os.path.isfile(p):
            return p
    return None


def ui_mode(env=None, exe=None, frozen=None, setting=None):
    """Which UI this launch uses: "webview" (today's default), "flutter" (the engine owns no window; the Flutter UI
    connects over the pipe), or "both" (WebView windows plus the pipe, for checking parity side by side).

    Installed builds read only the `ui_flutter` setting (settings.json in ProgramData, which only administrators can
    change): the environment is the user's to set (HKCU\\Environment) and must not decide what the elevated app does.
    Source runs also take NOBAD_VPN_UI. "flutter"/"both" need the Flutter UI to be there, else it stays "webview"."""
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    if setting is None:
        try:
            from ..ctx import ctx
            setting = bool(ctx.settings and ctx.settings.get("ui_flutter"))
        except Exception:
            setting = False
    env = os.environ if env is None else env
    want = "flutter" if setting else ""
    if not frozen:
        want = str(env.get("NOBAD_VPN_UI", "")).strip().lower() or want
    if want not in MODES or want == "webview":
        return "webview"
    exe = ui_exe() if exe is None else exe
    return want if exe else "webview"


_SAFE_PATH = re.compile(r"[A-Za-z]:\\[^'\"\x00-\x1f%`$]{1,400}")


def task_ps(exe, arg):
    """PowerShell that runs `exe` (+ `arg`) as the desktop's user at limited rights through a one-shot task.
    `exe` must be a plain absolute path without quotes or PowerShell specials; `arg` must be one of ARGS."""
    if not _SAFE_PATH.fullmatch(exe or "") or arg not in ARGS.values():
        raise ValueError("refusing to start that program")
    e = exe.replace("'", "''")
    act = f"New-ScheduledTaskAction -Execute '{e}'" + (f" -Argument '{arg}'" if arg else "")
    return ("$ErrorActionPreference='Stop';"
            "$sid=(Get-Process -Id $PID).SessionId;$exp=Join-Path $env:windir 'explorer.exe';"
            "$o=Get-CimInstance Win32_Process -Filter \"Name='explorer.exe' AND SessionId=$sid\" | "
            "Where-Object { $_.ExecutablePath -ieq $exp } | Select-Object -First 1 | Invoke-CimMethod -MethodName GetOwner;"
            "$who=if($o -and $o.User){$o.Domain+'\\'+$o.User}else{[Security.Principal.WindowsIdentity]::GetCurrent().Name};"
            "$n='NobadVPN window '+[guid]::NewGuid().ToString('N');"
            f"$a={act};"
            "$p=New-ScheduledTaskPrincipal -UserId $who -LogonType Interactive -RunLevel Limited;"
            "$s=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Days 0);"
            "Register-ScheduledTask -TaskName $n -Action $a -Principal $p -Settings $s -Force | Out-Null;"
            "try{Start-ScheduledTask -TaskName $n;Start-Sleep -Seconds 2}finally{Unregister-ScheduledTask -TaskName $n -Confirm:$false}")


def launch(window, exe=None, admin=None, runner=None, popen=None, shell_start=None):
    """Start the UI for `window` ("main" or "mini") as the signed-in user. True when the start was handed over."""
    from ..syscmd import is_admin, run
    if window not in ARGS:
        return False
    exe = exe or ui_exe()
    if not exe:
        log("NOBAD's window program (ui\\nobad_vpn_ui.exe) is missing; reinstall NOBAD VPN", "warn")
        return False
    admin = is_admin() if admin is None else admin
    if not admin:                                  # a source run at normal rights: start it directly
        try:
            (popen or subprocess.Popen)([exe] + ([ARGS[window]] if ARGS[window] else []), close_fds=True)
            return True
        except OSError as e:
            log(f"couldn't start NOBAD's window ({e.strerror or e})", "warn")
            return False
    if not _SAFE_PATH.fullmatch(exe):
        log("couldn't start NOBAD's window: its path has unexpected characters", "warn")
        return False
    if (shell_start or start_as_shell_user)(exe, ARGS[window]):
        return True
    try:
        ps = task_ps(exe, ARGS[window])
    except ValueError as e:
        log(f"couldn't start NOBAD's window: {e}", "warn")
        return False
    r = (runner or run)(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], timeout=30)
    if r.returncode != 0:
        log(f"couldn't start NOBAD's window as the signed-in user ({(r.stderr or '').strip()[:120]})", "warn")
        return False
    return True


def token_is_plain_user(tok):
    """True only for a token that is not elevated and at most Medium integrity: the window must never get more."""
    from . import security
    elev = security._token_info(tok, 20)                                  # TokenElevation
    if elev is None or ctypes.c_uint32.from_buffer(elev).value != 0:
        return False
    il = security.token_facts(tok).get("integrity")
    return isinstance(il, int) and il <= security.MEDIUM_RID


def start_as_shell_user(exe, arg):
    """CreateProcessWithTokenW with a primary copy of the desktop shell's token (the user, Medium integrity).
    True when the program started. Needs the engine's SeImpersonatePrivilege (elevated administrators have it)."""
    if os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes
    try:
        u, k, a = ctypes.WinDLL("user32"), ctypes.WinDLL("kernel32", use_last_error=True),             ctypes.WinDLL("advapi32", use_last_error=True)
        u.GetShellWindow.restype = wintypes.HWND
        k.OpenProcess.restype = wintypes.HANDLE
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        a.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
        a.DuplicateTokenEx.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                                       ctypes.POINTER(wintypes.HANDLE)]
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        shell = u.GetShellWindow()
        if not shell:
            return False
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(shell, ctypes.byref(pid))
        proc = k.OpenProcess(0x1000, False, pid.value)                     # PROCESS_QUERY_LIMITED_INFORMATION
        if not proc:
            return False
        tok, dup = wintypes.HANDLE(), wintypes.HANDLE()
        try:
            if not a.OpenProcessToken(proc, 0x2 | 0x8, ctypes.byref(tok)):  # TOKEN_DUPLICATE | TOKEN_QUERY
                return False
            # TOKEN_QUERY | DUPLICATE | ASSIGN_PRIMARY | ADJUST_DEFAULT | ADJUST_SESSIONID; SecurityImpersonation; Primary
            if not a.DuplicateTokenEx(tok, 0x8 | 0x2 | 0x1 | 0x80 | 0x100, None, 2, 1, ctypes.byref(dup)):
                return False
            if not token_is_plain_user(dup):            # the shell itself elevated (UAC off): use the limited task
                return False

            class SI(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR), ("lpDesktop", wintypes.LPWSTR),
                            ("lpTitle", wintypes.LPWSTR), ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
                            ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
                            ("dwXCountChars", wintypes.DWORD), ("dwYCountChars", wintypes.DWORD),
                            ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                            ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
                            ("lpReserved2", ctypes.c_void_p), ("hStdInput", wintypes.HANDLE),
                            ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE)]

            class PI(ctypes.Structure):
                _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                            ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]
            si, pi = SI(), PI()
            si.cb = ctypes.sizeof(SI)
            cmd = ctypes.create_unicode_buffer(f'"{exe}"' + (f" {arg}" if arg else ""))
            a.CreateProcessWithTokenW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPWSTR,
                                                  wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
                                                  ctypes.POINTER(SI), ctypes.POINTER(PI)]
            ok = a.CreateProcessWithTokenW(dup, 0, exe, cmd, 0x00000400, None, os.path.dirname(exe),
                                           ctypes.byref(si), ctypes.byref(pi))  # CREATE_UNICODE_ENVIRONMENT
            if not ok:
                return False
            k.CloseHandle(pi.hThread)
            k.CloseHandle(pi.hProcess)
            return True
        finally:
            for h in (dup, tok):
                if h:
                    k.CloseHandle(h)
            k.CloseHandle(proc)
    except (OSError, AttributeError):
        return False
