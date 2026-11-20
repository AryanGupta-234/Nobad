"""The engine's tray icon: the menu, the tooltip and what a click does (the Win32 loop itself is tray.Tray)."""
import os

from nobadfind import const, settings, tray


def test_menu_has_the_items_and_pause_follows_the_state():
    items = [label for _id, label in tray.menu(paused=False) if label]
    assert items == ["Open NOBAD Find", "Quick find bar", "Pause for 1 hour", "Settings", "Index", "Quit NOBAD Find"]
    labels = dict(tray.menu(paused=True))
    assert tray.CMD["resume"] in labels and labels[tray.CMD["resume"]] == "Resume"
    assert tray.CMD["pause"] not in labels


def test_tooltip_shows_the_level_and_the_files():
    assert tray.tooltip({"level": "gentle", "files": 12345, "paused": ""}) == "NOBAD Find: Gentle, 12,345 files"
    assert tray.tooltip({"level": "paused", "files": 3, "paused": "on battery"}) == "NOBAD Find: Paused (on battery), 3 files"
    assert len(tray.tooltip({"level": "full", "files": 1, "paused": "x" * 400})) < 128     # Windows' limit


def test_clicks_and_commands_become_actions():
    got = []
    t = tray.Tray(got.append, tip=lambda: "x", paused=lambda: False)
    t._on_click(tray.WM_LBUTTONUP)
    t._on_command(tray.CMD["settings"])
    t._on_command(tray.CMD["quit"])
    t._on_command(9999)                                   # not ours: ignored
    assert got == ["open", "settings", "quit"]


def test_tray_setting_defaults_on(tmp_path):
    assert const.DEFAULTS["tray"] is True
    st = settings.Settings(str(tmp_path / "s.json"))
    st.update({"tray": "yes"})                            # not a bool: refused
    assert st.get("tray") is True


def test_the_icon_file_is_there():
    assert os.path.isfile(tray.icon_path()) or tray.icon_path() == ""
