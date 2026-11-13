"""Native windows (pywebview): main window with remembered size/position, compact 'mini' window, DPI awareness."""
import ctypes
import os
import threading
import time
import webbrowser

from .const import UI_DIR, WINDOW_TITLE
from .ctx import ctx

MIN_W, MIN_H = 1060, 700
MINI_W, MINI_H = 340, 345   # inner content needs ~291 (+ title bar); measured with the real page


def set_dpi_awareness():
    """Per-monitor DPI awareness so text stays sharp on 125–300 % displays and when moving between monitors.
    Normally already set by boot.set_dpi_awareness (v2, before the splash); this is the fallback for other entry
    points. Windows ignores a second call, so the order of these attempts only matters the first time."""
    if os.name != "nt":
        return
    from .boot import set_dpi_awareness as _v2
    if _v2():
        return
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def ui_scale():
    """Display scale (1.25 at 125 %). pywebview takes positions and sizes in LOGICAL units and multiplies them by
    this, while Windows reports the screen and work area in PHYSICAL pixels: everything we hand to pywebview must be
    divided by it, or windows land off-screen (the tray quick view did, at 125 %)."""
    if os.name != "nt":
        return 1.0
    try:
        return max(1.0, ctypes.windll.user32.GetDpiForSystem() / 96.0)
    except Exception:
        return 1.0


def virtual_screen():
    """x, y, w, h of the whole desktop (all monitors) in logical units, or None."""
    if os.name != "nt":
        return None
    try:
        u, s = ctypes.windll.user32, ui_scale()
        return tuple(int(v / s) for v in (u.GetSystemMetrics(76), u.GetSystemMetrics(77), u.GetSystemMetrics(78),
                                          u.GetSystemMetrics(79)))
    except Exception:
        return None


def work_area():
    """left, top, right, bottom of the primary work area (screen minus taskbar) in logical units, or None."""
    if os.name != "nt":
        return None
    try:
        from ctypes import wintypes
        r = wintypes.RECT()
        ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(r), 0)
        s = ui_scale()
        return int(r.left / s), int(r.top / s), int(r.right / s), int(r.bottom / s)
    except Exception:
        return None


def mini_position(wa, w=None, h=None, margin=12):
    """Bottom-right corner of the work area, always fully on screen (logical units)."""
    w, h = w or MINI_W, h or MINI_H
    if not wa:
        return None, None
    left, top, right, bottom = wa
    return max(left, right - w - margin), max(top, bottom - h - margin)


