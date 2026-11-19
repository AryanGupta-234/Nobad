import os

import pytest

from nobadfind import api as api_mod, hardware, settings, winapi
from nobadfind.activity import Activity
from nobadfind.governor import Decision
from nobadfind.store import Store


class Ix:
    embedder = photo_text = pindex = None
    drive_list = []

    def __init__(self, phase="text"):
        self.status = {"phase": phase, "files": 3, "texts": 0, "vectors": 0, "paused": "", "rate": 0, "errors": 0,
                       "plan": {}, "last_scan": 0}

    def models_loaded(self):
        return []

    def roots(self, drives=None):
        return []

    def worker_names(self):
        return {}


class Gov:
    decision = Decision("gentle", "Gentle: you are using the PC")
    history = [{"t": 1.0, "cpu": 5.0, "gpu": 2.0, "find_cpu": 1.0, "find_mb": 100, "level": "gentle"}]

    def __init__(self):
        self.calls = []

    def pause_for(self, s):
        self.calls.append(("pause", s))

    def resume(self):
        self.calls.append(("resume",))


def make(tmp_path, phase="text", **changes):
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    s.upsert_files([("C:/p/a.docx", "a.docx", "C:/p", ".docx", "document", 10, 1.0, 1.0, 1),
                    ("C:/p/b.pdf", "b.pdf", "C:/p", ".pdf", "document", 10, 1.0, 1.0, 1),
                    ("C:/p/c.jpg", "c.jpg", "C:/p", ".jpg", "image", 50000, 1.0, 1.0, 1)])
    st = settings.Settings(str(tmp_path / "s.json"))
    if changes:
        st.update(changes)
    a = api_mod.Api(s, st, Ix(phase), None, lambda: None)
    a._governor, a._activity = Gov(), Activity()
    return a, s


def test_status_has_transparency_keys(tmp_path):
    a, s = make(tmp_path)
    a._activity.add("info", "hello")
    st = a.status()
    assert st["level"] == "gentle" and st["reason"].startswith("Gentle")
    assert isinstance(st["history"], list) and st["history"][0]["find_mb"] == 100
    r = st["resources"]
    assert isinstance(r["cpu"], float) and isinstance(r["memory_mb"], int) and isinstance(r["read_mb_s"], float)
    assert r["gpu"] == 2.0 and isinstance(r["processes"], list)
    for p in r["processes"]:
        assert set(p) == {"name", "pid", "cpu", "memory_mb"}
    assert {p["id"] for p in st["phases"]} == {"names", "text", "ocr", "meaning", "rebuild", "photos", "watching"}
    for p in st["phases"]:
        assert p["state"] in ("waiting", "running", "done", "off")
        assert isinstance(p["label"], str) and isinstance(p["done"], int) and isinstance(p["rate"], float)
        assert p["total"] is None or isinstance(p["total"], int)
        assert p["eta_s"] is None or isinstance(p["eta_s"], int)
    assert [m["id"] for m in st["models"]] == ["meaning", "photo", "ocr"]
    assert st["activity"][0]["text"] == "hello"
    assert st["files"] == 3 and "model" in st and "photo_model" in st      # old keys stay
    s.close()


def test_status_without_governor(tmp_path):
    a, s = make(tmp_path)
    a._governor = a._activity = None
    st = a.status()
    assert st["history"] == [] and st["activity"] == [] and st["resources"]["gpu"] is None
    assert a.pause_for(60) == {"ok": False} and a.resume() == {"ok": False}
    s.close()


def test_phase_states(tmp_path):
    a, s = make(tmp_path, "text")
    ph = {p["id"]: p for p in a.status()["phases"]}
    assert ph["text"]["state"] == "running" and ph["text"]["total"] == 2 and ph["text"]["done"] == 0
    assert ph["names"]["state"] == "done"
    assert ph["meaning"]["state"] == "off"                     # meaning search is not on
    s.close()
    a, s = make(tmp_path, "text", content=False)
    ph = {p["id"]: p for p in a.status()["phases"]}
    assert ph["text"]["state"] == "off" and ph["ocr"]["state"] == "off"
    s.close()


def test_phase_done_and_eta(tmp_path):
    a, s = make(tmp_path, "watching")
    s.set_text(1, 1.0, ["x"])
    s.set_text(2, 1.0, ["y"])
    ph = {p["id"]: p for p in a.status()["phases"]}
    assert ph["text"]["state"] == "done" and ph["text"]["done"] == 2
    assert ph["watching"]["state"] == "running"
    s.close()


