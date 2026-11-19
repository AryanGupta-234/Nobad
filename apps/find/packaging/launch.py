"""PyInstaller entry point for NobadFind.exe (same as `python -m nobadfind`)."""
import os
import sys

# Starts that never show NOBAD Find's window: the start-up picture closes at once, before the heavy imports
# (numpy) below, instead of flashing while they load. Worker processes start this exe again too.
NO_WINDOW = ("--background", "--version", "--wsearch", "--uninstall", "--multiprocessing-fork", "--open-with")
MUTEX = "Local\\NOBAD-Find"                  # app.single_instance's name: set while a copy runs


def already_running():
    """True while another NOBAD Find runs for this user (this start only asks it to show its window)."""
    if sys.platform != "win32":
        return False
    import ctypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenMutexW.restype = ctypes.c_void_p
    k.OpenMutexW.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p]
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    h = k.OpenMutexW(0x00100000, False, MUTEX)          # SYNCHRONIZE
    if not h:
        return False
    k.CloseHandle(h)
    return True


def no_window(argv):
    return any(a.split("=", 1)[0] in NO_WINDOW for a in argv[1:]) or already_running()


def close_splash_early(argv=None):
    """Close the splash now when this start shows no window. Not there when run from source."""
    try:
        import pyi_splash
    except ImportError:
        return False
    if not no_window(sys.argv if argv is None else argv):
        return False
    try:
        pyi_splash.close()
    except Exception:
        return False
    return True


close_splash_early()
# The worker processes (and the Windows Search helper) start this exe again: they never show the picture.
os.environ["PYINSTALLER_SUPPRESS_SPLASH_SCREEN"] = "1"

import multiprocessing  # noqa: E402  (after the splash check on purpose)

if __name__ == "__main__":
    multiprocessing.freeze_support()          # the text-reading worker processes start this exe again
    # After freeze_support, not at the top: a worker runs this file too, and the app's imports (numpy, the window,
    # the models) would cost every text reader about 500 MB of commit (docs/measurements.md).
    from nobadfind.app import main
    sys.exit(main())
