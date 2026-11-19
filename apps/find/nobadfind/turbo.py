"""The engine's side of the optional turbo index (the elevated reader is ntfs.py; the privacy reasoning is there).

- `turbo_set {on}` -> Turbo.turn_on / turn_off. On: the engine makes its private pipe, asks Windows to start
  `NobadFind.exe --turbo serve` elevated (one UAC prompt; saying no leaves the setting off), checks the client is that
  process in this session, and sends the scope. Off: the pipe closes and the helper ends.
- With the setting on, the indexer asks once per engine run (ensure) when indexing starts: one prompt per session.
  Declined then, the setting stays on (asked again next run) and the normal walk is used.
- Indexer._scan_names calls scan(): each NTFS drive in the scope is read by the helper (or caught up from the saved
  journal place when the scope hasn't changed), the rows go through the engine's own rules (Walker.excluded, the
  same check live changes get) before they reach the index. Drives the helper didn't cover are walked as before.
- Changes from the journal go to Indexer._on_changes (the indexer looks at each path again as the normal user).
  A lost journal (reset, wrapped) means a full read again (Indexer.rescan). A helper that ends is reported and the
  folder notifications (watcher.py) carry on alone.
- State in the contract's turbo_state shape; every change is pushed as the `turbo` event.
"""
import ctypes
import hashlib
import json
import os
import threading
import time
from ctypes import wintypes

from . import ntfs, winapi
from .kinds import kind_of
from .log import log
from .walker import Walker

CONNECT_TIMEOUT = 60             # seconds from the permission prompt being answered to the helper connecting
SAVE_USN_EVERY = 30              # seconds between saves of the journal place while following

DECLINED = ("Windows didn't get permission (the prompt was closed or answered No). NOBAD Find keeps using its "
            "normal folder walk.")
UNAVAILABLE = "The turbo index needs an NTFS drive in what you index; none was found, so the normal walk is used."
ENDED = "The turbo helper stopped; NOBAD Find went back to its normal folder walk and change notifications."


class Declined(Exception):
    """The user said no at the UAC prompt."""


def drive_of(path):
    d = os.path.splitdrive(path)[0]
    return d.upper() + "\\" if len(d) == 2 and d[1] == ":" else ""


