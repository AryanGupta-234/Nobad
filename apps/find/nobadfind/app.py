"""Start NOBAD Find: one copy per user, the index, the indexer, the hotkey and the window."""
import argparse
import ctypes
import json
import os
import sys
import threading
import time

from . import bar as quickbar, embed, jobs, lifecycle, winapi
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


def close_splash():
    """Close the start-up picture the exe shows while it unpacks (PyInstaller's splash). Not there when run from
    source, and closing it twice is harmless."""
    try:
        import pyi_splash
    except ImportError:
        return
    try:
        pyi_splash.close()
        log("start-up picture closed")
    except Exception as e:
        log(f"start-up picture: {type(e).__name__}", "warn")


def main(argv=None):
    args = parse_args(argv)
    if args.version or args.wsearch or args.uninstall:
        close_splash()                              # no window to wait for
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
        close_splash()
        winapi.message("NOBAD Find runs as your normal account. Start it without 'Run as administrator'.")
        return 1
    if not single_instance():
        # Already running (often hidden in the background): bring that window up instead of doing nothing.
        close_splash()
        if not args.background:
            winapi.ask_running_copy_to_show()
        return 0
    jobs.setup()                    # before any worker or the window: nothing Find starts can outlive it

    os.makedirs(DATA_DIR, exist_ok=True)
    init_log(LOG_PATH)
    if args.background:
        close_splash()                              # hidden start: there is no window to wait for
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
    apps = AppMemory(store)
    governor = Governor(settings, apps, activity, watchdog=watchdog,
                        release_idle=lambda: ui["indexer"].release_idle_models() if "indexer" in ui else None)
    governor.start()
    indexer = Indexer(store, settings, vindex, governor=governor)
    ui["indexer"] = indexer
    # Closing the window with background indexing off stops the indexer (lifecycle "hide_idle"); opening it
    # again starts it. Started hidden (with Windows), indexing follows the same setting.
    win_life = lifecycle.Window(indexer, bool(args.background and not settings.get("keep_background")), log,
                                quitting=lambda: getattr(ui.get("api"), "_quitting", False))
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
    api.governor, api.activity, api.apps = governor, activity, apps      # the status page reads these
    want_glass = settings.get("glass") and winapi.transparency_allowed()
    if want_glass:
        os.environ["WEBVIEW2_DEFAULT_BACKGROUND_COLOR"] = "00000000"     # let the acrylic show through the page
    win = webview.create_window(APP_NAME, os.path.join(UI_DIR, "index.html"), js_api=api, width=1080, height=720,
                                min_size=(720, 480), background_color="#000000" if want_glass else "#07080a",
                                hidden=args.background,
                                text_select=True)
    holder["w"] = win
    # Esc / "Hide after opening" hide the window: with background indexing off that stops indexing too
    api._on_hide = lambda: lifecycle.after_hide(win_life, settings, hk.ok, getattr(api, "_quitting", False))
    ui["win"] = win
    bar_ctl = bar_win = None
    if settings.get("bar"):
        # The quick find bar: a second, small window that starts hidden; its own hotkey shows it.
        bar_ctl = quickbar.Bar(lambda: bar_win, want_glass)
        bar_api = quickbar.BarApi(api, bar_ctl, lambda text: to_main(text))
        bar_win = webview.create_window(quickbar.TITLE, os.path.join(UI_DIR, "bar.html"), js_api=bar_api,
                                        width=quickbar.WIDTH, height=quickbar.HEIGHT, min_size=(320, 40),
                                        frameless=True, on_top=True, easy_drag=False, resizable=False, hidden=True,
                                        background_color="#000000" if want_glass else "#07080a")
        bar_win.events.closing += bar_ctl.closing

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

    def to_main(text):
        """The bar's Alt+Enter: the same way up as the hotkey (indexing restarts, the watchdog is told), then the
        words are typed into the search box. The text goes in as JSON, never pasted into the script."""
        bring_up()
        win.evaluate_js("window.nfQuery && window.nfQuery(" + json.dumps(text) + ")")

    def notice(text):
        win.evaluate_js("window.nfNotice && window.nfNotice(" + json.dumps(text) + ")")

    from .hotkey import Hotkey
    hk = Hotkey(settings.get("hotkey"), bring_up)
    show_evt = winapi.show_event()
    bar_hk = []

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
        if not args.background:
            win.events.loaded += close_splash       # the page is up: the start-up picture can go
            late = threading.Timer(12, close_splash)    # in case the page never reports loading
            late.daemon = True
            late.start()
        threading.Thread(target=make_glass, daemon=True, name="glass").start()
        if show_evt:
            threading.Thread(target=show_requests, daemon=True, name="show").start()
        if not args.background:
            threading.Thread(target=indexer.warm_models, daemon=True, name="warm").start()
        if not hk.start():
            notice("The hotkey is used by another app. Pick another one in Settings.")
        if bar_ctl:
            threading.Thread(target=bar_ctl.make_glass, daemon=True, name="barglass").start()
            bar_hk.append(quickbar.start_hotkey(settings.get("bar_hotkey"), bar_ctl.toggle, notice))

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
        for k in bar_hk:
            k.stop()
        if bar_ctl:
            bar_ctl.close()                         # else the hidden bar would keep the app alive
        return True

    win.events.closing += closing
    webview.start(started, http_server=True, private_mode=True)
    indexer.stop()
    governor.stop()
    indexer.join(5)                     # its database writes are committed before the process ends
    log("stopped")
    for f in (sys.stdout, sys.stderr):
        try:
            f.flush()
        except Exception:
            pass
    # End now: a leftover thread (pythonnet/WinForms, the concurrent.futures exit join) can't keep the
    # process alive, and ending it closes the job, which ends every worker and WebView2.
    os._exit(0)


if __name__ == "__main__":
    sys.exit(main())
