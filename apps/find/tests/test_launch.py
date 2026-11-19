"""Starting NOBAD Find: the engine starts the Flutter UI; a second start brings the running copy's window up on the
page asked for; it never silently does nothing."""
import pathlib
import sys
import threading

import pytest

from nobadfind import app, engine, winapi

APP = pathlib.Path(__file__).resolve().parent.parent
ISS = APP / "packaging" / "installer.iss"


def _second_copy(monkeypatch, argv):
    calls = []
    monkeypatch.setattr(winapi, "is_admin", lambda: False)
    monkeypatch.setattr(engine, "_single", lambda name: False)
    monkeypatch.setattr(winapi, "ask_running_copy_to_show",
                        lambda what="main", base=winapi.SHOW_EVENT: calls.append((what, base)) or True)
    assert app.main(argv) == 0
    return calls


def test_second_start_shows_the_running_window(monkeypatch):
    assert _second_copy(monkeypatch, []) == [("main", engine.show_base(engine.lock_name()))]


def test_second_start_forwards_the_page_and_the_bar(monkeypatch):
    assert [w for w, _b in _second_copy(monkeypatch, ["--page", "settings"])] == ["settings"]
    assert [w for w, _b in _second_copy(monkeypatch, ["--page", "index"])] == ["index"]
    assert [w for w, _b in _second_copy(monkeypatch, ["--page", "search"])] == ["main"]
    assert [w for w, _b in _second_copy(monkeypatch, ["--bar"])] == ["bar"]


def test_second_background_start_stays_quiet(monkeypatch):
    assert _second_copy(monkeypatch, ["--background"]) == []     # Start with Windows must not pop the window up


def test_the_first_window_each_start_asks_for():
    def first(*argv):
        return app.first_window(app.parse_args(list(argv)))
    assert first() == "main" and first("--page", "search") == "main"
    assert first("--page", "settings") == "settings" and first("--bar") == "bar"
    assert first("--background") is None and first("--engine") is None
    with pytest.raises(SystemExit):
        app.parse_args(["--page", "http://x"])


def test_the_real_index_keeps_the_old_show_event_name():
    """A 0.8.0 start (or anything that signals winapi.SHOW_EVENT) still reaches the main window."""
    assert engine.show_base("Local\\NOBAD-Find") == winapi.SHOW_EVENT
    assert winapi.show_event_name("main") == winapi.SHOW_EVENT
    assert winapi.show_event_name("bar") == winapi.SHOW_EVENT + "-bar"
    with pytest.raises(ValueError):
        winapi.show_event_name("C:\\x")


def test_admin_start_explains_itself_visibly(monkeypatch):
    said = []
    monkeypatch.setattr(winapi, "is_admin", lambda: True)
    monkeypatch.setattr(winapi, "message", lambda text, title="NOBAD Find": said.append(text))
    assert app.main([]) == 1
    assert said and "normal account" in said[0]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows event objects")
def test_show_event_round_trip():
    base = "Local\\NOBAD-Find-test-" + str(id(object()))
    h = winapi.show_event("settings", base)
    assert h
    assert not winapi.wait_event(h, 0)
    assert winapi.ask_running_copy_to_show("settings", base)
    assert winapi.wait_event(h, 1000)
    assert not winapi.wait_event(h, 0)                           # auto-reset: one request, one show
    assert not winapi.ask_running_copy_to_show("index", base)    # nobody listens for that page


@pytest.mark.skipif(sys.platform != "win32", reason="Windows event objects")
def test_show_requests_reach_the_engine():
    base = "Local\\NOBAD-Find-test-" + str(id(object()))
    stop, got = threading.Event(), []
    done = threading.Event()

    def show(what):
        got.append(what)
        if len(got) == 2:
            done.set()
    assert engine.show_requests(base, show, stop)
    try:
        assert winapi.ask_running_copy_to_show("bar", base)
        for _ in range(300):
            if got:
                break
            done.wait(0.01)
        assert got == ["bar"]
        assert winapi.ask_running_copy_to_show("main", base)
        assert done.wait(3)
        assert got == ["bar", "main"]
    finally:
        stop.set()


def test_show_requests_without_events_say_so():
    assert engine.show_requests("x", lambda w: None, threading.Event(), make=lambda what, base: None) is None


def test_installer_starts_the_app_as_the_signed_in_user():
    assert "runasoriginaluser" in ISS.read_text(encoding="utf-8")


def test_installer_stops_find_quickly_by_session_not_user_name():
    # "USERNAME eq" made every taskkill take ~30 s (owner lookup of every process): setup looked stuck.
    iss = ISS.read_text(encoding="utf-8")
    stop = iss[iss.index("procedure StopFind;"):iss.index("function PrepareToInstall")]
    assert '"SESSION eq ' in stop and "USERNAME eq" not in stop


def test_installer_stops_the_ui_too():
    """The UI runs outside the engine's job: upgrades and uninstalls stop nobad_find.exe as well."""
    iss = ISS.read_text(encoding="utf-8")
    stop = iss[iss.index("procedure StopFind;"):iss.index("function PrepareToInstall")]
    assert "{#MyUiExe}" in stop and '#define MyUiExe "nobad_find.exe"' in iss


def test_enter_keeps_the_window_up_unless_asked():
    # Enter used to open the file and hide the window, which looked like the app closing.
    from nobadfind.const import DEFAULTS
    assert DEFAULTS["hide_after_open"] is False


def test_watchdog_hooks_are_safe_before_the_pieces_exist():
    """M-3: the governor (and its watchdog) start before the indexer: no KeyError every 2 s."""
    pieces = {}
    hooks = engine.worker_hooks(pieces)
    assert hooks["names"]() == {}
    for k in ("release", "recycle", "release_idle"):
        assert hooks[k]() is None

    class Ix:
        def worker_names(self):
            return {7: "text reader"}
    pieces["indexer"] = Ix()
    assert hooks["names"]() == {7: "text reader"}


def test_logging_starts_before_the_job_setup():
    """M-2: jobs.setup() logs its failures, so the log must be open first."""
    src = (APP / "nobadfind" / "engine.py").read_text(encoding="utf-8")
    body = src[src.index("def run("):]
    assert body.index("init_log(LOG_PATH)") < body.index("jobs.setup()")


def test_no_web_view_is_left():
    """0.8.5: the pywebview window is gone; the window is the Flutter UI (ui_flutter, nobad_find.exe)."""
    assert not (APP / "nobadfind" / "ui").exists() and not (APP / "nobadfind" / "bar.py").exists()
    for name in ("requirements.txt", "requirements-lock.txt", "pyproject.toml", "packaging/nobadfind.spec"):
        text = (APP / name).read_text(encoding="utf-8").lower()
        assert "webview" not in text and "pythonnet" not in text, name
    for f in (APP / "nobadfind").rglob("*.py"):
        assert "import webview" not in f.read_text(encoding="utf-8"), f
