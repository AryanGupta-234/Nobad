"""`python -m nobadfind --engine`: NOBAD Find without a window, serving the UI over the private pipe (nobadfind.rpc).

Prototype for the Flutter UI (ROADMAP Phase 3 step 1). It builds the same pieces as app.py (settings, encrypted
store, governor, watchdog, indexer, Api) but no WebView. The hotkeys push a `show` event to the connected UIs.

Running next to the WebView app:
- With the default data folder the engine takes the same single-instance lock as the app, so the two can't run
  at the same time (they would share one index). Quit the app first.
- With NOBAD_FIND_DATA_DIR set (a separate index, used for measurements) the engine takes a lock of its own and can
  run next to the app; the app keeps the hotkeys then (the engine logs that they're taken).
- Only one engine per user can serve the pipe; a second one exits with an error.
"""
import ctypes
import hashlib
import os
import threading

from . import embed, jobs, winapi
from .const import APP_NAME, APP_VER, DATA_DIR, DB_PATH, KEY_PATH, LOG_PATH, SETTINGS_PATH
from .log import init as init_log, log

DEFAULT_DATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "NOBAD", "Find")


def lock_name(data_dir=DATA_DIR, default=DEFAULT_DATA_DIR):
    """The single-instance mutex: the app's own for the default index, a separate one for another data folder."""
    if os.path.normcase(os.path.abspath(data_dir)) == os.path.normcase(os.path.abspath(default)):
        return "Local\\NOBAD-Find"
    digest = hashlib.sha256(os.path.normcase(os.path.abspath(data_dir)).encode("utf-8")).hexdigest()[:16]
    return "Local\\NOBAD-Find-engine-" + digest


def _single(name):
    if not winapi.WIN:
        return True
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = ctypes.c_void_p
    _single.handle = k32.CreateMutexW(None, False, name)
    return ctypes.get_last_error() != 183          # ERROR_ALREADY_EXISTS


def main(stop=None):
    """Run until `stop` (a threading.Event) is set or the process is ended. Returns the exit code."""
    if winapi.is_admin():
        print("NOBAD Find runs as your normal account. Start it without 'Run as administrator'.")
        return 1
    if not _single(lock_name()):
        print("NOBAD Find is already running with this index. Quit it first.")
        return 1
    os.makedirs(DATA_DIR, exist_ok=True)
    init_log(LOG_PATH)
    jobs.setup()                    # nothing the engine starts can outlive it
    log(f"{APP_NAME} {APP_VER} engine starting")
    from .activity import Activity
    from .api import Api
    from .app import ui_hooks
    from .appmemory import AppMemory
    from .governor import Governor
    from .hotkey import Hotkey
    from .indexer import Indexer
    from .rpc import Rpc
    from .settings import Settings
    from .store import Store
    from .watchdog import Watchdog

    settings = Settings(SETTINGS_PATH)
    store = Store(DB_PATH, KEY_PATH)
    if not store.encrypted:
        log("SQLCipher missing: the index is NOT encrypted", "warn")
    vindex = embed.VectorIndex()
    activity = Activity()
    ui = {}
    hooks = ui_hooks(ui)            # "reload_ui" finds no window here and does nothing
    watchdog = Watchdog(activity, **{k: hooks[k] for k in ("release", "recycle", "reload_ui", "quit_app",
                                                           "visible", "names")})
    apps = AppMemory(store)
    governor = Governor(settings, apps, activity, watchdog=watchdog, release_idle=hooks["release_idle"])
    governor.start()
    indexer = Indexer(store, settings, vindex, governor=governor, activity=activity)
    ui["indexer"] = indexer
    api = Api(store, settings, indexer, vindex, lambda: None)
    api._watchdog, api.visible = watchdog, False          # no page heartbeats to expect
    api._governor, api._activity, api._apps = governor, activity, apps
    ui["api"] = api
    stop = stop or threading.Event()
    api.quit = lambda: (stop.set(), {"ok": True})[1]       # the watchdog's last resort ends the engine cleanly
    rpc = Rpc(api)
    if not rpc.start():
        print("The NOBAD Find pipe is in use: another engine is running for this user.")
        governor.stop()
        return 1
    indexer.start()
    keys = [Hotkey(settings.get("hotkey"), lambda: rpc.show("main"))]
    if settings.get("bar"):
        keys.append(Hotkey(settings.get("bar_hotkey"), lambda: rpc.show("bar"), hk_id=2))
    for hk in keys:
        if not hk.start():
            log(f"engine: hotkey {hk.spec} not available (another app, or the NOBAD Find window, has it)", "warn")
    log(f"engine ready (pid {os.getpid()})")
    print(f"NOBAD Find engine ready (pid {os.getpid()}). Ctrl+C stops it.", flush=True)
    try:
        while not stop.wait(0.5):
            pass
    except KeyboardInterrupt:
        pass
    log("engine stopping")
    for hk in keys:
        hk.stop()
    rpc.stop()
    indexer.stop()
    governor.stop()
    indexer.join(5)                 # database writes are committed first
    log("engine stopped")
    return 0
