"""NOBAD title bar: window actions, edge validation, geometry clamping and size memory (no real window needed)."""
from __future__ import annotations

from pathlib import Path

import pytest

import app_web.window as window_module
from app_web.api import api_post
from app_web.context import AppContext
from app_web.handlers import register_all
from app_web.settings_store import FIELDS_BY_ID, SettingError, coerce
from app_web.window import EDGES, MIN_H, MIN_W, WindowController, clamp_geometry

register_all()
SCREEN = (0, 0, 1920, 1080)
AREA = (0, 0, 1920, 1040)


# ---------------------------------------------------------------- geometry
def test_first_start_is_centred_on_the_work_area() -> None:
    assert clamp_geometry(None, SCREEN, AREA) == (320, 110, 1280, 820)


def test_a_mostly_off_screen_position_is_dropped() -> None:
    x, y, w, h = clamp_geometry({"x": 1800, "y": 900, "w": 1280, "h": 820}, SCREEN, AREA)
    assert (x, y) == (320, 110)


def test_a_partly_off_screen_position_slides_back_inside() -> None:
    assert clamp_geometry({"x": 700, "y": 100, "w": 1280, "h": 820}, SCREEN, AREA) == (640, 100, 1280, 820)


def test_sizes_never_go_below_the_minimum_or_above_the_screen() -> None:
    assert clamp_geometry({"w": 200, "h": 100}, SCREEN, AREA)[2:] == (MIN_W, MIN_H)
    assert clamp_geometry({"w": 5000, "h": 5000}, SCREEN, AREA)[2:] == (1920, 1040)


@pytest.mark.parametrize("saved", ["junk", {"w": "wide"}, {"x": True, "y": 0}])
def test_bad_saved_values_fall_back_to_defaults(saved: object) -> None:
    assert clamp_geometry(saved, SCREEN, AREA) == (320, 110, 1280, 820)


# ---------------------------------------------------------------- actions
class FakeNativeWindow:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.native = None

    def minimize(self) -> None:
        self.calls.append("minimize")

    def maximize(self) -> None:
        self.calls.append("maximize")

    def restore(self) -> None:
        self.calls.append("restore")

    def destroy(self) -> None:
        self.calls.append("destroy")


@pytest.fixture
def controller(monkeypatch: pytest.MonkeyPatch) -> WindowController:
    monkeypatch.setattr(window_module, "_WINDOWS", True)
    ctl = WindowController(frameless=True)
    ctl.frameless = True
    ctl.window = FakeNativeWindow()
    monkeypatch.setattr(ctl, "_hwnd", lambda: None)
    return ctl


def test_every_resize_edge_is_accepted_and_unknown_ones_are_refused(controller: WindowController) -> None:
    for edge in EDGES:                       # NOBAD VPN checks edges against its caption table, refusing all of them
        assert controller.action("resize", edge) == {"frameless": True, "maximized": False}
    with pytest.raises(ValueError):
        controller.action("resize", "move")
    with pytest.raises(ValueError):
        controller.action("explode")


def test_maximize_toggles_and_close_saves(controller: WindowController) -> None:
    saved: list[dict] = []
    controller._save = saved.append
    controller._load = lambda: None

    assert controller.action("maximize")["maximized"] is True
    assert controller.action("maximize")["maximized"] is False
    controller.action("minimize")
    controller.action("close")

    assert controller.window.calls == ["maximize", "restore", "minimize", "destroy"]
    assert saved and saved[-1]["maximized"] is False


def test_saved_size_compensates_for_the_frameless_border(controller: WindowController, monkeypatch: pytest.MonkeyPatch) -> None:
    controller._requested = (1280, 820)
    monkeypatch.setattr(controller, "_actual_size", lambda: (1264, 781))   # what pywebview really opens
    controller._measure_size_delta()
    controller._remember(w=1264, h=781)

    assert controller._geom == {"w": 1280, "h": 820}                       # no shrinking on the next start


def test_maximised_size_is_not_remembered(controller: WindowController) -> None:
    controller.maximized = True
    controller._remember(w=1920, h=1040)
    assert controller._geom == {}


# ---------------------------------------------------------------- API and setting
def test_window_api_without_a_window_reports_no_title_bar(tmp_path: Path) -> None:
    ctx = AppContext.create(tmp_path / "app.sqlite3")
    assert api_post("window.action", {"do": "state"}, ctx) == {"ok": True, "data": {"frameless": False, "maximized": False}}


def test_window_api_refuses_bad_input(tmp_path: Path, controller: WindowController) -> None:
    ctx = AppContext.create(tmp_path / "app.sqlite3")
    ctx.window = controller
    assert api_post("window.action", {"do": "resize", "edge": "nowhere"}, ctx) == {"ok": False, "error": "Unknown window edge."}
    assert not api_post("window.action", {"do": 5}, ctx)["ok"]
    assert api_post("window.action", {"do": "resize", "edge": "br"}, ctx)["ok"]


def test_window_geometry_round_trips_through_the_database(tmp_path: Path) -> None:
    ctx = AppContext.create(tmp_path / "app.sqlite3")
    ctx.save_window_geometry({"x": 10, "y": 20, "w": 1300, "h": 800, "maximized": True, "junk": "dropped"})
    assert ctx.load_window_geometry() == {"x": 10, "y": 20, "w": 1300, "h": 800, "maximized": True}


def test_title_bar_setting_is_on_by_default_and_only_accepts_booleans() -> None:
    spec = FIELDS_BY_ID["web_ui.custom_titlebar"]
    assert spec.default is True and coerce(spec, False) is False
    for bad in ("yes", 1, None):
        with pytest.raises(SettingError):
            coerce(spec, bad)


def test_visual_effects_are_off_by_default_like_nobad_vpn() -> None:
    spec = FIELDS_BY_ID["web_ui.visual_effects"]
    assert spec.default is False and spec.kind == "bool"


def test_linux_window_prefers_gtk_then_pyside6(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    import types

    from app_web import window as win

    fake_gi = types.ModuleType("gi")
    fake_gi.require_version = lambda name, version: None
    monkeypatch.setitem(sys.modules, "gi", fake_gi)
    assert win.linux_gui() == "gtk"

    def no_webkit(name, version):  # type: ignore[no-untyped-def]
        if name == "WebKit2":
            raise ValueError("Namespace WebKit2 not available")
    fake_gi.require_version = no_webkit
    monkeypatch.delenv("QT_API", raising=False)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object())
    assert win.linux_gui() == "qt" and __import__("os").environ["QT_API"] == "pyside6"

    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    with pytest.raises(win.WindowUnavailable) as err:
        win.linux_gui()
    assert "apt install python3-gi" in str(err.value) and "--browser" in str(err.value)


def test_windows_only_settings_are_hidden_elsewhere(monkeypatch: pytest.MonkeyPatch) -> None:
    from app_web import settings_store

    monkeypatch.setattr(settings_store.os, "name", "posix")
    assert "web_ui.custom_titlebar" not in [f["id"] for f in settings_store.schema()["fields"]]