class Turbo:
    def __init__(self, settings, store, indexer, push=None, launch=None, ntfs_drive=None, drives=None,
                 clock=time.time):
        self.settings, self.store, self.indexer = settings, store, indexer
        self._push = push
        self._launch = launch or self._launch_helper
        self._ntfs = ntfs_drive or ntfs.is_ntfs_fixed
        self._drives = drives or winapi.drives
        self._clock = clock
        self._lock = threading.Lock()              # one turn_on / turn_off at a time
        self._mlock = threading.Lock()             # state touched by the helper's messages
        self._link = None
        self._helper_volumes = set()
        self._vols = {}                            # drive -> {files, usn_ok, last_scan}
        self._waiting = {}                         # drive -> {"ev", "on_rows", "gen", "check", "result"}
        self._asked = False
        self._ntfs_cache = {}
        self.error = ""
        self._saved_at = 0.0

    # ----- state -----
    def running(self):
        link = self._link
        return link is not None and getattr(link, "alive", True)

    def _is_ntfs(self, d):
        if d not in self._ntfs_cache:
            try:
                self._ntfs_cache[d] = bool(self._ntfs(d))
            except Exception:
                self._ntfs_cache[d] = False
        return self._ntfs_cache[d]

    def state(self):
        fixed = [d["root"].upper() for d in self._drives() if d.get("type") == "fixed"]
        vols = []
        with self._mlock:
            for d in fixed:
                v = self._vols.get(d, {})
                vols.append({"drive": d, "ntfs": self._is_ntfs(d), "files": int(v.get("files", 0)),
                             "usn_ok": bool(v.get("usn_ok")) and self.running(), "last_scan": v.get("last_scan")})
        return {"available": any(v["ntfs"] for v in vols), "enabled": bool(self.settings.get("turbo")),
                "running": self.running(), "volumes": vols, "error": self.error}

    def _changed(self):
        if self._push is not None:
            try:
                self._push(self.state())
            except Exception as e:
                log(f"turbo event failed: {type(e).__name__}", "warn")

    def follows(self, path):
        """True if the change journal covers this path now (a watcher overflow needs no rescan there)."""
        d = drive_of(path)
        with self._mlock:
            return self.running() and bool(self._vols.get(d, {}).get("usn_ok"))

    # ----- on and off -----
    def ensure(self):
        """With the setting on: start the helper once per engine run (one permission prompt per session)."""
        if not self.settings.get("turbo") or self.running() or self._asked:
            return
        self.turn_on(keep_on_failure=True)

    def turn_on(self, keep_on_failure=False):
        with self._lock:
            self._asked = True
            if self.running():
                return {"ok": True, "error": ""}
            if not self.state()["available"]:
                self.error = UNAVAILABLE
                return self._failed(keep_on_failure)
            try:
                link = self._launch()
            except Declined:
                self.error = DECLINED
                return self._failed(keep_on_failure)
            except (OSError, PermissionError, TimeoutError) as e:
                log(f"turbo helper didn't start: {type(e).__name__} {getattr(e, 'winerror', '') or ''}", "warn")
                self.error = "The turbo helper didn't start; NOBAD Find keeps using its normal folder walk."
                return self._failed(keep_on_failure)
            self._link = link
            self.error = ""
            self.settings.update({"turbo": True})
            try:
                link.send(self._config(self.indexer.roots()))
            except OSError:
                self.link_closed()
                return {"ok": False, "error": self.error}
            log("turbo helper running")
        self._changed()
        return {"ok": True, "error": ""}

    def _failed(self, keep_on):
        if not keep_on:
            self.settings.update({"turbo": False})
        log(f"turbo: {self.error}", "warn")
        self._changed()
        return {"ok": False, "error": self.error}

    def turn_off(self):
        with self._lock:
            link, self._link = self._link, None
            if link is not None:
                try:
                    link.send({"t": "stop"})
                except OSError:
                    pass
                link.close()
            self.settings.update({"turbo": False})
            self.error = ""
            self._release_waiters()
        self._changed()
        return {"ok": True, "error": ""}

    def stop(self):
        """The engine is ending: the helper goes with it (and would on its own when the pipe closes)."""
        link, self._link = self._link, None
        if link is not None:
            try:
                link.send({"t": "stop"})
            except OSError:
                pass
            link.close()

    def link_closed(self):
        """The helper's pipe ended without turn_off."""
        if self._link is None:
            return
        self._link = None
        self.error = ENDED
        log("turbo helper ended", "warn")
        self._release_waiters()
        self._changed()

    def _release_waiters(self):
        with self._mlock:
            for w in self._waiting.values():
                w["ev"].set()

    # ----- the scope it may send -----
    def _config(self, roots):
        get = self.settings.get
        return {"t": "config", "roots": [r for r in roots if drive_of(r)], "exclude": list(get("exclude") or []),
                "include_system": bool(get("include_system")), "include_caches": bool(get("include_caches")),
                "include_secrets": bool(get("include_secrets"))}

    @staticmethod
    def _key(cfg):
        return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode("utf-8")).hexdigest()[:16]

    def _saved(self):
        try:
            v = json.loads(self.store.meta("turbo", "{}") or "{}")
            return v if isinstance(v, dict) else {}
        except ValueError:
            return {}

    # ----- reading drives -----
    def scan(self, roots, gen, on_rows, stop):
        """Read every NTFS drive in roots with the helper. Returns (drives read in full, drives caught up from the
        journal); the caller walks the rest. on_rows gets rows ready for Store.upsert_files."""
        full, caught = set(), set()
        link = self._link
        if not self.running():
            return full, caught
        cfg = self._config(roots)
        key = self._key(cfg)
        try:
            link.send(cfg)
        except OSError:
            self.link_closed()
            return full, caught
        rules = self.indexer.rules()
        check = _Checker(Walker(roots, exclude=cfg["exclude"], rules=rules), rules)
        saved = self._saved()
        want = sorted({drive_of(r) for r in roots} & self._helper_volumes)
        for d in want:
            prev = saved.get(d) if isinstance(saved.get(d), dict) else None
            since = {"journal": prev["journal"], "usn": prev["usn"]} if prev and prev.get("key") == key and all(
                isinstance(prev.get(k), int) for k in ("journal", "usn")) else None
            w = {"ev": threading.Event(), "on_rows": on_rows, "gen": gen, "check": check, "result": None, "files": 0}
            with self._mlock:
                self._waiting[d] = w
            try:
                link.send({"t": "scan", "drive": d, "since": since})
            except OSError:
                self.link_closed()
            while not w["ev"].wait(0.5):
                if stop.is_set() or not self.running():
                    break
            with self._mlock:
                self._waiting.pop(d, None)
            r = w["result"]
            if r is None:
                continue
            (full if r["full"] else caught).add(d)
            saved[d] = {"journal": r["journal"], "usn": r["usn"], "key": key}
            self.store.set_meta("turbo", json.dumps(saved))
            with self._mlock:
                v = self._vols.setdefault(d, {})
                v.update(usn_ok=bool(r["usn_ok"]), last_scan=self._clock())
                if r["full"]:
                    v["files"] = w["files"]
            log(f"turbo: {d} {'read' if r['full'] else 'caught up'} ({w['files']} entries)")
            self._changed()
        return full, caught

    def forget_place(self):
        """A rescan was asked for (settings, Rescan): read everything again instead of catching up."""
        self.store.set_meta("turbo", "{}")

    # ----- the helper's messages -----
    def on_message(self, msg):
        try:
            self._on_message(msg)
        except Exception as e:                         # a malformed message is ignored, never fatal
            log(f"turbo message ignored: {type(e).__name__}", "warn")

    def _on_message(self, msg):
        t = msg.get("t")
        d = msg.get("drive")
        if t != "hello" and not (isinstance(d, str) and ntfs.DRIVE_RE.match(d)):
            return
        if t == "hello":
            vols = msg.get("volumes")
            if isinstance(vols, list):
                self._helper_volumes = {v["drive"].upper() for v in vols if isinstance(v, dict) and isinstance(
                    v.get("drive"), str) and ntfs.DRIVE_RE.match(v["drive"])}
        elif t == "rows":
            with self._mlock:
                w = self._waiting.get(d)
            rows = msg.get("rows")
            if w is None or not isinstance(rows, list):
                return
            out = [r for r in (w["check"].row(x, d, w["gen"]) for x in rows) if r is not None]
            w["files"] += len(out)
            if out:
                w["on_rows"](out)
        elif t == "scanned":
            with self._mlock:
                w = self._waiting.get(d)
            if w is None:
                return
            j, u = msg.get("journal"), msg.get("usn")
            if not (isinstance(j, int) and isinstance(u, int)):
                return
            w["result"] = {"full": bool(msg.get("full")), "journal": j, "usn": u, "usn_ok": bool(msg.get("usn_ok"))}
            w["ev"].set()
        elif t == "failed":
            with self._mlock:
                w = self._waiting.get(d)
                self._vols.setdefault(d, {})["usn_ok"] = False
            self.error = f"Turbo couldn't read {d}; that drive uses the normal folder walk."
            log(f"turbo: {d} failed ({str(msg.get('error'))[:80]})", "warn")
            if w is not None:
                w["ev"].set()
            self._changed()
        elif t == "changes":
            paths = msg.get("paths")
            if not isinstance(paths, list):
                return
            ok = {p for p in paths if isinstance(p, str) and 3 <= len(p) < 32768 and drive_of(p) == d.upper()
                  and os.path.isabs(p) and "\x00" not in p}
            if ok:
                self.indexer._on_changes(d, ok)
        elif t == "usn":
            j, u = msg.get("journal"), msg.get("usn")
            now = self._clock()
            if isinstance(j, int) and isinstance(u, int) and now - self._saved_at >= SAVE_USN_EVERY:
                saved = self._saved()
                if isinstance(saved.get(d), dict) and saved[d].get("journal") == j:
                    saved[d]["usn"] = u
                    self.store.set_meta("turbo", json.dumps(saved))
                    self._saved_at = now
        elif t == "journal":
            with self._mlock:
                self._vols.setdefault(d, {})["usn_ok"] = False
            log(f"turbo: change journal of {d} lost; reading it again", "warn")
            self.forget_place()
            self.indexer.rescan()
            self._changed()

    # ----- the real helper (Windows) -----
    def _launch_helper(self):
        return PipeLink.start(self)


