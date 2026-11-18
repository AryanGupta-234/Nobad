"""The quick find bar: a small always-on-top search box on its own shortcut (default Ctrl+Alt+Space).

It shows on the monitor under the mouse, finds as you type, and goes away on Esc or when you click elsewhere.
It only talks to the same local search the main window uses; it never reports to the watchdog (that watches the
main window alone)."""
import ctypes
import threading
import time
from ctypes import wintypes

from . import winapi
from .hotkey import Hotkey
from .log import log

TITLE = "NOBAD Find bar"
WIDTH, HEIGHT, ROW, MAX_ROWS = 640, 64, 44, 8
TAKEN = "The quick find bar shortcut is used by another app. Pick another one in Settings."


def place(work_area, width=WIDTH, height=HEIGHT):
    """Top-left corner for the bar: centered across the work area, a third of the way down (pure function)."""
    left, top, right, bottom = work_area
    return left + (right - left - width) // 2, top + (bottom - top) // 3 - height // 2


def work_area_under_mouse():
    """((left, top, right, bottom) in physical pixels, scale) of the monitor the mouse is on, minus the taskbar."""
    fallback = ((0, 0, 1920, 1040), 1.0)
    if not winapi.WIN:
        return fallback
    try:
        user32 = ctypes.WinDLL("user32")

        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                        ("dwFlags", wintypes.DWORD)]
        user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
        user32.MonitorFromPoint.restype = wintypes.HANDLE
        user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        mon = user32.MonitorFromPoint(pt, 2)                    # MONITOR_DEFAULTTONEAREST
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if not mon or not user32.GetMonitorInfoW(mon, ctypes.byref(info)):
            return fallback
        r = info.rcWork
        scale = 1.0
        try:
            shcore = ctypes.WinDLL("shcore")
            shcore.GetDpiForMonitor.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.POINTER(wintypes.UINT),
                                                ctypes.POINTER(wintypes.UINT)]
            dx, dy = wintypes.UINT(), wintypes.UINT()
            if shcore.GetDpiForMonitor(mon, 0, ctypes.byref(dx), ctypes.byref(dy)) == 0 and dx.value:
                scale = dx.value / 96
        except OSError:
            pass
        return (r.left, r.top, r.right, r.bottom), scale
    except Exception as e:
        log(f"quick find bar: monitor lookup failed ({type(e).__name__})", "warn")
        return fallback


def _set_pos(hwnd, x, y, w, h, flags):
    user32 = ctypes.WinDLL("user32")
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, wintypes.UINT]
    user32.SetWindowPos(hwnd, wintypes.HWND(-1), x, y, w, h, flags)       # -1: HWND_TOPMOST


def _to_front(hwnd):
    """Take keyboard focus even when Windows would refuse a background window: join the input queue of the
    window that has focus for a moment (the usual, harmless way a launcher does it)."""
    user32 = ctypes.WinDLL("user32")
    k32 = ctypes.WinDLL("kernel32")
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.BringWindowToTop.argtypes = [wintypes.HWND]
    user32.SetFocus.argtypes = [wintypes.HWND]
    front = user32.GetForegroundWindow()
    theirs = user32.GetWindowThreadProcessId(front, None) if front else 0
    ours = k32.GetCurrentThreadId()
    joined = bool(theirs and theirs != ours and user32.AttachThreadInput(ours, theirs, True))
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if joined:
            user32.AttachThreadInput(ours, theirs, False)


