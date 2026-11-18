from nobadfind.activity import Activity
from nobadfind.watchdog import Watchdog


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make(pids=(), mem=None, job_mb=0, visible=True):
    c = Clock()
    log = {"kill": [], "release": 0, "reload": 0, "quit": 0}
    act = Activity()
    w = Watchdog(act, kill=log["kill"].append,
                 info=lambda pid: {"pid": pid, "cpu_seconds": 0.0, "memory_mb": (mem or {}).get(pid, 10)},
                 pids=lambda: list(pids), job_usage=lambda: {"memory_mb": job_mb},
                 release=lambda: log.__setitem__("release", log["release"] + 1),
                 reload_ui=lambda: log.__setitem__("reload", log["reload"] + 1),
                 quit_app=lambda: log.__setitem__("quit", log["quit"] + 1),
                 clock=c, visible=lambda: visible)
    return w, c, log, act


def test_kills_only_its_own_big_worker():
    w, c, log, act = make(pids=[11, 12], mem={11: 1638, 12: 400, 99: 9000})
    w.beat()
    w.check()
    assert log["kill"] == [11]
    assert act.recent()[0] == {"t": act.recent()[0]["t"], "kind": "kill",
                               "text": "Stopped a text reader using 1.6 GB; the file is skipped"}


def test_small_worker_message_in_mb():
    w, c, log, act = make(pids=[5], mem={5: 1501})
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


def test_missing_heartbeat_reloads_then_quits():
    w, c, log, act = make()
    c.t += 16
    w.check()
    assert log["reload"] == 1 and log["quit"] == 0
    assert act.recent()[0]["kind"] == "info"
    c.t += 5
    w.check()
    assert log["reload"] == 1
    c.t += 16
    w.check()
    assert log["quit"] == 1


def test_late_second_miss_reloads_again():
    w, c, log, act = make()
    c.t += 16
    w.check()
    c.t += 200
    w.check()
    assert log["reload"] == 2 and log["quit"] == 0


def test_hidden_window_needs_no_heartbeat():
    w, c, log, act = make(visible=False)
    c.t += 600
    w.check()
    assert log["reload"] == 0 and log["quit"] == 0


def test_window_shown_gives_page_time():
    state = {"v": False}
    w, c, log, act = make()
    w._visible = lambda: state["v"]
    c.t += 600
    state["v"] = True
    w.window_shown()
    c.t += 10
    w.check()
    assert log["reload"] == 0
    c.t += 6
    w.check()
    assert log["reload"] == 1
