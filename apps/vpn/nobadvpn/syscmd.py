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


def _shell_safe_url(url):
    """The URL as explorer.exe must receive it, or None. explorer.exe parses its own command line: a ',' or ';'
    splits it into switches, and an argument it doesn't recognise makes it open the Documents folder instead of the
    link (Wikipedia sections and news citations often contain commas). Those characters, spaces and non-ASCII
    letters are percent-encoded, which servers read identically; quotes and control characters are refused."""
    import urllib.parse
    url = str(url or "")
    if not url or len(url) > 2000 or any(c in url for c in '"\r\n\t\x00<>^`|\\'):
        return None
    try:
        u = urllib.parse.urlsplit(url)
    except ValueError:
        return None
    if u.scheme.lower() not in ("http", "https") or not u.netloc or u.username or u.password:
        return None
    return urllib.parse.quote(url, safe=":/?&=#%@+!$*()~'-._[]")


def open_url_as_user(url):
    """Open an http(s) link in the user's normal browser, NOT as administrator. NOBAD runs elevated and anything it
    starts directly inherits that (a captive-portal page from a café Wi-Fi would run in an admin browser). explorer.exe
    hands the link to the user's own desktop shell, which opens it at normal rights. Returns True if handed over."""
    url = _shell_safe_url(url)
    if not url:
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


def owner_sid(path):
    """String SID of the owner of `path` ('S-1-5-32-544'), None off Windows or on failure. Read from the file's own
    security descriptor with the link itself (not its target) when it is a reparse point."""
    if os.name != "nt":
        return None
    try:
        from ctypes import wintypes
        adv = ctypes.WinDLL("advapi32", use_last_error=True)
        sid, sd = ctypes.c_void_p(), ctypes.c_void_p()
        rc = adv.GetNamedSecurityInfoW(wintypes.LPCWSTR(path), 1, 1, ctypes.byref(sid), None, None, None, ctypes.byref(sd))
        if rc != 0:
            return None
        try:
            s = wintypes.LPWSTR()
            if not adv.ConvertSidToStringSidW(sid, ctypes.byref(s)):
                return None
            out = s.value
            ctypes.windll.kernel32.LocalFree(s)
            return out
        finally:
            ctypes.windll.kernel32.LocalFree(sd)
    except (OSError, AttributeError):
        return None


TRUSTED_OWNERS = ("S-1-5-32-544", "S-1-5-18", "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464")  # Admins, SYSTEM, TrustedInstaller


def owned_by_admins(path):
    return owner_sid(path) in TRUSTED_OWNERS


def harden_environment():
    """NOBAD runs elevated, but a normal user decides its inherited environment (HKCU\\Environment, or by starting
    the launcher task). Remove what would let them steer it: WEBVIEW2_* (another browser executable, a debugging
    port) and PSModulePath (fake DnsClient / NetTCPIP modules loaded into admin PowerShell)."""
    if os.name != "nt":
        return
    for k in [k for k in os.environ if k.upper().startswith("WEBVIEW2_")]:
        os.environ.pop(k, None)
    sysdir = os.path.join(known_folder("Windows") or r"C:\Windows", "System32")
    os.environ["PSModulePath"] = os.path.join(sysdir, "WindowsPowerShell", "v1.0", "Modules")


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


def authenticode(path, timeout=60):
    """The Authenticode signature of a file (#9: one check for the updater and the WireGuard installer):
    {'status': Valid|NotSigned|HashMismatch|NotTrusted|..., 'subject': str, 'thumbprint': upper-case SHA-1}."""
    if os.name != "nt":
        return {"status": "Unknown", "subject": "", "thumbprint": ""}
    lit = str(path).replace("'", "''")
    ps = (f"$s=Get-AuthenticodeSignature -LiteralPath '{lit}'; "
          "[string]$s.Status; [string]$s.SignerCertificate.Subject; [string]$s.SignerCertificate.Thumbprint")
    lines = [x.strip() for x in (run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                                     timeout=timeout).stdout or "").splitlines()] + ["", "", ""]
    return {"status": lines[0] or "UnknownError", "subject": lines[1], "thumbprint": lines[2].upper()}


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
        err = None
        try:
            fn(*args)
        except Exception as e:
            err = f"{type(e).__name__}: {e}"[:300]
            log(f"{key} failed: {err}", "bad")
        finally:
            with _busy_lock:
                _busy.discard(key)
            # the UI clears every "loading" state on task_done; `error` says the result event will never come
            broadcast("task_done", {"key": key, "error": err})

    threading.Thread(target=w, daemon=True).start()
    return True
