"""Light when idle: lazy models, honest confidence, previews by result id only, the memory reading."""
import time

import numpy as np

from nobadfind import embed, ocr, photo, search, winapi
from nobadfind.store import Store


class _Model:
    made = 0

    def __init__(self):
        _Model.made += 1

    def encode(self, texts):
        return np.ones((len(texts), 4), np.float32)


def test_lazy_model_loads_on_use_and_leaves_when_idle():
    _Model.made = 0
    m = embed.Lazy(_Model, "test")
    assert not m.loaded and _Model.made == 0           # nothing in memory until it's needed
    m.encode(["a"])
    assert m.loaded and _Model.made == 1
    assert not m.release_if_idle(idle=60)              # just used: stays
    m._used = time.monotonic() - 61
    assert m.release_if_idle(idle=60) and not m.loaded
    m.encode(["b"])
    assert _Model.made == 2                            # back when needed again


def test_ocr_keeps_words_not_noise():
    assert ocr.real_words("vzÄ") == ""
    assert ocr.real_words("Boarding pass gate 14") == "Boarding pass gate 14"
    assert ocr.real_words("TOTAL 12.50 CASH") == "TOTAL 12.50 CASH"


def _unit(v):
    v = np.asarray(v, np.float32)
    return v / np.linalg.norm(v)


class _Text:
    def encode(self, text):
        v = np.zeros(photo.PHOTO_DIM, np.float32)
        v[0] = 1.0
        return v


def test_lookalike_photos_are_less_sure(tmp_path):
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    s.upsert_files([(f"C:\\p\\IMG_{i}.jpg", f"IMG_{i}.jpg", "C:\\p", ".jpg", "image", 50_000, float(i), float(i), 1)
                    for i in range(3)])
    ids = [r[0] for r in s.q("SELECT id FROM files ORDER BY name")]
    vi = embed.VectorIndex(photo.PHOTO_DIM, ())

    def at(score):
        v = np.zeros(photo.PHOTO_DIM, np.float32)
        v[0], v[1] = score, (1 - score ** 2) ** 0.5
        return v
    vi.add(ids, np.stack([at(0.10), at(0.095), at(0.07)]))        # two close to the best, one look-alike
    r = search.search(s, "tulips", photo_text=_Text(), pindex=vi)["results"]
    assert [x["weak"] for x in r] == [False, False, True]
    assert r[2]["why"][-1] == "the picture may show it"
    s.close()


def test_previews_only_by_result_id(tmp_path):
    from nobadfind import api as api_mod, settings
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    s.upsert_files([("C:\\p\\notes.txt", "notes.txt", "C:\\p", ".txt", "text", 10, 1.0, 1.0, 1)])

    class Ix:
        embedder = photo_text = None
    a = api_mod.Api(s, settings.Settings(str(tmp_path / "s.json")), Ix(), None)
    assert a.thumbnail("C:\\Windows\\win.ini") == {"url": ""}           # a path from the page: refused
    assert a.thumbnail(True) == {"url": ""}
    fid = s.one("SELECT id FROM files")
    assert a.thumbnail(fid) == {"url": ""}                            # not a photo, video or PDF
    s.close()


def test_memory_is_safe():
    if winapi.WIN:
        assert winapi.memory_mb() > 0
