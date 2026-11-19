"""The worker job's memory limit (jobs.worker_memory_limit_mb) is a backstop: when it is hit, every worker's
allocations fail for a while. Files must not be written off as "too big" for that, and someone must hear about it."""
import concurrent.futures as cf

import pytest

from nobadfind import extract, indexer, ocr
from nobadfind import governor as g
from nobadfind.activity import Activity


def _oom(*a, **k):
    raise MemoryError()


@pytest.fixture
def pdf(tmp_path):
    p = tmp_path / "a.pdf"
    p.write_bytes(b"%PDF-1.4\n%%EOF\n")
    return str(p)


def test_out_of_memory_is_a_retry_not_too_big(tmp_path, monkeypatch):
    f = tmp_path / "a.txt"
    f.write_text("hello there")
    monkeypatch.setattr(extract, "read_text", _oom)
    assert extract.work((1, str(f), ".txt", 5, 1 << 20)) == (1, 5, [], extract.OUT_OF_MEMORY)


def test_parsers_that_catch_everything_still_let_out_of_memory_through(tmp_path, monkeypatch, pdf):
    import pypdf
    monkeypatch.setattr(pypdf, "PdfReader", _oom)
    assert extract.work((1, pdf, ".pdf", 5, 1 << 20))[3] == extract.OUT_OF_MEMORY
    h = tmp_path / "a.html"
    h.write_text("<p>hi</p>")
    monkeypatch.setattr(extract._HTML, "feed", _oom)
    assert extract.work((2, str(h), ".html", 5, 1 << 20))[3] == extract.OUT_OF_MEMORY


def test_ocr_lets_out_of_memory_through(monkeypatch):
    monkeypatch.setattr(ocr, "_load", lambda: object())
    monkeypatch.setattr(ocr, "_recognize", _oom)
    with pytest.raises(MemoryError):
        ocr.image_bytes_text(b"x" * 100)


def test_ocr_engine_out_of_memory_is_not_remembered_as_missing(monkeypatch):
    monkeypatch.setattr(ocr, "_engine", None)
    monkeypatch.setattr(ocr, "_missing", None)
    import builtins
    real = builtins.__import__

    def imp(name, *a, **k):
        if name.startswith("winrt"):
            raise MemoryError()
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", imp)
    with pytest.raises(MemoryError):
        ocr._load()
    assert ocr._missing is None


# ---------- the indexer ----------
class SyncPool:
    """A pool that runs each job at once, in this process (so extract.work can be replaced)."""
    def __init__(self, *a, **k):
        self._processes = {}

    def submit(self, fn, *args):
        f = cf.Future()
        f.set_result(fn(*args))
        return f

    def shutdown(self, **k):
        pass


class Gov:
    def __init__(self, level=g.GENTLE):
        self.decision = g.Decision(level, "why")


def _ix(tmp_path, n=6):
    from nobadfind.store import Store
    from nobadfind.walker import Walker
    from nobadfind.settings import Settings
    docs = tmp_path / "docs"
    docs.mkdir()
    for i in range(n):
        (docs / f"n{i}.txt").write_text(f"note {i}")
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    Walker([str(docs)], gen=1, on_batch=s.upsert_files).run()
    st = Settings(str(tmp_path / "s.json"))
    st.update({"content": True, "content_max_mb": 1, "ocr": False})
    act = Activity()
    ix = indexer.Indexer(s, st, governor=Gov(), activity=act)
    ix.status["plan"] = {"text_workers": 4, "text_workers_idle": 4}
    return ix, s, act


def test_files_that_hit_the_limit_are_read_again_one_at_a_time(tmp_path, monkeypatch):
    ix, s, act = _ix(tmp_path)
    real, seen = extract.work, {}

    def work(job):
        seen[job[0]] = seen.get(job[0], 0) + 1
        if seen[job[0]] == 1:                              # the first try of every file hits the limit
            return job[0], job[3], [], extract.OUT_OF_MEMORY
        return real(job)
    monkeypatch.setattr(indexer.cf, "ProcessPoolExecutor", SyncPool)
    monkeypatch.setattr(indexer.extract, "work", work)
    for _ in range(3):                                    # the indexer loop calls it again each round
        ix._read_texts()
    assert s.needs_text({".txt"}, 1 << 20) == []
    errs = [r[0] for r in s.q("SELECT text_err FROM files WHERE text_err IS NOT NULL")]
    assert errs == []                                     # nothing written off
    assert any("memory limit" in a["text"] for a in act.recent())


def test_a_file_that_runs_out_alone_is_too_big(tmp_path, monkeypatch):
    ix, s, act = _ix(tmp_path, n=2)
    monkeypatch.setattr(indexer.cf, "ProcessPoolExecutor", SyncPool)
    monkeypatch.setattr(indexer.extract, "work", lambda job: (job[0], job[3], [], extract.OUT_OF_MEMORY))
    for _ in range(4):
        ix._read_texts()
    assert s.needs_text({".txt"}, 1 << 20) == []          # alone and still out of memory: too big, as before
    notes = [a for a in act.recent() if "memory limit" in a["text"]]
    assert len(notes) == 1                                # said once, not per file


def test_photo_reader_out_of_memory_is_a_retry(tmp_path, monkeypatch):
    from nobadfind import photo
    p = tmp_path / "a.jpg"
    p.write_bytes(b"\xff\xd8" + b"x" * 20000)
    monkeypatch.setattr(photo, "decode_224", _oom)
    assert photo.embed_photo((1, str(p), 5, str(tmp_path)))[3] == photo.OUT_OF_MEMORY


class BrokenPool:
    """The meaning worker can't start (its model doesn't fit under the limit): every batch fails."""
    def __init__(self, *a, **k):
        self._processes = {}

    def submit(self, fn, *args):
        f = cf.Future()
        f.set_exception(cf.process.BrokenProcessPool("worker died while starting"))
        return f

    def shutdown(self, **k):
        pass


def test_a_meaning_worker_that_keeps_failing_backs_off_and_says_so_once(tmp_path, monkeypatch):
    ix, s, act = _ix(tmp_path, n=1)
    ix._vectors_in_worker, ix.embedder = True, object()
    now = [1000.0]
    ix._clock = lambda: now[0]
    monkeypatch.setattr(indexer.cf, "ProcessPoolExecutor", BrokenPool)
    calls = []
    monkeypatch.setattr(ix, "_name_vectors", lambda: calls.append(ix._encode(["x"])))
    monkeypatch.setattr(ix, "_chunk_vectors", lambda: None)
    ix._make_vectors()
    assert calls == [None]
    ix._make_vectors()                                    # right away: backing off, no new worker
    assert calls == [None]
    now[0] += 31
    ix._make_vectors()
    assert calls == [None, None]
    now[0] += 31                                          # the second wait is longer (60 s)
    ix._make_vectors()
    assert len(calls) == 2
    now[0] += 30
    ix._make_vectors()
    assert len(calls) == 3
    notes = [a for a in act.recent() if a["kind"] == "kill" and "meaning worker" in a["text"]]
    assert len(notes) == 1
