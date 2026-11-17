"""Photo meaning (decode, store, search) and the one-click Windows Search switch."""
import numpy as np
import pytest

from nobadfind import embed, ocr, photo, search, winapi
from nobadfind.store import Store


def _unit(v):
    v = np.asarray(v, np.float32)
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


@pytest.mark.skipif(not ocr.available(), reason="needs Windows' imaging (winrt)")
def test_decode_224_makes_the_models_picture():
    img = ocr.gray_bmp(300, 200, bytes([0] * 300 * 100 + [255] * 300 * 100))      # black top, white bottom
    px = photo.decode_224(img)
    assert px.shape == (3, 224, 224) and px.dtype == np.float32
    assert px.min() >= -1.0 and px.max() <= 1.0
    assert px[:, 10, :].mean() < -0.9 and px[:, 214, :].mean() > 0.9             # the right way up
    assert photo.decode_224(ocr.gray_bmp(40, 40, bytes(1600))) is None             # too small to be a photo


def test_embed_photo_never_raises(tmp_path):
    p = tmp_path / "broken.jpg"
    p.write_bytes(b"\xff\xd8 nope" * 3000)
    import faulthandler
    on = faulthandler.is_enabled()
    faulthandler.disable()
    try:
        fid, mt, blob, err = photo.embed_photo((7, str(p), 1.0, str(tmp_path)))
    finally:
        if on:
            faulthandler.enable()
    assert (fid, mt, blob) == (7, 1.0, b"") and err


def _store(tmp_path):
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    rows = [("C:\\p\\IMG_0042.jpg", "IMG_0042.jpg", "C:\\p", ".jpg", "image", 50_000, 1.0, 1.0, 1),
            ("C:\\p\\IMG_0043.jpg", "IMG_0043.jpg", "C:\\p", ".jpg", "image", 50_000, 2.0, 2.0, 1),
            ("C:\\p\\icon.png", "icon.png", "C:\\p", ".png", "image", 900, 3.0, 3.0, 1),
            ("C:\\p\\lease.pdf", "lease.pdf", "C:\\p", ".pdf", "pdf", 50_000, 4.0, 4.0, 1)]
    s.upsert_files(rows)
    return s


def test_photo_rows_follow_the_files(tmp_path):
    s = _store(tmp_path)
    todo = s.photos_to_read(photo.PHOTO_EXT, photo.MIN_PHOTO_BYTES, photo.MAX_PHOTO_BYTES)
    assert sorted(r[1] for r in todo) == ["C:\\p\\IMG_0042.jpg", "C:\\p\\IMG_0043.jpg"]   # not the tiny icon
    for fid, _p, mt in todo:
        s.set_photo_vector(fid, mt, _unit(np.ones(photo.PHOTO_DIM)).astype(np.float16).tobytes())
    assert s.photos_to_read(photo.PHOTO_EXT, photo.MIN_PHOTO_BYTES, photo.MAX_PHOTO_BYTES) == []
    s.upsert_files([("C:\\p\\IMG_0042.jpg", "IMG_0042.jpg", "C:\\p", ".jpg", "image", 50_000, 9.0, 9.0, 1)])
    assert [r[1] for r in s.photos_to_read(photo.PHOTO_EXT, photo.MIN_PHOTO_BYTES, photo.MAX_PHOTO_BYTES)] == \
        ["C:\\p\\IMG_0042.jpg"]                                                     # changed: read again
    s.remove_paths(["C:\\p\\IMG_0043.jpg"])
    assert s.stats()["photo_vectors"] == 1                                         # gone with its file
    s.close()


class _Text:
    """Dimension 0 = dog, 1 = beach."""
    def encode(self, text):
        v = np.zeros(photo.PHOTO_DIM, np.float32)
        v[0], v[1], v[2] = ("dog" in text), ("beach" in text), 1.0
        return _unit(v)


def _pindex(s):
    ids = dict(s.q("SELECT name, id FROM files"))
    vi = embed.VectorIndex(photo.PHOTO_DIM, ())

    def at(dog, beach):
        v = np.zeros(photo.PHOTO_DIM, np.float32)
        v[0], v[1], v[3] = dog, beach, 1.0
        return _unit(v)
    vi.add([ids["IMG_0042.jpg"], ids["IMG_0043.jpg"]], np.stack([at(1.0, 0.0), at(0.0, 1.0)]))
    return vi


def test_photos_found_by_what_they_show(tmp_path):
    s = _store(tmp_path)
    vi = _pindex(s)
    r = search.search(s, "dog", photo_text=_Text(), pindex=vi)["results"]
    assert r[0]["name"] == "IMG_0042.jpg" and any("picture" in w for w in r[0]["why"])
    assert search.search(s, "beach", photo_text=_Text(), pindex=vi)["results"][0]["name"] == "IMG_0043.jpg"
    assert search.search(s, "dog pdf", photo_text=_Text(), pindex=vi)["results"] == []   # not asking for photos
    s.close()


def test_switch_to_nobad_find(monkeypatch, tmp_path):
    from nobadfind import api as api_mod, settings
    st = settings.Settings(str(tmp_path / "s.json"))
    calls = []
    monkeypatch.setattr(api_mod.wsearch, "state", lambda: {"start": "delayed-auto", "running": True})
    monkeypatch.setattr(api_mod.wsearch, "request", lambda start: calls.append(start) or True)
    monkeypatch.setattr(api_mod, "set_autostart", lambda on: calls.append(("autostart", on)))

    class Ix:
        embedder = None
        photo_text = None
    a = api_mod.Api(None, st, Ix(), None, lambda: None)
    assert a.use_instead_of_windows_search(True)["ok"]
    assert calls == ["disabled", ("autostart", True)] and st.get("wsearch_prev") == "delayed-auto"
    assert st.get("autostart") is True
    calls.clear()
    assert a.use_instead_of_windows_search(False)["ok"] and calls == ["delayed-auto"]   # back as it was


def test_photo_files_are_pinned():
    for name, (path, size, sha) in photo.PHOTO_FILES.items():
        assert path and size > 1000 and len(sha) == 64 and int(sha, 16) >= 0
    assert photo.PHOTO_URL.startswith("https://huggingface.co/") and len(photo.PHOTO_REV) == 40
    assert winapi  # imported for the skip markers' module
