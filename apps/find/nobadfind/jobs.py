"""Windows job objects: no NOBAD Find process outlives the app, and background workers can be CPU-capped.

OUTER holds the main process (and so every child); WORKERS is a nested, named job the pool workers join."""
import ctypes
import os
from ctypes import wintypes

from . import winapi
from .log import log

WORKERS_PREFIX = "Local\\NOBADFind-workers-"
MAIN_PID_ENV = "NOBAD_FIND_MAIN_PID"

_KILL_ON_JOB_CLOSE = 0x2000
_JOB_MEMORY = 0x200            # JOB_OBJECT_LIMIT_JOB_MEMORY: committed memory of the whole job
_BREAKAWAY_OK = 0x800          # JOB_OBJECT_LIMIT_BREAKAWAY_OK: a child that asks may start outside the job
_CPU_ENABLE, _CPU_HARD_CAP = 0x1, 0x4
_PROCESS_TERMINATE_SET_QUOTA = 0x0001 | 0x0100
_QUERY_LIMITED = 0x1000
_JOB_ALL_ACCESS = 0x1F001F
_CLS_PIDS, _CLS_ACCOUNTING, _CLS_EXTENDED, _CLS_CPU_RATE = 3, 8, 9, 15

OUTER = None
WORKERS = None

if winapi.WIN:
    _k = ctypes.WinDLL("kernel32", use_last_error=True)      # own instance: argtypes here don't leak elsewhere
    _psapi = ctypes.WinDLL("psapi", use_last_error=True)
    _H, _D, _P = wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p
    _k.CreateJobObjectW.restype = _H
    _k.CreateJobObjectW.argtypes = [_P, wintypes.LPCWSTR]
    _k.OpenJobObjectW.restype = _H
    _k.OpenJobObjectW.argtypes = [_D, wintypes.BOOL, wintypes.LPCWSTR]
    _k.AssignProcessToJobObject.argtypes = [_H, _H]
    _k.SetInformationJobObject.argtypes = [_H, ctypes.c_int, _P, _D]
    _k.QueryInformationJobObject.argtypes = [_H, ctypes.c_int, _P, _D, _P]
    _k.OpenProcess.restype = _H
    _k.OpenProcess.argtypes = [_D, wintypes.BOOL, _D]
    _k.GetCurrentProcess.restype = _H
    _k.CloseHandle.argtypes = [_H]
    _k.GetProcessTimes.argtypes = [_H, _P, _P, _P, _P]
    _psapi.GetProcessMemoryInfo.argtypes = [_H, _P, _D]


class _IO(ctypes.Structure):
    _fields_ = [(n, ctypes.c_ulonglong) for n in ("ReadOps", "WriteOps", "OtherOps", "ReadBytes", "WriteBytes", "OtherBytes")]


class _Accounting(ctypes.Structure):
    _fields_ = [("TotalUser", ctypes.c_longlong), ("TotalKernel", ctypes.c_longlong),
                ("PeriodUser", ctypes.c_longlong), ("PeriodKernel", ctypes.c_longlong),
                ("PageFaults", wintypes.DWORD), ("TotalProcesses", wintypes.DWORD),
                ("ActiveProcesses", wintypes.DWORD), ("TerminatedProcesses", wintypes.DWORD), ("Io", _IO)]


class _Basic(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD), ("MinWS", ctypes.c_size_t), ("MaxWS", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD), ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]


class _Extended(ctypes.Structure):
    _fields_ = [("Basic", _Basic), ("Io", _IO), ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemory", ctypes.c_size_t),
                ("PeakJobMemory", ctypes.c_size_t)]


class _CpuRate(ctypes.Structure):
    _fields_ = [("ControlFlags", wintypes.DWORD), ("CpuRate", wintypes.DWORD)]


class _PMC(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t)]


_MAX_PIDS = 512


class _PidList(ctypes.Structure):
    _fields_ = [("Assigned", wintypes.DWORD), ("InList", wintypes.DWORD), ("Pids", ctypes.c_size_t * _MAX_PIDS)]


def process_info(pid):
    """{"pid", "cpu_seconds", "memory_mb"} for one process; zeros when it can't be read."""
    out = {"pid": int(pid), "cpu_seconds": 0.0, "memory_mb": 0}
    if not winapi.WIN:
        return out
    h = _k.OpenProcess(_QUERY_LIMITED, False, int(pid))
    if not h:
        return out
    try:
        ft = [ctypes.c_ulonglong() for _ in range(4)]
        if _k.GetProcessTimes(h, *[ctypes.byref(f) for f in ft]):
            out["cpu_seconds"] = (ft[2].value + ft[3].value) / 1e7      # kernel + user, 100 ns units
        pmc = _PMC()
        pmc.cb = ctypes.sizeof(_PMC)
        if _psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb):
            out["memory_mb"] = round(pmc.WorkingSetSize / 1048576)
    finally:
        _k.CloseHandle(h)
    return out


