"""The pywebview window that shows the web UI, with NOBAD's own title bar.

Ported from NOBAD VPN (apps/vpn/nobadvpn/window.py):
* On Windows the window is frameless and the page's header is the title bar: minimise / maximise / close buttons,
  drag on empty header space (Windows' own move loop, so snapping and Aero Shake work), double-click to maximise,
  and invisible edges that start Windows' own resize loop (``WM_SYSCOMMAND SC_SIZE``).
* The frameless window gets ``WS_MINIMIZEBOX | WS_SYSMENU`` back, so clicking its taskbar button minimises it,
  Win+Down works and the taskbar menu appears.
* Maximising keeps the taskbar visible, and the window's size and position are remembered (always clamped back
  fully on screen).
* Windows needs Microsoft Edge WebView2. pywebview can fall back to the Internet Explorer engine, which can't run
  this UI safely, so that case shows how to install WebView2 instead.

With the setting "NOBAD title bar" off (or on Linux/macOS) the window keeps the system title bar (dark on Windows)."""
from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
from collections.abc import Callable
from typing import Any

WINDOW_TITLE = "NOBAD File Bridge"
DEFAULT_SIZE = (1280, 820)
MIN_W, MIN_H = 1060, 700
BACKGROUND = "#08090d"
GEOMETRY_ROW = "web_ui.window"

WEBVIEW2_MISSING = (
    "NOBAD File Bridge needs Microsoft Edge WebView2 to show its window. Install the WebView2 Runtime from "
    "https://developer.microsoft.com/microsoft-edge/webview2/ and start the app again, or run it with --browser "
    "to use your web browser instead."
)

ACTIONS = ("minimize", "maximize", "close", "drag", "resize", "state")
EDGES = {"l": 1, "r": 2, "t": 3, "tl": 4, "tr": 5, "b": 6, "bl": 7, "br": 8}   # WMSZ_* for SC_SIZE
WM_NCLBUTTONDOWN, HTCAPTION = 0x00A1, 2
WM_SYSCOMMAND, SC_SIZE = 0x0112, 0xF000
WS_MINIMIZEBOX, WS_SYSMENU = 0x00020000, 0x00080000
_WINDOWS = os.name == "nt"


class WindowUnavailable(RuntimeError):
    pass


# ---------------------------------------------------------------- screen geometry (logical units)
def ui_scale() -> float:
    """Display scale (1.25 at 125 %). pywebview takes LOGICAL units; Windows reports PHYSICAL pixels."""
    if not _WINDOWS:
        return 1.0
    try:
        return max(1.0, ctypes.windll.user32.GetDpiForSystem() / 96.0)
    except Exception:
        return 1.0


def virtual_screen() -> tuple[int, int, int, int] | None:
    """x, y, w, h of the whole desktop (all monitors), or None."""
    if not _WINDOWS:
        return None
    try:
        u, s = ctypes.windll.user32, ui_scale()
        return tuple(int(u.GetSystemMetrics(i) / s) for i in (76, 77, 78, 79))  # type: ignore[return-value]
    except Exception:
        return None


def work_area() -> tuple[int, int, int, int] | None:
    """left, top, right, bottom of the primary work area (screen minus taskbar), or None."""
    if not _WINDOWS:
        return None
    try:
        from ctypes import wintypes

        r = wintypes.RECT()
        ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(r), 0)
        s = ui_scale()
        return int(r.left / s), int(r.top / s), int(r.right / s), int(r.bottom / s)
    except Exception:
        return None


