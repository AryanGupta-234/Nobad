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


def background_mode(on=True):
    """Lower this process's CPU, disk and memory priority (Windows background mode), or end it (on=False)."""
    if WIN:
        try:
            k32.SetPriorityClass(k32.GetCurrentProcess(), 0x00100000 if on else 0x00200000)  # _BEGIN / _END
        except Exception:
            pass


# ---------- drives ----------
KNOWN_FOLDERS = {   # Windows' own ids for the user's folders (they follow OneDrive and "move this folder")
    "downloads": "{374DE290-123F-4565-9164-39C4925E467B}", "desktop": "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}",
    "documents": "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}", "pictures": "{33E28130-4E1E-4676-835A-98395C3BC3BB}",
    "videos": "{18989B1D-99B5-455B-841C-AB7C74E4DDFC}", "music": "{4BD8D571-6D19-48D3-BE97-422220080E43}",
}
_known_cache = {}


def known_folder(name):
    """The real path of one of the user's folders ('downloads', 'desktop', ...), or '' if Windows has none."""
    if name in _known_cache:
        return _known_cache[name]
    path = ""
    if WIN and name in KNOWN_FOLDERS:
        import uuid

        class GUID(ctypes.Structure):
            _fields_ = [("b", ctypes.c_byte * 16)]
        g = GUID()
        ctypes.memmove(g.b, uuid.UUID(KNOWN_FOLDERS[name]).bytes_le, 16)
        out = ctypes.c_wchar_p()
        ole32 = ctypes.WinDLL("ole32")
        if shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(out)) == 0:
            path = out.value or ""
        ole32.CoTaskMemFree(out)
    elif name in KNOWN_FOLDERS:
        path = os.path.join(os.path.expanduser("~"), name.capitalize())
    _known_cache[name] = path
    return path


def _window_class(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(wintypes.HWND(hwnd), buf, 256)
    return buf.value


def _window_title(hwnd):
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(wintypes.HWND(hwnd), buf, 512)
    return buf.value


def foreground_window():
    if not WIN:
        return 0
    user32.GetForegroundWindow.restype = wintypes.HWND
    return user32.GetForegroundWindow() or 0


def window_pid(hwnd):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
    return pid.value


def foreground_folder(hwnd=None):
    """The folder the user is looking at right now: the active File Explorer window's folder, or the Desktop
    folder when the desktop is in front. '' for anything else (a browser, a game, ...).

    Asks Windows' Shell which folder each Explorer window shows (the same list the taskbar uses). Read only."""
    if not WIN:
        return ""
    user32.GetForegroundWindow.restype = wintypes.HWND
    hwnd = hwnd or user32.GetForegroundWindow()
    if not hwnd:
        return ""
    cls = _window_class(hwnd)
    if cls in ("Progman", "WorkerW"):
        return known_folder("desktop")
    if cls not in ("CabinetWClass", "ExploreWClass"):
        return ""
    title = _window_title(hwnd)
    try:
        import importlib
        importlib.import_module("clr")              # pythonnet, already loaded by the window library
        from System import Activator, Int32, Type
        from System.Reflection import BindingFlags

        def get(obj, name):
            return obj.GetType().InvokeMember(name, BindingFlags.GetProperty, None, obj, None)
        shell = Activator.CreateInstance(Type.GetTypeFromProgID("Shell.Application"))
        wins = shell.GetType().InvokeMember("Windows", BindingFlags.InvokeMethod, None, shell, None)
        tabs = []
        for i in range(int(get(wins, "Count"))):
            w = wins.GetType().InvokeMember("Item", BindingFlags.InvokeMethod, None, wins, [Int32(i)])
            if w is None or int(get(w, "HWND")) != int(hwnd):
                continue
            path = str(get(get(get(get(w, "Document"), "Folder"), "Self"), "Path") or "")
            name = str(get(w, "LocationName") or "")
            if os.path.isabs(path):
                tabs.append((name, path))
        # Windows 11 has tabs: every tab is listed with the same window; the window title is the active tab's
        for name, path in tabs:
            if name and (title == name or title.startswith(name + " - ")):
                return path
        return tabs[0][1] if tabs else ""
    except Exception as e:                       # no folder then; the log keeps the reason
        from .log import log
        log(f"couldn't read the File Explorer folder: {type(e).__name__}", "warn")
        return ""


def own_window(title):
    """The handle of this process's top-level window with this title (0 if none yet)."""
    if not WIN:
        return 0
    found = []
    pid = os.getpid()
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def each(h, _l):
        if window_pid(h) == pid and _window_title(h) == title:
            found.append(h)
            return False
        return True
    user32.EnumWindows(proc(each), 0)
    return found[0] if found else 0


def transparency_allowed():
    """Windows' own "Transparency effects" switch (Settings > Personalization > Colors)."""
    if not WIN:
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return bool(winreg.QueryValueEx(k, "EnableTransparency")[0])
    except OSError:
        return True


class _MARGINS(ctypes.Structure):
    _fields_ = [("l", ctypes.c_int), ("r", ctypes.c_int), ("t", ctypes.c_int), ("b", ctypes.c_int)]


def glass(hwnd):
    """Windows 11 acrylic behind the whole window, dark title bar. True if Windows took it (22H2 and later)."""
    if not WIN or not hwnd:
        return False
    try:
        dwm = ctypes.WinDLL("dwmapi")
        h = wintypes.HWND(hwnd)
        dark = ctypes.c_int(1)
        dwm.DwmSetWindowAttribute(h, 20, ctypes.byref(dark), 4)              # DWMWA_USE_IMMERSIVE_DARK_MODE
        backdrop = ctypes.c_int(3)                                           # DWMSBT_TRANSIENTWINDOW (acrylic)
        if dwm.DwmSetWindowAttribute(h, 38, ctypes.byref(backdrop), 4) != 0:  # DWMWA_SYSTEMBACKDROP_TYPE
            return False
        m = _MARGINS(-1, -1, -1, -1)                                          # the backdrop fills the client area
        return dwm.DwmExtendFrameIntoClientArea(h, ctypes.byref(m)) == 0
    except Exception:
        return False


class _PMC(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t)]


