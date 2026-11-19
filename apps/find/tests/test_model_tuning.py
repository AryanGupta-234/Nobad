"""ONNX Runtime tuning measured on the real models (docs/measurements.md, 2026-11-19 models section)."""
import numpy as np

from nobadfind import embed, indexer, photo
from nobadfind import governor as g


def test_meaning_batches_are_small():
    """Batch 64 x up to 256 tokens kept ~1.1 GB in ONNX Runtime's arena in the meaning worker; batch 4 keeps
    ~115 MB and runs faster (40 vs 30 chunks/s), with the same search quality."""
    e = embed.Embedder.__new__(embed.Embedder)
    e.spec, e.query = embed.DEFAULT_SPEC, False
    sizes = []
    e._encode = lambda texts: (sizes.append(len(texts)), np.ones((len(texts), embed.MODEL_DIM), np.float32))[1]
    out = e.encode([f"text {i}" for i in range(10)])
    assert out.shape == (10, embed.MODEL_DIM) and max(sizes) <= 4 and sum(sizes) == 10


class Gov:
    def __init__(self, level):
        self.decision = g.Decision(level, "why")


def _photo_ix(tmp_path, level):
    from nobadfind.store import Store
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    ix = indexer.Indexer(s, {"photo_meaning": True}, governor=Gov(level))
    ix.photo_text = object()
    ix.status["plan"] = {"text_workers": 8, "text_workers_idle": 15}
    return ix


def test_photo_worker_threads_follow_the_level(tmp_path, monkeypatch):
    """Vision runs 2.4 photos/s on 2 threads, 7.1 on 8: like the meaning worker, the photo worker gets threads
    from the level (CPU-capped with the other workers), one at Light."""
    made = []

    class Pool:
        def __init__(self, *a, **k):
            made.append(k)
            self._processes = {}

        def shutdown(self, **k):
            pass
    monkeypatch.setattr(indexer.cf, "ProcessPoolExecutor", Pool)
    monkeypatch.setattr(indexer.os, "cpu_count", lambda: 16)
    for level, want in ((g.FULL, 8), (g.GENTLE, 8), (g.LIGHT, 1)):
        made.clear()
        (tmp_path / level).mkdir()
        _photo_ix(tmp_path / level, level)._photo_vectors()
        assert made[0]["initializer"] is photo.init_worker and made[0]["initargs"] == (want,)


def test_photo_question_encoder_uses_four_threads(monkeypatch, tmp_path):
    """A photo question is encoded in the main process while you type: 45 ms on 2 threads, 28 ms on 4."""
    import onnxruntime as ort
    seen = {}

    class Sess:
        def __init__(self, path, opts, providers):
            seen["threads"] = opts.intra_op_num_threads
    monkeypatch.setattr(ort, "InferenceSession", Sess)
    monkeypatch.setattr(photo, "model_ready", lambda d=None: True)
    import tokenizers
    monkeypatch.setattr(tokenizers.Tokenizer, "from_file", staticmethod(lambda p: None))
    (tmp_path / "text.onnx").write_bytes(b"")
    photo.TextEncoder(str(tmp_path))
    assert seen["threads"] == photo.QUESTION_THREADS == 4


def test_vision_session_uses_the_workers_threads(monkeypatch, tmp_path):
    import onnxruntime as ort
    seen = {}

    class Sess:
        def __init__(self, path, opts, providers):
            seen["threads"] = opts.intra_op_num_threads
    monkeypatch.setattr(ort, "InferenceSession", Sess)
    monkeypatch.setattr(photo, "_vision", {})
    monkeypatch.setattr(photo, "_threads", [6])
    photo._vision_session(str(tmp_path))
    assert seen["threads"] == 6
