"""The watchdog ends NOBAD Find's OWN stuck or runaway work. It never touches another app.

- a text-reader worker over WORKER_MB is ended (the indexer treats it as a crashed reader and skips the file);
- all of Find's processes together over JOB_MB: the models are released and the worker processes start
  fresh (at most once per 5 minutes);
- the window is visible but its page stopped answering: reload it; a second miss soon after quits.
Only pids listed by jobs.WORKERS.pids() are ever ended, and never this process.
"""
import ctypes
import os
import threading
import time

from . import jobs as _jobs
from .log import log

WORKER_MB = 1500
JOB_MB = 3000
RELEASE_EVERY = 300      # seconds between model releases
BEAT_MISS = 15           # seconds without a heartbeat from a visible window
QUIT_WITHIN = 120        # a second miss within this many seconds quits
FIRST_BEAT_MAX = 60      # a page that never sends its first heartbeat counts as one miss after this long
KILL_WINDOW = 600        # the same kind of worker killed twice within this many seconds ...
KILL_PAUSE = 1800        # ... is left alone for this many seconds


def kill_process(pid):
    """TerminateProcess on one pid (the caller only passes Find's own workers)."""
    if os.name != "nt":
        return
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.restype = ctypes.c_void_p
    k.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    k.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    h = k.OpenProcess(0x0001, False, int(pid))           # PROCESS_TERMINATE
    if not h:
        log(f"watchdog could not open a worker (error {ctypes.get_last_error()})", "warn")
        return
    try:
        if not k.TerminateProcess(h, 1):
            log(f"watchdog could not end a worker (error {ctypes.get_last_error()})", "warn")
    finally:
        k.CloseHandle(h)


def _size(mb):
    return f"{mb / 1024:.1f} GB" if mb >= 1024 else f"{int(mb)} MB"


class Watchdog:
    def __init__(self, activity, kill=kill_process, info=_jobs.process_info,
                 pids=lambda: _jobs.WORKERS.pids() if _jobs.WORKERS else [],
                 job_usage=lambda: _jobs.OUTER.usage() if _jobs.OUTER else {"memory_mb": 0},
                 release=lambda: None, reload_ui=lambda: None, quit_app=lambda: None,
                 clock=time.monotonic, visible=lambda: True, names=lambda: {}, recycle=lambda: None):
        self.activity = activity
        self._kill, self._info, self._pids, self._job_usage = kill, info, pids, job_usage
        self._release, self._reload_ui, self._quit_app = release, reload_ui, quit_app
        self._recycle = recycle
        self._last_check = None      # monotonic time runs on while the PC sleeps: a long gap means it woke up
        self._clock, self._visible = clock, visible
        self._names = names
        self._last_beat = clock()
        self._shown_at = clock()
        self._armed = False          # no misses until the page's first heartbeat (or FIRST_BEAT_MAX)
        self._page_visible = True    # the page says whether it is really on screen (not minimized)
        self._last_release = None
        self._miss_at = None
        self._kills = {}             # kind -> times it was killed
        self._blocked = {}           # kind -> not before this time
        self._lock = threading.Lock()

    def beat(self):
        self._last_beat = self._clock()
        self._armed = True

    def window_shown(self):
        """The window just came back: the page gets a full BEAT_MISS from now before a miss counts."""
        self._last_beat = self._shown_at = self._clock()

    def page_visible(self, on):
        """The page reports document.visibilityState (hidden while minimized: it sends no heartbeats then)."""
        was, self._page_visible = self._page_visible, bool(on)
        if self._page_visible and not was:
            self.window_shown()

    def check(self):
        now = self._clock()
        woke = self._last_check is not None and now - self._last_check > 3 * BEAT_MISS
        self._last_check = now
        steps = [self._check_workers, self._check_job]
        if woke:
            self.window_shown()      # the PC slept: the page gets a fresh wait, its search is not reloaded away
        else:
            steps.append(self._check_heartbeat)
        for step in steps:
            try:
                step()
            except Exception as e:
                log(f"watchdog step failed: {type(e).__name__}", "warn")

    def _check_workers(self):
        me = os.getpid()
        for pid in list(self._pids()):
            if pid == me:
                continue
            mb = (self._info(pid) or {}).get("memory_mb", 0)
            if mb <= WORKER_MB:
                continue
            kind = self._names().get(pid, "background worker")
            now = self._clock()
            if now < self._blocked.get(kind, 0):
                continue
            self._kill(pid)
            if kind == "text reader":
                self.activity.add("kill", f"Stopped a text reader using {_size(mb)}; the file is skipped")
            else:
                the = "a" if kind == "background worker" else "the"
                self.activity.add("kill", f"Stopped {the} {kind} using {_size(mb)}; it starts again")
            times = [t for t in self._kills.get(kind, []) if now - t <= KILL_WINDOW] + [now]
            self._kills[kind] = times
            if len(times) >= 2:
                self._blocked[kind] = now + KILL_PAUSE
                self._kills[kind] = []
                self.activity.add("info", f"The {kind} grew too big twice in 10 minutes, so it is left alone "
                                          "for 30 minutes")

    def _check_job(self):
        if self._job_usage().get("memory_mb", 0) <= JOB_MB:
            return
        now = self._clock()
        if self._last_release is not None and now - self._last_release < RELEASE_EVERY:
            return
        self._last_release = now
        self._release()
        self._recycle()
        self.activity.add("model", "NOBAD Find is using a lot of memory, so it let go of its search models "
                                   "and restarts its workers")

    def _spawn(self, fn):
        """Reload and quit touch the page or window and can hang: never on the caller's thread."""
        def run():
            try:
                fn()
            except Exception as e:
                log(f"watchdog action failed: {type(e).__name__}", "warn")
        threading.Thread(target=run, daemon=True, name="watchdog-action").start()

    def _check_heartbeat(self):
        if not self._visible() or not self._page_visible:
            return
        now = self._clock()
        if self._armed:
            if now - self._last_beat < BEAT_MISS:
                return
        elif now - self._shown_at < FIRST_BEAT_MAX:
            return
        self._last_beat = self._shown_at = now          # a fresh wait before the next miss
        self._armed = False                             # the page must send a first heartbeat again
        if self._miss_at is not None and now - self._miss_at <= QUIT_WITHIN:
            self.activity.add("info", "NOBAD Find's window stopped responding again, so it is closing")
            self._spawn(self._quit_app)
            return
        self._miss_at = now
        self.activity.add("info", "NOBAD Find's window stopped responding, so it was reloaded")
        self._spawn(self._reload_ui)
