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


def early_splash(argv):
    if os.name != "nt":
        return None
    try:
        import ctypes
        from .const import SHOW_FLAG_PATH
        if not wants_splash(argv, ctypes.windll.shell32.IsUserAnAdmin(), os.path.exists(SHOW_FLAG_PATH)):
            return None
        from . import splash
        return splash.show()
    except Exception:
        return None  # cosmetic: never block start-up
