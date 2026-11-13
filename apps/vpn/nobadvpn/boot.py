"""Earliest start-up step, run by the launchers BEFORE the heavy imports (pywebview, the engine, ...).

Shows the splash right away in the process that will open the window: elevated (the non-elevated launcher only
hands over to the elevated task / UAC and exits) and not a CLI or background-only start."""
import os

_NO_WINDOW = {"--panic", "--repair-network", "--guard", "--selftest", "--version", "--watchdog", "-h", "--help"}


def wants_splash(argv, is_admin, show_flag_exists):
    flags = set(argv[1:])
    if flags & _NO_WINDOW:
        return False
    if "--background" in flags and not show_flag_exists:
        return False
    return bool(is_admin)


def set_app_identity():
    """Make every window of this process group under NOBAD VPN on the taskbar, even when run from source with
    python.exe. Must run before the first window (the splash) is created."""
    if os.name != "nt":
        return False
    try:
        import ctypes
        from .const import APP_ID
        return ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID) == 0
    except Exception:
        return False


def set_dpi_awareness():
    """Per-monitor v2 DPI awareness, set before ANY window exists (the splash, the tray icon, pywebview). Windows
    only accepts it once and only before the first window; if it is missed, Windows stretches the whole app as a
    bitmap on 125-300 % displays and it looks soft. v2 also scales dialogs and the title bar when the window moves
    to a monitor with a different scale."""
    if os.name != "nt":
        return False
    import ctypes
    try:
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):   # PER_MONITOR_AWARE_V2
            return True
    except Exception:
        pass
    try:
        return ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0                    # per-monitor (8.1+)
    except Exception:
        return False


def early_splash(argv):
    if os.name != "nt":
        return None
    set_dpi_awareness()
    set_app_identity()
    try:
        import ctypes
        from .autostart import show_requested
        if not wants_splash(argv, ctypes.windll.shell32.IsUserAnAdmin(), show_requested()):
            return None
        from . import splash
        return splash.show()
    except Exception:
        return None  # cosmetic: never block start-up