def clamp_geometry(saved, screen, area=None):
    """Return (x, y, w, h) for the main window, always FULLY on screen (logical units).

    `screen` is the whole desktop (x, y, w, h), `area` the primary work area (left, top, right, bottom). A saved
    position that is partly off-screen is moved back inside; one that is mostly off-screen (monitor unplugged, a
    position recorded while minimized) is dropped and the window is centred on the primary work area. Before, a
    window with only a 120 px slice visible was accepted, so NOBAD could open pushed against a screen edge."""
    saved = saved if isinstance(saved, dict) else {}
    try:
        w = max(MIN_W, int(saved.get("w", 1280)))
        h = max(MIN_H, int(saved.get("h", 820)))
    except (TypeError, ValueError):
        w, h = 1280, 820
    x, y = saved.get("x"), saved.get("y")
    if not (isinstance(x, int) and isinstance(y, int)):
        x = y = None
    if area:
        al, at, ar, ab = area
        w, h = min(w, max(1, ar - al)), min(h, max(1, ab - at))
    if screen:
        sx, sy, sw, sh = screen
        w, h = min(w, sw), min(h, sh)
        if x is not None:
            visible_w = min(x + w, sx + sw) - max(x, sx)
            visible_h = min(y + h, sy + sh) - max(y, sy)
            if visible_w < w * 0.5 or visible_h < h * 0.5 or y < sy:
                x = y = None                                # mostly off-screen: don't trust it
            else:
                x = min(max(x, sx), sx + sw - w)            # partly off-screen: slide it back inside
                y = min(max(y, sy), sy + sh - h)
    if x is None and area:
        al, at, ar, ab = area
        x, y = al + max(0, (ar - al - w) // 2), at + max(0, (ab - at - h) // 2)
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


def _signed(base_url, path):
    from .server import launch_url
    return launch_url(base_url, path)


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
        x, y, w, h = clamp_geometry(saved, virtual_screen(), work_area())
        # Frameless: the app's own top bar is the title bar (drag, snap, edge resize and the window buttons are
        # handed to Windows natively in titlebar_action, so it behaves like a normal window).
        kw = dict(width=w, height=h, min_size=(MIN_W, MIN_H), resizable=True, background_color="#07090d",
                  js_api=WindowApi(), text_select=False, hidden=True, frameless=bool(ctx.settings.get("custom_titlebar")),
                  easy_drag=False)
        if x is not None:
            kw.update(x=x, y=y)
        self._maximized = bool((saved or {}).get("maximized"))
        if self._maximized:
            kw["maximized"] = True
        try:
            self.main = webview.create_window(WINDOW_TITLE, _signed(self.url, "/"), **kw)
        except TypeError:  # older pywebview without `maximized`
            kw.pop("maximized", None)
            self.main = webview.create_window(WINDOW_TITLE, _signed(self.url, "/"), **kw)
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
            self.mini = self.webview.create_window("NOBAD VPN", _signed(self.url, "/mini"), **kw)
            self.mini.events.closing += self._mini_closing
        return self.mini

    def _wire(self, win):
        ev = win.events
        ev.closing += self._main_closing
        for name, fn in (("resized", lambda w, h: self._remember(w=int(w), h=int(h))),
                         ("moved", lambda x, y: int(x) > -10000 and int(y) > -10000      # minimized: -32000
                          and self._remember(x=int(x), y=int(y))),
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
            webbrowser.open(_signed(self.url, "/"))
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

    # ---- custom title bar (frameless main window)
    def _hwnd(self):
        try:
            return int(self.main.native.Handle.ToInt64())
        except Exception:
            try:
                return ctypes.windll.user32.FindWindowW(None, WINDOW_TITLE) or None
            except Exception:
                return None

    def _on_ui_thread(self, fn):
        """Run fn on the window's UI thread (mouse capture and form state belong to it)."""
        form = getattr(self.main, "native", None)
        if form is None:
            return fn()
        try:
            from System import Action
            form.BeginInvoke(Action(fn))
        except Exception:
            fn()

    HT = {"move": 2, "l": 10, "r": 11, "t": 12, "tl": 13, "tr": 14, "b": 15, "bl": 16, "br": 17}

    def titlebar_action(self, act, edge=None):
        """minimize | maximize (toggle) | close | drag | resize(edge) | state. Returns the window state."""
        if self.main is None or os.name != "nt":
            return {"maximized": False}
        if act == "minimize":
            self.main.minimize()
        elif act == "maximize":
            if self._maximized:
                self.main.restore()
                self._maximized = False
            else:
                def go():
                    try:                  # a borderless window would otherwise cover the taskbar when maximised
                        from System.Windows.Forms import Screen
                        form = self.main.native
                        wa = Screen.FromHandle(form.Handle).WorkingArea
                        sb = Screen.FromHandle(form.Handle).Bounds
                        from System.Drawing import Rectangle
                        form.MaximizedBounds = Rectangle(wa.X - sb.X, wa.Y - sb.Y, wa.Width, wa.Height)
                    except Exception:
                        pass
                    self.main.maximize()
                self._on_ui_thread(go)
                self._maximized = True
        elif act == "close":
            if self._main_closing():          # True: really close (no tray / quitting)
                from .lifecycle import request_quit
                request_quit(False)
        elif act in ("drag", "resize"):
            ht = self.HT.get("move" if act == "drag" else edge or "")
            hwnd = self._hwnd()
            if ht and hwnd and not (act == "resize" and self._maximized):
                def go():
                    u = ctypes.windll.user32
                    u.ReleaseCapture()
                    u.PostMessageW(hwnd, 0x00A1, ht, 0)      # WM_NCLBUTTONDOWN: Windows runs the move/size loop
                self._on_ui_thread(go)
        return {"maximized": bool(self._maximized)}

    def toggle_mini(self):
        wa = work_area()
        if self._ensure_mini(*mini_position(wa)) is None:
            return self.show_main()
        if getattr(self, "_mini_visible", False):
            return self.hide_mini()
        wa = work_area()
        try:
            x, y = mini_position(wa)
            if x is not None:
                self.mini.move(x, y)
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
        icon = os.path.join(UI_DIR, "brand", "nobad.ico")   # NOBAD icon on the title bar/taskbar, also for source runs
        try:
            self.webview.start(dark_titlebar, icon=icon if os.path.isfile(icon) else None)
        except TypeError:                                    # older pywebview without the icon argument
            self.webview.start(dark_titlebar)
