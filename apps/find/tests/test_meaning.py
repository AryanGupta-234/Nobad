"""Meaning search: name vectors, titles, the two-step index, and vectors that survive rescans."""
import numpy as np
import pytest

from nobadfind import embed, indexer, search
from nobadfind.store import Store


@pytest.mark.parametrize("name,folder,text", [
    ("IMG_20250612_goa_beach_sunset.jpg", "C:\\Users\\me\\Pictures", "goa beach sunset"),
    ("electricity-bill-march.pdf", "C:\\Users\\me\\Downloads", "electricity bill march"),
    ("DSC0001.jpg", "C:\\Users\\me\\Holiday photos", "holiday photos"),     # the folder says what it is
    ("DSC0001.jpg", "C:\\Users\\me\\Pictures", ""),                         # nothing to go on
    ("MyTaxReturn2024.pdf", "C:\\x", "tax return"),
    ("cv-2024-final.docx", "C:\\x\\Job hunt", "cv (job hunt)"),
    ("a1b2c3d4e5f6.bin", "C:\\x\\Downloads", ""),
])
def test_name_text(name, folder, text):
    assert embed.name_text(name, folder) == text


def test_chunk_text_has_title():
    assert embed.chunk_text("contract-final.txt", "The tenant pays") == "contract: The tenant pays"
    assert embed.chunk_text("IMG_0001.txt", "x") == "x"


def _unit(rows):
    rows = np.asarray(rows, np.float32)
    return rows / np.linalg.norm(rows, axis=1, keepdims=True)


@pytest.mark.parametrize("n", [500, 25_000])           # exact path, and the two-step path for big indexes
def test_vector_index_matches_exact(n):
    rng = np.random.default_rng(3)
    base = _unit(rng.standard_normal((50, 384)))
    m = _unit(base[rng.integers(0, 50, n)] + rng.normal(0, 0.2, (n, 384)))
    vi = embed.VectorIndex()
    for i in range(0, n, 700):                         # many small adds, like the indexer
        vi.add(np.arange(i, min(n, i + 700)), m[i:i + 700])
    q = _unit(base[:1] + rng.normal(0, 0.1, (1, 384)))[0]
    exact = np.argsort(-(m.astype(np.float16).astype(np.float32) @ q))[:30]
    got = [k for k, _s in vi.search(q, k=30)]
    assert len(set(got) & set(exact.tolist())) >= 29
    scores = [s for _k, s in vi.search(q, k=30)]
    assert scores == sorted(scores, reverse=True)


class _Fake:
    """Dimension 0 = beach-ness, 1 = rent-ness."""
    def encode(self, texts):
        return _unit([[("beach" in t) + ("seaside" in t), ("rent" in t) + ("tenancy" in t) + ("lease" in t),
                       0.05] + [0] * 381 for t in texts])


class _S(dict):
    def get(self, k, d=None):
        return super().get(k, d)


def _files(s):
    s.upsert_files([("C:\\p\\IMG_1_beach_day.jpg", "IMG_1_beach_day.jpg", "C:\\p", ".jpg", "image", 9, 1.0, 1.0, 1),
                    ("C:\\p\\tenancy-agreement.pdf", "tenancy-agreement.pdf", "C:\\p", ".pdf", "pdf", 9, 1.0, 1.0, 1),
                    ("C:\\p\\DSC0002.jpg", "DSC0002.jpg", "C:\\Users\\me\\Pictures", ".jpg", "image", 9, 1.0, 1.0, 1),
                    ("C:\\p\\tool.py", "tool.py", "C:\\p", ".py", "code", 9, 1.0, 1.0, 1)])


def test_name_vectors_find_files_without_text(tmp_path):
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    _files(s)
    vi = embed.VectorIndex()
    ix = indexer.Indexer(s, _S(), vi)
    ix.embedder = _Fake()
    ix._check_pause = lambda: ""
    ix._away = lambda: True
    ix._make_vectors()
    assert s.stats()["name_vectors"] == 2                 # DSC0002 has no words; code files get none
    assert s.names_without_vectors(indexer.NAME_KINDS) == []
    r = search.search(s, "seaside", embedder=_Fake(), vindex=vi)["results"]
    assert [x["name"] for x in r] == ["IMG_1_beach_day.jpg"] and "name has a close meaning" in r[0]["why"]
    assert search.search(s, "lease", embedder=_Fake(), vindex=vi)["results"][0]["name"] == "tenancy-agreement.pdf"
    # a rescan rewrites every row with the same name: the vectors must stay
    _files(s)
    assert s.stats()["name_vectors"] == 2
    # a rename drops the old name's vector so it's made again
    s.upsert_files([("C:\\p\\IMG_1_beach_day.jpg", "rent-receipt.jpg", "C:\\p", ".jpg", "image", 9, 1.0, 1.0, 1)])
    assert s.stats()["name_vectors"] == 1
    s.close()


def test_vectors_recomputed_when_method_changes(tmp_path, monkeypatch):
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    _files(s)
    s.add_name_vectors([(1, embed.to_blob(np.ones(384) / 384 ** .5))])
    s.set_meta("vec_version", "1")
    monkeypatch.setattr(embed, "model_ready", lambda *a: True)
    monkeypatch.setattr(embed, "Embedder", _Fake)
    ix = indexer.Indexer(s, _S(semantic=True), embed.VectorIndex())
    ix._load_embedder()
    assert s.meta("vec_version") == embed.VEC_VERSION and s.stats()["name_vectors"] == 0
    s.close()


def test_weak_meaning_is_not_shown(tmp_path):
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    _files(s)
    vi = embed.VectorIndex()
    vi.add([embed.name_key(1)], _unit([[0.1, 0.0, 1.0] + [0] * 381]))     # barely beach-like
    assert search.search(s, "seaside", embedder=_Fake(), vindex=vi)["results"] == []
    s.close()
