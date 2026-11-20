"""Review of #80 (MEDIUM and LOW): rebuild safety, the swap's one transaction, downloads, status names, tray."""
import threading

import numpy as np

from nobadfind import embed, indexer, models
from nobadfind.store import Store

from test_vector_rebuild import S, Stand, _store


def _ix(tmp_path, monkeypatch, text_model="minilm-l6-v2", encrypted=False):
    if encrypted:
        s = Store(str(tmp_path / "e.db"), str(tmp_path / "e.key"))
        assert s.encrypted
        s.upsert_files([("C:/p/a.txt", "a.txt", "C:/p", ".txt", "text", 10, 1.0, 1.0, 1)])
        s.set_text(1, 1.0, ["body 1"], None)
    else:
        s = _store(tmp_path)
    monkeypatch.setattr(models, "ready", lambda mid, data_dir=None: True)
    st = S(semantic=True, text_model=text_model, content=True)
    vi = embed.VectorIndex()
    ix = indexer.Indexer(s, st, vindex=vi)
    ix.make_embedder = lambda mid, query=False: Stand(mid, models.get(mid)["dim"])
    ix.vectors_in_process = True
    ix.status["plan"] = {}
    return ix, s, st, vi


# ---------- M1: a rebuild never swaps in a model the user already left ----------
def test_a_rebuild_for_a_model_no_longer_chosen_is_not_swapped_in(tmp_path, monkeypatch):
    ix, s, st, vi = _ix(tmp_path, monkeypatch)
    ix._load_embedder()
    ix._make_vectors()
    st["text_model"] = "bge-base-en-v1.5"
    real = s.add_vectors

    def switch_again(rows, next=False):
        if next:
            st["text_model"] = "gte-small"                # the user changed their mind mid-rebuild
        return real(rows, next=next)
    s.add_vectors = switch_again
    ix._make_vectors()
    assert s.meta("vec_model") in ("minilm-l6-v2", "gte-small")
    assert s.meta("vec_model") != "bge-base-en-v1.5" and ix.text_model != "bge-base-en-v1.5"


def test_the_model_being_rebuilt_cannot_be_removed(tmp_path):
    from test_api_status import make
    a, s = make(tmp_path)
    s.set_meta("vec_model_next", "gte-small")
    a._indexer.text_model = "minilm-l6-v2"
    assert a.model_remove("gte-small")["ok"] is False
    s.close()


# ---------- M2: the swap and the model id are one transaction; a mismatch is repaired ----------
def test_the_swap_and_the_model_id_commit_together(tmp_path):
    s = _store(tmp_path)
    c = [r[0] for r in s.chunks_without_vectors(10, next=True)]
    s.add_vectors([(c[0], embed.to_blob(np.ones(8)))], next=True)
    s.swap_vectors("bge-base-en-v1.5")
    assert s.meta("vec_model") == "bge-base-en-v1.5" and s.meta("vec_model_next") == ""


def test_vectors_that_dont_fit_their_model_are_made_again(tmp_path, monkeypatch):
    """A crash between an old swap and its tag: 384 numbers per vector, tagged as a 768-number model."""
    ix, s, st, vi = _ix(tmp_path, monkeypatch, "bge-base-en-v1.5", encrypted=True)
    s.add_name_vectors([(1, embed.to_blob(np.ones(384)))])
    s.set_meta("vec_model", "bge-base-en-v1.5")
    s.set_meta("vec_version", embed.VEC_VERSION)
    ix._load_embedder()
    assert ix.embedder is not None and ix.text_model == "bge-base-en-v1.5"      # meaning search stays on
    assert s.q("SELECT count(*) FROM nvecs")[0][0] == 0                        # and starts the vectors again
    s.close()


# ---------- L1: while a rebuild is pending, one meaning worker (no back and forth between two models) ----------
def test_a_pending_rebuild_uses_one_model_per_round(tmp_path, monkeypatch):
    ix, s, st, vi = _ix(tmp_path, monkeypatch)
    ix._load_embedder()
    ix._make_vectors()
    st["text_model"] = "bge-base-en-v1.5"
    used = []
    real = ix._encode
    monkeypatch.setattr(ix, "_encode", lambda texts, mid=None: used.append(mid) or real(texts, mid))
    s.upsert_files([("C:/p/new.txt", "new.txt", "C:/p", ".txt", "text", 10, 1.0, 1.0, 1)])     # the watcher
    ix._make_vectors()
    assert set(used) == {"bge-base-en-v1.5"}


