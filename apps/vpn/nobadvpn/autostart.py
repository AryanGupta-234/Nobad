"""Elevated scheduled tasks, so NOBAD never needs a UAC prompt after it has been set up once:

* TASK_NAME ("NobadVPN")            - 'Start with Windows': runs at sign-in (user setting).
* LAUNCH_TASK ("NobadVPN Launcher") - no trigger; a normal (non-elevated) launch asks it to start the elevated app.
  Only registered for an INSTALLED build (exe under Program Files, which only administrators can change), so it
  can never be used to run user-writable code with admin rights.

Checks use `schtasks /Query /XML` (~0.1 s) rather than PowerShell's Get-ScheduledTask (~4 s), because they run
on the launch path."""
import base64
import html
import os
import re
import sys
import time

from .const import FROZEN, LEGACY_TASK_NAME, TASK_NAME, known_folder
from .syscmd import entry_command, run

LAUNCH_TASK = TASK_NAME + " Launcher"


def task_exists(name=TASK_NAME):
    if os.name != "nt":
        return False
    return run(["schtasks", "/Query", "/TN", name], timeout=15).returncode == 0


def _quote_ps(s):
    return "'" + str(s).replace("'", "''") + "'"


def _launch_parts():
    cmd = entry_command(["--background"])
    exe = cmd[0]
    if not FROZEN and exe.lower().endswith("python.exe"):
        w = exe[:-10] + "pythonw.exe"
        if os.path.exists(w):
            exe = w
    args = " ".join(f'"{a}"' for a in cmd[1:])
    return exe, args


def build_register_script(exe, args, workdir, name=TASK_NAME, at_logon=True):
    trig = ("$t=New-ScheduledTaskTrigger -AtLogOn -User $u;$t.Delay='PT15S';" if at_logon else "")
    return (
        "$ErrorActionPreference='Stop';"
        "$u=[System.Security.Principal.WindowsIdentity]::GetCurrent().Name;"
        f"$a=New-ScheduledTaskAction -Execute {_quote_ps(exe)} -Argument {_quote_ps(args)} -WorkingDirectory {_quote_ps(workdir)};"
        + trig +
        "$p=New-ScheduledTaskPrincipal -UserId $u -LogonType Interactive -RunLevel Highest;"
        "$s=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable "
        "-MultipleInstances Parallel -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -Priority 4;"
        f"Register-ScheduledTask -TaskName {_quote_ps(name)} -Action $a "
        + ("-Trigger $t " if at_logon else "") +
        "-Principal $p -Settings $s -Force | Out-Null")


def _workdir(exe):
    if FROZEN:
        return os.path.dirname(exe)
    script = os.path.abspath(sys.argv[0]) if sys.argv and sys.argv[0] else ""
    if not script or os.path.basename(script).lower() == "__main__.py":
        return os.path.dirname(os.path.dirname(script)) if script else os.getcwd()  # folder that holds the package
    return os.path.dirname(script)


def parse_task_xml(xml):
    """(Command, Arguments) of the first Exec action in `schtasks /Query /XML` output, or None."""
    m = re.search(r"<Exec>.*?<Command>(.*?)</Command>(?:.*?<Arguments>(.*?)</Arguments>)?", xml or "", re.S)
    if not m:
        return None
    return html.unescape(m.group(1)).strip(), html.unescape(m.group(2) or "").strip()


def task_action(name=TASK_NAME):
    """(Execute, Arguments) of the installed task, or None."""
    if os.name != "nt":
        return None
    r = run(["schtasks", "/Query", "/TN", name, "/XML"], timeout=15)
    return parse_task_xml(r.stdout) if r.returncode == 0 else None


def action_matches(act, exe, args):
    norm = lambda p: os.path.normcase(os.path.abspath(p.strip().strip('"'))) if p else ""  # noqa: E731
    return bool(act) and norm(act[0]) == norm(exe) and act[1].replace('"', "") == args.replace('"', "")


def task_matches(name=TASK_NAME):
    """True if the task still launches THIS install (a moved/uninstalled copy would start nothing)."""
    exe, args = _launch_parts()
    return action_matches(task_action(name), exe, args)


def remove_legacy_task():
    """NOMAD Tunnel's startup task would launch the old app (or nothing) — remove it once."""
    if os.name == "nt" and run(["schtasks", "/Query", "/TN", LEGACY_TASK_NAME], timeout=15).returncode == 0:
        run(["schtasks", "/Delete", "/TN", LEGACY_TASK_NAME, "/F"], timeout=20)
        return True
    return False


def _register(name, at_logon):
    exe, args = _launch_parts()
    ps = build_register_script(exe, args, _workdir(exe), name=name, at_logon=at_logon)
    enc = base64.b64encode(ps.encode("utf-16-le")).decode()
    r = run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc], timeout=40)
    if r.returncode != 0:
        return False, (r.stderr or r.stdout or "could not create the scheduled task").strip()[:300]
    return True, ""


def enable():
    if os.name != "nt":
        return False, "Scheduled tasks are only available on Windows."
    if not installed_location():
        # the task runs elevated with no UAC prompt: it may only point at an exe in an admin-only folder
        return False, ("Start with Windows needs NOBAD VPN installed in Program Files. Install it with the setup "
                       "program, then turn this on again.")
    ok, err = _register(TASK_NAME, True)
    return (True, "NOBAD will start at sign-in without a UAC prompt.") if ok else (False, err)


def disable():
    if os.name != "nt":
        return True, ""
    if not task_exists():
        return True, ""
    r = run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"], timeout=20)
    return r.returncode == 0, (r.stderr or "").strip()[:300]


