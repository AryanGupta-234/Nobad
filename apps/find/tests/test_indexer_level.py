"""The governor thread, and the indexer obeying its level."""
import json
import time

from nobadfind import governor as g
from nobadfind import indexer
from nobadfind.activity import Activity
from nobadfind.governor import Governor, Sample
from nobadfind.settings import Settings, coerce


class S(dict):
    def get(self, k, d=None):
        return super().get(k, d)


class Apps:
    def __init__(self):
        self.lags, self.quiet = [], []

    def start_level(self, exe):
        return None

    def record_lag(self, exe, sample):
        self.lags.append(exe)

    def quiet_session(self, exe):
        self.quiet.append(exe)


class Group:
    def __init__(self):
        self.caps = []

    def set_cpu_cap(self, p):
        self.caps.append(p)
        return True


class FakeJobs:
    def __init__(self):
        self.WORKERS, self.OUTER = Group(), None


def smp(t=0.0, **kw):
    base = dict(t=t, cpu=20.0, gpu=None, mem_load=40, free_mb=8000, find_cpu=0.0, foreground="",
                game=False, presentation=False, hung=False, battery=False, call=False, idle_s=0.0)
    base.update(kw)
    return Sample(**base)


def gov(samples, jobs=None, apps=None, **settings):
    it = iter(samples)
    act = Activity()
    gv = Governor(S(**settings), apps or Apps(), act, sense=lambda: next(it), jobs=jobs or FakeJobs())
    return gv, act


GAME = dict(foreground="forza.exe", game=True)


def test_governor_thread_applies_cap_and_logs():
    jobs = FakeJobs()
    gv, act = gov([smp(t=time.time() + i, **GAME) for i in range(3)], jobs=jobs)
    for _ in range(3):
        gv.tick()
    assert gv.decision.level == g.LIGHT
    assert jobs.WORKERS.caps == [15]
    assert [a["kind"] for a in act.recent()] == ["level"]


def test_no_workers_job_is_fine():
    jobs = FakeJobs()
    jobs.WORKERS = None
    gv, act = gov([smp(**GAME)], jobs=jobs)
    gv.tick()
    assert gv.decision.level == g.LIGHT


def test_history_is_capped_at_150():
    gv, _ = gov([smp(t=float(i)) for i in range(200)])
    for _ in range(200):
        gv.tick()
    h = gv.history
    assert len(h) == 150
    assert set(h[0]) == {"t", "cpu", "gpu", "find_cpu", "find_mb", "level"}


def test_pause_for_and_resume():
    gv, act = gov([])
    gv.pause_for(60)
    assert gv.brain.pause_until > time.time() + 50
    gv.resume()
    assert gv.brain.pause_until == 0
    assert [a["kind"] for a in act.recent()] == ["info", "info"]


def test_quiet_game_session_is_reported_once_it_ends():
    apps = Apps()
    gv, _ = gov([smp(t=1.0, **GAME), smp(t=2.0, **GAME), smp(t=3.0, foreground="code.exe"),
                 smp(t=400.0, foreground="code.exe"),
                 smp(t=401.0, foreground="forza.exe", game=True), smp(t=402.0, foreground="other.exe", game=True)],
                apps=apps)
    for _ in range(4):
        gv.tick()
    assert apps.quiet == ["forza.exe"]          # away from the front for over 5 minutes
    gv.tick()
    gv.tick()
    assert apps.quiet == ["forza.exe", "forza.exe"]    # another game came to the front


def test_laggy_game_session_is_not_quiet():
    """M-6 (restored): a session in which the game lagged while NOBAD Find worked never counts as quiet."""
    apps = Apps()
    gv, _ = gov([smp(t=1.0, hung=True, find_cpu=10.0, **GAME), smp(t=2.0, **GAME),
                 smp(t=3.0, foreground="code.exe"), smp(t=400.0, foreground="code.exe")], apps=apps)
    for _ in range(4):
        gv.tick()
    assert apps.lags == ["forza.exe"] and apps.quiet == []


def test_alt_tab_is_not_a_session_end():
    apps = Apps()
    gv, _ = gov([smp(t=1.0, **GAME), smp(t=100.0, foreground="code.exe"), smp(t=200.0, **GAME),
                 smp(t=450.0, foreground="code.exe"), smp(t=520.0, foreground="code.exe")], apps=apps)
    for _ in range(4):
        gv.tick()
    assert apps.quiet == []
    gv.tick()
    assert apps.quiet == ["forza.exe"]


class Boom:
    def start_level(self, exe):
        raise RuntimeError("db locked")

    record_lag = quiet_session = start_level


def test_failing_app_memory_does_not_stop_the_decision():
    jobs = FakeJobs()
    gv, act = gov([smp(t=1.0, hung=True, find_cpu=10.0, **GAME), smp(t=2.0, **GAME),
                   smp(t=500.0, foreground="code.exe")], jobs=jobs, apps=Boom())
    for _ in range(3):
        gv.tick()
    assert jobs.WORKERS.caps[0] == 5 and gv.decision.level in (g.PAUSED, g.LIGHT, g.GENTLE)
    assert [a["kind"] for a in act.recent()][-1] == "level"


def test_quiet_session_failure_keeps_decision_and_cap():
    jobs = FakeJobs()
    apps = Apps()
    apps.quiet_session = Boom().quiet_session
    gv, _ = gov([smp(t=1.0, **GAME), smp(t=500.0, foreground="code.exe")], jobs=jobs, apps=apps)
    gv.tick()
    gv.tick()
    assert jobs.WORKERS.caps == [15] and gv.decision.level == g.LIGHT


