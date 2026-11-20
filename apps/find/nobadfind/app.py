"""Start NOBAD Find: NobadFind.exe runs the engine (index, indexer, hotkeys, tray, the private pipe; engine.py) and
starts the Flutter UI (nobad_find.exe; uilaunch.py). One copy per user: a second start asks the running copy to show
its window, on the page asked for, and ends.

    NobadFind.exe                       the engine + the main window
    NobadFind.exe --page settings|index the engine + the main window on that page (--page search: the default)
    NobadFind.exe --bar                 the engine + the quick find bar
    NobadFind.exe --background          the engine only (Start with Windows); the hotkey or the tray opens the window
    NobadFind.exe --engine              the engine only, messages on the console (development, measurements)
"""
import argparse
import os
import sys

from . import winapi
from .const import APP_NAME, APP_VER, SETTINGS_PATH

PAGES = ("search", "settings", "index")
ADMIN = "NOBAD Find runs as your normal account. Start it without 'Run as administrator'."


def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="NobadFind")
    p.add_argument("--background", action="store_true", help="start without a window; the hotkey opens it")
    p.add_argument("--page", choices=PAGES, help="open the main window on this page")
    p.add_argument("--bar", action="store_true", help="open the quick find bar instead of the main window")
    p.add_argument("--wsearch", choices=("auto", "delayed-auto", "demand", "disabled"), help=argparse.SUPPRESS)
    p.add_argument("--turbo", choices=("serve", "selftest"), help=argparse.SUPPRESS)   # the elevated NTFS helper
    p.add_argument("--version", action="store_true")
    p.add_argument("--engine", action="store_true", help="no window: serve the UI over the private pipe")
    p.add_argument("--uninstall", action="store_true", help=argparse.SUPPRESS)   # run by the uninstaller
    # the engine's Open with helper (Api.open_with): the path of a result the engine looked up by its id
    p.add_argument("--open-with", metavar="PATH", help=argparse.SUPPRESS)
    return p.parse_args(argv)


def first_window(args):
    """The window this start asks for (engine / uilaunch names: main, settings, index, bar), or None."""
    if args.background or args.engine:
        return None
    if args.bar:
        return "bar"
    return {"search": "main", None: "main"}.get(args.page, args.page)


def uninstall():
    """Undo what NOBAD Find changed outside its own folder: Windows Search (if it turned it off) and the
    "Start with Windows" entry. The index itself is deleted by the uninstaller if the user says so."""
    from . import wsearch
    from .api import set_autostart
    from .settings import Settings
    settings = Settings(SETTINGS_PATH)
    try:
        set_autostart(False)
    except OSError:
        pass
    prev = settings.get("wsearch_prev")
    if prev and wsearch.state().get("start") == "disabled":
        if not wsearch.request(prev):            # Windows asks for permission; saying no leaves it off
            print("Windows Search is still off. Turn it on in Services (WSearch) if you want it back.")
            return 1
    if prev:
        settings.update({"wsearch_prev": ""})
    return 0


def _end(code):
    for f in (sys.stdout, sys.stderr):
        try:
            if f is not None:
                f.flush()
        except Exception:
            pass
    # End now: a leftover thread (the concurrent.futures exit join, a hotkey loop) can't keep the process alive,
    # and ending it closes the job, which ends every worker with it. The UI runs outside the job and sees the pipe
    # close.
    os._exit(code)


def main(argv=None):
    args = parse_args(argv)
    if args.open_with:                              # outside Find's job, so the program picked outlives Find
        return winapi.open_with_dialog(args.open_with)
    if args.version:
        print(f"{APP_NAME} {APP_VER}")
        return 0
    if args.wsearch:                                # the elevated one-shot helper: nothing else runs
        from .wsearch import helper_main
        return helper_main(args.wsearch)
    if args.turbo:                                  # the elevated turbo index helper (ntfs.py): nothing else runs
        from .ntfs import helper_main as turbo_main
        return turbo_main(args.turbo)
    if args.uninstall:
        return uninstall()
    from . import engine
    if args.engine:                                 # headless: the Flutter UI connects to it over the pipe
        _end(engine.main())
    if winapi.is_admin():
        # Everything NOBAD Find needs works as the normal user; running it as admin would index as admin.
        winapi.message(ADMIN)
        return 1
    what = first_window(args)
    lock = engine.lock_name()
    if not engine._single(lock):
        # Already running (often without a window): ask it to bring its window up instead of doing nothing.
        if what:
            winapi.ask_running_copy_to_show(what, engine.show_base(lock))
        return 0
    _end(engine.run(open_ui=what, lock=lock))


if __name__ == "__main__":
    sys.exit(main())
