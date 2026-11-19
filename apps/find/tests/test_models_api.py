"""The models methods (contract: models, model_use, model_download, model_remove, auto_configure, model_language)."""
import os

import pytest

from nobadfind import api as api_mod, models

from test_api_status import make

PC = {"ram_gb": 15.7, "cores": 12, "threads": 16, "avx2": True, "avx512_vnni": False, "gpu": "Iris Xe",
      "vram_gb": 0.1, "directml": False, "disk_free_gb": 200.0, "ssd": True}


@pytest.fixture
def a(tmp_path, monkeypatch):
    monkeypatch.setattr(api_mod.hw, "scan", lambda: dict(PC))
    monkeypatch.setattr(api_mod.winapi, "windows_languages", lambda: ["en-GB"])
    monkeypatch.setattr(models, "DATA_DIR", str(tmp_path / "data"))
    a, s = make(tmp_path)
    a._models_dir = str(tmp_path / "data")
    import threading
    ix = a._indexer
    ix._load_embedder = ix._load_photo = lambda: None
    ix.wake, ix.text_model = threading.Event(), None
    yield a
    s.close()


def _fake_download(a, mid):
    m = models.get(mid)
    d = models.model_dir(mid, a._models_dir)
    os.makedirs(d, exist_ok=True)
    for name, (_p, size, _sha) in m["files"].items():
        with open(os.path.join(d, name), "wb") as f:
            f.truncate(size)


def test_models_lists_the_pc_the_tiers_and_every_model(a):
    r = a.models()
    assert r["pc"] == PC and r["tier_recommended"] == "best" and r["language_focus"] == "english"
    assert {m["id"] for m in r["models"]} == set(models.ids())
    by = {m["id"]: m for m in r["models"]}
    assert by["windows-ocr"]["builtin"] and by["minilm-l6-v2"]["state"] == "not_downloaded"
    assert sum(m["recommended"] for m in r["models"] if m["feature"] == "text") == 1
    assert all(m["capable"] for m in r["models"])


def test_language_focus_from_windows_then_the_users_choice(a, monkeypatch):
    monkeypatch.setattr(api_mod.winapi, "windows_languages", lambda: ["en-IN", "hi-IN"])
    assert a.models()["language_focus"] == "hindi"
    monkeypatch.setattr(api_mod.winapi, "windows_languages", lambda: ["en-US", "fr-FR"])
    assert a.models()["language_focus"] == "multilingual"
    assert a.model_language("english") == {"ok": True, "error": ""}
    assert a.models()["language_focus"] == "english"
    assert a.model_language("klingon")["ok"] is False


def test_model_use_selects_and_says_when_a_download_is_needed(a):
    r = a.model_use("text", "multilingual-e5-small")
    assert r == {"ok": True, "error": "", "needs_download": True}
    assert a._settings.get("text_model") == "multilingual-e5-small" and a._settings.get("semantic") is True
    _fake_download(a, "siglip2-base")
    assert a.model_use("photo", "siglip2-base")["needs_download"] is False
    assert a.model_use("photo", "multilingual-e5-small")["ok"] is False        # a text model for photos
    assert a.model_use("text", "nope")["ok"] is False


def test_model_download_needs_the_consent_word(a, monkeypatch):
    got = []
    monkeypatch.setattr(api_mod.embed, "_fetch_verified", lambda url, dest, size, sha, name, progress=None:
                        got.append((url, os.path.basename(dest), size, sha)))
    assert a.model_download("multilingual-e5-small", "yes")["ok"] is False and got == []
    assert a.model_download("windows-ocr", "DOWNLOAD")["ok"] is False
    assert a.model_download("multilingual-e5-small", "DOWNLOAD") == {"ok": True, "error": ""}
    a._mdl_thread.join(5)
    m = models.get("multilingual-e5-small")
    assert {g[1] for g in got} == set(m["files"])
    assert all(g[0].startswith("https://huggingface.co/" + m["repo"] + "/resolve/" + m["rev"] + "/") for g in got)
    assert a._settings.get("allow_model_download") is True        # the stored consent
    assert a.downloads()["multilingual-e5-small"]["state"] in ("ready", "missing")


def test_model_remove_keeps_builtin_and_active_models(a):
    _fake_download(a, "gte-small")
    assert a.model_remove("windows-ocr")["ok"] is False
    a._indexer.text_model = "gte-small"
    assert a.model_remove("gte-small")["ok"] is False
    a._indexer.text_model = "minilm-l6-v2"
    assert a.model_remove("gte-small") == {"ok": True, "error": ""}
    assert not models.ready("gte-small", a._models_dir)


def test_auto_configure_applies_the_tier_and_lists_the_downloads(a):
    r = a.auto_configure()
    assert r["tier"] == "best" and {s["feature"] for s in r["steps"]} == {"text", "photo", "ocr"}
    text = next(s for s in r["steps"] if s["feature"] == "text")
    assert text["needs_download"] is True and a._settings.get("text_model") == text["id"]
    assert next(s for s in r["steps"] if s["feature"] == "ocr")["needs_download"] is False


def test_status_shows_the_rebuild_as_its_own_phase(a):
    ph = {p["id"]: p for p in a.status()["phases"]}
    assert ph["rebuild"]["state"] == "off"
    a._store.set_meta("vec_model_next", "gte-small")
    a._totals = (0, None, {})                                 # counts again now
    a._indexer.status["phase"] = "rebuild"
    ph = {p["id"]: p for p in a.status()["phases"]}
    assert ph["rebuild"]["state"] == "running" and ph["rebuild"]["label"].startswith("Rebuilding")
