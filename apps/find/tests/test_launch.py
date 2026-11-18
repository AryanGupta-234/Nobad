"""Starting NOBAD Find while it already runs brings the running copy up; it never silently does nothing."""
import pathlib
import sys

import pytest

from nobadfind import app, winapi

UI = pathlib.Path(__file__).resolve().parent.parent / "nobadfind" / "ui" / "app.js"
ISS = pathlib.Path(__file__).resolve().parent.parent / "packaging" / "installer.iss"


def _second_copy(monkeypatch, argv):
    calls = []
    monkeypatch.setattr(winapi, "is_admin", lambda: False)
    monkeypatch.setattr(app, "single_instance", lambda: False)
    monkeypatch.setattr(winapi, "ask_running_copy_to_show", lambda: calls.append("show") or True)
    assert app.main(argv) == 0
    return calls


def test_second_start_shows_the_running_window(monkeypatch):
    assert _second_copy(monkeypatch, []) == ["show"]


def test_second_background_start_stays_quiet(monkeypatch):
    assert _second_copy(monkeypatch, ["--background"]) == []     # Start with Windows must not pop the window up


def test_admin_start_explains_itself_visibly(monkeypatch):
    said = []
    monkeypatch.setattr(winapi, "is_admin", lambda: True)
    monkeypatch.setattr(winapi, "message", lambda text, title="NOBAD Find": said.append(text))
    assert app.main([]) == 1
    assert said and "normal account" in said[0]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows event objects")
def test_show_event_round_trip():
    h = winapi.show_event()
    assert h
    assert not winapi.wait_event(h, 0)
    assert winapi.ask_running_copy_to_show()
    assert winapi.wait_event(h, 1000)
    assert not winapi.wait_event(h, 0)                           # auto-reset: one request, one show


def test_settings_has_a_real_quit():
    js = UI.read_text(encoding="utf-8")
    assert '"_quit", "quit"' in js and 'id="quitApp"' in js and 'api("quit")' in js


def test_installer_starts_the_app_as_the_signed_in_user():
    assert "runasoriginaluser" in ISS.read_text(encoding="utf-8")


def test_installer_stops_find_quickly_by_session_not_user_name():
    # "USERNAME eq" made every taskkill take ~30 s (owner lookup of every process): setup looked stuck.
    iss = ISS.read_text(encoding="utf-8")
    stop = iss[iss.index("procedure StopFind;"):iss.index("function PrepareToInstall")]
    assert '"SESSION eq ' in stop and "USERNAME eq" not in stop


def test_enter_keeps_the_window_up_unless_asked():
    # Enter used to open the file and hide the window, which looked like the app closing.
    from nobadfind.const import DEFAULTS
    js = UI.read_text(encoding="utf-8")
    assert DEFAULTS["hide_after_open"] is False
    assert '"hide_after_open", "switch"' in js
    opener = js[js.index('if (kind === "open")'):].split("\n", 1)[0]
    assert ".hide_after_open) api(\"hide\")" in opener


def test_splash_closed_in_app():
    root = pathlib.Path(__file__).resolve().parent.parent
    src = (root / "nobadfind" / "app.py").read_text(encoding="utf-8")
    assert "pyi_splash" in src and ".close()" in src and "except ImportError" in src
    assert "Splash(" in (root / "packaging" / "nobadfind.spec").read_text(encoding="utf-8")
    assert (root / "nobadfind" / "ui" / "brand" / "splash.png").exists()


def _launch_module(monkeypatch):
    import importlib.util
    monkeypatch.setenv("PYINSTALLER_SUPPRESS_SPLASH_SCREEN", "0")     # put back after the test
    path = pathlib.Path(__file__).resolve().parent.parent / "packaging" / "launch.py"
    spec = importlib.util.spec_from_file_location("nf_launch_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)                 # no pyi_splash here: nothing is closed on import
    import os
    assert os.environ["PYINSTALLER_SUPPRESS_SPLASH_SCREEN"] == "1"    # workers started later never show it
    return mod


def test_no_splash_for_starts_without_a_window(monkeypatch):
    """M-1: --background (Windows login), --version, --wsearch, --uninstall, worker processes and a second start
    close the start-up picture before the heavy imports; a normal first start keeps it until the page loads."""
    import types
    launch = _launch_module(monkeypatch)
    closed = []
    monkeypatch.setitem(sys.modules, "pyi_splash", types.SimpleNamespace(close=lambda: closed.append(1)))
    monkeypatch.setattr(launch, "already_running", lambda: False)
    for argv in (["x", "--background"], ["x", "--version"], ["x", "--wsearch", "auto"], ["x", "--wsearch=demand"],
                 ["x", "--uninstall"], ["x", "--multiprocessing-fork", "parent_pid=1", "pipe_handle=2"]):
        assert launch.close_splash_early(argv) is True, argv
    assert launch.close_splash_early(["x"]) is False and len(closed) == 6
    monkeypatch.setattr(launch, "already_running", lambda: True)
    assert launch.close_splash_early(["x"]) is True


@pytest.mark.skipif(sys.platform != "win32", reason="Windows mutex")
def test_already_running_sees_the_app_mutex(monkeypatch):
    import ctypes
    launch = _launch_module(monkeypatch)
    assert launch.already_running() is False
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateMutexW.restype = ctypes.c_void_p
    k.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    h = k.CreateMutexW(None, False, launch.MUTEX)
    try:
        assert launch.already_running() is True
    finally:
        k.CloseHandle(h)


def test_watchdog_hooks_are_safe_before_the_pieces_exist():
    """M-3: the governor (and its watchdog) start before the indexer, api and window: no KeyError every 2 s."""
    ui = {}
    hooks = app.ui_hooks(ui)
    assert hooks["visible"]() is False and hooks["names"]() == {}
    for k in ("release", "recycle", "release_idle", "reload_ui", "quit_app"):
        assert hooks[k]() is None

    class Ix:
        def worker_names(self):
            return {7: "text reader"}
    ui["indexer"] = Ix()
    assert hooks["names"]() == {7: "text reader"}


def test_logging_starts_before_the_job_setup():
    """M-2: jobs.setup() logs its failures, so the log must be open first."""
    src = (pathlib.Path(__file__).resolve().parent.parent / "nobadfind" / "app.py").read_text(encoding="utf-8")
    body = src[src.index("def main("):]
    assert body.index("init_log(LOG_PATH)") < body.index("jobs.setup()")


def test_closing_quit_path_arms_the_hard_exit():
    """Re-review: closing with no hotkey quits through closing(); a hung WebView2 teardown must still end."""
    armed, stopped = [], []

    class Api:
        def _arm_hard_exit(self):
            armed.append(1)

    class Stops:
        def __init__(self, name):
            self.name = name

        def stop(self):
            stopped.append(self.name)

        close = stop
    app.quit_teardown(Api(), Stops("indexer"), Stops("governor"), Stops("hotkey"), [Stops("bar hotkey")],
                      Stops("bar"))
    assert armed == [1] and stopped == ["indexer", "governor", "hotkey", "bar hotkey", "bar"]
