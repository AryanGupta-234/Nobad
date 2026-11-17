"""The optional "turn off Windows Search indexing" switch.

Turning the WSearch service off frees CPU and disk, but Start menu, Explorer and Outlook search stop finding
files. So it is off by default, and the start type Windows had before is saved and put back with one click.

Reading the state needs no admin. Changing it runs this app once more, elevated, as
`--wsearch disabled|auto|delayed-auto|demand`: the helper accepts only those four words and runs `sc.exe`
with a fixed argument list. It writes nothing anywhere.
"""
import os
import re
import subprocess
import sys

from . import winapi

STARTS = ("auto", "delayed-auto", "demand", "disabled")
CREATE_NO_WINDOW = 0x08000000


def _system32():
    """The real System32 folder from Windows itself (not from an environment variable the user controls)."""
    if winapi.WIN:
        import ctypes
        buf = ctypes.create_unicode_buffer(260)
        if winapi.k32.GetSystemDirectoryW(buf, 260):
            return buf.value
    return r"C:\Windows\System32"


def _sc(*args, timeout=20):
    exe = os.path.join(_system32(), "sc.exe")
    return subprocess.run([exe, *args], capture_output=True, text=True, timeout=timeout,
                          creationflags=CREATE_NO_WINDOW if winapi.WIN else 0)


def parse_qc(out):
    """START_TYPE from `sc qc WSearch` output."""
    m = re.search(r"START_TYPE\s*:\s*(\d)\s+(\S+)(?:\s+\(DELAYED\))?", out)
    if not m:
        return None
    code = m.group(1)
    if code == "2":
        return "delayed-auto" if "DELAYED" in out.upper() else "auto"
    return {"3": "demand", "4": "disabled"}.get(code)


def parse_query(out):
    m = re.search(r"STATE\s*:\s*\d\s+(\w+)", out)
    return m.group(1).lower() if m else None


def state():
    """{'start': 'auto'|..., 'running': bool} or {'missing': True}."""
    try:
        qc = _sc("qc", "WSearch")
        q = _sc("query", "WSearch")
    except (OSError, subprocess.TimeoutExpired):
        return {"missing": True}
    start = parse_qc(qc.stdout)
    if start is None:
        return {"missing": True}
    return {"start": start, "running": parse_query(q.stdout) == "running"}


def request(start):
    """From the app: ask Windows (UAC) to set WSearch to start. Returns True if it now matches."""
    if start not in STARTS:
        raise ValueError("unknown start type")
    code = winapi.run_elevated(winapi.self_command("--wsearch", start))
    if code is None:
        return False                                         # the user said no at the UAC prompt
    return state().get("start") == start


def helper_main(start):
    """Runs elevated. Only the four known words are accepted; everything else exits."""
    if start not in STARTS:
        return 2
    r = _sc("config", "WSearch", "start=", start)       # sc wants "start=" and the value as two arguments
    if r.returncode != 0:
        return 3
    if start == "disabled":
        _sc("stop", "WSearch", timeout=60)
    elif start in ("auto", "delayed-auto"):
        _sc("start", "WSearch", timeout=60)
    return 0


if __name__ == "__main__":
    sys.exit(helper_main(sys.argv[1] if len(sys.argv) > 1 else ""))