class _Checker:
    """The engine's own rules on every row the helper sends (it already dropped what it must; this is the engine
    not trusting a more privileged process to have the same idea of the scope)."""

    def __init__(self, walker, rules):
        self.w, self.rules = walker, rules
        self._dirs = {}

    def _dir_ok(self, d):
        ok = self._dirs.get(d)
        if ok is None:
            ok = self._dirs[d] = not self.w.excluded(d)
        return ok

    def row(self, x, drive, gen):
        if not (isinstance(x, list) and len(x) == 5):
            return None
        path, is_dir, size, mtime, ctime = x
        if not (isinstance(path, str) and 3 < len(path) < 32768 and "\x00" not in path and os.path.isabs(path)
                and drive_of(path) == drive.upper() and is_dir in (0, 1)):
            return None
        if not (size is None or (isinstance(size, int) and not isinstance(size, bool) and size >= 0)):
            return None
        if not all(v is None or (isinstance(v, (int, float)) and not isinstance(v, bool)) for v in (mtime, ctime)):
            return None
        parent, name = os.path.split(path)
        if not name or not self._dir_ok(parent):
            return None
        if is_dir:
            if self.w.excluded(path):
                return None
            return (path, name, parent, "", "folder", 0, mtime, ctime, gen)
        if self.rules.skip_file(name):
            return None
        return (path, name, parent, os.path.splitext(name)[1].lower(), kind_of(name), size, mtime, ctime, gen)