def clamp_geometry(saved: Any, screen: tuple[int, int, int, int] | None, area: tuple[int, int, int, int] | None = None):
    """(x, y, w, h) for the window, always FULLY on screen. A saved position that is mostly off-screen (monitor
    unplugged, recorded while minimised) is dropped and the window is centred on the work area."""
    saved = saved if isinstance(saved, dict) else {}
    try:
        w = max(MIN_W, int(saved.get("w", DEFAULT_SIZE[0])))
        h = max(MIN_H, int(saved.get("h", DEFAULT_SIZE[1])))
    except (TypeError, ValueError):
        w, h = DEFAULT_SIZE
    x, y = saved.get("x"), saved.get("y")
    if not (isinstance(x, int) and isinstance(y, int)) or isinstance(x, bool) or isinstance(y, bool):
        x = y = None
    if area:
        al, at, ar, ab = area
        w, h = min(w, max(1, ar - al)), min(h, max(1, ab - at))
    if screen:
        sx, sy, sw, sh = screen
        w, h = min(w, sw), min(h, sh)
        if x is not None and y is not None:
            visible_w = min(x + w, sx + sw) - max(x, sx)
            visible_h = min(y + h, sy + sh) - max(y, sy)
            if visible_w < w * 0.5 or visible_h < h * 0.5 or y < sy:
                x = y = None
            else:
                x = min(max(x, sx), sx + sw - w)
                y = min(max(y, sy), sy + sh - h)
    if x is None and area:
        al, at, ar, ab = area
        x, y = al + max(0, (ar - al - w) // 2), at + max(0, (ab - at - h) // 2)
    return x, y, w, h


def dark_system_titlebar() -> None:
    """Dark caption for the system title bar (when NOBAD's own title bar is off). Runs once the window exists."""
    if not _WINDOWS:
        return
    for _ in range(40):
        try:
            hwnd = ctypes.windll.user32.FindWindowW(None, WINDOW_TITLE)
            if hwnd:
                on = ctypes.c_int(1)
                for attr in (20, 19):                                   # DWMWA_USE_IMMERSIVE_DARK_MODE
                    ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(on), 4)
                caption = ctypes.c_int(0x0D0908)                        # COLORREF of #08090d (BGR)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(caption), 4)
                text = ctypes.c_int(0xF6F4F4)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 36, ctypes.byref(text), 4)
                return
        except Exception:
            return
        time.sleep(0.15)