def test_models_cards_for_meaning_photo_ocr(tmp_path):
    a, s = make(tmp_path)
    a._model.update(state="downloading", got=5 * 1048576, size=23 * 1048576)
    m = {x["id"]: x for x in a.status()["models"]}
    assert m["meaning"]["license"] == "Apache-2.0" and m["meaning"]["size_mb"] == 22
    assert m["meaning"]["download"]["got_mb"] == 5 and m["meaning"]["download"]["size_mb"] == 23
    assert m["photo"]["download"] is None and m["photo"]["size_mb"] > 100
    assert m["ocr"]["device"] == "Windows" and m["ocr"]["size_mb"] == 0 and m["ocr"]["memory_mb"] is None
    for x in m.values():
        assert isinstance(x["on_disk"], bool) and isinstance(x["loaded"], bool) and isinstance(x["items"], int)
    s.close()


def test_pause_for_and_resume_reach_the_governor(tmp_path):
    a, s = make(tmp_path)
    assert a.pause_for(900) == {"ok": True}
    assert a.resume() == {"ok": True}
    assert a._governor.calls == [("pause", 900), ("resume",)]
    assert a.pause_for("x") == {"ok": False} and a.pause_for(True) == {"ok": False}
    s.close()


def test_learned_apps_and_reset(tmp_path):
    class Apps:
        def __init__(self):
            self.reset_with = "unset"

        def list(self):
            return [{"exe": "game.exe"}]

        def reset(self, exe=None):
            self.reset_with = exe
    a, s = make(tmp_path)
    assert a.learned_apps() == []
    a._apps = Apps()
    assert a.learned_apps() == [{"exe": "game.exe"}]
    a.reset_learned(None)
    assert a._apps.reset_with is None
    a.reset_learned("game.exe")
    assert a._apps.reset_with == "game.exe"
    assert a.reset_learned(5) == {"ok": False}
    s.close()


@pytest.mark.skipif(not winapi.WIN, reason="Windows only")
def test_hardware_scan_shape():
    h = hardware.scan()
    assert h["ram_gb"] > 0 and h["cores"] >= 1 and h["threads"] >= h["cores"]
    assert isinstance(h["avx2"], bool) and isinstance(h["avx512_vnni"], bool)
    assert isinstance(h["gpu"], str) and h["vram_gb"] >= 0 and isinstance(h["directml"], bool)
    assert h["disk_free_gb"] >= 0 and h["ssd"] in (True, False, None)
    assert hardware.scan() is h                                  # cached


def _clock(a):
    t = [0.0]
    a._clock = lambda: t[0]
    return t


class FakeJob:
    def __init__(self):
        self.cpu, self.read = 0.0, 0

    def pids(self):
        return [os.getpid(), 999]

    def usage(self):
        return {"cpu_seconds": self.cpu, "read_bytes": self.read, "write_bytes": 0, "memory_mb": 0, "processes": 2}


def test_resource_rates_are_deltas(tmp_path, monkeypatch):
    a, s = make(tmp_path)
    t = _clock(a)
    job, secs = FakeJob(), {os.getpid(): 0.0, 999: 0.0}
    monkeypatch.setattr(api_mod.jobs, "OUTER", job)
    monkeypatch.setattr(api_mod.jobs, "process_info",
                        lambda pid: {"pid": pid, "cpu_seconds": secs[pid], "memory_mb": 50 if pid == 999 else 100})
    r = a.status()["resources"]
    assert r["cpu"] == 0.0 and r["read_mb_s"] == 0.0 and r["memory_mb"] == 150          # first call: no rates
    t[0] = 10.0
    cores = os.cpu_count() or 1
    job.cpu, job.read, secs[999] = 5.0, 20 * 1048576, 5.0
    r = a.status()["resources"]
    assert r["read_mb_s"] == 2.0
    assert r["cpu"] == round(5.0 / 10 / cores * 100, 1)
    proc = {p["pid"]: p for p in r["processes"]}
    assert proc[os.getpid()]["name"] == "Main" and proc[999]["name"] == "Window (WebView2)"
    assert proc[999]["cpu"] == round(5.0 / 10 / cores * 100, 1) and proc[os.getpid()]["cpu"] == 0.0
    s.close()


def test_model_cards_describe_the_worker(tmp_path, monkeypatch):
    a, s = make(tmp_path)
    a._indexer.worker_names = lambda: {999: "meaning worker"}
    a._indexer.meaning_device = lambda: "GPU"
    monkeypatch.setattr(api_mod.jobs, "OUTER", FakeJob())
    monkeypatch.setattr(api_mod.jobs, "process_info", lambda pid: {"pid": pid, "cpu_seconds": 0.0, "memory_mb": 77})
    m = {x["id"]: x for x in a.status()["models"]}
    assert m["meaning"]["loaded"] and m["meaning"]["memory_mb"] == 77 and m["meaning"]["device"] == "GPU"
    assert not m["photo"]["loaded"] and m["photo"]["memory_mb"] is None and m["photo"]["device"] == "CPU"
    s.close()