# ---------- the pipe to the helper (Windows) ----------
_W = {}


def _win():
    if not _W:
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        H, D, B = wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL
        for name, res, args in (("GetProcessId", D, [H]),
                                ("GetNamedPipeClientSessionId", B, [H, ctypes.POINTER(D)]),
                                ("GetNamedPipeClientProcessId", B, [H, ctypes.POINTER(D)]),
                                ("ProcessIdToSessionId", B, [D, ctypes.POINTER(D)]),
                                ("GetCurrentProcessId", D, []),
                                ("WaitForMultipleObjects", D, [D, ctypes.POINTER(H), B, D]),
                                ("CloseHandle", B, [H]),
                                ("AssignProcessToJobObject", B, [H, H])):
            f = getattr(k, name)
            f.restype, f.argtypes = res, args
        _W["k"] = k
    return _W["k"]


def start_elevated(argv):
    """ShellExecuteEx "runas" (the UAC prompt), not waiting: the helper's process handle. Raises Declined."""
    sei = winapi._SEI()
    sei.cbSize = ctypes.sizeof(sei)
    sei.fMask = 0x40 | 0x400                       # SEE_MASK_NOCLOSEPROCESS | SEE_MASK_FLAG_NO_UI
    sei.lpVerb = "runas"
    sei.lpFile = argv[0]
    import subprocess
    import sys
    sei.lpParameters = subprocess.list2cmdline(argv[1:])
    sei.lpDirectory = None if getattr(sys, "frozen", False) else os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))
    sei.nShow = 0
    if not winapi.shell32.ShellExecuteExW(ctypes.byref(sei)):
        err = ctypes.get_last_error() or ctypes.GetLastError()
        if err == 1223:                            # ERROR_CANCELLED: No at the prompt
            raise Declined()
        raise OSError(err, "runas")
    if not sei.hProcess:
        raise OSError(0, "no process handle")
    return sei.hProcess


