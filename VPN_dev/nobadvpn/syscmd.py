"""Thin wrappers around Windows tools (ping, sc, wireguard.exe) plus small thread helpers."""
import ctypes
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time

from .const import FROZEN, WG_DIRS
from .logbus import broadcast, log

_NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)


class _Result:
    def __init__(self, err=""):
        self.stdout = ""
        self.stderr = err
        self.returncode = 1


def run(cmd, timeout=15, input_text=None):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, creationflags=_NOWIN,
                              input=input_text)
    except Exception as e:  # missing exe, timeout, ...
        return _Result(str(e))


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def entry_command(extra_args=()):
    """Command line that re-launches this app (works for `python nobad_vpn.py` and a frozen exe)."""
    if FROZEN:
        return [sys.executable, *extra_args]
    script = os.path.abspath(sys.argv[0]) if sys.argv and sys.argv[0] else ""
    if not script or os.path.basename(script).lower() == "__main__.py":
        # started as `python -m <package>`: the file can't run on its own (relative imports)
        return [sys.executable, "-m", __name__.split(".")[0], *extra_args]
    return [sys.executable, script, *extra_args]


def try_self_elevate(args=None):
    if os.name != "nt" or is_admin():
        return False
    try:
        cmd = entry_command(sys.argv[1:] if args is None else args)
        params = " ".join(f'"{a}"' for a in cmd[1:])
        return ctypes.windll.shell32.ShellExecuteW(None, "runas", cmd[0], params, None, 1) > 32
    except Exception:
        return False


def wg_tool(exe):
    for d in WG_DIRS:
        p = os.path.join(d, exe)
        if os.path.exists(p):
            return p
    return shutil.which(exe)


def service_running(name):
    return "RUNNING" in (run(["sc", "query", f"WireGuardTunnel${name}"]).stdout or "")


def list_wg_services():
    """Names of every installed WireGuard tunnel service (ours or the WireGuard GUI's)."""
    out = run(["sc", "query", "type=", "service", "state=", "all"], timeout=20).stdout or ""
    return sorted(set(re.findall(r"SERVICE_NAME:\s*WireGuardTunnel\$(\S+)", out)))


def ping_stats(host, count=3, timeout_ms=1500):
    r = run(["ping", "-n", str(count), "-w", str(timeout_ms), host], timeout=count * (timeout_ms / 1000 + 1) + 3)
    out = r.stdout or ""
    m = re.search(r"\((\d+)%", out)
    loss = int(m.group(1)) if m else 100
    vals = re.findall(r"=\s*(\d+)\s*ms", out)
    rtt = jit = None
    if loss < 100 and len(vals) >= 3:
        mn, mx, av = (int(x) for x in vals[-3:])
        rtt, jit = av, mx - mn
    return {"rtt": rtt, "loss": loss, "jitter": jit}


def quality_of(h):
    if h["rtt"] is None or h["loss"] >= 50:
        return "bad"
    if h["loss"] > 5 or h["rtt"] > 250 or (h["jitter"] or 0) > 80:
        return "poor"
    if h["loss"] > 0 or h["rtt"] > 120 or (h["jitter"] or 0) > 30:
        return "fair"
    return "great"


def probe_endpoint(ips):
    if not ips:
        return {"rtt": None, "loss": 100, "jitter": None, "src": "dns"}
    ip = ips[0]
    p = ping_stats(ip, 3, 1200)
    if p["rtt"] is not None:
        return {**p, "src": "icmp"}
    for port in (443, 80):  # many VPN hosts drop ICMP — estimate with TCP instead
        try:
            t = time.time()
            s = socket.create_connection((ip, port), 1.5)
            s.close()
            return {"rtt": round((time.time() - t) * 1000), "loss": 0, "jitter": None, "src": "tcp", "est": True}
        except OSError:
            continue
    return {"rtt": None, "loss": 100, "jitter": None, "src": "none"}


# ---- thread helpers ----------------------------------------------------------
_busy = set()
_busy_lock = threading.Lock()


def spawn(fn, *args):
    t = threading.Thread(target=fn, args=args, daemon=True)
    t.start()
    return t


def is_busy(key):
    with _busy_lock:
        return key in _busy


def run_once(key, fn, *args):
    with _busy_lock:
        if key in _busy:
            return False
        _busy.add(key)

    def w():
        try:
            fn(*args)
        except Exception as e:
            log(f"{key} failed: {e}", "bad")
        finally:
            with _busy_lock:
                _busy.discard(key)
            broadcast("task_done", {"key": key})

    threading.Thread(target=w, daemon=True).start()
    return True
