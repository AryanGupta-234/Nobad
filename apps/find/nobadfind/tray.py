"""The engine's tray icon (Shell_NotifyIcon through ctypes, on a message-loop thread of its own).

It belongs to the engine because it must be there while the UI is closed. Left click opens (or focuses) the UI;
right click shows the menu below; the tooltip shows the work level and how many files are indexed. Every action
goes to one callback (engine.Wiring.tray_action), so the menu itself holds no logic.
"""
import ctypes
import os
import sys
import threading
from ctypes import wintypes

from .log import log

WM_APP, WM_COMMAND, WM_DESTROY, WM_CLOSE, WM_NULL = 0x8000, 0x0111, 0x0002, 0x0010, 0x0000
WM_LBUTTONUP, WM_RBUTTONUP, WM_CONTEXTMENU = 0x0202, 0x0205, 0x007B
CALLBACK = WM_APP + 1
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_SHOWTIP = 0x1, 0x2, 0x4, 0x80
MF_STRING, MF_SEPARATOR = 0x0, 0x800
TPM_RIGHTBUTTON, TPM_RETURNCMD, TPM_NONOTIFY = 0x2, 0x100, 0x80

CMD = {"open": 1, "bar": 2, "pause": 3, "resume": 4, "settings": 5, "index": 6, "quit": 7}
_ACTION = {v: k for k, v in CMD.items()}


def menu(paused):
    """[(command id, label)]; (0, "") is a separator."""
    return [(CMD["open"], "Open NOBAD Find"), (CMD["bar"], "Quick find bar"), (0, ""),
            (CMD["resume"], "Resume") if paused else (CMD["pause"], "Pause for 1 hour"),
            (CMD["settings"], "Settings"), (CMD["index"], "Index"), (0, ""), (CMD["quit"], "Quit NOBAD Find")]


def tooltip(brief):
    """'NOBAD Find: Gentle, 12,345 files' (Windows shows at most 127 characters)."""
    level = (brief.get("level") or "").capitalize() or "Starting"
    if brief.get("paused") and brief.get("level") == "paused":
        level += f" ({brief['paused']})"
    files = int(brief.get("files") or 0)
    text = f"NOBAD Find: {level}, {files:,} file{'s' if files != 1 else ''}"
    return text if len(text) < 128 else text[:124] + "..."


def icon_path():
    """The NOBAD Find icon: the exe's own when installed, packaging/nobadfind.ico from source ("" if missing)."""
    if getattr(sys, "frozen", False):
        return sys.executable
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packaging", "nobadfind.ico")
    return p if os.path.isfile(p) else ""


class _NID(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT),
                ("uFlags", wintypes.UINT), ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
                ("szTip", ctypes.c_wchar * 128), ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD),
                ("szInfo", ctypes.c_wchar * 256), ("uVersion", wintypes.UINT), ("szInfoTitle", ctypes.c_wchar * 64),
                ("dwInfoFlags", wintypes.DWORD), ("guidItem", ctypes.c_byte * 16), ("hBalloonIcon", wintypes.HICON)]


LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class _WNDCLASSEX(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HICON)]


