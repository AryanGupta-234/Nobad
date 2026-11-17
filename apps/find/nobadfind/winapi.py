"""Small Windows API wrappers (ctypes only; nothing here builds a shell string)."""
import ctypes
import os
import subprocess
import sys
from ctypes import wintypes

WIN = sys.platform == "win32"
if WIN:
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)


INVALID_HANDLE = ctypes.c_void_p(-1).value


def is_admin():
    try:
        return bool(shell32.IsUserAnAdmin()) if WIN else os.geteuid() == 0
    except Exception:
        return False


# ---------- DPAPI: protects the index key with the user's Windows login ----------
class _BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data):
    buf = ctypes.create_string_buffer(data, len(data))
    return _BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def _crypt(fn, data):
    src, _keep = _blob(data)
    out = _BLOB()
    if not fn(ctypes.byref(src), None, None, None, None, 0x1, ctypes.byref(out)):   # CRYPTPROTECT_UI_FORBIDDEN
        raise OSError(ctypes.get_last_error(), "DPAPI failed")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        k32.LocalFree(out.pbData)


def dpapi_protect(data: bytes) -> bytes:
    return _crypt(crypt32.CryptProtectData, data)


def dpapi_unprotect(data: bytes) -> bytes:
    return _crypt(crypt32.CryptUnprotectData, data)


# ---------- one-shot elevation (UAC prompt) for a helper with fixed arguments ----------
class _SEI(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
                ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
                ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                ("dwHotKey", wintypes.DWORD), ("hIcon", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]


def self_command(*args):
    """argv that starts this app again with extra arguments (frozen exe or python -m nobadfind)."""
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    return [sys.executable, "-I", "-m", "nobadfind", *args]


def run_elevated(argv, wait=True, timeout_ms=10 * 60 * 1000):
    """Start argv elevated (UAC). Returns the exit code, or None if the user said no."""
    sei = _SEI()
    sei.cbSize = ctypes.sizeof(sei)
    sei.fMask = 0x40 | 0x400            # SEE_MASK_NOCLOSEPROCESS | SEE_MASK_FLAG_NO_UI
    sei.lpVerb = "runas"
    sei.lpFile = argv[0]
    sei.lpParameters = subprocess.list2cmdline(argv[1:])
    # python -m nobadfind needs the folder that holds the package as its working directory
    sei.lpDirectory = None if getattr(sys, "frozen", False) else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sei.nShow = 0
    if not shell32.ShellExecuteExW(ctypes.byref(sei)):
        return None                     # cancelled at the UAC prompt
    if not wait:
        k32.CloseHandle(sei.hProcess)
        return 0
    k32.WaitForSingleObject(sei.hProcess, timeout_ms)
    code = wintypes.DWORD()
    k32.GetExitCodeProcess(sei.hProcess, ctypes.byref(code))
    k32.CloseHandle(sei.hProcess)
    return code.value


# ---------- what the PC is doing (to stay out of the way) ----------
class _SPS(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_byte), ("BatteryFlag", ctypes.c_byte), ("BatteryLifePercent", ctypes.c_byte),
                ("SystemStatusFlag", ctypes.c_byte), ("BatteryLifeTime", wintypes.DWORD),
                ("BatteryFullLifeTime", wintypes.DWORD)]


def on_battery():
    if not WIN:
        return False
    s = _SPS()
    return bool(k32.GetSystemPowerStatus(ctypes.byref(s))) and s.ACLineStatus == 0


def busy_fullscreen():
    """True during a full-screen game, a presentation or 'quiet time'."""
    if not WIN:
        return False
    state = ctypes.c_int()
    try:
        if shell32.SHQueryUserNotificationState(ctypes.byref(state)) != 0:
            return False
    except Exception:
        return False
    return state.value in (2, 3, 4)      # QUNS_BUSY, QUNS_RUNNING_D3D_FULL_SCREEN, QUNS_PRESENTATION_MODE


class _LII(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def idle_seconds():
    if not WIN:
        return 0
    lii = _LII(ctypes.sizeof(_LII), 0)
    if not user32.GetLastInputInfo(ctypes.byref(lii)):
        return 0
    return max(0, (k32.GetTickCount() - lii.dwTime) & 0xFFFFFFFF) / 1000.0


def background_mode():
    """Lower this process's CPU, disk and memory priority (Windows background mode)."""
    if WIN:
        try:
            k32.SetPriorityClass(k32.GetCurrentProcess(), 0x00100000)   # PROCESS_MODE_BACKGROUND_BEGIN
        except Exception:
            pass


# ---------- drives ----------
def fixed_drives():
    """Fixed local drives, e.g. ['C:\\', 'D:\\']."""
    if not WIN:
        return ["/"]
    mask = k32.GetLogicalDrives()
    out = []
    for i in range(26):
        if mask & (1 << i):
            root = f"{chr(65 + i)}:\\"
            if k32.GetDriveTypeW(root) == 3:     # DRIVE_FIXED
                out.append(root)
    return out


def filesystem(root):
    if not WIN:
        return ""
    name = ctypes.create_unicode_buffer(64)
    ok = k32.GetVolumeInformationW(root, None, 0, None, None, None, name, 64)
    return name.value if ok else ""


class _SPQ(ctypes.Structure):
    _fields_ = [("PropertyId", ctypes.c_int), ("QueryType", ctypes.c_int), ("Extra", ctypes.c_byte * 1)]


class _DSP(ctypes.Structure):
    _fields_ = [("Version", wintypes.DWORD), ("Size", wintypes.DWORD), ("IncursSeekPenalty", ctypes.c_bool)]


def is_ssd(root):
    """True for SSDs, False for spinning disks, None if Windows can't tell. Works without admin."""
    if not WIN:
        return None
    h = k32.CreateFileW(f"\\\\.\\{root[:2]}", 0, 3, None, 3, 0, None)
    if not h or h == INVALID_HANDLE:
        return None
    try:
        q = _SPQ(7, 0)                       # StorageDeviceSeekPenaltyProperty, PropertyStandardQuery
        out = _DSP()
        n = wintypes.DWORD()
        ok = k32.DeviceIoControl(wintypes.HANDLE(h), 0x2D1400, ctypes.byref(q), ctypes.sizeof(q),
                                 ctypes.byref(out), ctypes.sizeof(out), ctypes.byref(n), None)
        return (not out.IncursSeekPenalty) if ok else None
    finally:
        k32.CloseHandle(wintypes.HANDLE(h))


k32_types_set = False


def _set_types():
    global k32_types_set
    if not WIN or k32_types_set:
        return
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                wintypes.DWORD, wintypes.HANDLE]
    k32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                    ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    k32.DeviceIoControl.restype = wintypes.BOOL
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.LocalFree.argtypes = [ctypes.c_void_p]
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    crypt32.CryptProtectData.argtypes = crypt32.CryptUnprotectData.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
        ctypes.c_void_p]
    k32_types_set = True


_set_types()
