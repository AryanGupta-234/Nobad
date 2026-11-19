"""Model tiers (spec 2026-11-18 §4): the catalog, the recommended tier from the PC, what each model needs."""
import os

from nobadfind import models

PC_SMALL = {"ram_gb": 7.8, "cores": 4, "threads": 8, "avx2": True, "avx512_vnni": False, "gpu": "", "vram_gb": 0.0,
            "directml": False, "disk_free_gb": 50.0, "ssd": True}
PC_MID = dict(PC_SMALL, ram_gb=11.8, cores=6)
PC_BIG = dict(PC_SMALL, ram_gb=15.7, cores=12)       # a 16 GB PC reports 15.7
PC_GPU = dict(PC_SMALL, ram_gb=11.8, cores=6, directml=True, vram_gb=6.0)


def test_recommended_tier_follows_the_spec_table():
    assert models.recommend(PC_SMALL) == "light"           # < 8 GB or <= 4 cores
    assert models.recommend(dict(PC_BIG, cores=4)) == "light"
    assert models.recommend(PC_MID) == "balanced"
    assert models.recommend(PC_BIG) == "best"              # 16 GB+ and 8+ cores
    assert models.recommend(PC_GPU) == "best"              # or a DirectML card with 4 GB+


def test_catalog_has_every_feature_and_only_permissive_licences():
    ids = {m["id"]: m for m in models.CATALOG}
    assert {m["feature"] for m in models.CATALOG} == {"text", "photo", "ocr"}
    for m in models.CATALOG:
        assert m["licence"] in ("MIT", "Apache-2.0", "Windows"), m["id"]
        assert "clip" not in m["id"].lower() or "siglip" in m["id"].lower()
        if not m["builtin"]:
            assert m["files"] and all(len(sha) == 64 and size > 0 for _p, size, sha in m["files"].values())
            assert m["source"].startswith("https://huggingface.co/") and len(m["rev"]) == 40
    assert ids["minilm-l6-v2"]["tier"] == "light" and ids["multilingual-e5-small"]["tier"] == "balanced"
    assert ids["multilingual-e5-base"]["tier"] == "best"
    assert "hi" in ids["multilingual-e5-small"]["languages"]


def test_the_current_models_keep_their_folders(tmp_path):
    """People who downloaded a model in 0.7.0 keep it: same folder, same files."""
    assert models.model_dir("minilm-l6-v2", str(tmp_path)) == os.path.join(str(tmp_path), "model")
    assert models.model_dir("siglip-base", str(tmp_path)) == os.path.join(str(tmp_path), "photo-model")
    assert models.model_dir("multilingual-e5-small", str(tmp_path)) == os.path.join(
        str(tmp_path), "models", "multilingual-e5-small")


def test_ready_needs_every_file_at_its_size(tmp_path):
    m = models.get("minilm-l6-v2")
    d = models.model_dir(m["id"], str(tmp_path))
    os.makedirs(d)
    assert not models.ready(m["id"], str(tmp_path))
    for name, (_p, size, _sha) in m["files"].items():
        with open(os.path.join(d, name), "wb") as f:
            f.truncate(size)
    assert models.ready(m["id"], str(tmp_path))
    assert models.ready("windows-ocr", str(tmp_path))       # built into Windows


def test_capable_says_why_not():
    best = models.get("multilingual-e5-base")
    ok, why = models.capable(best, PC_SMALL)
    assert not ok and "16 GB" in why
    assert models.capable(best, PC_BIG) == (True, "")
    ok, why = models.capable(best, dict(PC_BIG, disk_free_gb=0.1))
    assert not ok and "disk" in why
    assert models.capable(models.get("minilm-l6-v2"), PC_SMALL) == (True, "")


def test_tier_current_from_the_settings():
    s = {"semantic": True, "text_model": "multilingual-e5-small", "photo_meaning": True, "photo_model": "siglip-base"}
    assert models.tier_current(s) == "balanced"
    assert models.tier_current(dict(s, text_model="minilm-l6-v2", photo_meaning=False)) == "light"
    assert models.tier_current(dict(s, text_model="multilingual-e5-base", photo_model="siglip2-base")) == "best"
    assert models.tier_current(dict(s, text_model="bge-base-en-v1.5", photo_model="siglip-base")) == "custom"
    assert models.tier_current(dict(s, text_model="gte-small", photo_meaning=False)) == "light"     # English focus


def test_tier_choice_per_feature():
    assert models.tier_choice("light") == {"text": "minilm-l6-v2", "photo": "", "ocr": "windows-ocr"}
    assert models.tier_choice("best")["photo"] == "siglip2-base"


