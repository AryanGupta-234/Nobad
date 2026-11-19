"""Switching the text (or photo) model: new vectors are built next to the old ones, the old ones stay searchable,
and they swap in one transaction once complete. Vectors from two models are never searched together."""
import numpy as np

from nobadfind import embed, indexer, models
from nobadfind.store import Store


def blob(x, dim=4):
    return embed.to_blob(np.full(dim, x, np.float32))


def _store(tmp_path):
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    s.upsert_files([("C:/p/a.txt", "a.txt", "C:/p", ".txt", "text", 10, 1.0, 1.0, 1),
                    ("C:/p/b.txt", "b.txt", "C:/p", ".txt", "text", 10, 1.0, 1.0, 1)])
    for fid in (1, 2):
        s.set_text(fid, 1.0, [f"body {fid}"], None)
    return s


def test_next_vectors_live_beside_the_current_ones_and_swap_in(tmp_path):
    s = _store(tmp_path)
    chunks = [r[0] for r in s.chunks_without_vectors(10)]
    s.add_vectors([(c, blob(1)) for c in chunks])
    s.add_name_vectors([(1, blob(1)), (2, blob(1))])
    assert s.chunks_without_vectors(10) == []
    assert len(s.chunks_without_vectors(10, next=True)) == 2          # the new model has none yet
    s.add_vectors([(chunks[0], blob(2, 8))], next=True)
    assert len(s.chunks_without_vectors(10, next=True)) == 1
    assert s.count_chunks_without_vectors(next=True) == 1
    s.add_vectors([(chunks[1], blob(2, 8))], next=True)
    s.add_name_vectors([(1, blob(2, 8)), (2, blob(2, 8))], next=True)
    s.swap_vectors()
    assert {len(v) for _k, v in s.q("SELECT chunk_id, v FROM vecs")} == {16}      # 8 float16 = the new model's
    assert s.q("SELECT count(*) FROM vecs_next")[0][0] == 0 and s.q("SELECT count(*) FROM nvecs_next")[0][0] == 0


def test_deleted_files_and_chunks_leave_the_next_tables_too(tmp_path):
    s = _store(tmp_path)
    c = s.chunks_without_vectors(10, next=True)[0][0]
    s.add_vectors([(c, blob(3))], next=True)
    s.add_name_vectors([(1, blob(3))], next=True)
    s.set_text(1, 2.0, ["changed"], None)                 # the chunk is replaced
    s.remove_paths(["C:/p/a.txt"])
    assert s.q("SELECT count(*) FROM vecs_next")[0][0] == 0 and s.q("SELECT count(*) FROM nvecs_next")[0][0] == 0


def test_vector_model_of_an_old_index_is_minilm(tmp_path):
    """Indexes from 0.7.0 have MiniLM vectors and no model id."""
    s = _store(tmp_path)
    assert indexer.vector_model(s) is None                 # nothing made yet
    s.add_name_vectors([(1, blob(1))])
    assert indexer.vector_model(s) == "minilm-l6-v2"
    s.set_meta("vec_model", "bge-small-en-v1.5")
    assert indexer.vector_model(s) == "bge-small-en-v1.5"


def test_vector_index_takes_the_models_size(tmp_path):
    vi = embed.VectorIndex()
    vi.reset(768, "bge-base-en-v1.5")
    assert vi.dim == 768 and vi.model == "bge-base-en-v1.5" and vi.n == 0
    assert models.get("bge-base-en-v1.5")["dim"] == 768


# ---------- the indexer switches models in the background ----------
class Stand:
    """A stand-in model: every text -> the same unit vector of its model's size."""
    def __init__(self, mid, dim):
        self.model_id, self.dim = mid, dim

    def encode(self, texts):
        v = np.zeros((len(texts), self.dim), np.float32)
        v[:, 0] = 1
        return v


class S(dict):
    def get(self, k, d=None):
        return super().get(k, d)


def _ix(tmp_path, monkeypatch, text_model):
    s = _store(tmp_path)
    monkeypatch.setattr(models, "ready", lambda mid, data_dir=None: True)
    st = S(semantic=True, text_model=text_model, content=True)
    vi = embed.VectorIndex()
    ix = indexer.Indexer(s, st, vindex=vi)
    ix.make_embedder = lambda mid, query=False: Stand(mid, models.get(mid)["dim"])
    ix.vectors_in_process = True                          # stand-in models: no meaning worker process
    ix.status["plan"] = {}
    return ix, s, st, vi


def test_a_fresh_index_uses_the_chosen_model_at_once(tmp_path, monkeypatch):
    ix, s, st, vi = _ix(tmp_path, monkeypatch, "bge-base-en-v1.5")
    ix._load_embedder()
    ix._make_vectors()
    assert ix.text_model == "bge-base-en-v1.5" == s.meta("vec_model") == vi.model
    assert vi.dim == 768 and vi.n > 0 and ix.embedder.model_id == "bge-base-en-v1.5"


def test_switching_rebuilds_beside_the_old_vectors_then_swaps(tmp_path, monkeypatch):
    ix, s, st, vi = _ix(tmp_path, monkeypatch, "minilm-l6-v2")
    ix._load_embedder()
    ix._make_vectors()
    assert s.meta("vec_model") == "minilm-l6-v2" and vi.dim == 384
    st["text_model"] = "bge-base-en-v1.5"                 # the user picks another model
    seen = []
    real = s.add_vectors

    def watch(rows, next=False):
        seen.append((next, vi.model, s.meta("vec_model")))        # while rebuilding, search keeps the old set
        return real(rows, next=next)
    s.add_vectors = watch
    ix._make_vectors()
    assert (True, "minilm-l6-v2", "minilm-l6-v2") in seen
    assert s.meta("vec_model") == "bge-base-en-v1.5" and vi.model == "bge-base-en-v1.5" and vi.dim == 768
    assert ix.embedder.model_id == "bge-base-en-v1.5"
    assert {len(v) for (v,) in s.q("SELECT v FROM vecs")} == {768 * 2}
    assert any("BGE base" in a for a in ix._notes)


