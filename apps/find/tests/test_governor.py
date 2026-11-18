import datetime

from nobadfind import governor as g
from nobadfind.governor import Brain, Sample


class FakeSettings:
    def __init__(self, **kw):
        self.kw = kw

    def get(self, key):
        return self.kw.get(key)


class FakeApps:
    def __init__(self, learned=None):
        self.learned = learned
        self.lags = []

    def start_level(self, exe):
        return self.learned

    def record_lag(self, exe, sample):
        self.lags.append((exe, sample))


def smp(t=0.0, **kw):
    base = dict(t=t, cpu=20.0, gpu=None, mem_load=40, free_mb=8000, find_cpu=0.0,
                foreground="", game=False, presentation=False, hung=False,
                battery=False, call=False, idle_s=0.0)
    base.update(kw)
    return Sample(**base)


def brain(apps=None, cpu_count=8, **settings):
    return Brain(FakeSettings(**settings), apps or FakeApps(), cpu_count=cpu_count)


GAME = dict(foreground="forzahorizon5.exe", game=True)


def test_game_with_headroom_is_light():
    d = brain().decide(smp(**GAME))
    assert d.level == g.LIGHT
    assert d.reason == "Light: forzahorizon5 is running, so NOBAD Find uses 1 worker"


def test_game_and_hot_cpu_for_10s_pauses():
    b = brain()
    for t in range(0, 10):  # 0..9 s hot: held for 9 s only
        assert b.decide(smp(t, cpu=92, **GAME)).level == g.LIGHT
    d = b.decide(smp(10, cpu=92, **GAME))
    assert d.level == g.PAUSED
    assert d.reason == "Paused: the PC is busy (CPU 92%)"


def test_cool_sample_resets_hot_timer():
    b = brain()
    for t in range(0, 9):
        b.decide(smp(t, cpu=92, **GAME))
    b.decide(smp(9, cpu=30, **GAME))
    assert b.decide(smp(10, cpu=92, **GAME)).level == g.LIGHT
    assert b.decide(smp(19, cpu=92, **GAME)).level == g.LIGHT
    assert b.decide(smp(20, cpu=92, **GAME)).level == g.PAUSED


def test_presentation_always_pauses():
    d = brain().decide(smp(presentation=True, idle_s=999))
    assert d.level == g.PAUSED
    assert d.reason == "Paused: presentation or quiet time"


def test_battery_and_call_follow_settings():
    on = brain(pause_on_battery=True, pause_on_call=True)
    assert on.decide(smp(battery=True)).reason == "Paused: on battery"
    assert on.decide(smp(1, call=True)).reason == "Paused: microphone or camera in use"
    off = brain(pause_on_battery=False, pause_on_call=False)
    assert off.decide(smp(battery=True, call=True)).level == g.GENTLE


def test_games_mode_always_and_off():
    d = brain(games_mode="always").decide(smp(**GAME))
    assert d.level == g.PAUSED
    d = brain(games_mode="off").decide(smp(idle_s=0, **GAME))
    assert d.level == g.GENTLE
    d = brain(games_mode="off").decide(smp(idle_s=200, **GAME))
    assert d.level == g.FULL


def test_unknown_games_mode_is_smart():
    assert brain(games_mode="bogus").decide(smp(**GAME)).level == g.LIGHT


def test_step_up_one_level_after_30s():
    b = brain()
    assert b.decide(smp(0, presentation=True)).level == g.PAUSED
    # conditions clear; user is using the PC, so GENTLE is allowed
    assert b.decide(smp(1)).level == g.PAUSED
    assert b.decide(smp(30)).level == g.PAUSED  # only 29 s allowed
    assert b.decide(smp(31)).level == g.LIGHT
    assert b.decide(smp(60)).level == g.LIGHT
    assert b.decide(smp(61)).level == g.GENTLE


def test_step_down_is_immediate():
    b = brain()
    b.decide(smp(0))
    assert b.decide(smp(1, presentation=True)).level == g.PAUSED


def test_away_with_headroom_is_full():
    d = brain().decide(smp(idle_s=300))
    assert d.level == g.FULL
    assert d.reason == "Full: you're away"
    d = brain().decide(smp(idle_s=300, cpu=60))
    assert d.level == g.GENTLE
    assert d.reason == "Gentle: you're using the PC"


def test_unknown_gpu_is_ignored():
    b = brain()
    for t in range(0, 40):
        d = b.decide(smp(t, cpu=30, gpu=None))
    assert d.level == g.GENTLE


def test_hot_gpu_pauses():
    b = brain()
    b.decide(smp(0, gpu=90))
    assert b.decide(smp(10, gpu=90)).level == g.PAUSED


def test_low_memory_pauses():
    d = brain().decide(smp(free_mb=900))
    assert d.level == g.PAUSED
    assert d.reason == "Paused: low on memory (900 MB free)"


def test_hung_foreground_records_lag_once():
    apps = FakeApps()
    b = brain(apps)
    w = dict(foreground="game.exe", game=True, find_cpu=10.0)      # NOBAD Find is working
    d = b.decide(smp(0, hung=True, **w))
    assert d.level == g.PAUSED
    assert d.reason == "Paused: game isn't responding"
    b.decide(smp(1, hung=True, **w))
    assert len(apps.lags) == 1
    assert apps.lags[0][0] == "game.exe"
    b.decide(smp(2, **w))
    b.decide(smp(3, hung=True, **w))
    assert len(apps.lags) == 2


