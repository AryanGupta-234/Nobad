"""Native windows (pywebview): main window with remembered size/position, compact 'mini' window, DPI awareness."""
import ctypes
import os
import threading
import time
import webbrowser

from .const import WINDOW_TITLE
from .ctx import ctx

MIN_W, MIN_H = 1060, 700
MINI_W, MINI_H = 340, 270


def set_dpi_awareness():
    """Per-monitor DPI awareness so text stays sharp on 125–300 % displays and when moving between monitors."""
    if os.name != "nt":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def virtual_screen():
    """x, y, w, h of the whole desktop (all monitors), or None."""
    if os.name != "nt":
        return None
    try:
        u = ctypes.windll.user32
        return u.GetSystemMetrics(76), u.GetSystemMetrics(77), u.GetSystemMetrics(78), u.GetSystemMetrics(79)
    except Exception:
        return None


def work_area():
    if os.name != "nt":
        return None
    try:
        from ctypes import wintypes
        r = wintypes.RECT()
        ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(r), 0)
        return r.left, r.top, r.right, r.bottom
    except Exception:
        return None


def clamp_geometry(saved, screen):
    """Return (x, y, w, h) with x/y None when the saved position would be off-screen (monitor unplugged)."""
    saved = saved if isinstance(saved, dict) else {}
    try:
        w = max(MIN_W, int(saved.get("w", 1280)))
        h = max(MIN_H, int(saved.get("h", 820)))
    except (TypeError, ValueError):
        w, h = 1280, 820
    x, y = saved.get("x"), saved.get("y")
    if screen:
        sx, sy, sw, sh = screen
        w, h = min(w, sw), min(h, sh)
        if isinstance(x, int) and isinstance(y, int):
            # require a reasonable slice of the window (title bar region) to be visible
            if not (sx - w + 120 <= x <= sx + sw - 120 and sy <= y <= sy + sh - 80):
                x = y = None
        else:
            x = y = None
    elif not (isinstance(x, int) and isinstance(y, int)):
        x = y = None
    return x, y, w, h


def dark_titlebar():
    if os.name != "nt":
        return
    for _ in range(40):
        try:
            hwnd = ctypes.windll.user32.FindWindowW(None, WINDOW_TITLE)
            if hwnd:
                v = ctypes.c_int(1)
                for attr in (20, 19):
                    ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), 4)
                cap = ctypes.c_int(0x120D0A)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(cap), 4)
                txt = ctypes.c_int(0xF7EEE8)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 36, ctypes.byref(txt), 4)
                return
        except Exception:
            return
        time.sleep(0.15)


def hide_console():
    if os.name != "nt":
        return
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        pass


class WindowApi:
    def close(self):
        from .lifecycle import request_quit
        request_quit(False)