def test_capable_checks_the_disk_for_the_vectors_too():
    pc = {"ram_gb": 15.7, "cores": 12, "directml": False, "vram_gb": 0, "disk_free_gb": 2.0}
    m = models.get("gte-small")
    assert models.capable(m, pc) == (True, "")
    ok, why = models.capable(m, pc, vectors=5_000_000)              # 5 M vectors x 384 x 2 bytes = 3.8 GB
    assert not ok and "disk" in why


# ---------- L3, M5: downloads ----------
def test_one_download_per_model_at_a_time(tmp_path, monkeypatch):
    from nobadfind import api as api_mod
    from test_api_status import make
    a, s = make(tmp_path)
    a._models_dir = str(tmp_path / "data")
    gate, calls = threading.Event(), []
    monkeypatch.setattr(api_mod.embed, "_fetch_verified", lambda url, dest, size, sha, name, progress=None,
                        part=".part": (calls.append(part), gate.wait(5)))
    threads = [threading.Thread(target=a.model_download, args=("gte-small", "DOWNLOAD")) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    gate.set()
    a._mdl_thread.join(5)
    assert len(calls) == len(models.get("gte-small")["files"])        # one download, not five
    assert all(p != ".part" for p in calls)                            # not the legacy download's file names
    s.close()


def test_a_photo_model_downloaded_after_being_chosen_starts(tmp_path, monkeypatch):
    from nobadfind import api as api_mod
    from test_api_status import make
    a, s = make(tmp_path)
    a._models_dir = str(tmp_path / "data")
    loaded = []
    a._indexer._load_photo = lambda: loaded.append("photo")
    a._indexer._load_embedder = lambda: None
    a._indexer.wake, a._indexer.text_model = threading.Event(), None
    a._settings.update({"photo_meaning": True, "photo_model": "siglip2-base"})
    monkeypatch.setattr(api_mod.embed, "_fetch_verified", lambda *x, **k: None)
    a.model_download("siglip2-base", "DOWNLOAD")
    a._mdl_thread.join(5)
    import time
    for _ in range(50):
        if loaded:
            break
        time.sleep(0.02)
    assert loaded == ["photo"]
    s.close()


# ---------- M6: status names the models in use ----------
def test_status_cards_name_the_active_models(tmp_path, monkeypatch):
    from test_api_status import make
    a, s = make(tmp_path)
    a._settings.update({"semantic": True, "text_model": "gte-small", "photo_meaning": True,
                        "photo_model": "siglip2-base"})
    a._indexer.text_model = "gte-small"
    cards = {c["id"]: c for c in a.status()["models"]}
    assert "GTE small" in cards["meaning"]["name"] and "SigLIP 2" in cards["photo"]["name"]
    assert cards["meaning"]["size_mb"] == models.size_mb(models.get("gte-small"))
    s.close()


# ---------- L4: the tray follows its setting at once ----------
def test_the_tray_setting_applies_live(tmp_path):
    from test_api_status import make
    a, s = make(tmp_path)
    seen = []
    a._on_tray = seen.append
    a.set_settings({"tray": False})
    a.set_settings({"tray": True})
    assert seen == [False, True]
    s.close()


# ---------- L5: names and text are NFC at index time ----------
def test_names_and_text_are_nfc(tmp_path):
    import unicodedata
    from nobadfind import extract
    decomposed = unicodedata.normalize("NFD", "बड़ी café")
    assert extract.clean(decomposed) == unicodedata.normalize("NFC", "बड़ी café")
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    s.upsert_files([("C:/d/" + decomposed + ".txt", decomposed + ".txt", "C:/d", ".txt", "text", 1, 1.0, 1.0, 1)])
    name, path = s.q("SELECT name, path FROM files")[0]
    assert name == unicodedata.normalize("NFC", decomposed + ".txt")
    assert path == "C:/d/" + decomposed + ".txt"                     # the path is the real one, as Windows has it
    s.close()