class Bar:
    """Shows, moves, grows and hides the bar's window. Positions are physical pixels (Win32 directly), so the
    monitor's scale is applied here once and pywebview's own logical-pixel conversion never gets involved."""

    def __init__(self, get_window, want_glass=False):
        self._win = get_window
        self._want_glass = want_glass
        self._lock = threading.Lock()
        self._scale = 1.0
        self._closing = False
        self._shown_at = 0.0
        self.visible = False

    def _hwnd(self):
        return winapi.own_window(TITLE)

    def show(self):
        win = self._win()
        hwnd = self._hwnd()
        if not win or not hwnd:
            return
        with self._lock:
            area, self._scale = work_area_under_mouse()
            w, h = round(WIDTH * self._scale), round(HEIGHT * self._scale)
            x, y = place(area, w, h)
            _set_pos(hwnd, x, y, w, h, 0x40)                  # SWP_SHOWWINDOW
            _set_pos(hwnd, x, y, w, h, 0x40)                  # again: a monitor with another scale rescales once
            self.visible = True
            self._shown_at = time.monotonic()
        win.show()
        _to_front(hwnd)
        self._focus_page(win)
        win.run_js("window.barShow && window.barShow()")

    @staticmethod
    def _focus_page(win):
        """pywebview only gives the web page keyboard focus the first time the window is shown; do it each time."""
        try:
            from System import Func, Type
            form = win.native

            def focus():
                form.webview.Focus()
            form.Invoke(Func[Type](focus))
        except Exception as e:
            log(f"quick find bar: could not focus the page ({type(e).__name__})", "warn")

    def hide(self):
        win = self._win()
        self.visible = False
        if win:
            win.hide()

    def blurred(self):
        """The page lost focus: put the bar away, unless this is just Windows shuffling focus while it comes up."""
        if self.visible and time.monotonic() - self._shown_at > 0.5:
            self.hide()

    def toggle(self):
        self.hide() if self.visible else self.show()

    def fit(self, rows):
        """Grow or shrink to the number of result rows (each ROW tall) under the 64 px search box."""
        hwnd = self._hwnd()
        if not hwnd:
            return
        rows = max(0, min(MAX_ROWS, int(rows)))
        _set_pos(hwnd, 0, 0, round(WIDTH * self._scale), round((HEIGHT + rows * ROW) * self._scale),
                 0x2 | 0x10)                                  # SWP_NOMOVE | SWP_NOACTIVATE

    def make_glass(self):
        """Acrylic and rounded corners, like the main window. Runs once, after the window exists."""
        hwnd = 0
        for _ in range(50):
            hwnd = self._hwnd()
            if hwnd:
                break
            time.sleep(0.1)
        if not hwnd:
            return
        if self._want_glass and winapi.glass(hwnd):
            self._win().run_js("document.documentElement.classList.add('glass')")
        try:
            pref = ctypes.c_int(2)                            # DWMWA_WINDOW_CORNER_PREFERENCE = round
            ctypes.WinDLL("dwmapi").DwmSetWindowAttribute(wintypes.HWND(hwnd), 33, ctypes.byref(pref), 4)
        except OSError:
            pass

    def closing(self):
        """The window's closing event: a stray Alt+F4 only hides the bar. Return True to let it close."""
        if self._closing:
            return True
        self.hide()
        return False

    def close(self):
        """Really close it (NOBAD Find is quitting)."""
        self._closing = True
        win = self._win()
        if win:
            threading.Thread(target=win.destroy, daemon=True, name="barclose").start()


class BarApi:
    """What the bar page may call. Everything stays inside the main Api's own checks."""

    def __init__(self, api, bar, to_main):
        self._api, self._bar, self._to_main = api, bar, to_main

    def search(self, text):
        if not isinstance(text, str):
            return []
        r = self._api.search(text)
        rows = r.get("results") if isinstance(r, dict) else None
        return [{"id": x["id"], "name": x["name"], "folder": x.get("dir", ""), "kind": x.get("kind", "")}
                for x in (rows or [])[:MAX_ROWS]]

    def open(self, file_id):
        r = self._api.open(file_id)
        if r and r.get("ok"):
            self._bar.hide()
        return r

    def reveal(self, file_id):
        r = self._api.reveal(file_id)
        if r and r.get("ok"):
            self._bar.hide()
        return r

    def to_main(self, text):
        """Continue in the full window with the same words typed in."""
        self._to_main(text if isinstance(text, str) else "")
        self._bar.hide()

    def hide(self):
        self._bar.hide()

    def blurred(self):
        self._bar.blurred()

    def fit(self, rows):
        if isinstance(rows, int) and not isinstance(rows, bool):
            self._bar.fit(rows)


def start_hotkey(spec, callback, notify):
    """Register the bar's own hotkey (id 2). If another app has it, say so and leave the main hotkey alone."""
    hk = Hotkey(spec, callback, hk_id=2)
    if not hk.start():
        notify(TAKEN)
    return hk