def test_usage_failure_does_not_abort_tick():
    class Bad:
        def usage(self):
            raise OSError("gone")

    jobs = FakeJobs()
    jobs.OUTER = Bad()
    gv, _ = gov([smp(t=1.0)], jobs=jobs)
    gv.tick()
    assert gv.history[0]["find_mb"] == 0


def test_usage_is_read_once_per_tick():
    class Counting:
        n = 0

        def usage(self):
            Counting.n += 1
            return {"cpu_seconds": 1.0, "memory_mb": 7}

    jobs = FakeJobs()
    jobs.OUTER = Counting()
    gv, _ = gov([smp(t=1.0)], jobs=jobs)
    gv.tick()
    assert Counting.n == 1 and gv.history[0]["find_mb"] == 7


def test_non_game_session_is_not_reported():
    apps = Apps()
    gv, _ = gov([smp(t=1.0, foreground="code.exe"), smp(t=2.0, foreground="a.exe")], apps=apps)
    gv.tick()
    gv.tick()
    assert apps.quiet == []


def test_old_pause_fullscreen_setting_migrates(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"pause_fullscreen": False}))
    assert Settings(str(p)).get("games_mode") == "off"
    p.write_text(json.dumps({"pause_fullscreen": False, "games_mode": "always"}))
    assert Settings(str(p)).get("games_mode") == "always"
    p.write_text(json.dumps({"pause_fullscreen": True}))
    assert Settings(str(p)).get("games_mode") == "smart"


def test_games_mode_coerce():
    assert coerce("games_mode", "bogus") == "smart"
    assert coerce("games_mode", "always") == "always"
    assert coerce("bar_hotkey", "nonsense") == "ctrl+alt+space"
    assert coerce("keep_background", "x") is False


class FakeGov:
    def __init__(self, level, reason="why"):
        self.decision = g.Decision(level, reason)


def test_indexer_waits_while_paused(tmp_path):
    fg = FakeGov(g.PAUSED, "Paused: test")
    ix = indexer.Indexer(None, S(), governor=fg)
    import threading
    threading.Timer(0.3, lambda: setattr(fg, "decision", g.Decision(g.GENTLE, "Gentle: ok"))).start()
    assert ix._wait_while_paused() is True
    assert ix.status["level"] == g.GENTLE and ix.status["reason"] == "Gentle: ok" and ix.status["paused"] == ""
    fg.decision = g.Decision(g.PAUSED, "Paused: again")
    threading.Timer(0.3, ix.stop_ev.set).start()
    assert ix._wait_while_paused() is False
    assert ix.status["paused"] == "Paused: again"


def test_indexer_uses_light_limit_and_rechecks_each_loop(tmp_path, monkeypatch):
    from nobadfind.store import Store
    from nobadfind.walker import Walker
    docs = tmp_path / "docs"
    docs.mkdir()
    for i in range(6):
        (docs / f"n{i}.txt").write_text(f"note {i}")
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    Walker([str(docs)], gen=1, on_batch=s.upsert_files).run()
    fg = FakeGov(g.LIGHT)
    ix = indexer.Indexer(s, S(content=True, content_max_mb=1, ocr=False, src_mail=True), governor=fg)
    ix.status["plan"] = {"text_workers": 3, "text_workers_idle": 4}
    peak, checks = [0], [0]

    class Pool:
        def __init__(self, *a, **k):
            pass

        def submit(self, fn, job):
            import concurrent.futures as cf
            f = cf.Future()
            f.set_result((job[0], job[3], [], ""))
            return f

        def shutdown(self, **k):
            pass

    orig = ix._wait_while_paused

    def counting():
        checks[0] += 1
        return orig()

    real_wait = indexer.cf.wait

    def spy(fs, **k):
        peak[0] = max(peak[0], len(fs))
        return real_wait(fs, **k)

    monkeypatch.setattr(indexer.cf, "ProcessPoolExecutor", Pool)
    monkeypatch.setattr(indexer.cf, "wait", spy)
    monkeypatch.setattr(ix, "_wait_while_paused", counting)
    ix._read_texts()
    assert peak[0] == 1                       # LIGHT: one file at a time
    assert checks[0] >= 6                     # the level is looked at before every batch
    assert ix.status["texts"] == 6
    s.close()


def test_breathe_only_skips_at_full(monkeypatch):
    waits = []
    fg = FakeGov(g.FULL)
    ix = indexer.Indexer(None, S(), governor=fg)
    monkeypatch.setattr(ix.stop_ev, "wait", lambda t: waits.append(t))
    ix._breathe()
    assert waits == []
    fg.decision = g.Decision(g.GENTLE, "")
    ix._breathe()
    assert waits == [0.25]


def test_every_tick_lets_idle_models_go():
    """I-11: with the window closed the indexer loop doesn't run, so the governor releases idle models."""
    calls = []
    it = iter([smp(t=1.0), smp(t=2.0)])
    gv = Governor(S(), Apps(), Activity(), sense=lambda: next(it), jobs=FakeJobs(),
                  release_idle=lambda: calls.append(1))
    gv.tick()

    def boom():
        raise RuntimeError("model busy")
    gv.release_idle = boom
    assert gv.tick().level                          # a failing release never stops the governor
    assert calls == [1]
