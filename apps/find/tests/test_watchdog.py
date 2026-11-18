from nobadfind.activity import Activity
from nobadfind.watchdog import Watchdog


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make(pids=(), mem=None, job_mb=0, visible=True, names=None, reload_ui=None):
    c = Clock()
    log = {"kill": [], "release": 0, "reload": 0, "quit": 0}
    act = Activity()
    w = Watchdog(act, kill=log["kill"].append,
                 info=lambda pid: {"pid": pid, "cpu_seconds": 0.0, "memory_mb": (mem or {}).get(pid, 10)},
                 pids=lambda: list(pids), job_usage=lambda: {"memory_mb": job_mb},
                 release=lambda: log.__setitem__("release", log["release"] + 1),
                 reload_ui=reload_ui or (lambda: log.__setitem__("reload", log["reload"] + 1)),
                 names=lambda: names or {},
                 quit_app=lambda: log.__setitem__("quit", log["quit"] + 1),
                 clock=c, visible=lambda: visible)
    return w, c, log, act


def test_kills_only_its_own_big_worker():
    w, c, log, act = make(pids=[11, 12], mem={11: 1638, 12: 400, 99: 9000}, names={11: "text reader"})
    w.beat()
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
    assert log["release"] == 1
    assert act.recent()[0]["kind"] == "model"
    c.t += 299
    w.beat()
    w.check()
    assert log["release"] == 1
    c.t += 2
    w.beat()
    w.check()
    assert log["release"] == 2


def settle():
    import time
    time.sleep(0.15)


def test_missing_heartbeat_reloads_then_quits():
    w, c, log, act = make()
    w.beat()
    c.t += 16
    w.check()
    settle()
    assert log["reload"] == 1 and log["quit"] == 0
    assert act.recent()[0]["kind"] == "info"
    w.beat()                       # the reloaded page is alive for a moment
    c.t += 16
    w.check()
    settle()
    assert log["reload"] == 1 and log["quit"] == 1


def test_late_second_miss_reloads_again():
    w, c, log, act = make()
    w.beat()
    c.t += 16
    w.check()
    w.beat()
    c.t += 200
    w.check()
    settle()
    assert log["reload"] == 2 and log["quit"] == 0


def test_minimized_page_is_not_a_miss():
    w, c, log, act = make()
    w.beat()
    w.page_visible(False)
    c.t += 300
    w.check()
    settle()
    assert log["reload"] == 0 and log["quit"] == 0
    w.page_visible(True)
    c.t += 10
    w.check()
    settle()
    assert log["reload"] == 0
    c.t += 6
    w.check()
    settle()
    assert log["reload"] == 1


def test_blocking_reload_does_not_block_check_and_next_miss_quits():
    import threading
    import time
    block = threading.Event()
    w, c, log, act = make(reload_ui=block.wait)
    w.beat()
    c.t += 16
    t0 = time.time()
    w.check()
    assert time.time() - t0 < 1
    c.t += 61                       # the hung page never sends a first heartbeat
    w.check()
    settle()
    assert log["quit"] == 1
    block.set()


def test_slow_first_load_is_not_a_miss():
    w, c, log, act = make()
    c.t += 40
    w.check()
    settle()
    assert log["reload"] == 0
    w.beat()
    c.t += 10
    w.check()
    settle()
    assert log["reload"] == 0
    w2, c2, log2, _ = make()
    c2.t += 61
    w2.check()
    settle()
    assert log2["reload"] == 1


def test_worker_names_and_backoff():
    names = {1: "meaning worker", 2: "photo worker", 3: "text reader"}
    w, c, log, act = make(pids=[1, 2, 3, 4], mem={1: 2048, 2: 1600, 3: 1600, 4: 1600}, names=names)
    w.beat()
    w.check()
    texts = [a["text"] for a in act.recent()]
    assert any(t.startswith("Stopped the meaning worker using 2.0 GB") for t in texts)
    assert any(t.startswith("Stopped the photo worker") for t in texts)
    assert any(t.startswith("Stopped a text reader") for t in texts)
    assert any(t.startswith("Stopped a background worker") for t in texts)
    c.t += 60
    w.beat()
    w.check()                       # second time for each kind: killed, then left alone
    assert len(log["kill"]) == 8
    assert any(a["kind"] == "info" and "left alone" in a["text"] for a in act.recent())
    c.t += 60
    w.beat()
    w.check()
    assert len(log["kill"]) == 8
    c.t += 1801
    w.beat()
    w.check()
    assert len(log["kill"]) == 12


def test_hidden_window_needs_no_heartbeat():
    w, c, log, act = make(visible=False)
    c.t += 600
    w.check()
    assert log["reload"] == 0 and log["quit"] == 0


def test_window_shown_gives_page_time():
    state = {"v": False}
    w, c, log, act = make()
    w.beat()
    w._visible = lambda: state["v"]
    c.t += 600
    state["v"] = True
    w.window_shown()
    c.t += 10
    w.check()
    assert log["reload"] == 0
    c.t += 6
    w.check()
    settle()
    assert log["reload"] == 1
