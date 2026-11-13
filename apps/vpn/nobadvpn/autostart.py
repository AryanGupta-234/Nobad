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

from .const import FROZEN, LEGACY_TASK_NAME, SHOW_FLAG_PATH, TASK_NAME, known_folder
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
        try:
            if show_window:
                os.makedirs(os.path.dirname(SHOW_FLAG_PATH), exist_ok=True)
                with open(SHOW_FLAG_PATH, "w") as f:
                    f.write("1")
        except OSError:
            pass
        if run(["schtasks", "/Run", "/TN", name], timeout=20).returncode == 0:
            return True
    return False


def consume_show_flag():
    try:
        if os.path.exists(SHOW_FLAG_PATH):
            os.remove(SHOW_FLAG_PATH)
            return True
    except OSError:
        pass
    return False