class Tray:
    """start() shows the icon on its own thread; stop() removes it. on_action(name) gets every click."""

    def __init__(self, on_action, tip, paused):
        self.on_action, self.tip, self.paused = on_action, tip, paused
        self.hwnd = None
        self._icon = None
        self._thread = None
        self._ready = threading.Event()
        self._proc = WNDPROC(self._wndproc)           # kept: Windows calls it for as long as the window lives

    # ----- what a click means (tested without a desktop) -----
    def _on_click(self, msg):
        if msg == WM_LBUTTONUP:
            self.on_action("open")
        elif msg in (WM_RBUTTONUP, WM_CONTEXTMENU):
            cmd = self._popup()
            if cmd:
                self._on_command(cmd)

    def _on_command(self, cmd):
        action = _ACTION.get(int(cmd))
        if action:
            try:
                self.on_action(action)
            except Exception as e:
                log(f"tray action {action} failed: {type(e).__name__}", "warn")

    # ----- Win32 -----
    def start(self):
        if sys.platform != "win32":
            return False
        self._thread = threading.Thread(target=self._run, daemon=True, name="tray")
        self._thread.start()
        return self._ready.wait(5) and self.hwnd is not None

    def stop(self):
        if self.hwnd:
            ctypes.windll.user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
        if self._thread is not None:
            self._thread.join(3)

    def update(self):
        """Refresh the tooltip (the level or the file count changed)."""
        if self.hwnd:
            self._notify(NIM_MODIFY)

    def _u32(self):
        u = ctypes.WinDLL("user32", use_last_error=True)
        u.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        u.DefWindowProcW.restype = LRESULT
        u.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                      ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                      wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p]
        u.CreateWindowExW.restype = wintypes.HWND
        u.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                     wintypes.HWND, ctypes.c_void_p]
        u.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
        u.CreatePopupMenu.restype = wintypes.HMENU
        u.DestroyMenu.argtypes = [wintypes.HMENU]
        u.LoadImageW.restype = wintypes.HANDLE
        u.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int,
                                 wintypes.UINT]
        u.LoadIconW.restype = wintypes.HICON
        u.LoadIconW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
        u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        u.SetForegroundWindow.argtypes = [wintypes.HWND]
        return u

    def _load_icon(self, u):
        path = icon_path()
        if path.lower().endswith(".exe"):
            sh = ctypes.WinDLL("shell32")
            small = wintypes.HICON()
            sh.ExtractIconExW.argtypes = [wintypes.LPCWSTR, ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(wintypes.HICON),
                                          wintypes.UINT]
            if sh.ExtractIconExW(path, 0, None, ctypes.byref(small), 1) and small.value:
                return small.value
        elif path:
            h = u.LoadImageW(None, path, 1, 0, 0, 0x10 | 0x40)        # IMAGE_ICON, LR_LOADFROMFILE | LR_DEFAULTSIZE
            if h:
                return h
        return u.LoadIconW(None, ctypes.c_void_p(32512))              # IDI_APPLICATION

    def _notify(self, what):
        nid = _NID()
        nid.cbSize = ctypes.sizeof(_NID)
        nid.hWnd, nid.uID = self.hwnd, 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP | NIF_SHOWTIP
        nid.uCallbackMessage, nid.hIcon = CALLBACK, self._icon
        try:
            nid.szTip = self.tip()[:127]
        except Exception:
            nid.szTip = "NOBAD Find"
        sh = ctypes.WinDLL("shell32")
        sh.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(_NID)]
        return bool(sh.Shell_NotifyIconW(what, ctypes.byref(nid)))

    def _popup(self):
        u = self._u32()
        m = u.CreatePopupMenu()
        try:
            for cmd, label in menu(bool(self.paused())):
                u.AppendMenuW(m, MF_SEPARATOR if not cmd else MF_STRING, cmd, label or None)
            pt = wintypes.POINT()
            u.GetCursorPos(ctypes.byref(pt))
            u.SetForegroundWindow(self.hwnd)          # else the menu doesn't close when you click elsewhere
            cmd = u.TrackPopupMenu(m, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY, pt.x, pt.y, 0, self.hwnd, None)
            u.PostMessageW(self.hwnd, WM_NULL, 0, 0)
            return cmd
        finally:
            u.DestroyMenu(m)

    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == CALLBACK:
                self._on_click(lparam & 0xFFFF)
                return 0
            if msg == self._taskbar_created:             # Explorer restarted: the icon must be added again
                self._notify(NIM_ADD)
                return 0
            if msg == WM_DESTROY:
                self._notify(NIM_DELETE)
                ctypes.windll.user32.PostQuitMessage(0)
                return 0
        except Exception as e:
            log(f"tray message failed: {type(e).__name__}", "warn")
        return self._u32().DefWindowProcW(hwnd, msg, wparam, lparam)

    def _run(self):
        try:
            u = self._u32()
            self._taskbar_created = u.RegisterWindowMessageW("TaskbarCreated")
            hinst = ctypes.windll.kernel32.GetModuleHandleW(None)
            wc = _WNDCLASSEX()
            wc.cbSize = ctypes.sizeof(_WNDCLASSEX)
            wc.lpfnWndProc, wc.hInstance, wc.lpszClassName = self._proc, hinst, "NOBADFindTray"
            u.RegisterClassExW(ctypes.byref(wc))
            self.hwnd = u.CreateWindowExW(0, "NOBADFindTray", "NOBAD Find", 0, 0, 0, 0, 0, None, None, hinst, None)
            if not self.hwnd:
                log(f"tray window failed (error {ctypes.get_last_error()})", "warn")
                return
            self._icon = self._load_icon(u)
            if not self._notify(NIM_ADD):
                log("tray icon could not be added", "warn")
            self._ready.set()
            msg = wintypes.MSG()
            while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                u.TranslateMessage(ctypes.byref(msg))
                u.DispatchMessageW(ctypes.byref(msg))
        except Exception as e:
            log(f"tray failed: {type(e).__name__}", "warn")
        finally:
            self._ready.set()
            self.hwnd = None

    _taskbar_created = -1