class WindowManager:
    def __init__(self, base_url):
        self.url = base_url
        self.webview = None
        self.main = None
        self.mini = None
        self._geom = {}
        self._save_timer = None
        self._maximized = False
        self.revealed_event = threading.Event()

    # ---- remembered state
    def _remember(self, **kw):
        if self._maximized:
            return  # the maximized size is not the size to restore to next time
        self._geom.update(kw)
        if self._save_timer:
            self._save_timer.cancel()
        self._save_timer = threading.Timer(1.0, self.save_state)
        self._save_timer.daemon = True
        self._save_timer.start()

    def save_state(self):
        cur = dict(ctx.settings.get("window") or {})
        new = dict(cur, **self._geom, maximized=bool(self._maximized))
        if new != cur:
            ctx.settings.set("window", new)

    # ---- creation
    def create(self, start_hidden=False, on_shown=None):
        """Main window only. It is created hidden and revealed once the page has loaded (no blank white flash;
        the splash stays up until then). The mini window is created on first use, not at start-up."""
        try:
            import webview
        except ImportError:
            return False
        self.webview = webview
        hide_console()
        saved = ctx.settings.get("window")
        x, y, w, h = clamp_geometry(saved, virtual_screen())
        kw = dict(width=w, height=h, min_size=(MIN_W, MIN_H), resizable=True, background_color="#07090d",
                  js_api=WindowApi(), text_select=False, hidden=True)
        if x is not None:
            kw.update(x=x, y=y)
        self._maximized = bool((saved or {}).get("maximized"))
        if self._maximized:
            kw["maximized"] = True
        try:
            self.main = webview.create_window(WINDOW_TITLE, self.url + "/", **kw)
        except TypeError:  # older pywebview without `maximized`
            kw.pop("maximized", None)
            self.main = webview.create_window(WINDOW_TITLE, self.url + "/", **kw)
        self._wire(self.main)
        self._on_shown = on_shown
        self._revealed = False
        if start_hidden:
            self.revealed_event.set()   # nothing to wait for
        if not start_hidden:
            self.main.events.loaded += self._reveal
            t = threading.Timer(15.0, self._reveal)  # safety net if 'loaded' never fires
            t.daemon = True
            t.start()
        elif on_shown:
            on_shown()
        return True

    def _reveal(self, *_a):
        if self._revealed:
            return
        self._revealed = True
        self.revealed_event.set()
        try:
            self.main.show()
        except Exception:
            pass
        if self._on_shown:
            try:
                self._on_shown()
            except Exception:
                pass

    def _ensure_mini(self, x=None, y=None):
        if self.mini is None and self.webview is not None and ctx.tray and ctx.tray.available:
            kw = dict(width=MINI_W, height=MINI_H, resizable=False, on_top=True, hidden=True,
                      background_color="#0b0c10", text_select=False)
            if x is not None:
                kw.update(x=x, y=y)
            self.mini = self.webview.create_window("NOBAD VPN", self.url + "/mini", **kw)
            self.mini.events.closing += self._mini_closing
        return self.mini

    def _wire(self, win):
        ev = win.events
        ev.closing += self._main_closing
        for name, fn in (("resized", lambda w, h: self._remember(w=int(w), h=int(h))),
                         ("moved", lambda x, y: self._remember(x=int(x), y=int(y))),
                         ("maximized", lambda: setattr(self, "_maximized", True)),
                         ("restored", lambda: setattr(self, "_maximized", False))):
            try:
                getattr(ev, name).__iadd__(fn)
            except Exception:
                pass

    def _main_closing(self):
        self.save_state()
        tray_ok = bool(ctx.tray and ctx.tray.icon is not None)
        if ctx.quitting or not (ctx.settings.get("close_to_tray") and tray_ok):
            return True
        self.hide_main()
        return False  # cancel the close: the app lives in the tray

    def _mini_closing(self):
        if ctx.quitting:
            return True
        self.hide_mini()
        return False

    # ---- show / hide
    def show_main(self):
        if self.main is None:
            webbrowser.open(self.url + "/")
            return
        try:
            self.main.show()
            if not self._maximized:
                self.main.restore()  # un-minimize (restore() would also un-maximize)
            self.main.on_top = True   # bring to the front (a second launch hands over to this window)
            self.main.on_top = False
        except Exception:
            pass

    def hide_main(self):
        try:
            self.main.hide()
        except Exception:
            pass

    def toggle_mini(self):
        wa = work_area()
        if self._ensure_mini(*((wa[2] - MINI_W - 12, wa[3] - MINI_H - 12) if wa else (None, None))) is None:
            return self.show_main()
        if getattr(self, "_mini_visible", False):
            return self.hide_mini()
        wa = work_area()
        try:
            if wa:
                self.mini.move(wa[2] - MINI_W - 12, wa[3] - MINI_H - 12)
            self.mini.show()
            self._mini_visible = True
        except Exception:
            pass

    def hide_mini(self):
        try:
            if self.mini is not None:
                self.mini.hide()
        except Exception:
            pass
        self._mini_visible = False

    def destroy_all(self):
        self.save_state()
        for w in (self.mini, self.main):
            try:
                if w is not None:
                    w.destroy()
            except Exception:
                pass

    def run(self):
        """Blocks until all windows are closed/destroyed."""
        self.webview.start(dark_titlebar)