def installed_location(exe=None):
    """True for a frozen build inside Program Files (admin-only folder) — the only case where an elevated
    no-UAC launcher task is safe to offer."""
    if not FROZEN or os.name != "nt":
        return False
    exe = os.path.normcase(os.path.realpath(os.path.abspath(exe or sys.executable)))
    # from the shell, not %ProgramFiles%: a user can redirect environment variables for the elevated app
    roots = {known_folder("ProgramFiles"), known_folder("ProgramFilesX86")} - {None}
    return any(exe.startswith(os.path.normcase(os.path.abspath(r)) + os.sep) for r in roots)


def ensure_launcher_task():
    """Register (or repair) the no-UAC launcher task for an installed build. Returns True if it is in place."""
    if not installed_location():
        return False
    if task_matches(LAUNCH_TASK):
        return True
    ok, _err = _register(LAUNCH_TASK, False)
    return ok


GUARD_TASK = TASK_NAME + " Guard"


def build_guard_script(exe, args, workdir, name=GUARD_TASK):
    """Boot guard: runs `--guard` as SYSTEM ~20 s after Windows starts (before anyone needs to sign in). It only
    restores internet when NOBAD died and left the kill switch on with nobody to remove it (recovery.guard_decide).
    Lowest task priority, 3-minute time limit: it costs nothing on a normal boot."""
    wd = f" -WorkingDirectory {_quote_ps(workdir)}" if workdir else ""
    return (
        "$ErrorActionPreference='Stop';"
        f"$a=New-ScheduledTaskAction -Execute {_quote_ps(exe)} -Argument {_quote_ps(args)}{wd};"
        "$t=New-ScheduledTaskTrigger -AtStartup;$t.Delay='PT20S';"
        "$p=New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest;"
        "$s=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable "
        "-ExecutionTimeLimit (New-TimeSpan -Minutes 3) -Priority 7;"
        f"Register-ScheduledTask -TaskName {_quote_ps(name)} -Action $a -Trigger $t -Principal $p -Settings $s "
        "-Force | Out-Null")


def _guard_parts():
    cmd = entry_command(["--guard"])
    return cmd[0], " ".join(f'"{a}"' for a in cmd[1:])


def ensure_guard_task():
    """Register (or repair) the boot guard. INSTALLED builds only: a SYSTEM task must never point at an exe
    that a normal user could replace. Returns True if it is in place."""
    if not installed_location():
        return False
    exe, args = _guard_parts()
    if action_matches(task_action(GUARD_TASK), exe, args):
        return True
    ps = build_guard_script(exe, args, _workdir(exe))
    enc = base64.b64encode(ps.encode("utf-16-le")).decode()
    return run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc], timeout=40).returncode == 0


def launch_via_task(show_window=True):
    """From a NON-elevated process: ask an elevated task to start the app (no UAC prompt).
    Prefers the launcher task, then the start-with-Windows task; skips any task that points elsewhere."""
    if os.name != "nt":
        return False
    exe, args = _launch_parts()
    for name in (LAUNCH_TASK, TASK_NAME):
        if not action_matches(task_action(name), exe, args):
            continue  # missing, or a stale task from another install location
        ev = request_show() if show_window else None
        try:
            if run(["schtasks", "/Run", "/TN", name], timeout=20).returncode == 0:
                if ev:
                    wait_show_taken(ev)
                return True
        finally:
            _close(ev)
    return False


# ---- "show the window" hand-off (#20)
# The non-elevated launcher asks the elevated app to show its window. This used to be a file in %LOCALAPPDATA%
# that the elevated app deleted, and a planted junction/link could turn that delete against any file. A named event
# in this sign-in session needs no file at all: the launcher creates it signalled and keeps it open until the app
# has reset it (or a timeout), and the app only opens it and resets it.
SHOW_EVENT = r"Local\NobadVPN.ShowWindow"
_EVENT_MODIFY_STATE, _SYNCHRONIZE = 0x0002, 0x00100000


def _kernel32():
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateEventW.restype = wintypes.HANDLE
    k.CreateEventW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR)
    k.OpenEventW.restype = wintypes.HANDLE
    k.OpenEventW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
    k.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    k.ResetEvent.argtypes = (wintypes.HANDLE,)
    k.CloseHandle.argtypes = (wintypes.HANDLE,)
    return k


def _close(h):
    if h:
        try:
            _kernel32().CloseHandle(h)
        except Exception:
            pass


def request_show():
    """Launcher side: a manual-reset event, signalled. Returns the handle (keep it open) or None."""
    if os.name != "nt":
        return None
    try:
        return _kernel32().CreateEventW(None, True, True, SHOW_EVENT) or None
    except Exception:
        return None


def wait_show_taken(h, timeout=15.0):
    """Launcher side: wait until the elevated app has taken the request (reset the event), so it still exists
    when the app looks for it."""
    k = _kernel32()
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if k.WaitForSingleObject(h, 0) != 0:      # no longer signalled: the app took it
            return True
        time.sleep(0.1)
    return False


def _show_event(reset):
    if os.name != "nt":
        return False
    try:
        k = _kernel32()
        h = k.OpenEventW(_EVENT_MODIFY_STATE | _SYNCHRONIZE, False, SHOW_EVENT)
        if not h:
            return False
        try:
            wanted = k.WaitForSingleObject(h, 0) == 0
            if wanted and reset:
                k.ResetEvent(h)
            return wanted
        finally:
            k.CloseHandle(h)
    except Exception:
        return False


def show_requested():
    """App side, early (splash decision): is a window wanted? Doesn't take the request."""
    return _show_event(reset=False)


def consume_show_flag():
    """App side: take the request to show the window, if there is one."""
    return _show_event(reset=True)
