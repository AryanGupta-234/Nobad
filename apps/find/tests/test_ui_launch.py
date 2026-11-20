"""The engine starts the Flutter UI when a hotkey or the tray asks for a window and no UI is connected."""
import os

from nobadfind import uilaunch


class Events:
    def __init__(self):
        self.shown = []

    def show(self, what, text=None):
        self.shown.append(what)


def test_ui_exe_from_the_env_then_the_dev_build(tmp_path, monkeypatch):
    exe = tmp_path / "nobad_find.exe"
    exe.write_bytes(b"MZ")
    monkeypatch.setattr(uilaunch.sys, "frozen", False, raising=False)
    monkeypatch.setenv("NOBAD_FIND_UI_EXE", str(exe))
    assert uilaunch.ui_exe() == str(exe)
    monkeypatch.setenv("NOBAD_FIND_UI_EXE", str(tmp_path / "missing.exe"))
    dev = uilaunch.DEV_BUILD
    assert uilaunch.ui_exe() == (dev if os.path.isfile(dev) else None)
    assert dev.endswith(os.path.join("ui_flutter", "build", "windows", "x64", "runner", "Release", "nobad_find.exe"))


def test_frozen_engine_uses_the_ui_next_to_it(tmp_path, monkeypatch):
    engine = tmp_path / "NobadFind.exe"
    (tmp_path / "nobad_find.exe").write_bytes(b"MZ")
    monkeypatch.setattr(uilaunch.sys, "frozen", True, raising=False)
    monkeypatch.setattr(uilaunch.sys, "executable", str(engine))
    monkeypatch.delenv("NOBAD_FIND_UI_EXE", raising=False)
    assert uilaunch.ui_exe() == str(tmp_path / "nobad_find.exe")


def test_a_window_request_with_no_ui_starts_it_on_that_page():
    started, ev = [], Events()
    clock = [100.0]
    ui = uilaunch.Launcher(ev, connected=lambda: False, exe=lambda: r"C:\ui\nobad_find.exe",
                           start=started.append, clock=lambda: clock[0])
    ui.show("main")
    assert started == [[r"C:\ui\nobad_find.exe", "--page", "search"]] and ev.shown == []
    ui.show("settings")                                     # still starting: not a second copy
    assert len(started) == 1
    clock[0] += 20
    ui.show("bar")
    assert started[-1] == [r"C:\ui\nobad_find.exe", "--bar"]
    clock[0] += 20
    ui.show("index")
    assert started[-1][-2:] == ["--page", "index"]


def test_a_connected_ui_just_gets_the_show_event():
    started, ev = [], Events()
    ui = uilaunch.Launcher(ev, connected=lambda: True, exe=lambda: "x.exe", start=started.append)
    ui.show("settings")
    assert ev.shown == ["settings"] and started == []


def test_no_ui_installed_says_so_once():
    notes, ev = [], Events()
    ui = uilaunch.Launcher(ev, connected=lambda: False, exe=lambda: None, start=lambda a: None, note=notes.append)
    ui.show("main")
    ui.show("main")
    assert len(notes) == 1 and ev.shown == []
