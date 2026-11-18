from nobadfind import governor as g
from nobadfind.activity import Activity
from nobadfind.appmemory import AppMemory
from nobadfind.store import Store

DAY = 86400.0


def sample(t=1_000_000.0, cpu=90.0, gpu=None):
    return g.Sample(t=t, cpu=cpu, gpu=gpu, mem_load=50, free_mb=4000, find_cpu=5.0, foreground="x.exe",
                    game=True, presentation=False, hung=False, battery=False, call=False, idle_s=0.0)


def mem(tmp_path):
    return AppMemory(Store(str(tmp_path / "i.db"), encrypt=False))


def test_one_lag_starts_light(tmp_path):
    m = mem(tmp_path)
    assert m.start_level("x.exe") is None
    m.record_lag("X.EXE", sample())
    assert m.start_level("x.exe") == g.LIGHT
    row = m.list()[0]
    assert row["exe"] == "x.exe" and row["lag_events"] == 1 and row["worst_cpu"] == 90.0
    assert row["worst_gpu"] is None and "once" in row["reason"]


def test_two_lags_start_paused(tmp_path):
    m = mem(tmp_path)
    m.record_lag("x.exe", sample(1_000_000.0, gpu=70.0))
    m.record_lag("x.exe", sample(1_000_000.0 + DAY, cpu=95.0))
    assert m.start_level("x.exe") == g.PAUSED
    row = m.list()[0]
    assert row["lag_events"] == 2 and row["worst_cpu"] == 95.0 and row["worst_gpu"] == 70.0
    assert "twice in the last 30 days" in row["reason"]


def test_old_lags_are_forgotten(tmp_path):
    m = mem(tmp_path)
    m.record_lag("x.exe", sample(1_000_000.0))
    m.record_lag("x.exe", sample(1_000_000.0 + 31 * DAY))
    assert m.start_level("x.exe") == g.LIGHT
    assert m.list()[0]["lag_events"] == 1


def test_three_quiet_sessions_step_up(tmp_path):
    m = mem(tmp_path)
    m.record_lag("x.exe", sample())
    m.record_lag("x.exe", sample(1_000_100.0))
    for _ in range(2):
        m.quiet_session("x.exe")
    assert m.start_level("x.exe") == g.PAUSED
    m.quiet_session("x.exe")
    assert m.start_level("x.exe") == g.LIGHT
    for _ in range(3):
        m.quiet_session("x.exe")
    assert m.start_level("x.exe") is None
    m.quiet_session("never-seen.exe")
    assert len(m.list()) == 1


def test_lag_resets_quiet_count(tmp_path):
    m = mem(tmp_path)
    m.record_lag("x.exe", sample())
    m.quiet_session("x.exe")
    m.quiet_session("x.exe")
    m.record_lag("x.exe", sample(1_000_100.0))
    m.quiet_session("x.exe")
    m.quiet_session("x.exe")
    assert m.start_level("x.exe") == g.PAUSED


def test_reset_one_and_all(tmp_path):
    m = mem(tmp_path)
    m.record_lag("a.exe", sample())
    m.record_lag("b.exe", sample())
    m.reset("a.exe")
    assert [r["exe"] for r in m.list()] == ["b.exe"]
    m.reset()
    assert m.list() == [] and m.start_level("b.exe") is None


def test_names_only_no_paths(tmp_path):
    m = mem(tmp_path)
    m.record_lag(r"C:\Games\x.exe", sample())
    m.record_lag("C:/Games/x.exe", sample())
    m.record_lag("a" * 65 + ".exe", sample())
    m.record_lag("", sample())
    assert m.list() == []
    assert m.start_level(r"C:\Games\x.exe") is None


def test_memory_survives_reopen(tmp_path):
    m = mem(tmp_path)
    m.record_lag("x.exe", sample())
    m.record_lag("x.exe", sample(1_000_100.0))
    m.store.close()
    m2 = mem(tmp_path)
    assert m2.start_level("x.exe") == g.PAUSED
    assert m2.list()[0]["lag_events"] == 2


def test_activity_keeps_50_newest():
    a = Activity()
    for i in range(60):
        a.add("info", f"n{i}")
    r = a.recent()
    assert len(r) == 50 and r[0]["text"] == "n59" and r[-1]["text"] == "n10"
    assert set(r[0]) == {"t", "kind", "text"}
    assert [x["text"] for x in a.recent(2)] == ["n59", "n58"]
