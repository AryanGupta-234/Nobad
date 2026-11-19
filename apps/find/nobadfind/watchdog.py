"""The watchdog ends NOBAD Find's OWN stuck or runaway work. It never touches another app.

- a text-reader worker over WORKER_MB is ended (the indexer treats it as a crashed reader and skips the file);
- all of Find's processes together over JOB_MB: the models are released and the worker processes start
  fresh (at most once per 5 minutes).
A UI that stops answering is the UI's own process: the engine notices it by its pipe closing (rpc), not here.
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
                 release=lambda: None, clock=time.monotonic, names=lambda: {}, recycle=lambda: None):
        self.activity = activity
        self._kill, self._info, self._pids, self._job_usage = kill, info, pids, job_usage
        self._release, self._recycle = release, recycle
        self._clock = clock
        self._names = names
        self._last_release = None
        self._miss_at = None
        self._kills = {}             # kind -> times it was killed
        self._blocked = {}           # kind -> not before this time
        self._lock = threading.Lock()

    def check(self):
        for step in (self._check_workers, self._check_job):
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
