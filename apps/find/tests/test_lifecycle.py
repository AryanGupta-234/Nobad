"""Lifecycle: what closing the window does, a restartable indexer, the meaning worker, safe model downloads."""
import concurrent.futures as cf
import hashlib
import os
import threading
import time

import numpy as np
import pytest

from nobadfind import embed, indexer, lifecycle
from nobadfind.store import Store


class _S(dict):
    def get(self, k, d=None):
        return super().get(k, d)


def test_on_close_modes():
    assert lifecycle.on_close(_S(keep_background=True), hotkey_ok=True, quitting=False) == "hide"
    assert lifecycle.on_close(_S(keep_background=False), hotkey_ok=True, quitting=False) == "hide_idle"
    assert lifecycle.on_close(_S(), hotkey_ok=True, quitting=False) == "hide_idle"        # default: off
    # no hotkey: a hidden Find could never be opened again, so closing quits
    assert lifecycle.on_close(_S(keep_background=True), hotkey_ok=False, quitting=False) == "quit"
    assert lifecycle.on_close(_S(keep_background=False), hotkey_ok=False, quitting=False) == "quit"
    # "Quit NOBAD Find" always quits
    assert lifecycle.on_close(_S(keep_background=True), hotkey_ok=True, quitting=True) == "quit"
    assert lifecycle.on_close(_S(keep_background=False), hotkey_ok=True, quitting=True) == "quit"


def _indexer_threads():
    return [t for t in threading.enumerate() if t.name == "indexer" and t.is_alive()]


def test_indexer_restarts_cleanly_three_times(tmp_path, monkeypatch):
    monkeypatch.setattr(indexer, "DEBOUNCE", 0)
    root = tmp_path / "files"
    root.mkdir()
    (root / "a.txt").write_text("hello")
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    s.set_meta("last_scan", time.time())          # a recent index: the loop goes straight to watching
    ix = indexer.Indexer(s, _S(roots=[str(root)], content=False))
    before = len(_indexer_threads())
    try:
        for _ in range(3):
            assert ix.start() is True
            assert ix.start() is False              # already running: never a second loop
            for _w in range(100):
                if ix.status["phase"] == "watching":
                    break
                time.sleep(0.05)
            assert ix.status["phase"] == "watching"
            ix.stop()
            assert ix.join(timeout=10) is True
            assert len(_indexer_threads()) == before
            ix.status["phase"] = "stopped"
    finally:
        ix.stop()
        ix.join()
        s.close()


def test_release_models_releases_now():
    released = []

    class M(embed.Lazy):
        def release_if_idle(self, idle=None):
            released.append((self.name, idle))

    ix = indexer.Indexer(None, _S())
    ix.embedder, ix.photo_text = M(None, "meaning"), M(None, "photo text")
    ix.release_models()
    assert released == [("meaning", 0), ("photo text", 0)]


needs_model = pytest.mark.skipif(not embed.model_ready(), reason="meaning model not downloaded")


@needs_model
def test_meaning_worker_matches_in_process():
    texts = ["contract: The tenant pays the rent", "goa beach sunset", "electricity bill march", "x"]
    with cf.ProcessPoolExecutor(max_workers=1, initializer=embed.init_meaning_worker,
                                initargs=(embed.MODEL_DIR, 2, False)) as pool:
        data = pool.submit(embed.encode_job, texts).result(timeout=120)
    assert isinstance(data, bytes)
    got = np.frombuffer(data, np.float32).reshape(len(texts), embed.MODEL_DIM)
    want = embed.Embedder(gpu=False).encode(texts)
    assert np.allclose(got, want, atol=1e-5)


@needs_model
def test_embedder_gpu_false_uses_cpu_only():
    e = embed.Embedder(gpu=False)
    assert e.device == "CPU"
    assert e.sess.get_providers() == ["CPUExecutionProvider"]


