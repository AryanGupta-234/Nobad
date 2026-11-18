import pytest

from nobadfind import api as api_mod, hardware, settings, winapi
from nobadfind.activity import Activity
from nobadfind.governor import Decision
from nobadfind.store import Store


class Ix:
    embedder = photo_text = None
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
    a.governor, a.activity = Gov(), Activity()
    return a, s


def test_status_has_transparency_keys(tmp_path):
    a, s = make(tmp_path)
    a.activity.add("info", "hello")
    st = a.status()
    assert st["level"] == "gentle" and st["reason"].startswith("Gentle")
    assert isinstance(st["history"], list) and st["history"][0]["find_mb"] == 100
    r = st["resources"]
    assert isinstance(r["cpu"], float) and isinstance(r["memory_mb"], int) and isinstance(r["read_mb_s"], float)
    assert r["gpu"] == 2.0 and isinstance(r["processes"], list)
    for p in r["processes"]:
        assert set(p) == {"name", "pid", "cpu", "memory_mb"}
    assert {p["id"] for p in st["phases"]} == {"names", "text", "ocr", "meaning", "photos", "watching"}
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
    a.governor = a.activity = None
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
    assert a.governor.calls == [("pause", 900), ("resume",)]
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
    a.apps = Apps()
    assert a.learned_apps() == [{"exe": "game.exe"}]
    a.reset_learned(None)
    assert a.apps.reset_with is None
    a.reset_learned("game.exe")
    assert a.apps.reset_with == "game.exe"
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
