"""Start NOBAD Find: one copy per user, the index, the indexer, the hotkey and the window."""
import argparse
import ctypes
import os
import sys
import threading
import time

from . import embed, jobs, lifecycle, winapi
from .const import APP_NAME, APP_VER, DATA_DIR, DB_PATH, KEY_PATH, LOG_PATH, SETTINGS_PATH
from .log import init as init_log, log

UI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui")


def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="NobadFind")
    p.add_argument("--background", action="store_true", help="start hidden; the hotkey opens the window")
    p.add_argument("--wsearch", choices=("auto", "delayed-auto", "demand", "disabled"), help=argparse.SUPPRESS)
    p.add_argument("--version", action="store_true")
    p.add_argument("--uninstall", action="store_true", help=argparse.SUPPRESS)   # run by the uninstaller
    return p.parse_args(argv)


def single_instance():
    """True if this is the only NOBAD Find running for this user."""
    if not winapi.WIN:
        return True
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = ctypes.c_void_p
    single_instance.handle = k32.CreateMutexW(None, False, "Local\\NOBAD-Find")
    return ctypes.get_last_error() != 183          # ERROR_ALREADY_EXISTS


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


def main(argv=None):
    args = parse_args(argv)
    if args.version:
        print(f"{APP_NAME} {APP_VER}")
        return 0
    if args.wsearch:                                # the elevated one-shot helper: nothing else runs
        from .wsearch import helper_main
        return helper_main(args.wsearch)
    if args.uninstall:
        return uninstall()
    if winapi.is_admin():
        # Everything NOBAD Find needs works as the normal user; running it as admin would index as admin.
        winapi.message("NOBAD Find runs as your normal account. Start it without 'Run as administrator'.")
        return 1
    if not single_instance():
        # Already running (often hidden in the background): bring that window up instead of doing nothing.
        if not args.background:
            winapi.ask_running_copy_to_show()
        return 0
    jobs.setup()                    # before any worker or the window: nothing Find starts can outlive it

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
    from .activity import Activity
    from .appmemory import AppMemory
    from .governor import Governor
    activity = Activity()
    from .watchdog import Watchdog
    ui = {}      # the pieces the watchdog reaches later: window, api, indexer
    watchdog = Watchdog(activity, release=lambda: ui["indexer"].release_models(),
                        reload_ui=lambda: ui["win"].evaluate_js("location.reload()"),
                        quit_app=lambda: ui["api"].quit(), visible=lambda: ui["api"].visible,
                        names=lambda: ui["indexer"].worker_names())
    governor = Governor(settings, AppMemory(store), activity, watchdog=watchdog)
    governor.start()
    indexer = Indexer(store, settings, vindex, governor=governor)
    ui["indexer"] = indexer
    # Closing the window with background indexing off stops the indexer (lifecycle "hide_idle"); opening it
    # again starts it. Started hidden (with Windows), indexing follows the same setting.
    win_life = lifecycle.Window(indexer, bool(args.background and not settings.get("keep_background")), log)
    wanted = win_life.wanted

    if win_life.want_idle:
        log("started in the background: indexing starts when the window opens")
    else:
        indexer.start()

    import webview
    from .api import Api
    holder = {}
    api = Api(store, settings, indexer, vindex, lambda: holder.get("w"))
    api.watchdog, api.visible = watchdog, not args.background
    ui["api"] = api
    api.governor, api.activity = governor, activity      # the status page reads these
    want_glass = settings.get("glass") and winapi.transparency_allowed()
    if want_glass:
        os.environ["WEBVIEW2_DEFAULT_BACKGROUND_COLOR"] = "00000000"     # let the acrylic show through the page
    win = webview.create_window(APP_NAME, os.path.join(UI_DIR, "index.html"), js_api=api, width=1080, height=720,
                                min_size=(720, 480), background_color="#000000" if want_glass else "#07080a",
                                hidden=args.background,
                                text_select=True)
    holder["w"] = win
    ui["win"] = win

    def bring_up():
        api.visible = True
        watchdog.window_shown()
        front = winapi.foreground_window()          # before our window takes the front: where you were
        wanted(False)
        if not front or winapi.window_pid(front) == os.getpid():
            win.show()                              # already in front: keep the folder it was opened from
            win.restore()
            win.evaluate_js("window.nfFocus && window.nfFocus()")
            return
        api.here = ""
        bring_up.n = getattr(bring_up, "n", 0) + 1
        mine = bring_up.n

        def find_here():
            folder = winapi.foreground_folder(front) if front else ""
            if mine == bring_up.n:                  # a newer hotkey press wins
                api.here = folder
                win.evaluate_js("window.nfHere && window.nfHere()")
        threading.Thread(target=find_here, daemon=True, name="here").start()
        threading.Thread(target=indexer.warm_models, daemon=True, name="warm").start()
        win.show()
        win.restore()
        win.evaluate_js("window.nfFocus && window.nfFocus()")

    from .hotkey import Hotkey
    hk = Hotkey(settings.get("hotkey"), bring_up)
    show_evt = winapi.show_event()

    def show_requests():
        # Starting NOBAD Find again (Start menu, desktop) while it runs signals this event.
        while not getattr(api, "_quitting", False):
            if winapi.wait_event(show_evt, 1000):
                api.here = ""
                api.visible = True
                watchdog.window_shown()
                wanted(False)
                win.show()
                win.restore()
                win.evaluate_js("window.nfFocus && window.nfFocus()")

    def make_glass():
        hwnd = 0
        for _ in range(50):                        # the window appears a moment after the app starts
            hwnd = winapi.own_window(APP_NAME)
            if hwnd:
                break
            time.sleep(0.1)
        ok = bool(want_glass and winapi.glass(hwnd))
        log(f"see-through window: {'on' if ok else 'off'} (wanted {bool(want_glass)}, window {hwnd != 0})")
        if ok:
            win.evaluate_js("document.documentElement.classList.add('glass')")

    def started():
        threading.Thread(target=make_glass, daemon=True, name="glass").start()
        if show_evt:
            threading.Thread(target=show_requests, daemon=True, name="show").start()
        if not args.background:
            threading.Thread(target=indexer.warm_models, daemon=True, name="warm").start()
        if not hk.start():
            win.evaluate_js("window.nfNotice && window.nfNotice('The hotkey is used by another app. Pick another "
                            "one in Settings.')")

    def closing():
        # with the hotkey ready, closing the window keeps NOBAD Find in the background, like a launcher;
        # unless background indexing is on, everything but this one idle process stops (lifecycle.on_close)
        mode = lifecycle.on_close(settings, hk.ok, getattr(api, "_quitting", False))
        if mode != "quit":
            api.visible = False
            win.hide()
            if mode == "hide_idle":
                wanted(True)
            return False
        indexer.stop()
        governor.stop()
        hk.stop()
        return True

    win.events.closing += closing
    webview.start(started, http_server=True, private_mode=True)
    indexer.stop()
    governor.stop()
    log("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
