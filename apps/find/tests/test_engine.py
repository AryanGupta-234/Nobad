"""engine.py's wiring without Windows: idle start, the UI's window and indexing, quit order, hotkey notices,
and the one-at-a-time folder dialog."""
import threading
import time

from nobadfind import engine, settings as settings_mod, winapi
from nobadfind.api import Api
from nobadfind.rpc import handlers, protocol
from nobadfind.rpc.events import Events


class Ix:
    def __init__(self):
        self.calls = []
        self._running = False

    def start(self):
        if self._running:
            return False
        self._running = True
        self.calls.append("start")
        return True

    def stop(self, keep_watching=False):
        self._running = False
        self.calls.append("stop")

    def join(self, t=None):
        return True

    def release_models(self):
        self.calls.append("release")

    def warm_models(self):
        pass


class Conn:
    def __init__(self):
        self.events, self.shown, self.sent, self.pid, self.alive = set(), set(), [], 0, True

    def send(self, obj):
        self.sent.append(obj)
        return True


class Key:
    """A hotkey that registers (or not, when another app holds it)."""
    taken = set()

    def __init__(self, spec, callback, hk_id=1):
        self.spec, self.callback, self.ok = spec, callback, False

    def start(self):
        self.ok = self.spec not in Key.taken
        return self.ok

    def stop(self):
        pass


def wait_for(cond, secs=3.0):
    deadline = time.time() + secs
    while not cond() and time.time() < deadline:
        time.sleep(0.01)
    return cond()


def make(tmp_path, **changes):
    st = settings_mod.Settings(str(tmp_path / "s.json"))
    st.update(dict({"hotkey": "ctrl+alt+shift+f11", "bar_hotkey": "ctrl+alt+shift+f12"}, **changes))
    ix = Ix()
    api = Api(None, st, ix, None)
    conn = Conn()
    conn.events.update({"quitting", "notice", "show"})
    ev = Events(lambda: [conn], lambda c: None, api)
    stop = threading.Event()
    w = engine.Wiring(api, st, ix, ev, stop, ui_pids=lambda: set(), make_hotkey=Key, dialog=lambda: "C:\\x",
                      trim=lambda: None, launcher=lambda events: events)
    return w, api, ix, ev, conn, stop


def test_starts_idle_and_indexes_once_the_ui_shows(tmp_path):
    """Like app.py --background: no UI yet means no indexing, unless "Keep indexing in the background" is on."""
    w, api, ix, ev, conn, stop = make(tmp_path)
    w.start()
    time.sleep(0.1)
    assert ix.calls == []
    api.ui_shown()
    assert wait_for(lambda: ix.calls == ["start"])


def test_keep_background_indexes_from_the_start(tmp_path):
    w, api, ix, ev, conn, stop = make(tmp_path, keep_background=True)
    w.start()
    assert ix.calls == ["start"]


def test_the_ui_closing_stops_indexing_again(tmp_path):
    w, api, ix, ev, conn, stop = make(tmp_path)
    w.start()
    m = handlers.methods(api, ev)
    protocol.handle_line('{"jsonrpc":"2.0","id":1,"method":"ui_shown"}', m, conn)
    assert wait_for(lambda: ix.calls == ["start"])
    ev.gone(conn, api.hide)                                # its pipe closed (Rpc._dropped)
    assert wait_for(lambda: ix.calls == ["start", "stop", "release"])


def test_quit_from_the_watchdog_stops_at_once(tmp_path):
    w, api, ix, ev, conn, stop = make(tmp_path)
    assert api.quit() == {"ok": True}
    assert stop.is_set() and [m["method"] for m in conn.sent] == ["quitting"]


def test_quit_over_the_pipe_stops_only_after_the_reply(tmp_path):
    w, api, ix, ev, conn, stop = make(tmp_path)
    m = handlers.methods(api, ev)
    after = []
    r = protocol.handle_line('{"jsonrpc":"2.0","id":1,"method":"quit","params":{"confirm":"QUIT"}}', m, conn,
                             after=after)
    assert r["result"] == {"ok": True, "error": ""}
    assert [x["method"] for x in conn.sent] == ["quitting"] and not stop.is_set()
    for fn in after:                                       # Server._answer runs these once the reply is written
        fn()
    assert stop.is_set()


def test_hotkeys_another_app_holds_become_notices(tmp_path):
    w, api, ix, ev, conn, stop = make(tmp_path)
    Key.taken = {"ctrl+alt+shift+f11", "ctrl+alt+shift+f12"}
    try:
        keys = w.start()
    finally:
        Key.taken = set()
    assert len(keys) == 2
    assert [x["params"]["text"] for x in conn.sent] == [
        "The hotkey is used by another app. Pick another one in Settings.",
        "The quick find bar shortcut is used by another app. Pick another one in Settings."]


def test_bar_hotkey_shows_the_bar(tmp_path):
    w, api, ix, ev, conn, stop = make(tmp_path)
    keys = w.start()
    keys[1].callback()
    assert conn.sent[-1]["params"] == {"what": "bar", "text": None}


def test_pick_folder_uses_the_engine_dialog(tmp_path):
    w, api, ix, ev, conn, stop = make(tmp_path)
    m = handlers.methods(api, ev)
    r = protocol.handle_line('{"jsonrpc":"2.0","id":1,"method":"pick_folder"}', m, conn)
    assert r["result"] == {"path": "C:\\x", "busy": False}


