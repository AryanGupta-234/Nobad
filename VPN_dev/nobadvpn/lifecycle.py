"""Process lifecycle: single instance, clean-exit marker, quit."""
import json
import os
import re

from .const import CLEAN_EXIT_PATH, FROZEN, INSTANCE_PATH
from .ctx import ctx
from .logbus import log
from .syscmd import run, spawn


_prev = {"clean": True}


def mark_started():
    _prev["clean"] = os.path.exists(CLEAN_EXIT_PATH) or not os.path.exists(os.path.dirname(CLEAN_EXIT_PATH))
    try:
        os.remove(CLEAN_EXIT_PATH)
    except OSError:
        pass


def previous_exit_clean():
    """False if the last run ended without writing its clean-exit marker (crash, kill, power loss)."""
    return _prev["clean"]


def mark_clean_exit():
    try:
        os.makedirs(os.path.dirname(CLEAN_EXIT_PATH), exist_ok=True)
        with open(CLEAN_EXIT_PATH, "w") as f:
            f.write("1")
    except OSError:
        pass


def write_instance(port, token=None):
    """Advertise the running copy. The file lives in ProgramData\\NobadVPN, which is locked to SYSTEM and
    Administrators, so only another elevated NOBAD can read the control token."""
    try:
        with open(INSTANCE_PATH, "w") as f:
            json.dump({"port": port, "pid": os.getpid(), "ts": __import__("time").time(), "token": token}, f)
    except OSError:
        pass


def remove_instance():
    try:
        with open(INSTANCE_PATH) as f:
            if json.load(f).get("pid") != os.getpid():
                return  # a newer copy owns the file now
    except (OSError, ValueError):
        pass
    try:
        os.remove(INSTANCE_PATH)
    except OSError:
        pass


def read_instance():
    try:
        with open(INSTANCE_PATH) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def _post_local(port, token, path, body, timeout):
    import urllib.request
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never route loopback via a proxy
    req = urllib.request.Request(f"http://127.0.0.1:{int(port)}{path}", data=json.dumps(body).encode(),
                                 headers={"X-Token": token, "Content-Type": "application/json"}, method="POST")
    with opener.open(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


def process_image(pid):
    """Full path of the executable running as `pid`, or None (gone, no access, not Windows)."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, int(pid))          # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return None
        try:
            buf, size = ctypes.create_unicode_buffer(32768), wintypes.DWORD(32768)
            return buf.value if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)) else None
        finally:
            k32.CloseHandle(h)
    except Exception:
        return None


def is_nobad_process(pid, image=None):
    """True only if `pid` runs NOBAD's own executable. instance.json can outlive a crash, and Windows reuses
    process IDs: without this an elevated NOBAD could force-kill an unrelated program (and its children)."""
    path = (image or process_image)(pid)
    if not path:
        return False
    return os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(os.sys.executable))


def handoff_to_running(show=True, timeout=2.5, pid_alive=None, post=None, image=None):
    """Second launch: if NOBAD is already running and responsive, bring its window forward and return True
    (the caller just exits; nothing is re-initialised, so this takes well under a second).
    If the running copy does not answer, it is replaced (killed with its watchdog) and False is returned."""
    from .watchdog import _pid_alive
    pid_alive = pid_alive or _pid_alive
    post = post or _post_local
    inst = read_instance()
    if not inst:
        return False
    try:
        pid, port, token = int(inst.get("pid") or 0), int(inst.get("port") or 0), inst.get("token")
    except (TypeError, ValueError):
        return False
    if not pid or pid in (os.getpid(), os.getppid()) or not pid_alive(pid):
        return False
    if port and token:
        try:
            if post(port, token, "/api/window", {"do": "show" if show else "noop"}, timeout).get("ok"):
                return True
        except Exception:
            pass
    if not is_nobad_process(pid, image):
        log(f"stale instance file (pid {pid} is no longer NOBAD) — ignoring it", "info")
        return False
    log(f"previous NOBAD (pid {pid}) is not responding — replacing it", "warn")
    run(["taskkill", "/PID", str(pid), "/T", "/F"], timeout=15)
    return False


def kill_other_instances():
    """Replace stray older copies (and their watchdogs). Frozen builds use `tasklist` (fast); source runs only
    deal with the advertised instance (handoff_to_running) — scanning every python.exe is slow and risky."""
    if os.name != "nt" or not FROZEN:
        return
    me, parent = os.getpid(), os.getppid()
    pids = []
    for image in {os.path.basename(os.sys.executable), "NomadTunnel.exe"}:
        out = run(["tasklist", "/FO", "CSV", "/NH", "/FI", f"IMAGENAME eq {image}"], timeout=10).stdout or ""
        for m in re.finditer(r'^"[^"]+","(\d+)"', out, re.M):
            pid = int(m.group(1))
            if pid not in (me, parent):
                pids.append(pid)
    for pid in pids:
        run(["taskkill", "/PID", str(pid), "/T", "/F"], timeout=15)
    if pids:
        log(f"replaced {len(pids)} older NOBAD process(es)", "info")


def request_quit(disconnect=False):
    """Leave the app. By default the VPN keeps running (the service is independent); `disconnect` tears it down."""
    def go():
        ctx.quitting = True
        try:
            if disconnect and ctx.tunnel:
                ctx.tunnel.disconnect(manual=False)
        finally:
            ctx.quit_event.set()
            if ctx.windows:
                ctx.windows.destroy_all()
    spawn(go)