def test_eta_rate_window_and_reset(tmp_path):
    a, s = make(tmp_path, "text")
    t = _clock(a)
    a._indexer.status["texts"] = 0
    a.status()
    t[0] = 10.0
    a._indexer.status["texts"] = 20
    ph = {p["id"]: p for p in a.status()["phases"]}["text"]
    remaining = ph["total"] - ph["done"]
    assert ph["rate"] == 2.0 and ph["eta_s"] == int(remaining / 2.0)
    t[0] = 11.0
    a._indexer.status["phase"] = "watching"
    a.status()
    t[0] = 12.0
    a._indexer.status.update(phase="text", texts=40)
    ph = {p["id"]: p for p in a.status()["phases"]}["text"]
    assert ph["rate"] == 0.0 and ph["eta_s"] is None          # old samples were dropped when the phase stopped
    s.close()


def test_download_speed(tmp_path):
    a, s = make(tmp_path)
    t = _clock(a)
    a._model.update(state="downloading", got=5 * 1048576, size=23 * 1048576)
    assert a.status()["models"][0]["download"]["mb_s"] == 0.0
    t[0] = 5.0
    a._model["got"] = 15 * 1048576
    assert a.status()["models"][0]["download"]["mb_s"] == 2.0
    s.close()


def test_counts_are_cached_and_refreshed_in_background(tmp_path):
    a, s = make(tmp_path)
    calls = []
    real = s.count_needs_text
    s.count_needs_text = lambda *x, **k: (calls.append(1), real(*x, **k))[1]
    first = a._counts(0.0)
    n = len(calls)
    assert n > 0
    assert a._counts(5.0) is first and len(calls) == n          # inside 10 s: no queries
    assert a._counts(11.0) is first                              # stale: old values now, refresh in the background
    a._refresher.join(5)
    assert len(calls) > n and a._counts(12.0) is not first
    s.close()


def test_newest_first_listing_and_version_for_the_home_screen(tmp_path):
    a, s = make(tmp_path)
    r = a.search("", {"sort": "newest"})                      # the Home screen's "Recently changed"
    assert {x["name"] for x in r["results"]} == {"a.docx", "b.pdf", "c.jpg"}
    assert a.search("", {"sort": "bogus"})["results"] == []   # an unknown order alone is still not a search
    assert a.search("", {})["results"] == []
    from nobadfind.const import APP_VER
    assert a.status()["version"] == APP_VER


def test_open_starts_the_file_outside_finds_job(tmp_path, monkeypatch):
    """C-1: Api.open goes through the breakaway launcher, so Quit never takes the opened app down."""
    a, s = make(tmp_path)
    f = tmp_path / "note.txt"
    f.write_text("hi")
    s.upsert_files([(str(f), "note.txt", str(tmp_path), ".txt", "text", 2, 1.0, 1.0, 1)])
    fid = s.one("SELECT id FROM files WHERE path=?", (str(f),))
    opened, started = [], []
    monkeypatch.setattr(api_mod.winapi, "open_outside_job", lambda p: opened.append(p))
    monkeypatch.setattr(api_mod.os, "startfile", lambda p: started.append(p), raising=False)
    assert a.open(fid) == {"ok": True}
    assert opened == [str(f)] and started == []

    def refused(p):
        raise PermissionError(5, "Access is denied")
    monkeypatch.setattr(api_mod.winapi, "open_outside_job", refused)
    assert a.open(fid) == {"ok": True}                  # breakaway refused: the old way, logged
    assert started == [str(f)]
    s.close()


def test_open_outside_job_starts_explorer_with_breakaway(monkeypatch):
    calls = []

    class P:
        def __init__(self, argv, **kw):
            calls.append((argv, kw))
    monkeypatch.setattr(winapi.subprocess, "Popen", P)
    monkeypatch.setenv("WINDIR", r"C:\Windows")
    path = "C:\\a, b & c\\\u00e4 \u65e5.txt"
    winapi.open_outside_job(path)
    argv, kw = calls[0]
    assert argv == [os.path.join(r"C:\Windows", "explorer.exe"), path]       # a list: no shell string
    assert kw["creationflags"] & winapi.CREATE_BREAKAWAY_FROM_JOB and not kw.get("shell")


