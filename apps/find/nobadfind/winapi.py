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

SHOW_EVENT = "Local\\NOBAD-Find-Show"         # a second start asks the running copy to show its window


def show_event():
    """The running copy's auto-reset "show the window" event (None off Windows or on failure)."""
    if not WIN:
        return None
    k32.CreateEventW.restype = ctypes.c_void_p
    return k32.CreateEventW(None, False, False, SHOW_EVENT) or None


def wait_event(handle, timeout_ms):
    """True when the event was signalled within the timeout."""
    k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    return k32.WaitForSingleObject(handle, timeout_ms) == 0          # WAIT_OBJECT_0


def ask_running_copy_to_show():
    """Signal the copy that is already running to bring its window up. True if it was reached."""
    if not WIN:
        return False
    k32.OpenEventW.restype = ctypes.c_void_p
    h = k32.OpenEventW(0x0002, False, SHOW_EVENT)                     # EVENT_MODIFY_STATE
    if not h:
        return False
    try:
        user32.AllowSetForegroundWindow(wintypes.DWORD(0xFFFFFFFF))  # ASFW_ANY: it may take the front
        k32.SetEvent.argtypes = [ctypes.c_void_p]
        return bool(k32.SetEvent(h))
    finally:
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        k32.CloseHandle(h)


def message(text, title="NOBAD Find"):
    """A plain message box: the packaged app has no console, so print() would show nothing."""
    if not WIN:
        print(text)
        return
    user32.MessageBoxW(None, text, title, 0x40)                     # MB_ICONINFORMATION


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


CREATE_BREAKAWAY_FROM_JOB = 0x01000000


def open_outside_job(path):
    """Open a file in its default program, from outside NOBAD Find's job: the program (and its unsaved work)
    must keep running when Find quits or crashes, and must not count as Find's own use. explorer.exe starts
    with CREATE_BREAKAWAY_FROM_JOB and an argument list (no shell string) and hands the file to the running
    desktop shell, so the program gets the shell's environment, not Find's. Raises OSError when Windows
    refuses the breakaway (the caller falls back to os.startfile)."""
    explorer = os.path.join(os.environ.get("WINDIR") or "C:\\Windows", "explorer.exe")
    return subprocess.Popen([explorer, path], creationflags=CREATE_BREAKAWAY_FROM_JOB, close_fds=True)


def start_outside_job(argv):
    """Start a program of Find's own (the UI, the Open with helper) outside Find's job, as the normal user:
    an argument list, never a shell string. Raises OSError when Windows refuses the breakaway."""
    return subprocess.Popen(list(argv), creationflags=CREATE_BREAKAWAY_FROM_JOB, close_fds=True)


OAIF_EXEC = 0x4                 # run the program the user picks (never changes the default: no OAIF_REGISTER_EXT)


class _OpenAsInfo(ctypes.Structure):
    _fields_ = [("pcszFile", wintypes.LPCWSTR), ("pcszClass", wintypes.LPCWSTR), ("oaifInFlags", wintypes.DWORD)]


def open_with_dialog(path):
    """Windows' "Open with" picker for one file, in this (helper) process. 0 when it opened, else 1."""
    if not WIN:
        return 1
    sh = ctypes.WinDLL("shell32")
    sh.SHOpenWithDialog.argtypes = [wintypes.HWND, ctypes.POINTER(_OpenAsInfo)]
    sh.SHOpenWithDialog.restype = ctypes.c_long
    ole = ctypes.WinDLL("ole32")
    ole.CoInitializeEx(None, 0x2)                       # apartment threaded, as shell dialogs want
    info = _OpenAsInfo(path, None, OAIF_EXEC)
    return 0 if sh.SHOpenWithDialog(None, ctypes.byref(info)) == 0 else 1


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


def _notification_state():
    """SHQueryUserNotificationState as an int, or None when Windows can't say."""
    if not WIN:
        return None
    state = ctypes.c_int()
    try:
        if shell32.SHQueryUserNotificationState(ctypes.byref(state)) != 0:
            return None
    except Exception:
        return None
    return state.value


def presentation_mode():
    """True during a presentation or 'busy' quiet time (QUNS_PRESENTATION_MODE, QUNS_BUSY)."""
    return _notification_state() in (2, 4)


def fullscreen_game():
    """True while a full-screen Direct3D program runs (QUNS_RUNNING_D3D_FULL_SCREEN)."""
    return _notification_state() == 3


