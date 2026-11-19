"""This process's memory and priorities through ctypes, for tests that start a fresh Python (no psutil in CI)."""
import ctypes
from ctypes import wintypes

IDLE_PRIORITY_CLASS, NORMAL_PRIORITY_CLASS = 0x40, 0x20


class _PMC(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t)]


def _k():
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.GetCurrentProcess.restype = wintypes.HANDLE
    k.GetPriorityClass.argtypes = [wintypes.HANDLE]
    k.GetProcessInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    return k


def _pmc():
    k, ps = _k(), ctypes.WinDLL("psapi")
    ps.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
    m = _PMC()
    m.cb = ctypes.sizeof(m)
    ps.GetProcessMemoryInfo(k.GetCurrentProcess(), ctypes.byref(m), m.cb)
    return m


def private_bytes():
    return _pmc().PagefileUsage


def working_set():
    return _pmc().WorkingSetSize


def priority_class():
    k = _k()
    return k.GetPriorityClass(k.GetCurrentProcess())


def memory_priority():
    k = _k()
    m = wintypes.ULONG()
    k.GetProcessInformation(k.GetCurrentProcess(), 0, ctypes.byref(m), 4)       # ProcessMemoryPriority
    return m.value


def io_priority():
    k, nt = _k(), ctypes.WinDLL("ntdll")
    nt.NtQueryInformationProcess.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.ULONG,
                                             ctypes.c_void_p]
    v = wintypes.ULONG()
    nt.NtQueryInformationProcess(k.GetCurrentProcess(), 33, ctypes.byref(v), 4, None)    # ProcessIoPriority
    return v.value
