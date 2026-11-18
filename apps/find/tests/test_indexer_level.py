"""The governor thread, and the indexer obeying its level."""
import concurrent.futures as cf
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
    gv, _ = gov([smp(t=1.0, hung=True, find_cpu=100.0, **GAME), smp(t=2.0, **GAME),
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
    gv, act = gov([smp(t=1.0, hung=True, find_cpu=100.0, **GAME), smp(t=2.0, **GAME),
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

    def counting(*a, **k):
        checks[0] += 1
        return orig(*a, **k)

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


# ---------- paused: nothing runs (I-8), paused time is not work time (I-9), kills are listed (I-10) ----------
class _Proc:
    def __init__(self):
        self.ended = False

    def terminate(self):
        self.ended = True


class _Pool:
    """A ProcessPoolExecutor stand-in with one worker process and futures the test completes."""
    made = []

    def __init__(self, *a, **k):
        self._processes = {4242: _Proc()}
        self.futures, self.down = [], False
        _Pool.made.append(self)

    def submit(self, fn, *args):
        f = cf.Future()
        self.futures.append((f, args))
        return f

    def shutdown(self, **k):
        self.down = True
        self._processes = {}


def _clocked(ix, fg, per_wait, unpause_after=None):
    """A fake clock: each pause-wait round moves it per_wait seconds; after unpause_after rounds the level is
    Gentle again."""
    c, rounds = [0.0], [0]
    ix._clock = lambda: c[0]

    def wait(t=None):
        c[0] += per_wait
        rounds[0] += 1
        if unpause_after is not None and rounds[0] >= unpause_after:
            fg.decision = g.Decision(g.GENTLE, "Gentle: ok")
        return ix.stop_ev.is_set()
    ix.stop_ev.wait = wait
    return c


def _text_ix(tmp_path, fg, n=1):
    from nobadfind.store import Store
    from nobadfind.walker import Walker
    docs = tmp_path / "docs"
    docs.mkdir()
    for i in range(n):
        (docs / f"n{i}.txt").write_text(f"note {i}")
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    Walker([str(docs)], gen=1, on_batch=s.upsert_files).run()
    act = Activity()
    ix = indexer.Indexer(s, S(content=True, content_max_mb=1, ocr=False, src_mail=True), governor=fg, activity=act)
    ix.status["plan"] = {"text_workers": 1, "text_workers_idle": 1}
    return ix, s, act


def test_long_pause_ends_the_text_readers(tmp_path, monkeypatch):
    """I-8: paused for over a minute (low memory, a game), the reader processes end; the file in flight is
    simply read again later, not marked."""
    fg = FakeGov(g.GENTLE)
    ix, s, act = _text_ix(tmp_path, fg)
    _Pool.made.clear()
    monkeypatch.setattr(indexer.cf, "ProcessPoolExecutor", _Pool)

    def no_result(fs, **k):
        assert ix.worker_names() == {4242: "text reader"}
        fg.decision = g.Decision(g.PAUSED, "Paused: low on memory (900 MB free)")
        return set(), set(fs)
    monkeypatch.setattr(indexer.cf, "wait", no_result)
    _clocked(ix, fg, per_wait=20)
    ix._read_texts()
    pool = _Pool.made[0]
    assert pool._processes == {} and pool.down and ix.worker_names() == {}
    assert ix._recycled is True
    assert len(s.needs_text({".txt"}, 1 << 20)) == 1          # not marked: read again when work resumes
    assert any(a["kind"] == "kill" and "ended its text readers" in a["text"] for a in act.recent())
    s.close()


def test_paused_time_does_not_count_against_a_file(tmp_path, monkeypatch):
    """I-9: 250 s of work, a 30 s pause, 40 s more: 290 s of work, under the 300 s limit (the old clock said 320)."""
    fg = FakeGov(g.GENTLE)
    ix, s, act = _text_ix(tmp_path, fg)
    _Pool.made.clear()
    monkeypatch.setattr(indexer.cf, "ProcessPoolExecutor", _Pool)
    c = _clocked(ix, fg, per_wait=30, unpause_after=1)
    calls = [0]

    def scripted(fs, **k):
        calls[0] += 1
        if calls[0] == 1:
            c[0] += 250
            fg.decision = g.Decision(g.PAUSED, "Paused: on battery")
            return set(), set(fs)
        if calls[0] == 2:
            c[0] += 40
            return set(), set(fs)
        f, args = _Pool.made[0].futures[0]
        job = args[0]
        f.set_result((job[0], job[3], [], ""))
        return {f}, set()
    monkeypatch.setattr(indexer.cf, "wait", scripted)
    ix._read_texts()
    assert s.q("SELECT text_err FROM files")[0][0] in ("", None)
    assert not any(a["kind"] == "kill" for a in act.recent())
    s.close()


def test_stuck_reader_is_listed_in_activity(tmp_path, monkeypatch):
    """I-10: a reader stopped after 5 minutes on one file shows in the activity list with its reason."""
    fg = FakeGov(g.GENTLE)
    ix, s, act = _text_ix(tmp_path, fg)
    monkeypatch.setattr(indexer.cf, "ProcessPoolExecutor", _Pool)
    c = [0.0]
    ix._clock = lambda: c[0]

    def slow(fs, **k):
        c[0] += 301
        return set(), set(fs)
    monkeypatch.setattr(indexer.cf, "wait", slow)
    ix._read_texts()
    assert s.q("SELECT text_err FROM files")[0][0] == "took too long"
    kills = [a["text"] for a in act.recent() if a["kind"] == "kill"]
    assert kills == ["Stopped a text reader stuck on one file for 5 minutes; the file is skipped"]
    s.close()


def test_long_pause_ends_the_meaning_worker(monkeypatch):
    """I-8: the meaning worker (and its model) leaves memory when the pause lasts over a minute."""
    fg = FakeGov(g.PAUSED, "Paused: a game")
    act = Activity()
    ix = indexer.Indexer(None, S(), governor=fg, activity=act)
    ix._mpool = _Pool()
    assert ix.worker_names() == {4242: "meaning worker"}
    _clocked(ix, fg, per_wait=20, unpause_after=None)
    ix._chunk_vectors()                       # the store is never reached: still paused
    assert ix._mpool is None and ix.worker_names() == {} and ix._recycled
    assert any("ended its meaning worker" in a["text"] for a in act.recent())


def test_meaning_timeout_is_listed_and_skips_paused_time(monkeypatch):
    fg = FakeGov(g.GENTLE)
    act = Activity()
    ix = indexer.Indexer(None, S(), governor=fg, activity=act)
    ix._vectors_in_worker = True
    monkeypatch.setattr(indexer.cf, "ProcessPoolExecutor", _Pool)
    c = [0.0]
    ix._clock = lambda: c[0]
    seen = []

    def tick(fs, timeout=None, **k):
        c[0] += 30
        seen.append(c[0])
        # one 30 s round paused: it must not count towards the 2-minute limit
        fg.decision = g.Decision(g.PAUSED if 30 <= c[0] < 60 else g.GENTLE, "x")
        return set(), set(fs)
    monkeypatch.setattr(indexer.cf, "wait", tick)
    assert ix._encode(["a"]) is None
    assert c[0] == 180                        # 150 s of work + 30 s paused (the old clock gave up at 150)
    assert ix._mpool is None
    kills = [a["text"] for a in act.recent() if a["kind"] == "kill"]
    assert kills == ["Restarted the meaning worker: a batch took longer than 2 minutes"]


def test_photo_wait_skips_paused_time_and_ends_the_reader_when_paused_long(monkeypatch):
    fg = FakeGov(g.GENTLE)
    ix = indexer.Indexer(None, S(), governor=fg)
    c = [0.0]
    ix._clock = lambda: c[0]
    f = cf.Future()

    def tick(fs, timeout=None, **k):
        c[0] += 10
        fg.decision = g.Decision(g.PAUSED if c[0] >= 200 else g.GENTLE, "x")
        return set(), set(fs)
    monkeypatch.setattr(indexer.cf, "wait", tick)
    assert ix._await(f, 300) is indexer.RECYCLE            # 190 s of work, then paused for a minute
    assert c[0] < 300
    ix.stop_ev.set()
    assert ix._await(f, 300) is None                       # stopping


def test_watchdog_recycle_ends_the_workers_at_a_safe_point(tmp_path, monkeypatch):
    """M-5: Find over its memory limit: the worker pools end (not just the models), the work is redone later."""
    fg = FakeGov(g.GENTLE)
    ix, s, act = _text_ix(tmp_path, fg)
    _Pool.made.clear()
    monkeypatch.setattr(indexer.cf, "ProcessPoolExecutor", _Pool)

    def no_result(fs, **k):
        ix.recycle_workers()                       # the watchdog, from its own thread
        return set(), set(fs)
    monkeypatch.setattr(indexer.cf, "wait", no_result)
    ix._read_texts()
    assert _Pool.made[0]._processes == {} and ix.worker_names() == {} and ix._recycled
    assert len(s.needs_text({".txt"}, 1 << 20)) == 1
    assert any("Using a lot of memory, so NOBAD Find ended its text readers" in a["text"] for a in act.recent())
    ix.recycle_workers()
    assert ix._recycle_req is False                # no worker running: nothing to do
    ix._mpool = _Pool()
    ix.recycle_workers()
    assert ix._await(cf.Future(), 300) is indexer.RECYCLE    # a meaning or photo batch in flight stops too
    s.close()