def busy_fullscreen():
    """True during a full-screen game, a presentation or 'quiet time'."""
    return presentation_mode() or fullscreen_game()


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


class _BROWSEINFOW(ctypes.Structure):
    _fields_ = [("hwndOwner", wintypes.HWND), ("pidlRoot", ctypes.c_void_p), ("pszDisplayName", wintypes.LPWSTR),
                ("lpszTitle", wintypes.LPCWSTR), ("ulFlags", wintypes.UINT), ("lpfn", ctypes.c_void_p),
                ("lParam", wintypes.LPARAM), ("iImage", ctypes.c_int)]


_dialog = {"hwnd": None}
_dialog_lock = None                 # made on first use (threading is imported lazily here)


def _to_front(hwnd):
    """Topmost and in front: the engine has no window of its own, so the dialog has no owner to sit on."""
    u = ctypes.WinDLL("user32")
    u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                               ctypes.c_int, wintypes.UINT]
    u.SetForegroundWindow.argtypes = [wintypes.HWND]
    u.SetWindowPos(hwnd, wintypes.HWND(-1), 0, 0, 0, 0, 0x1 | 0x2 | 0x40)   # TOPMOST; NOSIZE|NOMOVE|SHOWWINDOW
    u.SetForegroundWindow(hwnd)


def _front_dialog():
    hwnd = _dialog["hwnd"]
    if hwnd:
        _to_front(hwnd)


_BFFCALLBACK = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HWND, wintypes.UINT, wintypes.LPARAM,
                                  wintypes.LPARAM) if WIN else None


def _on_dialog(hwnd, msg, lparam, data):
    if msg == 1:                                                   # BFFM_INITIALIZED
        _dialog["hwnd"] = hwnd
        try:
            _to_front(hwnd)
        except OSError:
            pass
    return 0


_on_dialog_c = _BFFCALLBACK(_on_dialog) if WIN else None


def _browse_folder(title, out):
    ole32, sh = ctypes.WinDLL("ole32"), ctypes.WinDLL("shell32")
    sh.SHBrowseForFolderW.argtypes = [ctypes.POINTER(_BROWSEINFOW)]
    sh.SHBrowseForFolderW.restype = ctypes.c_void_p
    sh.SHGetPathFromIDListW.argtypes = [ctypes.c_void_p, wintypes.LPWSTR]
    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    inited = ole32.CoInitializeEx(None, 0x2) in (0, 1)           # COINIT_APARTMENTTHREADED: the dialog needs STA
    try:
        name = ctypes.create_unicode_buffer(260)
        info = _BROWSEINFOW(None, None, ctypes.cast(name, wintypes.LPWSTR), title,
                            0x1 | 0x40,                             # BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE
                            ctypes.cast(_on_dialog_c, ctypes.c_void_p), 0, 0)
        try:
            pidl = sh.SHBrowseForFolderW(ctypes.byref(info))
        finally:
            _dialog["hwnd"] = None
        if pidl:
            try:
                path = ctypes.create_unicode_buffer(260)
                if sh.SHGetPathFromIDListW(pidl, path):
                    out.append(path.value)
            finally:
                ole32.CoTaskMemFree(pidl)
    finally:
        if inited:
            ole32.CoUninitialize()


def pick_folder(title="Choose a folder for NOBAD Find"):
    """Windows' folder dialog, shown by this process (the engine, for the pipe's pick_folder), topmost and in
    front. The chosen folder, "" if cancelled, or None at once when a dialog is already open (that one is
    brought to the front again). Runs on a thread of its own so COM is set up the way the dialog needs."""
    global _dialog_lock
    if not WIN:
        return ""
    import threading
    if _dialog_lock is None:
        _dialog_lock = threading.Lock()
    if not _dialog_lock.acquire(blocking=False):
        try:
            _front_dialog()
        except OSError:
            pass
        return None
    try:
        out = []
        t = threading.Thread(target=_browse_folder, args=(title, out), daemon=True, name="folder-dialog")
        t.start()
        t.join()
        return out[0] if out else ""
    finally:
        _dialog_lock.release()


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


# ---------- sensors ----------
class _FILETIME(ctypes.Structure):
    _fields_ = [("lo", wintypes.DWORD), ("hi", wintypes.DWORD)]

    def value(self):
        return (self.hi << 32) | self.lo


