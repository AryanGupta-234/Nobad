"""Native startup splash (company logo) shown the moment the elevated app starts, until the main window is ready.

A Win32 layered window drawn with UpdateLayeredWindow: per-pixel alpha (rounded corners and soft shadow from the
PNG), no taskbar button, never steals focus. It needs only ctypes + Pillow, runs on its own thread with its own
message loop, and costs a few milliseconds. Any failure is silent: the splash is cosmetic and must never block
the app from starting."""
import os
import threading
import time

from .const import UI_DIR

SPLASH_PNG = os.path.join(UI_DIR, "brand", "splash.png")   # rendered at 2x by packaging/make_brand.py
BASE_W, BASE_H = 440, 260                                  # logical size at 100 % scaling
MAX_SECONDS = 25                                           # never linger if the window never reports ready


def premultiplied_bgra(img):
    """Pillow RGBA image -> raw top-down BGRA bytes with premultiplied alpha (what UpdateLayeredWindow wants)."""
    from PIL import Image, ImageChops
    img = img.convert("RGBA")
    r, g, b, a = img.split()
    r, g, b = (ImageChops.multiply(c, a) for c in (r, g, b))
    return Image.merge("RGBA", (b, g, r, a)).tobytes()


def load_image(scale=1.0, path=SPLASH_PNG):
    from PIL import Image
    img = Image.open(path).convert("RGBA")
    w, h = max(1, round(BASE_W * scale)), max(1, round(BASE_H * scale))
    if img.size != (w, h):
        img = img.resize((w, h), Image.LANCZOS)
    return img


