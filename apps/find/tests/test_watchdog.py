from nobadfind.activity import Activity
from nobadfind.watchdog import Watchdog


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make(pids=(), mem=None, job_mb=0, names=None):
    c = Clock()
    log = {"kill": [], "release": 0, "recycle": 0}
    act = Activity()
    w = Watchdog(act, kill=log["kill"].append,
                 info=lambda pid: {"pid": pid, "cpu_seconds": 0.0, "memory_mb": (mem or {}).get(pid, 10)},
                 pids=lambda: list(pids), job_usage=lambda: {"memory_mb": job_mb},
                 release=lambda: log.__setitem__("release", log["release"] + 1),
                 recycle=lambda: log.__setitem__("recycle", log["recycle"] + 1),
                 names=lambda: names or {}, clock=c)
    return w, c, log, act


def test_kills_only_its_own_big_worker():
    w, c, log, act = make(pids=[11, 12], mem={11: 1638, 12: 400, 99: 9000}, names={11: "text reader"})
    w.check()
    assert log["kill"] == [11]
    assert act.recent()[0] == {"t": act.recent()[0]["t"], "kind": "kill",
                               "text": "Stopped a text reader using 1.6 GB; the file is skipped"}


def test_small_worker_message_in_mb():
    w, c, log, act = make(pids=[5], mem={5: 1501}, names={5: "text reader"})
    w.check()
    assert act.recent()[0]["text"] == "Stopped a text reader using 1.5 GB; the file is skipped"


def test_job_memory_releases_models_once_per_5_min():
    w, c, log, act = make(job_mb=3100)
    w.check()
    w.check()
    assert log["release"] == 1 and log["recycle"] == 1          # M-5: the worker pools start fresh too
    assert act.recent()[0]["kind"] == "model"
    c.t += 299
    w.check()
    assert log["release"] == 1
    c.t += 2
    w.check()
    assert log["release"] == 2


def test_worker_names_and_backoff():
    names = {1: "meaning worker", 2: "photo worker", 3: "text reader"}
    w, c, log, act = make(pids=[1, 2, 3, 4], mem={1: 2048, 2: 1600, 3: 1600, 4: 1600}, names=names)
    w.check()
    texts = [a["text"] for a in act.recent()]
    assert any(t.startswith("Stopped the meaning worker using 2.0 GB") for t in texts)
    assert any(t.startswith("Stopped the photo worker") for t in texts)
    assert any(t.startswith("Stopped a text reader") for t in texts)
    assert any(t.startswith("Stopped a background worker") for t in texts)
    c.t += 60
    w.check()                       # second time for each kind: killed, then left alone
    assert len(log["kill"]) == 8
    assert any(a["kind"] == "info" and "left alone" in a["text"] for a in act.recent())
    c.t += 60
    w.check()
    assert len(log["kill"]) == 8
    c.t += 1801
    w.check()
    assert len(log["kill"]) == 12