class CpuSampler:
    """System-wide CPU use since the previous call (GetSystemTimes). The first call has nothing to compare."""

    def __init__(self):
        self._last = None

    def percent(self):
        if not WIN:
            return None
        idle, kern, user = _FILETIME(), _FILETIME(), _FILETIME()
        try:
            if not k32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user)):
                return None
        except Exception:
            return None
        now = (idle.value(), kern.value() + user.value())      # kernel time already includes idle time
        last, self._last = self._last, now
        if last is None:
            return None
        total = now[1] - last[1]
        if total <= 0:
            return None
        return max(0.0, min(100.0, 100.0 * (total - (now[0] - last[0])) / total))


class _MEMSTATUS(ctypes.Structure):
    _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD), ("ullTotalPhys", ctypes.c_uint64),
                ("ullAvailPhys", ctypes.c_uint64), ("ullTotalPageFile", ctypes.c_uint64),
                ("ullAvailPageFile", ctypes.c_uint64), ("ullTotalVirtual", ctypes.c_uint64),
                ("ullAvailVirtual", ctypes.c_uint64), ("ullAvailExtendedVirtual", ctypes.c_uint64)]


def memory_status():
    """(memory load in percent, free physical memory in MB); (0, 0) if Windows can't say."""
    if not WIN:
        return (0, 0)
    m = _MEMSTATUS()
    m.dwLength = ctypes.sizeof(m)
    try:
        if not k32.GlobalMemoryStatusEx(ctypes.byref(m)):
            return (0, 0)
    except Exception:
        return (0, 0)
    return (int(m.dwMemoryLoad), int(m.ullAvailPhys // 1048576))


def memory_status_total_mb():
    """The PC's physical memory in MB; 0 if Windows can't say."""
    if not WIN:
        return 0
    m = _MEMSTATUS()
    m.dwLength = ctypes.sizeof(m)
    try:
        if not k32.GlobalMemoryStatusEx(ctypes.byref(m)):
            return 0
    except Exception:
        return 0
    return int(m.ullTotalPhys // 1048576)


class _PDH_VALUE(ctypes.Structure):
    _fields_ = [("CStatus", wintypes.DWORD), ("doubleValue", ctypes.c_double)]


class _PDH_ITEM(ctypes.Structure):
    _fields_ = [("szName", ctypes.c_void_p), ("FmtValue", _PDH_VALUE)]


_PDH_GPU_PATH = "\\GPU Engine(*engtype_3D)\\Utilization Percentage"
_PDH_MORE_DATA = 0x800007D2
_PDH_FMT_DOUBLE = 0x200


class GpuSampler:
    """Busiest 3D engine's utilisation in percent (Windows performance counters); None if unavailable.

    Like CpuSampler, the first call only starts the measurement."""

    def __init__(self):
        self._query = None
        self._counter = None
        self._pdh = None
        if not WIN:
            return
        try:
            pdh = ctypes.WinDLL("pdh")
            pdh.PdhOpenQueryW.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
            pdh.PdhAddEnglishCounterW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.c_void_p,
                                                  ctypes.POINTER(ctypes.c_void_p)]
            pdh.PdhCollectQueryData.argtypes = [ctypes.c_void_p]
            pdh.PdhGetFormattedCounterArrayW.argtypes = [ctypes.c_void_p, wintypes.DWORD,
                                                         ctypes.POINTER(wintypes.DWORD),
                                                         ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
            pdh.PdhCloseQuery.argtypes = [ctypes.c_void_p]
            q, c = ctypes.c_void_p(), ctypes.c_void_p()
            if pdh.PdhOpenQueryW(None, None, ctypes.byref(q)) != 0:
                return
            if pdh.PdhAddEnglishCounterW(q, _PDH_GPU_PATH, None, ctypes.byref(c)) != 0:
                pdh.PdhCloseQuery(q)
                return
            self._pdh, self._query, self._counter = pdh, q, c
            pdh.PdhCollectQueryData(q)
        except Exception:
            self._pdh = self._query = self._counter = None

    def percent(self):
        pdh = self._pdh
        if not WIN or pdh is None:
            return None
        try:
            if pdh.PdhCollectQueryData(self._query) != 0:
                return None
            size, count = wintypes.DWORD(0), wintypes.DWORD(0)
            r = pdh.PdhGetFormattedCounterArrayW(self._counter, _PDH_FMT_DOUBLE, ctypes.byref(size),
                                                 ctypes.byref(count), None)
            if (r & 0xFFFFFFFF) != _PDH_MORE_DATA or not size.value:
                return None
            buf = ctypes.create_string_buffer(size.value)
            if pdh.PdhGetFormattedCounterArrayW(self._counter, _PDH_FMT_DOUBLE, ctypes.byref(size),
                                                ctypes.byref(count), buf) != 0:
                return None
            items = ctypes.cast(buf, ctypes.POINTER(_PDH_ITEM))
            vals = [items[i].FmtValue.doubleValue for i in range(count.value)
                    if items[i].FmtValue.CStatus in (0, 1)]          # valid data / new data
        except Exception:
            return None
        return max(0.0, min(100.0, max(vals))) if vals else None

    def __del__(self):
        try:
            if self._pdh is not None and self._query is not None:
                self._pdh.PdhCloseQuery(self._query)
        except Exception:
            pass


def foreground_exe():
    """Lower-case exe file name of the foreground window's program ('' if unknown)."""
    if not WIN:
        return ""
    hwnd = foreground_window()
    if not hwnd:
        return ""
    try:
        pid = window_pid(hwnd)
        if not pid:
            return ""
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                   ctypes.POINTER(wintypes.DWORD)]
        h = k32.OpenProcess(0x1000, False, pid)            # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            n = wintypes.DWORD(1024)
            if not k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                return ""
            return buf.value.rsplit("\\", 1)[-1].lower()
        finally:
            k32.CloseHandle(h)
    except Exception:
        return ""


def foreground_hung(timeout_ms=250):
    """True when the foreground window's program isn't answering (hung, or no reply within timeout_ms)."""
    if not WIN:
        return False
    hwnd = foreground_window()
    if not hwnd:
        return False
    try:
        user32.IsHungAppWindow.argtypes = [wintypes.HWND]
        if user32.IsHungAppWindow(hwnd):
            return True
        user32.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
                                               wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
        user32.SendMessageTimeoutW.restype = ctypes.c_ssize_t
        out = ctypes.c_size_t()
        ctypes.set_last_error(0)
        # WM_NULL with SMTO_ABORTIFHUNG: 0 means no answer; ERROR_TIMEOUT tells a hang from a vanished window
        if user32.SendMessageTimeoutW(hwnd, 0, 0, 0, 0x0002, int(timeout_ms), ctypes.byref(out)) == 0:
            return ctypes.get_last_error() == 1460
        return False
    except Exception:
        return False


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


# ---------- Find's own processes: EcoQoS, working set (ROADMAP Phase 1) ----------
class _PowerThrottling(ctypes.Structure):
    _fields_ = [("Version", wintypes.DWORD), ("ControlMask", wintypes.DWORD), ("StateMask", wintypes.DWORD)]


_THROTTLE_EXECUTION_SPEED = 0x1         # PROCESS_POWER_THROTTLING_EXECUTION_SPEED
_PROCESS_POWER_THROTTLING = 4           # PROCESS_INFORMATION_CLASS.ProcessPowerThrottling
_SET_INFORMATION_QUOTA = 0x0200 | 0x0100 | 0x0400 | 0x1000   # set information + set quota + query (limited)
_own = None


def _own_dll():
    """kernel32/psapi with their own argtypes (they don't leak into the rest of winapi)."""
    global _own
    if _own is None:
        k, ps = ctypes.WinDLL("kernel32", use_last_error=True), ctypes.WinDLL("psapi", use_last_error=True)
        k.OpenProcess.restype = wintypes.HANDLE
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.GetCurrentProcess.restype = wintypes.HANDLE
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.SetProcessInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        k.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
        ps.EmptyWorkingSet.argtypes = [wintypes.HANDLE]
        _own = (k, ps)
    return _own


def _with_process(pid, fn):
    """fn(handle) on this process (pid None) or on one of Find's own processes. False when it can't be opened."""
    if not WIN:
        return False
    k, _ps = _own_dll()
    if pid is None:
        return bool(fn(k.GetCurrentProcess()))
    h = k.OpenProcess(_SET_INFORMATION_QUOTA, False, int(pid))
    if not h:
        return False
    try:
        return bool(fn(h))
    finally:
        k.CloseHandle(h)


def eco_qos(on=True, pid=None, job=None):
    """EcoQoS ("efficiency mode", Task Manager's leaf): Windows runs the process on efficiency cores at low clocks.
    Only for Find's worker processes (the governor, at Light and Paused). job: the worker job's handle; the process
    must still be in it (a worker that ended may have its pid reused by another program). True if applied."""
    st = _PowerThrottling(1, _THROTTLE_EXECUTION_SPEED, _THROTTLE_EXECUTION_SPEED if on else 0)

    def apply(h):
        k, _ps = _own_dll()
        if job is not None:
            inside = wintypes.BOOL()
            if not k.IsProcessInJob(h, job, ctypes.byref(inside)) or not inside.value:
                return False
        return k.SetProcessInformation(h, _PROCESS_POWER_THROTTLING, ctypes.byref(st), ctypes.sizeof(st))
    try:
        return _with_process(pid, apply)
    except (OSError, AttributeError):          # Windows before 10 1709 has no power throttling
        return False


def trim_working_set(pid=None):
    """Hand the working set back to Windows (EmptyWorkingSet): what's needed again is paged back in on use.
    For Find's own processes only, when they go idle. True if done."""
    try:
        return _with_process(pid, lambda h: _own_dll()[1].EmptyWorkingSet(h))
    except OSError:
        return False


_IDLE_PRIORITY_CLASS, _NORMAL_PRIORITY_CLASS = 0x40, 0x20
_MEMORY_PRIORITY_LOW, _MEMORY_PRIORITY_NORMAL = 2, 5
_IO_VERY_LOW, _IO_NORMAL = 0, 2
_PROCESS_MEMORY_PRIORITY, _PROCESS_IO_PRIORITY = 0, 33


def worker_priority(low=True):
    """A worker process steps aside: idle CPU priority, low memory priority (its pages are the first Windows
    reuses) and very low I/O priority, or back to normal (low=False). Not Windows background mode: entered as a
    process starts, background mode pins its working set near 32 MB, and a reader parsing a PDF then page-faults
    about 400 times as often (20x slower; docs/measurements.md). Only for Find's own workers, on themselves."""
    if not WIN:
        return False
    k, _ps = _own_dll()
    h = k.GetCurrentProcess()
    ok = bool(k.SetPriorityClass(h, _IDLE_PRIORITY_CLASS if low else _NORMAL_PRIORITY_CLASS))
    mem = wintypes.ULONG(_MEMORY_PRIORITY_LOW if low else _MEMORY_PRIORITY_NORMAL)
    ok = bool(k.SetProcessInformation(h, _PROCESS_MEMORY_PRIORITY, ctypes.byref(mem), 4)) and ok
    try:
        nt = ctypes.WinDLL("ntdll")
        nt.NtSetInformationProcess.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.ULONG]
        io = wintypes.ULONG(_IO_VERY_LOW if low else _IO_NORMAL)
        ok = nt.NtSetInformationProcess(h, _PROCESS_IO_PRIORITY, ctypes.byref(io), 4) == 0 and ok
    except (OSError, AttributeError):
        ok = False
    return ok


def windows_languages():
    """The user's display languages and keyboard languages, as tags ("en-GB", "hi-IN"); [] if Windows can't say.
    Read from Windows only (no network): the language focus for Settings -> Models."""
    if not WIN:
        return []
    out = []
    try:
        k = ctypes.WinDLL("kernel32")
        n, size = wintypes.ULONG(), wintypes.ULONG(0)
        k.GetUserPreferredUILanguages(0x8, ctypes.byref(n), None, ctypes.byref(size))       # MUI_LANGUAGE_NAME
        buf = ctypes.create_unicode_buffer(size.value or 1)
        if k.GetUserPreferredUILanguages(0x8, ctypes.byref(n), buf, ctypes.byref(size)):
            out += [t for t in buf[:size.value].split("\x00") if t]
        u = ctypes.WinDLL("user32")
        count = u.GetKeyboardLayoutList(0, None)
        if count > 0:
            layouts = (ctypes.c_void_p * count)()
            u.GetKeyboardLayoutList(count, layouts)
            name = ctypes.create_unicode_buffer(85)
            for h in layouts:
                lang = (h or 0) & 0xFFFF
                if lang and k.LCIDToLocaleName(lang, name, 85, 0):
                    out.append(name.value)
    except Exception:
        pass
    return list(dict.fromkeys(out))