class _Timer:
    made = []

    def __init__(self, secs, fn):
        self.secs, self.fn, self.daemon, self.started = secs, fn, False, False
        _Timer.made.append(self)

    def start(self):
        self.started = True


class _StopIx(Ix):
    def __init__(self):
        super().__init__()
        self.calls = []

    def stop(self, keep_watching=False):
        self.calls.append("stop")

    def join(self, timeout=10):
        self.calls.append(("join", timeout))
        return True


def test_quit_arms_a_hard_exit_that_lets_the_indexer_finish_first(tmp_path):
    """I-1: a hung window teardown can't keep NOBAD Find running; the indexer stops and is joined before the
    process ends, so a SQLite write in progress is committed."""
    a, s = make(tmp_path)
    a._indexer = _StopIx()
    exits, destroyed = [], []

    class W:
        def destroy(self):
            destroyed.append(1)
    a._win = lambda: W()
    a._timer, a._exit = _Timer, exits.append
    _Timer.made.clear()
    assert a.quit() == {"ok": True}
    t = _Timer.made[0]
    assert t.secs == api_mod.QUIT_TIMEOUT == 15 and t.daemon and t.started and destroyed
    assert exits == []                                # nothing happens unless the quit hangs
    a._indexer.calls.clear()
    t.fn()
    assert a._indexer.calls == ["stop", ("join", 5)] and exits == [0]
    s.close()


def test_hide_tells_the_app(tmp_path):
    """I-2: Api.hide calls the app's hook (app.py: lifecycle.after_hide) after hiding the window."""
    a, s = make(tmp_path)
    order = []

    class W:
        def hide(self):
            order.append("hide")
    a._win = lambda: W()
    assert a.hide() == {"ok": True}                  # no hook set: just hides
    a._on_hide = lambda: order.append("hook")
    a.hide()
    assert order == ["hide", "hide", "hook"] and a.visible is False
    s.close()


def _exposed(obj, base="", out=None, seen=None):
    """pywebview 6.2's js_api walk (webview/util.py get_functions): every public method, recursing into
    public non-callable attributes."""
    import inspect
    out = {} if out is None else out
    seen = set() if seen is None else seen
    if id(obj) in seen:
        return out
    seen.add(id(obj))
    for name in dir(obj):
        if name.startswith("_"):
            continue
        full = f"{base}.{name}" if base else name
        try:
            attr = getattr(obj, name)
        except Exception:
            continue
        if inspect.ismethod(attr) or inspect.isfunction(attr):
            out[full] = True
        elif inspect.isclass(attr) or (not callable(attr) and hasattr(attr, "__module__")):
            _exposed(attr, full, out, seen)
    return out


API_METHODS = {"download_model", "download_photo_model", "downloads", "forget", "get_settings", "hardware", "heartbeat",
               "here_folder", "hide", "learned_apps", "open", "page_visible", "path_of", "pause_for", "pick_folder",
               "quit", "rescan", "reset_learned", "resume", "reveal", "search", "set_settings", "status",
               "status_brief", "thumbnail", "ui_shown", "scope_info", "turbo_state", "turbo_set",
               "use_instead_of_windows_search", "wipe", "wsearch_set", "wsearch_state",
               # 0.8.0: Open with and the model tiers (the WebView page may call them like any Api method)
               "open_with", "models", "model_use", "model_download", "model_remove", "auto_configure",
               "model_language"}


def test_the_page_sees_only_the_api_methods(tmp_path):
    """I-5: wired like app.py does, the page can reach the checked methods and nothing nested
    (no store.q, store.wipe, governor.stop, settings.update, watchdog.check)."""
    from nobadfind import bar
    from nobadfind.appmemory import AppMemory
    from nobadfind.governor import Governor
    from nobadfind.watchdog import Watchdog
    a, s = make(tmp_path)
    act = Activity()
    apps = AppMemory(s)
    wd = Watchdog(act)
    a._watchdog, a._governor, a._activity, a._apps = wd, Governor(a._settings, apps, act, watchdog=wd), act, apps
    a.visible, a.here = True, r"C:\Users"
    a._on_hide = lambda: None
    assert set(_exposed(a)) == API_METHODS
    b = bar.BarApi(a, bar.Bar(lambda: None, False), lambda text: None)
    assert set(_exposed(b)) == {"blurred", "fit", "hide", "open", "reveal", "search", "to_main"}
    s.close()


def test_hard_exit_is_armed_once(tmp_path):
    a, s = make(tmp_path)
    a._timer = _Timer
    _Timer.made.clear()
    a._arm_hard_exit()
    a._arm_hard_exit()
    assert len(_Timer.made) == 1 and _Timer.made[0].daemon and _Timer.made[0].started
    s.close()
