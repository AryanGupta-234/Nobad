"""Start NOBAD Find: one copy per user, the index, the indexer, the hotkey and the window."""
import argparse
import ctypes
import os
import sys

from . import embed, winapi
from .const import APP_NAME, APP_VER, DATA_DIR, DB_PATH, KEY_PATH, LOG_PATH, SETTINGS_PATH
from .log import init as init_log, log

UI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui")


def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="NobadFind")
    p.add_argument("--background", action="store_true", help="start hidden; the hotkey opens the window")
    p.add_argument("--wsearch", choices=("auto", "delayed-auto", "demand", "disabled"), help=argparse.SUPPRESS)
    p.add_argument("--version", action="store_true")
    return p.parse_args(argv)


def single_instance():
    """True if this is the only NOBAD Find running for this user."""
    if not winapi.WIN:
        return True
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = ctypes.c_void_p
    single_instance.handle = k32.CreateMutexW(None, False, "Local\\NOBAD-Find")
    return ctypes.get_last_error() != 183          # ERROR_ALREADY_EXISTS


def main(argv=None):
    args = parse_args(argv)
    if args.version:
        print(f"{APP_NAME} {APP_VER}")
        return 0
    if args.wsearch:                                # the elevated one-shot helper: nothing else runs
        from .wsearch import helper_main
        return helper_main(args.wsearch)
    if winapi.is_admin():
        # Everything NOBAD Find needs works as the normal user; running it as admin would index as admin.
        print("NOBAD Find runs as your normal account. Start it without 'Run as administrator'.")
        return 1
    if not single_instance():
        return 0

    os.makedirs(DATA_DIR, exist_ok=True)
    init_log(LOG_PATH)
    log(f"{APP_NAME} {APP_VER} starting")
    from .indexer import Indexer
    from .settings import Settings
    from .store import Store
    settings = Settings(SETTINGS_PATH)
    store = Store(DB_PATH, KEY_PATH)
    if not store.encrypted:
        log("SQLCipher missing: the index is NOT encrypted", "warn")
    vindex = embed.VectorIndex()
    indexer = Indexer(store, settings, vindex)
    indexer.start()

    import webview
    from .api import Api
    holder = {}
    api = Api(store, settings, indexer, vindex, lambda: holder.get("w"))
    win = webview.create_window(APP_NAME, os.path.join(UI_DIR, "index.html"), js_api=api, width=1080, height=720,
                                min_size=(720, 480), background_color="#07080a", hidden=args.background,
                                text_select=True)
    holder["w"] = win

    def bring_up():
        win.show()
        win.restore()
        win.evaluate_js("window.nfFocus && window.nfFocus()")

    from .hotkey import Hotkey
    hk = Hotkey(settings.get("hotkey"), bring_up)

    def started():
        if not hk.start():
            win.evaluate_js("window.nfNotice && window.nfNotice('The hotkey is used by another app. Pick another "
                            "one in Settings.')")

    def closing():
        # with the hotkey ready, closing the window keeps NOBAD Find in the background, like a launcher
        if hk.ok and not getattr(api, "_quitting", False):
            win.hide()
            return False
        indexer.stop()
        hk.stop()
        return True

    win.events.closing += closing
    webview.start(started, http_server=True, private_mode=True)
    indexer.stop()
    log("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