def test_e5_models_mark_questions_and_passages():
    """multilingual-e5 was trained with "query: " and "passage: " in front; all-MiniLM without."""
    e5, mini = models.get("multilingual-e5-small"), models.get("minilm-l6-v2")
    assert (e5["query_prefix"], e5["passage_prefix"]) == ("query: ", "passage: ")
    assert (mini["query_prefix"], mini["passage_prefix"]) == ("", "")


# ---------- the encoder follows the model's card ----------
import numpy as np  # noqa: E402

from nobadfind import embed  # noqa: E402


class FakeTok:
    def __init__(self):
        self.seen = []

    def encode_batch(self, texts):
        self.seen.extend(texts)

        class E:
            def __init__(self, n):
                self.ids, self.attention_mask = [5] * n + [0] * (4 - n), [1] * n + [0] * (4 - n)
        return [E(min(4, len(t.split()))) for t in texts]


class FakeSess:
    """last_hidden_state: token i of every text is [i+1, i+1, ...] (CLS = token 0 = all ones)."""
    def run(self, _names, feed):
        b, n = feed["input_ids"].shape
        return [np.stack([np.stack([np.full(3, i + 1.0, np.float32) for i in range(n)]) for _ in range(b)])]


def fake_embedder(spec, query=False):
    e = embed.Embedder.__new__(embed.Embedder)
    e.tok, e.sess, e.inputs, e.spec, e.query = FakeTok(), FakeSess(), {"input_ids", "attention_mask"}, spec, query
    import threading
    e._lock = threading.Lock()
    return e


def test_prefixes_for_questions_and_passages():
    spec = models.get("multilingual-e5-small")
    p, q = fake_embedder(spec), fake_embedder(spec, query=True)
    p.encode(["the rent agreement"])
    q.encode(["flat payment"])
    assert p.tok.seen == ["passage: the rent agreement"] and q.tok.seen == ["query: flat payment"]


def test_pooling_cls_or_mean():
    cls = fake_embedder(dict(models.get("multilingual-e5-small"), pooling="cls"))
    mean = fake_embedder(dict(models.get("multilingual-e5-small"), pooling="mean"))
    a, b = cls.encode(["one two three"])[0], mean.encode(["one two three"])[0]
    # "passage: one two three" = 4 words -> 4 tokens [1, 2, 3, 4]: CLS = token 0, mean = 2.5; both unit length
    assert np.allclose(a, b)            # same direction here, so check the raw pooling instead
    raw_cls = cls._pool(np.array([[[1.0, 0], [3.0, 3.0]]]), np.array([[1, 1]]))
    raw_mean = mean._pool(np.array([[[1.0, 0], [3.0, 3.0]]]), np.array([[1, 1]]))
    assert np.allclose(raw_cls, [[1.0, 0]]) and np.allclose(raw_mean, [[2.0, 1.5]])


def test_every_text_model_says_how_it_pools():
    for mid in models.ids("text"):
        assert models.get(mid)["pooling"] in ("mean", "cls"), mid


# ---------- never mix two models in one search ----------
class Emb:
    def __init__(self, mid):
        self.model_id = mid

    def encode(self, texts):
        return np.ones((len(texts), 3), np.float32) / np.sqrt(3)


def test_meaning_hits_need_the_question_and_the_vectors_from_one_model(tmp_path):
    from nobadfind import search
    from nobadfind.query import parse
    from nobadfind.store import Store
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    vi = embed.VectorIndex(3)
    vi.add([embed.name_key(1)], np.ones((1, 3), np.float32) / np.sqrt(3))
    vi.model = "minilm-l6-v2"
    q = parse("budget")
    calls = []
    s.q = lambda *a: calls.append(a) or []
    assert search._meaning_hits(s, q, Emb("bge-small-en-v1.5"), vi, 10) == ([], {})
    assert calls == []                                    # not even looked up
    search._meaning_hits(s, q, Emb("minilm-l6-v2"), vi, 10)
    assert calls                                          # same model: searched


def test_meaning_floors_come_from_the_model():
    from nobadfind import search
    assert search.floors("") == (search.MIN_MEANING, search.MEANING_SPREAD, search.NAME_SPREAD,
                                 search.NAME_STRONG)          # an unknown model (tests' stand-ins): the 0.7.0 floors
    for mid in models.ids("text"):                            # each measured on the eval sets (tools/eval_text.py)
        assert 0 < search.floors(mid)[0] < 1 and 0 < search.floors(mid)[1] < 0.5, mid
    e5 = models.get("multilingual-e5-small")
    assert search.floors("multilingual-e5-small")[0] == e5["min_score"]
