"""Thin wrappers around Windows tools (ping, sc, wireguard.exe) plus small thread helpers."""
import ctypes
import functools
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time

from .const import FROZEN, WG_DIRS, known_folder
from .logbus import broadcast, log

_NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)


class _Result:
    def __init__(self, err=""):
        self.stdout = ""
        self.stderr = err
        self.returncode = 1


# Windows tools NOBAD runs, relative to System32 (#19). NOBAD runs elevated, and finding a tool by name searches the
# current folder and PATH, which a normal user can change: a planted netsh.exe would run with admin rights.
SYSTEM_TOOLS = {
    "powershell": r"WindowsPowerShell\v1.0\powershell.exe", "netsh": "netsh.exe", "schtasks": "schtasks.exe",
    "sc": "sc.exe", "route": "route.exe", "taskkill": "taskkill.exe", "tasklist": "tasklist.exe", "ping": "ping.exe",
    "icacls": "icacls.exe", "msiexec": "msiexec.exe", "ipconfig": "ipconfig.exe", "arp": "arp.exe",
    "nslookup": "nslookup.exe", "netstat": "netstat.exe", "reg": "reg.exe", "whoami": "whoami.exe",
    "pnputil": "pnputil.exe", "wevtutil": "wevtutil.exe", "cmd": "cmd.exe",
}


@functools.lru_cache(maxsize=1)
def system32():
    win = known_folder("Windows")
    return os.path.join(win, "System32") if win else r"C:\Windows\System32"


def resolve_tool(exe):
    """Full path of a Windows tool given by bare name (`netsh`, `sc.exe`), or None if it isn't one NOBAD knows."""
    base = os.path.basename(exe).lower()
    name = base[:-4] if base.endswith(".exe") else base
    rel = SYSTEM_TOOLS.get(name)
    return os.path.join(system32(), rel) if rel and base == exe.lower() else None


def _resolve_cmd(cmd):
    if os.name != "nt" or not cmd or not isinstance(cmd[0], str) or os.path.isabs(cmd[0]):
        return cmd
    full = resolve_tool(cmd[0])
    if full:
        return [full] + list(cmd[1:])
    if FROZEN:      # the installed (elevated) app never searches PATH for a program
        raise FileNotFoundError(f"refusing to run {cmd[0]!r} by name; it is not a known Windows tool")
    return cmd


def run(cmd, timeout=15, input_text=None):
    try:
        return subprocess.run(_resolve_cmd(cmd), capture_output=True, text=True, timeout=timeout,
                              creationflags=_NOWIN, input=input_text)
    except Exception as e:  # missing exe, timeout, ...
        return _Result(str(e))


ADMINS_SID = "*S-1-5-32-544"
SYSTEM_SID = "*S-1-5-18"


def lock_dir(path, allow_user=False):
    """Make a folder private to SYSTEM + Administrators (+ the signed-in user if `allow_user`).

    Also takes ownership for Administrators, recursively, and resets anything already inside to inherit the new
    rules. Without that, an ordinary user who created the folder (or a file in it) before NOBAD did would stay its
    owner and could give themselves access again. Returns True when the folder is locked."""
    if os.name != "nt":
        return True
    # Never follow a junction or symlink: a planted one would make these recursive owner/ACL changes hit another
    # folder (a system folder, or one the user controls).
    if os.path.normcase(os.path.realpath(path)) != os.path.normcase(os.path.abspath(path)):
        log(f"refused to lock {path}: it is (or passes through) a junction or symbolic link", "bad")
        return False
    removed = remove_reparse_points(path)
    if removed:
        log(f"removed {removed} link(s) planted in {path} before locking it", "warn")
    owner = run(["icacls", path, "/setowner", ADMINS_SID, "/T", "/C", "/Q"], timeout=30)
    grants = [f"{SYSTEM_SID}:(OI)(CI)F", f"{ADMINS_SID}:(OI)(CI)F"]
    user = os.environ.get("USERNAME")
    if allow_user and user:
        grants.append(f"{user}:(OI)(CI)M")
    cmd = ["icacls", path, "/inheritance:r"]
    for g in grants:
        cmd += ["/grant:r", g]
    acl = run(cmd, timeout=15)
    if any(os.scandir(path)):
        run(["icacls", os.path.join(path, "*"), "/reset", "/T", "/C", "/Q"], timeout=60)
    if owner.returncode != 0 or acl.returncode != 0:
        log(f"couldn't make {path} private (owner {owner.returncode}, permissions {acl.returncode}): "
            f"{(owner.stderr or acl.stderr or owner.stdout or acl.stdout or '').strip()[:160]}", "bad")
        return False
    return True


def open_url_as_user(url):
    """Open an http(s) link in the user's normal browser, NOT as administrator. NOBAD runs elevated and anything it
    starts directly inherits that (a captive-portal page from a café Wi-Fi would run in an admin browser). explorer.exe
    hands the link to the user's own desktop shell, which opens it at normal rights. Returns True if handed over."""
    import urllib.parse
    url = str(url or "")
    u = urllib.parse.urlsplit(url)
    if u.scheme not in ("http", "https") or not u.netloc or any(c in url for c in '"\r\n\t\x00 '):
        return False
    if os.name != "nt":
        import webbrowser
        return bool(webbrowser.open(url))
    from .const import known_folder
    win = known_folder("Windows") or r"C:\Windows"
    try:
        subprocess.Popen([os.path.join(win, "explorer.exe"), url], creationflags=_NOWIN)
        return True
    except OSError:
        return False


def _is_reparse(p):
    try:
        st = os.lstat(p)
    except OSError:
        return False
    return bool(getattr(st, "st_file_attributes", 0) & 0x400) or os.path.islink(p)   # FILE_ATTRIBUTE_REPARSE_POINT


def remove_reparse_points(root):
    """Delete junctions/symlinks anywhere under `root` (the LINK, never its target) so recursive icacls can't be
    steered elsewhere. Returns how many were removed."""
    n = 0
    for dirpath, dirs, files in os.walk(root, followlinks=False):
        for name in list(dirs) + files:
            p = os.path.join(dirpath, name)
            if not _is_reparse(p):
                continue
            try:
                if os.path.isdir(p) and not os.path.islink(p):
                    os.rmdir(p)          # a junction: rmdir removes the link only
                else:
                    os.unlink(p)
                n += 1
            except OSError:
                pass
            if name in dirs:
                dirs.remove(name)        # never descend into it
    return n


def private_workdir(parent, prefix="w-"):
    """A fresh, admin-only folder under `parent` for files that will run elevated (installers). Each download gets
    its own folder, so nothing another user placed in `parent` earlier can be picked up or swapped in."""
    import tempfile
    os.makedirs(parent, exist_ok=True)
    work = tempfile.mkdtemp(prefix=prefix, dir=parent)
    if not lock_dir(work):
        shutil.rmtree(work, ignore_errors=True)
        raise PermissionError(f"couldn't make a private folder in {parent}")
    return work


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


@functools.lru_cache(maxsize=1)
def wg_dirs():
    pf = [known_folder("ProgramFiles"), known_folder("ProgramFilesX86")]
    return [os.path.join(p, "WireGuard") for p in pf if p] or list(WG_DIRS)


def wg_tool(exe):
    for d in wg_dirs():
        p = os.path.join(d, exe)
        if os.path.exists(p):
            return p
    # Only a development run looks on PATH: the installed app is elevated and PATH is user-controlled (#19).
    return None if FROZEN else shutil.which(exe)


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
