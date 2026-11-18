"""The watchdog ends NOBAD Find's OWN stuck or runaway work. It never touches another app.

- a text-reader worker over WORKER_MB is ended (the indexer treats it as a crashed reader and skips the file);
- all of Find's processes together over JOB_MB: the models are released (at most once per 5 minutes);
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
    if h:
        try:
            k.TerminateProcess(h, 1)
        finally:
            k.CloseHandle(h)


def _size(mb):
    return f"{mb / 1024:.1f} GB" if mb >= 1024 else f"{int(mb)} MB"


class Watchdog:
    def __init__(self, activity, kill=kill_process, info=_jobs.process_info,
                 pids=lambda: _jobs.WORKERS.pids() if _jobs.WORKERS else [],
                 job_usage=lambda: _jobs.OUTER.usage() if _jobs.OUTER else {"memory_mb": 0},
                 release=lambda: None, reload_ui=lambda: None, quit_app=lambda: None,
                 clock=time.monotonic, visible=lambda: True):
        self.activity = activity
        self._kill, self._info, self._pids, self._job_usage = kill, info, pids, job_usage
        self._release, self._reload_ui, self._quit_app = release, reload_ui, quit_app
        self._clock, self._visible = clock, visible
        self._last_beat = clock()
        self._last_release = None
        self._miss_at = None
        self._lock = threading.Lock()

    def beat(self):
        self._last_beat = self._clock()

    def window_shown(self):
        """The window just came back: the page gets a full BEAT_MISS from now before a miss counts."""
        self._last_beat = self._clock()

    def check(self):
        for step in (self._check_workers, self._check_job, self._check_heartbeat):
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
            if mb > WORKER_MB:
                self._kill(pid)
                self.activity.add("kill", f"Stopped a text reader using {_size(mb)}; the file is skipped")

    def _check_job(self):
        if self._job_usage().get("memory_mb", 0) <= JOB_MB:
            return
        now = self._clock()
        if self._last_release is not None and now - self._last_release < RELEASE_EVERY:
            return
        self._last_release = now
        self._release()
        self.activity.add("model", "NOBAD Find is using a lot of memory, so it let go of its search models")

    def _check_heartbeat(self):
        if not self._visible():
            return
        now = self._clock()
        if now - self._last_beat < BEAT_MISS:
            return
        self._last_beat = now                           # a fresh BEAT_MISS before the next miss
        if self._miss_at is not None and now - self._miss_at <= QUIT_WITHIN:
            self.activity.add("info", "NOBAD Find's window stopped responding again, so it is closing")
            self._quit_app()
            return
        self._miss_at = now
        self.activity.add("info", "NOBAD Find's window stopped responding, so it was reloaded")
        self._reload_ui()