def test_no_lag_record_without_foreground():
    apps = FakeApps()
    brain(apps).decide(smp(0, free_mb=500))
    assert apps.lags == []


def test_learned_start_level_used():
    d = brain(FakeApps(learned=g.PAUSED)).decide(smp(**GAME))
    assert d.level == g.PAUSED
    assert "learned to make room for forzahorizon5" in d.reason


def test_user_pause_until():
    b = brain()
    b.pause_until = 1_000_000.0
    d = b.decide(smp(999_000.0, idle_s=999))
    hhmm = datetime.datetime.fromtimestamp(1_000_000.0).strftime("%H:%M")
    assert d.level == g.PAUSED
    assert d.reason == f"Paused: you asked for a break until {hhmm}"
    assert b.decide(smp(1_000_001.0)).level == g.PAUSED  # step-up delay still applies
    assert b.decide(smp(1_000_040.0)).level == g.LIGHT


def test_workers_for_levels():
    plan = {"text_workers_idle": 4, "text_workers": 2}
    assert g.workers_for(g.FULL, plan) == 4
    assert g.workers_for(g.GENTLE, plan) == 2
    assert g.workers_for(g.LIGHT, plan) == 1
    assert g.workers_for(g.PAUSED, plan) == 0


def test_hot_timer_is_continuous_across_other_pauses():
    apps = FakeApps()
    b = brain(apps)
    for t in range(0, 6):
        b.decide(smp(t, cpu=92, foreground="game.exe", game=True))
    for t in range(6, 126):
        b.decide(smp(t, cpu=20, presentation=True, foreground="game.exe", game=True))
    d = b.decide(smp(126, cpu=92, foreground="game.exe", game=True))
    assert d.level != g.PAUSED or "busy" not in d.reason
    assert apps.lags == []


def test_unknown_cpu_never_gives_full():
    assert brain().decide(smp(cpu=None, idle_s=300)).level == g.GENTLE


def test_lag_recorded_when_app_becomes_known_mid_lag():
    apps = FakeApps()
    b = brain(apps)
    b.decide(smp(0, free_mb=500, find_cpu=10.0))
    assert apps.lags == []
    b.decide(smp(1, free_mb=500, foreground="game.exe", game=True, find_cpu=10.0))
    assert [e for e, _ in apps.lags] == ["game.exe"]
    b.decide(smp(2, free_mb=500, foreground="game.exe", game=True, find_cpu=10.0))
    assert len(apps.lags) == 1


def test_finds_own_cpu_does_not_count_as_you_using_the_pc():
    """I-3: away, the PC at 85% of which NOBAD Find itself is 80%: Full holds (no flapping, no busy pause)."""
    apps = FakeApps()
    b = brain(apps)
    levels = {b.decide(smp(t, cpu=85.0, find_cpu=80.0, idle_s=300 + t, foreground="code.exe")).level
              for t in range(0, 62, 2)}
    assert levels == {g.FULL} and apps.lags == []


def test_busy_reason_shows_the_cpu_other_apps_use():
    b = brain()
    for t in range(0, 11):
        d = b.decide(smp(t, cpu=95.0, find_cpu=5.0))
    assert d.level == g.PAUSED and d.reason == "Paused: the PC is busy (CPU 90%)"


def test_no_lag_is_learned_while_find_is_not_working():
    """I-4: Find idle (window closed, nothing running): a hung app is not blamed on NOBAD Find."""
    apps = FakeApps()
    d = brain(apps).decide(smp(0, hung=True, foreground="word.exe", find_cpu=0.5))
    assert d.level == g.PAUSED and apps.lags == []            # still paused, just not learned


def test_no_lag_is_learned_about_finds_own_window():
    apps = FakeApps()
    b = brain(apps)
    d = b.decide(smp(0, hung=True, foreground="nobadfind.exe", foreground_is_self=True, find_cpu=40.0))
    assert d.level == g.PAUSED and apps.lags == []
    b.decide(smp(1, foreground="word.exe", find_cpu=40.0))
    b.decide(smp(2, hung=True, foreground="word.exe", find_cpu=40.0))
    assert [e for e, _ in apps.lags] == ["word.exe"]


def test_unknown_app_is_an_app_unless_it_is_a_game():
    """M-7: with no exe name, a non-game reason says "an app"; game reasons keep "a game"."""
    assert brain().decide(smp(hung=True)).reason == "Paused: an app isn't responding"
    assert brain(games_mode="always").decide(smp(game=True)).reason == "Paused: a game is running"
    assert brain().decide(smp(game=True)).reason.startswith("Light: a game is running")


def test_working_is_measured_in_cores_not_a_share_of_all_cpus():
    """Re-review: at Light (1 worker) on a 32-thread PC Find uses about 3% of all CPUs; that is one busy core, so
    a game that lags then is still learned. Half a core is the line."""
    apps = FakeApps()
    b = brain(apps, cpu_count=32)
    assert b.decide(smp(0, hung=True, find_cpu=3.2, **GAME)).level == g.PAUSED
    assert [e for e, _ in apps.lags] == ["forzahorizon5.exe"]
    idle = FakeApps()
    brain(idle, cpu_count=32).decide(smp(0, hung=True, find_cpu=0.5, **GAME))
    assert idle.lags == []