class Splash:
    def __init__(self, path=SPLASH_PNG):
        self.path = path
        self.hwnd = None
        self._ready = threading.Event()
        self._closed = threading.Event()
        self._thread = None
        self.shown_at = None

    @property
    def visible(self):
        return self.hwnd is not None and not self._closed.is_set()

    def show(self):
        if os.name != "nt" or not os.path.exists(self.path) or self._thread:
            return False
        self._thread = threading.Thread(target=self._run, name="splash", daemon=True)
        self._thread.start()
        self._ready.wait(1.5)
        return self.hwnd is not None

    def close(self):
        if self._closed.is_set():
            return
        self._closed.set()
        h = self.hwnd
        if h:
            try:
                import ctypes
                ctypes.windll.user32.PostMessageW(h, 0x0010, 0, 0)  # WM_CLOSE
            except Exception:
                pass

    # ------------------------------------------------------------------ Win32
    def _run(self):
        try:
            self._create_and_loop()
        except Exception:
            self.hwnd = None
        finally:
            self._ready.set()
            self._closed.set()

    def _create_and_loop(self):
        import ctypes
        from ctypes import wintypes as wt

        user32, gdi32, kernel32 = ctypes.windll.user32, ctypes.windll.gdi32, ctypes.windll.kernel32
        LRESULT = ctypes.c_ssize_t
        WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
        user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
        user32.DefWindowProcW.restype = LRESULT
        user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
                                           ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
        user32.CreateWindowExW.restype = wt.HWND
        user32.GetDC.restype = wt.HDC
        user32.GetDC.argtypes = [wt.HWND]
        user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
        gdi32.CreateCompatibleDC.restype = wt.HDC
        gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
        gdi32.SelectObject.restype = wt.HGDIOBJ
        gdi32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
        gdi32.DeleteObject.argtypes = [wt.HGDIOBJ]
        gdi32.DeleteDC.argtypes = [wt.HDC]
        kernel32.GetModuleHandleW.restype = wt.HMODULE
        user32.LoadCursorW.restype = wt.HANDLE
        user32.LoadCursorW.argtypes = [wt.HINSTANCE, ctypes.c_void_p]
        user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
        user32.SetTimer.argtypes = [wt.HWND, ctypes.c_size_t, wt.UINT, ctypes.c_void_p]
        user32.DestroyWindow.argtypes = [wt.HWND]
        user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
        user32.UpdateLayeredWindow.argtypes = [wt.HWND, wt.HDC, ctypes.c_void_p, ctypes.c_void_p, wt.HDC,
                                               ctypes.c_void_p, wt.DWORD, ctypes.c_void_p, wt.DWORD]

        # DPI: per-monitor aware so the splash is sharp (window.py sets the same; a second call is harmless)
        try:
            user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except Exception:
            pass
        try:
            dpi = user32.GetDpiForSystem()
        except Exception:
            dpi = 96
        scale = max(1.0, dpi / 96.0)

        img = load_image(scale, self.path)
        w, h = img.size
        data = premultiplied_bgra(img)

        class WNDCLASSEXW(ctypes.Structure):
            _fields_ = [("cbSize", wt.UINT), ("style", wt.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                        ("cbWndExtra", ctypes.c_int), ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
                        ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH), ("lpszMenuName", wt.LPCWSTR),
                        ("lpszClassName", wt.LPCWSTR), ("hIconSm", wt.HICON)]

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG), ("biPlanes", wt.WORD),
                        ("biBitCount", wt.WORD), ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                        ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
                        ("biClrImportant", wt.DWORD)]

        class BLENDFUNCTION(ctypes.Structure):
            _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                        ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]

        def wndproc(hwnd, msg, wparam, lparam):
            if msg == 0x0010:      # WM_CLOSE
                user32.DestroyWindow(hwnd)
                return 0
            if msg == 0x0002:      # WM_DESTROY
                user32.PostQuitMessage(0)
                return 0
            if msg == 0x0021:      # WM_MOUSEACTIVATE -> MA_NOACTIVATE (clicking never steals focus)
                return 3
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._wndproc = WNDPROC(wndproc)  # keep a reference for the window's lifetime
        hinst = kernel32.GetModuleHandleW(None)
        cls = "NobadVPNSplash"
        wc = WNDCLASSEXW(ctypes.sizeof(WNDCLASSEXW), 0, self._wndproc, 0, 0, hinst, None,
                         user32.LoadCursorW(None, ctypes.c_void_p(32514)),  # IDC_APPSTARTING
                         None, None, cls, None)
        user32.RegisterClassExW(ctypes.byref(wc))

        work = wt.RECT()
        user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(work), 0)  # SPI_GETWORKAREA (primary monitor)
        x = work.left + ((work.right - work.left) - w) // 2
        y = work.top + ((work.bottom - work.top) - h) // 2

        WS_EX = 0x00080000 | 0x00000008 | 0x00000080 | 0x08000000  # LAYERED | TOPMOST | TOOLWINDOW | NOACTIVATE
        hwnd = user32.CreateWindowExW(WS_EX, cls, "NOBAD VPN", 0x80000000, x, y, w, h, None, None, hinst, None)
        if not hwnd:
            return

        screen = user32.GetDC(None)
        mem = gdi32.CreateCompatibleDC(screen)
        bmi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        bits = ctypes.c_void_p()
        gdi32.CreateDIBSection.restype = wt.HBITMAP
        gdi32.CreateDIBSection.argtypes = [wt.HDC, ctypes.c_void_p, wt.UINT, ctypes.POINTER(ctypes.c_void_p),
                                           wt.HANDLE, wt.DWORD]
        hbmp = gdi32.CreateDIBSection(screen, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
        if not hbmp or not bits:
            user32.ReleaseDC(None, screen)
            gdi32.DeleteDC(mem)
            user32.DestroyWindow(hwnd)
            return
        ctypes.memmove(bits, data, len(data))
        old = gdi32.SelectObject(mem, hbmp)
        size, src, dst = wt.SIZE(w, h), wt.POINT(0, 0), wt.POINT(x, y)
        blend = BLENDFUNCTION(0, 0, 255, 1)  # AC_SRC_OVER, per-pixel alpha
        user32.UpdateLayeredWindow(hwnd, screen, ctypes.byref(dst), ctypes.byref(size), mem, ctypes.byref(src), 0,
                                   ctypes.byref(blend), 2)  # ULW_ALPHA
        user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
        self.hwnd = hwnd
        self.shown_at = time.time()
        self._ready.set()
        if self._closed.is_set():          # close() raced ahead of creation
            user32.PostMessageW(hwnd, 0x0010, 0, 0)
        # safety net: never stay up forever
        user32.SetTimer(hwnd, 1, MAX_SECONDS * 1000, None)

        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == 0x0113:      # WM_TIMER
                user32.DestroyWindow(hwnd)
                continue
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        gdi32.SelectObject(mem, old)
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(mem)
        user32.ReleaseDC(None, screen)
        self.hwnd = None


_current = {"splash": None}


def show():
    """Show the splash (once per process). Returns the Splash or None."""
    if _current["splash"] is None:
        s = Splash()
        _current["splash"] = s if s.show() else None
        if _current["splash"] is None:
            _current["splash"] = False
    return _current["splash"] or None


def close():
    s = _current["splash"]
    if s:
        s.close()