class Job:
    def __init__(self, name=None, kill_on_close=True, breakaway=False):
        """breakaway: a process started with CREATE_BREAKAWAY_FROM_JOB may leave the job. Only OUTER has it, so
        the program a file opens in outlives Find. Never the silent kind: workers and WebView2 stay inside."""
        self.handle = None
        if not winapi.WIN:
            return
        h = _k.CreateJobObjectW(None, name)
        if not h:
            log("could not create a process group (error %d)" % ctypes.get_last_error())
            return
        self.handle = h
        if kill_on_close:
            info = _Extended()
            info.Basic.LimitFlags = _KILL_ON_JOB_CLOSE | (_BREAKAWAY_OK if breakaway else 0)
            if not _k.SetInformationJobObject(h, _CLS_EXTENDED, ctypes.byref(info), ctypes.sizeof(info)):
                log("could not set close-with-app on a process group (error %d)" % ctypes.get_last_error())

    def _assign_handle(self, ph):
        ok = bool(_k.AssignProcessToJobObject(self.handle, ph))
        if not ok:
            log("could not add a process to its group (error %d)" % ctypes.get_last_error())
        return ok

    def assign_self(self):
        if self.handle:
            self._assign_handle(_k.GetCurrentProcess())

    def assign(self, pid):
        if not self.handle:
            return False
        ph = _k.OpenProcess(_PROCESS_TERMINATE_SET_QUOTA, False, int(pid))
        if not ph:
            return False
        try:
            return self._assign_handle(ph)
        finally:
            _k.CloseHandle(ph)

    def set_memory_limit(self, mb):
        """A hard limit on the memory the whole group commits: past it, allocations in its processes fail.
        Keeps the other limits (close-with-app). True on success."""
        if not self.handle:
            return False
        info = _Extended()
        if not _k.QueryInformationJobObject(self.handle, _CLS_EXTENDED, ctypes.byref(info), ctypes.sizeof(info), None):
            return False
        info.Basic.LimitFlags |= _JOB_MEMORY
        info.JobMemoryLimit = int(mb) * 1024 * 1024
        if not _k.SetInformationJobObject(self.handle, _CLS_EXTENDED, ctypes.byref(info), ctypes.sizeof(info)):
            log("could not set the background memory limit (error %d)" % ctypes.get_last_error())
            return False
        return True

    def set_cpu_cap(self, percent):
        """Hard-cap the whole group at percent of all CPU time; None lifts the cap. True on success."""
        if not self.handle:
            return False
        info = _CpuRate()
        if percent is not None:
            info.ControlFlags = _CPU_ENABLE | _CPU_HARD_CAP
            info.CpuRate = max(1, min(100, int(percent))) * 100
        if not _k.SetInformationJobObject(self.handle, _CLS_CPU_RATE, ctypes.byref(info), ctypes.sizeof(info)):
            log("could not change the background CPU limit (error %d)" % ctypes.get_last_error())
            return False
        return True

    def cpu_cap(self):
        """The cap now in force as a percent, or None when there is none."""
        if not self.handle:
            return None
        info = _CpuRate()
        if not _k.QueryInformationJobObject(self.handle, _CLS_CPU_RATE, ctypes.byref(info), ctypes.sizeof(info), None):
            return None
        if info.ControlFlags & _CPU_ENABLE and info.ControlFlags & _CPU_HARD_CAP:
            return info.CpuRate // 100
        return None

    def pids(self):
        if not self.handle:
            return []
        lst = _PidList()
        if not _k.QueryInformationJobObject(self.handle, _CLS_PIDS, ctypes.byref(lst), ctypes.sizeof(lst), None):
            return []
        return [int(p) for p in lst.Pids[:lst.InList]]

    def usage(self):
        out = {"cpu_seconds": 0.0, "read_bytes": 0, "write_bytes": 0, "memory_mb": 0, "processes": 0}
        if not self.handle:
            return out
        acc = _Accounting()
        if _k.QueryInformationJobObject(self.handle, _CLS_ACCOUNTING, ctypes.byref(acc), ctypes.sizeof(acc), None):
            out["cpu_seconds"] = (acc.TotalUser + acc.TotalKernel) / 1e7
            out["read_bytes"] = acc.Io.ReadBytes
            out["write_bytes"] = acc.Io.WriteBytes
        pids = self.pids()
        out["processes"] = len(pids)
        out["memory_mb"] = sum(process_info(p)["memory_mb"] for p in pids)
        return out

    def close(self):
        h, self.handle = self.handle, None
        if h:
            _k.CloseHandle(h)


def worker_memory_limit_mb(total_mb):
    """The worker group's hard memory limit: a quarter of the PC's memory, 1-4 GB. A backstop above the watchdog
    (watchdog.JOB_MB, working set) for a reader or model gone wrong; normal work commits far less
    (docs/measurements.md)."""
    return max(1024, min(4096, int(total_mb) // 4))


def setup():
    """Main process, once at start: everything Find starts from here on dies with the app."""
    global OUTER, WORKERS
    if not winapi.WIN or OUTER is not None:
        return
    os.environ[MAIN_PID_ENV] = str(os.getpid())
    OUTER = Job(breakaway=True)         # files opened from Find start outside it (winapi.open_outside_job)
    OUTER.assign_self()
    WORKERS = Job(WORKERS_PREFIX + str(os.getpid()))
    total = winapi.memory_status_total_mb()
    if total:
        WORKERS.set_memory_limit(worker_memory_limit_mb(total))


def join_workers():
    """Pool-worker initializer: move this process into the main process's WORKERS job (no-op if missing)."""
    if not winapi.WIN:
        return
    try:
        h = _k.OpenJobObjectW(_JOB_ALL_ACCESS, False, WORKERS_PREFIX + os.environ.get(MAIN_PID_ENV, ""))
        if not h:
            return
        try:
            _k.AssignProcessToJobObject(h, _k.GetCurrentProcess())
        finally:
            _k.CloseHandle(h)
    except Exception:
        pass
