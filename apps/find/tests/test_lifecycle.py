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


class _FakeIndexer:
    """Stand-in indexer: the old thread keeps 'running' for `slow` joins after stop()."""

    def __init__(self, slow=0):
        self.running, self.slow, self.calls = True, slow, []

    def stop(self, keep_watching=False):
        self.calls.append("stop")
        self._ending = self.slow

    def join(self, timeout=10):
        if self.running and self._ending <= 0:
            self.running = False
        self._ending -= 1
        return not self.running

    def start(self):
        if self.running:
            return False
        self.running = True
        self.calls.append("start")
        return True

    def release_models(self):
        self.calls.append("release")


def test_window_hide_then_show():
    ix = _FakeIndexer()
    w = lifecycle.Window(ix, False)
    w.wanted(True).join(5)
    assert ix.calls == ["stop", "release"] and w.idle and not ix.running
    w.wanted(False).join(5)
    assert ix.calls[-1] == "start" and ix.running and not w.idle


def test_window_show_twice_quickly_starts_once():
    ix = _FakeIndexer()
    w = lifecycle.Window(ix, True)
    ix.running = False                            # started hidden: no indexer yet
    a, b = w.wanted(False), w.wanted(False)
    a.join(5), b.join(5)
    assert ix.calls.count("start") == 1 and ix.running


def test_window_show_after_hide_whose_join_timed_out():
    ix = _FakeIndexer(slow=3)                     # the old thread needs several joins to end
    w = lifecycle.Window(ix, False, join_timeout=0.01)
    # the hide times out once, then the window is shown again before the old thread has gone
    ix.stop(); w.stopping = True
    assert ix.join() is False
    w.wanted(False).join(5)
    assert ix.running and not w.idle and not w.stopping    # indexing is back on; no lost show
    assert "release" not in ix.calls


def test_window_latest_wish_wins():
    ix = _FakeIndexer(slow=2)
    w = lifecycle.Window(ix, False, join_timeout=0.01)
    w.wanted(True)
    t = w.wanted(False)
    t.join(5)
    time.sleep(0.2)
    assert not w.want_idle and ix.running


def _pool_with(fut_factory, monkeypatch):
    class Pool:
        def __init__(self, max_workers, initializer, initargs):
            self.down = False

        def submit(self, fn, texts):
            return fut_factory()

        def shutdown(self, wait=True, cancel_futures=False):
            self.down = True

    monkeypatch.setattr(indexer.cf, "ProcessPoolExecutor", Pool)
    ix = indexer.Indexer(None, _S())
    ix._vectors_in_worker = True
    return ix


def test_worker_failure_returns_none_and_next_batch_gets_a_new_pool(monkeypatch):
    import concurrent.futures.process as cfp

    def broken():
        f = cf.Future()
        f.set_exception(cfp.BrokenProcessPool("worker died"))
        return f

    ix = _pool_with(broken, monkeypatch)
    assert ix._encode(["a"]) is None              # the indexer thread carries on, the batch is redone
    assert ix._mpool is None
    ok = []
    ix2 = _pool_with(lambda: ok.append(1) or _done(), monkeypatch)
    assert ix2._encode(["a"]) is not None


def _done():
    f = cf.Future()
    f.set_result(np.zeros((1, embed.MODEL_DIM), np.float32).tobytes())
    return f


def test_hung_meaning_job_is_given_up(monkeypatch):
    monkeypatch.setattr(indexer, "MEANING_TIMEOUT", 0.3)
    ix = _pool_with(cf.Future, monkeypatch)       # a future that never completes
    t0 = time.monotonic()
    assert ix._encode(["a"]) is None
    assert time.monotonic() - t0 < 5 and ix._mpool is None


def test_settle_never_starts_the_indexer_while_quitting():
    """I-1: a show that is still settling when Quit is chosen must not start indexing again after quit's stop."""
    ix = _FakeIndexer()
    quitting = [False]
    w = lifecycle.Window(ix, True, quitting=lambda: quitting[0])
    ix.running = False
    quitting[0] = True
    w.wanted(False).join(5)
    assert "start" not in ix.calls and not ix.running


def test_hiding_the_window_goes_idle_when_background_indexing_is_off():
    """I-2: Esc / "Hide after opening" stop indexing and the workers like closing does (keep_background off)."""
    ix = _FakeIndexer()
    w = lifecycle.Window(ix, False)
    t = lifecycle.after_hide(w, _S(keep_background=False), hotkey_ok=True, quitting=False)
    t.join(5)
    assert ix.calls == ["stop", "release"] and w.idle
    ix2 = _FakeIndexer()
    w2 = lifecycle.Window(ix2, False)
    assert lifecycle.after_hide(w2, _S(keep_background=True), hotkey_ok=True, quitting=False) is None
    assert lifecycle.after_hide(w2, _S(keep_background=False), hotkey_ok=False, quitting=False) is None
    assert ix2.calls == [] and ix2.running            # background on, or no hotkey: just hidden


def test_release_if_idle_never_waits_for_a_model_load():
    """Re-review: the governor calls release_if_idle every tick; a load holding the lock must not stall it."""
    m = embed.Lazy(lambda: None, "meaning")
    m._model, m._used = object(), 0.0
    m._lock.acquire()                              # a load in progress on another thread
    try:
        t0 = time.monotonic()
        assert m.release_if_idle(0) is False and time.monotonic() - t0 < 0.5
        assert m._model is not None
    finally:
        m._lock.release()
    assert m.release_if_idle(0) is True and m._model is None