def test_only_one_folder_dialog_at_a_time(monkeypatch):
    gate, entered = threading.Event(), threading.Event()

    def browse(title, out):
        entered.set()
        gate.wait(5)
        out.append("C:\\chosen")
    monkeypatch.setattr(winapi, "WIN", True)
    monkeypatch.setattr(winapi, "_browse_folder", browse)
    monkeypatch.setattr(winapi, "_front_dialog", lambda: None)
    got = []
    t = threading.Thread(target=lambda: got.append(winapi.pick_folder()))
    t.start()
    assert entered.wait(3)
    t0 = time.time()
    assert winapi.pick_folder() is None                    # busy: answered at once, not queued
    assert time.time() - t0 < 1
    gate.set()
    t.join(3)
    assert got == ["C:\\chosen"]


def test_measure_overrides_only_with_a_separate_index():
    env = {"NOBAD_FIND_MEASURE_LEVEL": "light", "NOBAD_FIND_MEASURE_PIPE": "run1"}
    assert engine.measure_overrides(env, r"C:/D/NOBAD/Find", r"C:/D/NOBAD/Find") == {"level": None, "pipe": None}
    got = engine.measure_overrides(env, r"C:/tmp/m", r"C:/D/NOBAD/Find", base="PIPE-S-1-5")
    assert got == {"level": "light", "pipe": "PIPE-S-1-5-measure-run1"}


def test_measure_overrides_refuse_odd_values():
    env = {"NOBAD_FIND_MEASURE_LEVEL": "turbo", "NOBAD_FIND_MEASURE_PIPE": "../x"}
    assert engine.measure_overrides(env, r"C:/tmp/m", r"C:/D", base="p") == {"level": None, "pipe": None}
    assert engine.measure_overrides({}, r"C:/tmp/m", r"C:/D", base="p") == {"level": None, "pipe": None}


def test_the_real_index_is_recognised_under_another_spelling(tmp_path):
    """An 8.3 short name (or a junction) for the default folder is still the real index: no dev switches, and the
    app's own lock."""
    import ctypes
    import pytest
    real = tmp_path / "Real Index Folder"
    real.mkdir()
    buf = ctypes.create_unicode_buffer(1024)
    if not ctypes.windll.kernel32.GetShortPathNameW(str(real), buf, 1024) or buf.value.lower() == str(real).lower():
        pytest.skip("no 8.3 names on this drive")
    env = {"NOBAD_FIND_MEASURE_LEVEL": "light", "NOBAD_FIND_MEASURE_PIPE": "x"}
    assert engine.measure_overrides(env, buf.value, str(real), base="p") == {"level": None, "pipe": None}
    assert engine.lock_name(buf.value, str(real)) == "Local\\NOBAD-Find"


class FakeUi:
    def __init__(self):
        self.asked = []

    def show(self, what, text=None):
        self.asked.append(what)

    def here(self, path):
        pass


def test_hotkeys_with_no_ui_go_through_the_launcher(tmp_path):
    """No UI connected: the launcher starts one on the right page (uilaunch.Launcher)."""
    st = settings_mod.Settings(str(tmp_path / "s.json"))
    st.update({"hotkey": "ctrl+alt+shift+f11", "bar_hotkey": "ctrl+alt+shift+f12"})
    ix, ui = Ix(), FakeUi()
    api = Api(None, st, ix, None)
    ev = Events(lambda: [], lambda c: None, api)
    w = engine.Wiring(api, st, ix, ev, threading.Event(), ui_pids=lambda: set(), make_hotkey=Key,
                      dialog=lambda: "x", trim=lambda: None, launcher=lambda events: ui)
    keys = w.start()
    keys[1].callback()
    keys[0].callback()
    assert ui.asked == ["bar", "main"]


def test_tray_actions(tmp_path):
    st = settings_mod.Settings(str(tmp_path / "s.json"))
    ix, ui = Ix(), FakeUi()
    api = Api(None, st, ix, None)
    paused = []
    api.pause_for = lambda s: paused.append(s) or {"ok": True}
    api.resume = lambda: paused.append("resume") or {"ok": True}
    ev = Events(lambda: [], lambda c: None, api)
    stop = threading.Event()
    w = engine.Wiring(api, st, ix, ev, stop, ui_pids=lambda: set(), make_hotkey=Key, dialog=lambda: "x",
                      trim=lambda: None, launcher=lambda events: ui)
    for action in ("open", "bar", "settings", "index", "pause", "resume"):
        w.tray_action(action)
    assert ui.asked == ["main", "bar", "settings", "index"] and paused == [3600, "resume"]
    w.tray_action("quit")
    assert stop.is_set()


def test_closing_the_last_window_quits_unless_stay_running(tmp_path):
    """0.8.5 (maintainer): closing NOBAD Find leaves no process running; "stay_running" keeps the old behaviour."""
    for stay in (False, True):
        st = settings_mod.Settings(str(tmp_path / f"s{stay}.json"))
        st.update({"stay_running": stay})
        ix, ui = Ix(), FakeUi()
        api = Api(None, st, ix, None)
        ev = Events(lambda: [], lambda c: None, api)
        stop = threading.Event()
        engine.Wiring(api, st, ix, ev, stop, ui_pids=lambda: set(), make_hotkey=Key, dialog=lambda: "x",
                      trim=lambda: None, launcher=lambda events: ui)
        api._on_all_closed()
        assert stop.is_set() is (not stay)