# ---------------------------------------------------------------- window controller
class WindowController:
    """Owns the pywebview window. ``action()`` backs the page's title-bar buttons (API ``window.action``)."""

    def __init__(self, *, frameless: bool, load_geometry: Callable[[], Any] | None = None,
                 save_geometry: Callable[[dict[str, Any]], None] | None = None) -> None:
        self.frameless = bool(frameless) and _WINDOWS
        self.window: Any = None
        self.maximized = False
        self._load = load_geometry or (lambda: None)
        self._save = save_geometry or (lambda _g: None)
        self._geom: dict[str, Any] = {}
        self._save_timer: threading.Timer | None = None
        self._requested: tuple[int, int] | None = None
        self._size_delta: tuple[int, int] | None = None

    # ---- create / run
    def run(self, launch_url: str, *, debug: bool = False) -> None:
        try:
            import webview
        except ImportError as exc:
            raise WindowUnavailable("pywebview isn't installed. Run the app with --browser, or install pywebview.") from exc

        webview.settings["ALLOW_DOWNLOADS"] = False
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
        saved = self._load()
        x, y, w, h = clamp_geometry(saved, virtual_screen(), work_area())
        kwargs: dict[str, Any] = dict(
            width=w, height=h, min_size=(MIN_W, MIN_H), resizable=True, background_color=BACKGROUND,
            text_select=True, frameless=self.frameless, easy_drag=False,
        )
        if x is not None:
            kwargs.update(x=x, y=y)
        self._requested = (w, h)
        self.maximized = bool((saved or {}).get("maximized")) if isinstance(saved, dict) else False
        if self.maximized:
            kwargs["maximized"] = True
        try:
            self.window = webview.create_window(WINDOW_TITLE, launch_url, **kwargs)
        except TypeError:                     # older pywebview without `maximized`
            kwargs.pop("maximized", None)
            self.window = webview.create_window(WINDOW_TITLE, launch_url, **kwargs)
        self._wire(self.window)
        gui = "edgechromium" if sys.platform == "win32" else None
        started = None if self.frameless else dark_system_titlebar
        try:
            webview.start(started, gui=gui, debug=debug, private_mode=True)
        except Exception as exc:
            if sys.platform == "win32":
                raise WindowUnavailable(WEBVIEW2_MISSING) from exc
            raise WindowUnavailable(f"Couldn't open the window: {exc}") from exc
        finally:
            self.save_now()

    def _wire(self, win: Any) -> None:
        ev = win.events
        handlers = (
            ("resized", lambda w, h: self._remember(w=int(w), h=int(h))),
            ("moved", lambda x, y: int(x) > -10000 and int(y) > -10000 and self._remember(x=int(x), y=int(y))),
            ("maximized", lambda: setattr(self, "maximized", True)),
            ("restored", lambda: setattr(self, "maximized", False)),
            ("shown", self._on_shown),
            ("loaded", self._on_shown),
            ("closing", lambda: self.save_now()),
        )
        for name, fn in handlers:
            try:
                getattr(ev, name).__iadd__(fn)
            except Exception:
                pass

    def _on_shown(self) -> None:
        self._enable_taskbar_minimize()
        self._measure_size_delta()

    def _measure_size_delta(self) -> None:
        """pywebview opens a frameless window smaller than asked (it takes off the size of a normal border and
        caption), while its resize events report the real size. Saving that size and asking for it next time would
        shrink the window on every start, so the difference is measured once and added back when saving."""
        if self._size_delta is not None or self._requested is None or self.maximized:
            return
        actual = self._actual_size()
        if actual is None:
            return
        dw, dh = self._requested[0] - actual[0], self._requested[1] - actual[1]
        self._size_delta = (dw, dh) if 0 <= dw <= 64 and 0 <= dh <= 96 else (0, 0)

    def _actual_size(self) -> tuple[int, int] | None:
        hwnd = self._hwnd() if _WINDOWS else None
        if not hwnd:
            return None
        try:
            from ctypes import wintypes

            r = wintypes.RECT()
            if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r)):
                return None
            s = ui_scale()
            return int(round((r.right - r.left) / s)), int(round((r.bottom - r.top) / s))
        except Exception:
            return None

    # ---- remembered size and position
    def _remember(self, **values: int) -> None:
        if self.maximized:
            return                          # the maximised size isn't the size to restore to next time
        if self._size_delta and "w" in values and "h" in values:
            values = dict(values, w=values["w"] + self._size_delta[0], h=values["h"] + self._size_delta[1])
        self._geom.update(values)
        if self._save_timer:
            self._save_timer.cancel()
        self._save_timer = threading.Timer(1.0, self.save_now)
        self._save_timer.daemon = True
        self._save_timer.start()

    def save_now(self) -> None:
        current = self._load()
        merged = dict(current if isinstance(current, dict) else {}, **self._geom, maximized=bool(self.maximized))
        if merged != current:
            try:
                self._save(merged)
            except Exception:
                pass

    # ---- native helpers (Windows)
    def _hwnd(self) -> int | None:
        try:
            return int(self.window.native.Handle.ToInt64())
        except Exception:
            try:
                return ctypes.windll.user32.FindWindowW(None, WINDOW_TITLE) or None
            except Exception:
                return None

    def _on_ui_thread(self, fn: Callable[[], None]) -> None:
        """Run fn on the window's UI thread (mouse capture and form state belong to it)."""
        form = getattr(self.window, "native", None)
        if form is None:
            fn()
            return
        try:
            from System import Action  # pythonnet, present with the WinForms backend

            form.BeginInvoke(Action(fn))
        except Exception:
            fn()

    def _enable_taskbar_minimize(self) -> bool:
        """Give the frameless window WS_MINIMIZEBOX | WS_SYSMENU: invisible here (no native caption) but it brings
        back taskbar click-to-minimise, Win+Down, the minimise animation and the taskbar menu."""
        if not self.frameless:
            return False
        hwnd = self._hwnd()
        if not hwnd:
            return False
        try:
            u = ctypes.windll.user32
            get = getattr(u, "GetWindowLongPtrW", u.GetWindowLongW)
            setl = getattr(u, "SetWindowLongPtrW", u.SetWindowLongW)
            get.restype = setl.restype = ctypes.c_ssize_t
            get.argtypes = [ctypes.c_void_p, ctypes.c_int]
            setl.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
            style = get(ctypes.c_void_p(hwnd), -16)                     # GWL_STYLE
            wanted = style | WS_MINIMIZEBOX | WS_SYSMENU
            if wanted != style:
                setl(ctypes.c_void_p(hwnd), -16, wanted)
            return True
        except Exception:
            return False

    # ---- native file dialogs (the page can't see real paths on its own)
    def pick(self, kind: str, start: str | None = None) -> list[str]:
        if self.window is None:
            return []
        import webview

        dialog = {"file": webview.FileDialog.OPEN, "files": webview.FileDialog.OPEN, "folder": webview.FileDialog.FOLDER}[kind]
        chosen = self.window.create_file_dialog(dialog, directory=start or "", allow_multiple=kind == "files")
        return [str(p) for p in (chosen or [])]

    # ---- title-bar actions
    def state(self) -> dict[str, Any]:
        return {"frameless": self.frameless and self.window is not None, "maximized": bool(self.maximized)}

    def action(self, act: str, edge: str | None = None) -> dict[str, Any]:
        """minimize | maximize (toggle) | close | drag | resize(edge) | state. Returns the window state."""
        if act not in ACTIONS:
            raise ValueError("Unknown window action.")
        if edge is not None and edge not in EDGES:
            raise ValueError("Unknown window edge.")
        if self.window is None or not _WINDOWS:
            return self.state()
        if act == "minimize":
            self.window.minimize()
        elif act == "maximize":
            self._toggle_maximize()
        elif act == "close":
            self.save_now()
            self.window.destroy()
        elif act == "drag":
            hwnd = self._hwnd()
            if hwnd:
                def drag() -> None:
                    u = ctypes.windll.user32
                    u.ReleaseCapture()
                    u.PostMessageW(hwnd, WM_NCLBUTTONDOWN, HTCAPTION, 0)    # Windows' own move loop
                self._on_ui_thread(drag)
        elif act == "resize":
            # A frameless window has no sizing border, so WM_NCLBUTTONDOWN with HTLEFT/... is ignored.
            # WM_SYSCOMMAND SC_SIZE + direction starts Windows' own resize loop (live resize, snapping, min size).
            direction = EDGES.get(edge or "")
            hwnd = self._hwnd()
            if direction and hwnd and not self.maximized:
                def resize() -> None:
                    u = ctypes.windll.user32
                    u.ReleaseCapture()
                    u.PostMessageW(hwnd, WM_SYSCOMMAND, SC_SIZE + direction, 0)
                self._on_ui_thread(resize)
        return self.state()

    def _toggle_maximize(self) -> None:
        if self.maximized:
            self.window.restore()
            self.maximized = False
            return

        def maximize() -> None:
            try:                    # a borderless window would otherwise cover the taskbar when maximised
                from System.Drawing import Rectangle
                from System.Windows.Forms import Screen

                form = self.window.native
                screen = Screen.FromHandle(form.Handle)
                wa, bounds = screen.WorkingArea, screen.Bounds
                form.MaximizedBounds = Rectangle(wa.X - bounds.X, wa.Y - bounds.Y, wa.Width, wa.Height)
            except Exception:
                pass
            self.window.maximize()

        self._on_ui_thread(maximize)
        self.maximized = True