class PipeLink:
    """The engine's end: one pipe instance for one helper. send() writes a line; the reader thread hands each message
    to turbo.on_message and calls turbo.link_closed() when the pipe ends."""

    def __init__(self, turbo, conn, proc, server):
        self.turbo, self.conn, self.proc, self._server = turbo, conn, proc, server
        self.alive = True
        threading.Thread(target=self._read, daemon=True, name="turbo-pipe").start()

    @classmethod
    def start(cls, turbo, timeout=CONNECT_TIMEOUT):
        from .rpc import server as srv
        k, a = srv._dlls()
        w = _win()
        sid = srv.user_sid()
        name = ntfs.pipe_name(sid, os.getpid())
        sd = ctypes.c_void_p()
        if not a.ConvertStringSecurityDescriptorToSecurityDescriptorW(srv.sddl_for(sid), 1, ctypes.byref(sd), None):
            raise ctypes.WinError(ctypes.get_last_error())
        sa = srv._SA(ctypes.sizeof(srv._SA), sd, False)
        h = k.CreateNamedPipeW(name, srv.PIPE_ACCESS_DUPLEX | srv.FILE_FLAG_OVERLAPPED | srv.FILE_FLAG_FIRST_PIPE_INSTANCE,
                               srv.PIPE_REJECT_REMOTE_CLIENTS, 1, srv.BUF, srv.BUF, 0, ctypes.byref(sa))
        k.LocalFree(sd)
        if not h or h == srv.INVALID_HANDLE:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            proc = start_elevated(winapi.self_command("--turbo", "serve"))
        except BaseException:
            k.CloseHandle(h)
            raise
        pid = w.GetProcessId(proc)
        from . import jobs
        if jobs.OUTER is not None and getattr(jobs.OUTER, "handle", None):
            if not w.AssignProcessToJobObject(jobs.OUTER.handle, proc):     # Windows may refuse for an elevated
                log("turbo helper is outside the job; it ends on its own with the engine")
        ov = srv._OVERLAPPED()
        ov.hEvent = k.CreateEventW(None, True, False, None)
        try:
            ok = k.ConnectNamedPipe(h, ctypes.byref(ov))
            err = ctypes.get_last_error()
            if not ok and err == srv.ERROR_IO_PENDING:
                arr = (wintypes.HANDLE * 2)(ov.hEvent, proc)
                r = w.WaitForMultipleObjects(2, arr, False, int(timeout * 1000))
                if r != 0:
                    k.CancelIoEx(h, ctypes.byref(ov))
                    k.CloseHandle(h)
                    raise TimeoutError("the helper didn't connect")
            elif not ok and err != srv.ERROR_PIPE_CONNECTED:
                k.CloseHandle(h)
                raise ctypes.WinError(err)
        finally:
            k.CloseHandle(ov.hEvent)
        cpid, csess, mine = wintypes.DWORD(), wintypes.DWORD(), wintypes.DWORD()
        w.ProcessIdToSessionId(w.GetCurrentProcessId(), ctypes.byref(mine))
        if not (w.GetNamedPipeClientProcessId(h, ctypes.byref(cpid)) and cpid.value == pid) or not (
                w.GetNamedPipeClientSessionId(h, ctypes.byref(csess)) and csess.value == mine.value):
            k.DisconnectNamedPipe(h)
            k.CloseHandle(h)
            raise PermissionError("the pipe's client isn't the helper NOBAD Find started")
        return cls(turbo, srv.Conn(k, h), proc, srv)

    def send(self, msg):
        if not self.conn.send(msg):
            self.alive = False
            raise OSError(0, "turbo pipe closed")

    def close(self):
        self.alive = False
        self.conn.close()

    def _read(self):
        srv = self._server
        k, _a = srv._dlls()
        ov = srv._OVERLAPPED()
        ov.hEvent = k.CreateEventW(None, True, False, None)
        buf = ctypes.create_string_buffer(srv.BUF)
        n = wintypes.DWORD()
        lines = ntfs.Lines()
        try:
            while self.alive and self.conn.alive:
                k.ResetEvent(ov.hEvent)
                if not k.ReadFile(self.conn.handle, buf, srv.BUF, None, ctypes.byref(ov)) \
                        and ctypes.get_last_error() != srv.ERROR_IO_PENDING:
                    break
                k.WaitForSingleObject(ov.hEvent, srv.INFINITE)
                if not k.GetOverlappedResult(self.conn.handle, ctypes.byref(ov), ctypes.byref(n), False):
                    break
                for msg in lines.feed(buf.raw[:n.value]):
                    self.turbo.on_message(msg)
        except ValueError:
            log("turbo helper sent a message that isn't one; closing", "warn")
        except Exception as e:
            log(f"turbo pipe ended: {type(e).__name__}", "warn")
        finally:
            k.CloseHandle(ov.hEvent)
            was = self.alive
            self.alive = False
            self.conn.close()
            _win().CloseHandle(self.proc)
            if was:
                self.turbo.link_closed()