def memory_mb():
    """This process's memory in use right now (working set), in MB."""
    if not WIN:
        return 0
    pmc = _PMC()
    pmc.cb = ctypes.sizeof(_PMC)
    psapi = ctypes.WinDLL("psapi")
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
    if not psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
        return 0
    return round(pmc.WorkingSetSize / 1048576)


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


DRIVE_TYPES = {2: "removable", 3: "fixed", 4: "network", 5: "cd", 6: "ram"}


def drives():
    """Every drive letter Windows shows this user: [{'root': 'E:\\', 'type': 'removable', 'label': 'SANDISK'}]."""
    if not WIN:
        return [{"root": "/", "type": "fixed", "label": ""}]
    mask = k32.GetLogicalDrives()
    out = []
    old = k32.SetErrorMode(0x0001)          # SEM_FAILCRITICALERRORS: an empty card reader must not pop a dialog
    try:
        for i in range(26):
            if not mask & (1 << i):
                continue
            root = f"{chr(65 + i)}:\\"
            kind = DRIVE_TYPES.get(k32.GetDriveTypeW(root))
            if not kind:
                continue
            label = ctypes.create_unicode_buffer(261)
            # a network drive whose server is off can block for seconds here: its name isn't worth that
            ok = kind != "network" and k32.GetVolumeInformationW(root, label, 261, None, None, None, None, 0)
            if kind in ("removable", "cd") and not ok:
                continue                          # no disc or card in it
            out.append({"root": root, "type": kind, "label": label.value if ok else ""})
    finally:
        k32.SetErrorMode(old)
    return out


def running_exes():
    """Lower-case full paths of the programs running right now (those this user may look at)."""
    if not WIN:
        return set()
    psapi = ctypes.WinDLL("psapi")
    ids = (wintypes.DWORD * 4096)()
    got = wintypes.DWORD()
    if not psapi.EnumProcesses(ids, ctypes.sizeof(ids), ctypes.byref(got)):
        return set()
    out = set()
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                               ctypes.POINTER(wintypes.DWORD)]
    for pid in ids[:got.value // ctypes.sizeof(wintypes.DWORD)]:
        h = k32.OpenProcess(0x1000, False, pid)            # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            continue
        try:
            buf = ctypes.create_unicode_buffer(1024)
            n = wintypes.DWORD(1024)
            if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                out.add(buf.value.lower())
        finally:
            k32.CloseHandle(h)
    return out


CALL_MAX_AGE = 4 * 3600          # older "still in use" records are left over from an app that crashed


def in_call(now=None):
    """True while an app is using the microphone or the camera (a call or a recording).

    Reads the user's own privacy "last used" records, the same ones the Windows privacy page shows. No admin.
    An app that crashes leaves its record "in use" forever, so a record only counts when it started in the last
    few hours and, for desktop programs, when that program is still running."""
    if not WIN:
        return False
    import time
    import winreg
    base = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore"
    now_ft = int(((now or time.time()) + 11644473600) * 10_000_000)       # unix seconds -> FILETIME
    procs = []

    def alive(path):
        name = path.rsplit("\\", 1)[-1]
        if "\\NonPackaged\\" not in path:
            return True                                 # Store apps: the age check is all we have
        if not procs:
            procs.append(running_exes())
        return name.replace("#", "\\").lower() in procs[0]

    def busy(path, depth=0):
        try:
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path)
        except OSError:
            return False
        with k:
            try:
                start = winreg.QueryValueEx(k, "LastUsedTimeStart")[0]
                stop = winreg.QueryValueEx(k, "LastUsedTimeStop")[0]
                if start and not stop and 0 <= now_ft - start < CALL_MAX_AGE * 10_000_000 and alive(path):
                    return True
            except (OSError, TypeError):
                pass
            if depth >= 2:
                return False
            i = 0
            while i < 500:
                try:
                    sub = winreg.EnumKey(k, i)
                except OSError:
                    break
                if busy(path + "\\" + sub, depth + 1):
                    return True
                i += 1
        return False

    return any(busy(f"{base}\\{dev}") for dev in ("microphone", "webcam"))


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