def test_a_model_not_downloaded_yet_changes_nothing(tmp_path, monkeypatch):
    ix, s, st, vi = _ix(tmp_path, monkeypatch, "minilm-l6-v2")
    ix._load_embedder()
    ix._make_vectors()
    st["text_model"] = "bge-base-en-v1.5"
    monkeypatch.setattr(models, "ready", lambda mid, data_dir=None: mid == "minilm-l6-v2")
    ix._make_vectors()
    assert s.meta("vec_model") == "minilm-l6-v2" and s.q("SELECT count(*) FROM vecs_next")[0][0] == 0


# ---------- photos: one model's vectors at a time ----------
def test_photo_model_switch_starts_the_photo_vectors_again(tmp_path, monkeypatch):
    s = _store(tmp_path)
    s.set_photo_vector(1, 1.0, embed.to_blob(np.ones(768)), None)
    monkeypatch.setattr(models, "ready", lambda mid, data_dir=None: True)
    monkeypatch.setattr(indexer.photo, "TextEncoder", lambda model_dir, style="siglip": ("enc", model_dir, style))
    st = S(photo_meaning=True, photo_model="siglip-base")
    ix = indexer.Indexer(s, st, vindex=embed.VectorIndex())
    ix._load_photo()
    assert ix.photo_model == "siglip-base" and s.meta("pvec_model") == "siglip-base" and ix.pindex.n == 1
    assert ix.photo_text.model_id == "siglip-base"
    st["photo_model"] = "siglip2-base"
    ix._load_photo()
    assert ix.photo_model == "siglip2-base" and ix.pindex.model == "siglip2-base"
    assert s.q("SELECT count(*) FROM pvecs")[0][0] == 0             # SigLIP and SigLIP 2 are never compared
    assert ix.photo_text._factory() == ("enc", models.model_dir("siglip2-base"), "siglip2")


def test_siglip2_questions_are_lower_case_with_end_of_text_and_padding():
    from nobadfind import photo

    class Tok:
        def encode(self, text):
            class E:
                ids = [7, 8, 1] + [0] * 61
            Tok.seen = text
            return E()
    ids = photo.question_ids(Tok(), "Sunset over THE Sea", "siglip2")
    assert Tok.seen == "sunset over the sea" and len(ids) == 64 and ids[:3] == [7, 8, 1] and ids[3] == 0


def test_the_vision_session_follows_the_model_folder(monkeypatch, tmp_path):
    """Review H2: the worker cached one vision session and ignored a new model's folder."""
    from nobadfind import photo
    import onnxruntime as ort
    made = []
    monkeypatch.setattr(ort, "InferenceSession", lambda path, opts, providers: made.append(path) or object())
    monkeypatch.setattr(photo, "_vision", {})
    photo._vision_session(str(tmp_path / "a"))
    photo._vision_session(str(tmp_path / "a"))
    photo._vision_session(str(tmp_path / "b"))
    assert [p.split("\\")[-2] if "\\" in p else p.split("/")[-2] for p in made] == ["a", "b"]


class SyncPhotoPool:
    def __init__(self, *a, **k):
        self._processes = {}

    def submit(self, fn, *args):
        import concurrent.futures as cf
        f = cf.Future()
        f.set_result(fn(*args))
        return f

    def shutdown(self, **k):
        pass


def test_a_photo_pass_running_through_a_switch_writes_nothing_under_the_new_id(tmp_path, monkeypatch):
    s = _store(tmp_path)
    s.upsert_files([(f"C:/p/img{i}.jpg", f"img{i}.jpg", "C:/p", ".jpg", "image", 50000, 1.0, 1.0, 1) for i in range(20)])
    monkeypatch.setattr(models, "ready", lambda mid, data_dir=None: True)
    monkeypatch.setattr(indexer.photo, "TextEncoder", lambda model_dir, style="siglip": object())
    st = S(photo_meaning=True, photo_model="siglip-base")
    ix = indexer.Indexer(s, st, vindex=embed.VectorIndex())
    ix.status["plan"] = {}
    ix._load_photo()
    monkeypatch.setattr(indexer.cf, "ProcessPoolExecutor", SyncPhotoPool)
    made_with = []

    def embed_photos(jobs, fast=False):
        made_with.append(jobs[0][3])
        if len(made_with) == 1:                            # the user switches while this batch is being made
            st["photo_model"] = "siglip2-base"
            ix._load_photo()
        return [(fid, mtime, embed.to_blob(np.ones(768)), None) for fid, _p, mtime, _d in jobs]
    monkeypatch.setattr(indexer.photo, "embed_photos", embed_photos)
    ix._photo_vectors()
    assert s.meta("pvec_model") == "siglip2-base"
    assert s.q("SELECT count(*) FROM pvecs")[0][0] == 0      # the old model's batch was thrown away
    ix._photo_vectors()                                      # the next pass: the new model's folder
    assert made_with[-1] == models.model_dir("siglip2-base")
    assert s.q("SELECT count(*) FROM pvecs")[0][0] == 20
