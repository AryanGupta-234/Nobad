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