def test_indexer_vectors_come_from_the_worker(tmp_path, monkeypatch):
    """With the real model, index-time vectors are made in the worker; the bytes become float32 rows."""
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    s.upsert_files([("C:\\p\\goa-beach.jpg", "goa-beach.jpg", "C:\\p", ".jpg", "image", 9, 1.0, 1.0, 1)])
    vi = embed.VectorIndex()
    ix = indexer.Indexer(s, _S(), vi)
    ix.embedder = object()                       # the query encoder must not be used for indexing
    ix._vectors_in_worker = True
    ix._away = lambda: True
    sent = []

    class Pool:
        def __init__(self, max_workers, initializer, initargs):
            assert max_workers == 1 and initializer is embed.init_meaning_worker
            self.gpu = initargs[2]
            self.down = False

        def submit(self, fn, texts):
            assert fn is embed.encode_job
            sent.append(list(texts))
            f = cf.Future()
            v = np.zeros((len(texts), embed.MODEL_DIM), np.float32)
            v[:, 0] = 1
            f.set_result(v.tobytes())
            return f

        def shutdown(self, wait=True, cancel_futures=False):
            self.down = True

    monkeypatch.setattr(indexer.cf, "ProcessPoolExecutor", Pool)
    ix._make_vectors()
    assert sent == [["goa beach"]]
    assert s.stats()["name_vectors"] == 1 and vi.n == 1
    assert ix._mpool is None                      # the worker process ends when the work is done
    s.close()


def test_meaning_worker_follows_the_level(tmp_path, monkeypatch):
    """GPU only at Full: a GPU worker is replaced by a CPU one at the next batch when the level drops."""
    from nobadfind import governor as g

    class Gov:
        decision = g.Decision(g.FULL, "Full: you're away")

    made = []

    class Pool:
        def __init__(self, max_workers, initializer, initargs):
            made.append(initargs[2])

        def submit(self, fn, texts):
            f = cf.Future()
            f.set_result(np.zeros((len(texts), embed.MODEL_DIM), np.float32).tobytes())
            Gov.decision = g.Decision(g.GENTLE, "Gentle: you're using the PC")      # drops after one batch
            return f

        def shutdown(self, wait=True, cancel_futures=False):
            pass

    monkeypatch.setattr(indexer.cf, "ProcessPoolExecutor", Pool)
    ix = indexer.Indexer(None, _S(), governor=Gov())
    ix._vectors_in_worker = True
    ix.status["plan"] = {"text_workers": 2, "text_workers_idle": 4}
    ix._encode(["a"])
    ix._encode(["b"])
    ix._encode(["c"])
    assert made == [True, False]
    ix._end_meaning_pool()


class _Resp:
    """A download that sends some bytes, then fails (the window closed, the network dropped)."""

    def __init__(self, data, fail_after=None):
        self.data, self.fail_after, self.pos = data, fail_after, 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def geturl(self):
        return "https://huggingface.co/x"

    def read(self, n):
        if self.fail_after is not None and self.pos >= self.fail_after:
            raise ConnectionResetError("closed")
        b = self.data[self.pos:self.pos + min(n, 4)]
        self.pos += len(b)
        return b


def _fake_model(monkeypatch, data):
    files = {"model.onnx": ("onnx/model.onnx", len(data), hashlib.sha256(data).hexdigest())}
    monkeypatch.setattr(embed, "MODEL_FILES", files)


def test_close_during_download_leaves_no_partial_model(tmp_path, monkeypatch):
    data = b"0123456789abcdef" * 4
    _fake_model(monkeypatch, data)
    monkeypatch.setattr(embed.urllib.request, "urlopen", lambda *a, **k: _Resp(data, fail_after=20))
    d = str(tmp_path / "model")
    with pytest.raises(OSError):
        embed.download_model(d)
    assert not embed.model_ready(d)
    assert os.listdir(d) == []                    # neither the final name nor a .part is left
    # a stale file of the right size but the wrong content is never kept under the final name
    with open(os.path.join(d, "model.onnx"), "wb") as f:
        f.write(b"x" * len(data))
    monkeypatch.setattr(embed.urllib.request, "urlopen", lambda *a, **k: _Resp(b"y" * len(data)))
    with pytest.raises(OSError):
        embed.download_model(d)
    assert os.listdir(d) == []
    # a good download lands under the final name only once it's checked
    monkeypatch.setattr(embed.urllib.request, "urlopen", lambda *a, **k: _Resp(data))
    embed.download_model(d)
    assert os.listdir(d) == ["model.onnx"] and embed.model_ready(d)
