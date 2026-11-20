"""The governor: turns sensor samples into a work level and a reason.

``Brain`` is pure logic: time comes only from ``Sample.t`` (seconds; ``Brain.pause_until`` is on the
same clock and is shown as a wall-clock time, so callers feed ``time.time()``). ``Governor`` is the
thread that reads the real sensors every couple of seconds, runs the brain and applies the result.
"""
import datetime
import os
import threading
import time
from collections import deque
from dataclasses import dataclass

from . import jobs as _jobs
from . import winapi
from .log import log

FULL, GENTLE, LIGHT, PAUSED = "full", "gentle", "light", "paused"
ORDER = [PAUSED, LIGHT, GENTLE, FULL]
CPU_CAP = {FULL: None, GENTLE: 35, LIGHT: 15, PAUSED: 5}
ECO_LEVELS = (LIGHT, PAUSED)        # workers in efficiency mode (EcoQoS)

# Every tunable number lives here.
LIMITS = {
    "HOT_CPU": 85,
    "HOT_GPU": 85,
    "HOT_FOR": 10,
    "LOW_FREE_MB": 1500,
    "STEP_UP_AFTER": 30,
    "IDLE_AFTER": 120,
    "IDLE_CPU_MAX": 50,
    "LAG_FIND_CORES": 0.5,   # NOBAD Find counts as working (so a lag may be learned) from half a core
}

_EASING = {
    PAUSED: "Paused: waiting a moment before starting again",
    LIGHT: "Light: easing back in",
    GENTLE: "Gentle: easing back in",
    FULL: "Full: easing back in",
}


@dataclass
class Sample:
    t: float
    cpu: float | None
    gpu: float | None
    mem_load: int
    free_mb: int
    find_cpu: float
    foreground: str
    game: bool
    presentation: bool
    hung: bool
    battery: bool
    call: bool
    idle_s: float
    foreground_is_self: bool = False     # the window in front is NOBAD Find's own (main window or bar)


@dataclass
class Decision:
    level: str
    reason: str


def workers_for(level, plan):
    if level == FULL:
        return plan["text_workers_idle"]
    if level == GENTLE:
        return plan["text_workers"]
    if level == LIGHT:
        return 1
    return 0


def _app(exe, unknown="an app"):
    name = (exe or "").lower()
    if name.endswith(".exe"):
        name = name[:-4]
    return name or unknown


def _prefix(level):
    return level.capitalize()


class Brain:
    def __init__(self, settings, apps, cpu_count=None):
        self.settings = settings
        self.apps = apps
        self.cpu_count = cpu_count or os.cpu_count() or 1     # find_cpu is a percent of all of them
        self.pause_until = 0.0
        self._level = None       # level currently applied
        self._up_since = None    # when a higher level became continuously allowed
        self._hot_since = None   # when CPU/GPU became continuously hot
        self._lag_recorded = False  # this lag episode already sent to record_lag
        self.fixed = None        # a level pinned for a measurement (engine.measure_overrides, dev only)

    def _games_mode(self):
        mode = self.settings.get("games_mode")
        return mode if mode in ("always", "smart", "off") else "smart"

    def _wanted(self, s):
        """The level the sensors allow right now, with its reason. CPU is what the other apps use: Find's own
        work must not count as you using the PC (Full would never hold while you're away)."""
        others = None if s.cpu is None else max(0.0, s.cpu - (s.find_cpu or 0.0))
        hot = ((others is not None and others >= LIMITS["HOT_CPU"])
               or (s.gpu is not None and s.gpu >= LIMITS["HOT_GPU"]))
        if not hot:
            self._hot_since = None
        elif self._hot_since is None:
            self._hot_since = s.t
        hot_long = hot and s.t - self._hot_since >= LIMITS["HOT_FOR"]

        early = None
        if s.t < self.pause_until:
            until = datetime.datetime.fromtimestamp(self.pause_until).strftime("%H:%M")
            early = f"Paused: you asked for a break until {until}"
        elif s.presentation:
            early = "Paused: presentation or quiet time"
        elif self.settings.get("pause_on_battery") and s.battery:
            early = "Paused: on battery"
        elif self.settings.get("pause_on_call") and s.call:
            early = "Paused: microphone or camera in use"
        if early:
            self._lag_recorded = False
            return PAUSED, early

        lag = None
        if s.hung:
            lag = f"Paused: {_app(s.foreground)} isn't responding"
        elif hot_long:
            lag = f"Paused: the PC is busy (CPU {round(others)}%)" if (
                others is not None and others >= LIMITS["HOT_CPU"]
            ) else f"Paused: the PC is busy (graphics {round(s.gpu)}%)"
        elif s.free_mb < LIMITS["LOW_FREE_MB"]:
            lag = f"Paused: low on memory ({s.free_mb} MB free)"
        if lag:
            # learned only while Find is working, and never about Find's own window (still paused either way)
            # in cores, not a share of all CPUs: one Light worker on a 32-thread PC is only about 3%
            working = (s.find_cpu or 0.0) * self.cpu_count / 100 >= LIMITS["LAG_FIND_CORES"]
            if not self._lag_recorded and s.foreground and working and not s.foreground_is_self:
                self.apps.record_lag(s.foreground, s)
                self._lag_recorded = True
            return PAUSED, lag
        self._lag_recorded = False

        if s.game:
            mode = self._games_mode()
            if mode == "always":
                return PAUSED, f"Paused: {_app(s.foreground, 'a game')} is running"
            if mode == "smart":
                learned = self.apps.start_level(s.foreground) if s.foreground else None
                if learned in ORDER and ORDER.index(learned) < ORDER.index(LIGHT):
                    return learned, (f"{_prefix(learned)}: NOBAD Find learned to "
                                     f"make room for {_app(s.foreground, 'a game')}")
                return LIGHT, (f"Light: {_app(s.foreground, 'a game')} is running, "
                               "so NOBAD Find uses 1 worker")
        if (s.idle_s >= LIMITS["IDLE_AFTER"] and others is not None
                and others < LIMITS["IDLE_CPU_MAX"]):
            return FULL, "Full: you're away"
        return GENTLE, "Gentle: you're using the PC"

    def decide(self, s):
        if self.fixed in ORDER:
            self._level = self.fixed
            return Decision(self.fixed, f"{_prefix(self.fixed)}: fixed for a measurement")
        wanted, reason = self._wanted(s)
        if self._level is None:
            self._level = wanted
            self._up_since = None
            return Decision(wanted, reason)
        cur, want = ORDER.index(self._level), ORDER.index(wanted)
        if want <= cur:  # same or lower: apply at once
            self._level = wanted
            self._up_since = None
            return Decision(wanted, reason)
        # A higher level is allowed: it must hold for a while, then one step.
        if self._up_since is None:
            self._up_since = s.t
        if s.t - self._up_since >= LIMITS["STEP_UP_AFTER"]:
            self._level = ORDER[cur + 1]
            self._up_since = s.t
            if self._level == wanted:
                self._up_since = None
                return Decision(wanted, reason)
        return Decision(self._level, _EASING[self._level])


HISTORY = 150            # samples kept for the live chart (5 minutes at one every 2 s)
SLOW_SENSE_EVERY = 15    # battery and call checks cost a registry walk


SESSION_GAP = 300        # seconds a game may stay out of the front (alt-tab) before its session is over


class _SafeApps:
    def __init__(self, apps):
        self._apps = apps

    def start_level(self, exe):
        try:
            return self._apps.start_level(exe)
        except Exception as e:
            log(f"app memory unavailable: {type(e).__name__}", "warn")
            return None

    def record_lag(self, exe, sample):
        try:
            self._apps.record_lag(exe, sample)
        except Exception as e:
            log(f"app memory unavailable: {type(e).__name__}", "warn")

    def quiet_session(self, exe):
        try:
            self._apps.quiet_session(exe)
        except Exception as e:
            log(f"app memory unavailable: {type(e).__name__}", "warn")


class Governor(threading.Thread):
    def __init__(self, settings, apps, activity, sense=None, every=2.0, jobs=None, watchdog=None,
                 release_idle=None, eco=None):
        super().__init__(daemon=True, name="governor")
        self.settings, self.activity = settings, activity
        self.apps = _SafeApps(apps)                 # a store error must never stop the governor
        self.brain = Brain(settings, self.apps)
        self.every = every
        self.jobs = _jobs if jobs is None else jobs
        self.watchdog = watchdog
        self.release_idle = release_idle            # models idle for a few minutes leave memory (window closed too)
        self.decision = Decision(GENTLE, "Gentle: starting up")
        self._history = deque(maxlen=HISTORY)
        self._stop_ev = threading.Event()
        self._applied = None
        self._session = {"exe": "", "seen": 0.0, "lagged": False}   # the current game session
        self._usage = {"cpu_seconds": 0.0, "memory_mb": 0}
        self._sense = sense or self._real_sense
        self._cpu, self._gpu = None, None
        self._slow = (0.0, False, False)         # (checked at, on battery, in call)
        self._last_cpu_s = None                  # (wall time, Find's CPU seconds)
        self._eco = eco if eco is not None else (lambda on, pid, job=None: winapi.eco_qos(on, pid=pid, job=job))
        self._eco_set = {}                       # worker pid -> EcoQoS on/off as last applied

    # ---------- control ----------
    def pause_for(self, seconds):
        self.brain.pause_until = time.time() + max(0, int(seconds))
        self.activity.add("info", f"You paused NOBAD Find for {int(seconds) // 60} min")

    def resume(self):
        self.brain.pause_until = 0.0
        self.activity.add("info", "You resumed NOBAD Find")

    def stop(self):
        self._stop_ev.set()

    @property
    def history(self):
        return list(self._history)

    def run(self):
        while not self._stop_ev.is_set():
            try:
                self.tick()
            except Exception as e:                  # a sensor hiccup must never stop the governor
                log(f"governor tick failed: {type(e).__name__}", "warn")
            self._stop_ev.wait(self.every)

    # ---------- one step ----------
    def tick(self):
        self._usage = self._read_usage()            # once per tick: find_cpu and find_mb share it
        s = self._sense()
        d = self.brain.decide(s)
        self._history.append({"t": s.t, "cpu": s.cpu, "gpu": s.gpu, "find_cpu": s.find_cpu,
                              "find_mb": self._usage["memory_mb"], "level": d.level})
        if d.level != self._applied:
            self._applied = d.level
            workers = getattr(self.jobs, "WORKERS", None)
            if workers is not None:
                workers.set_cpu_cap(CPU_CAP[d.level])
            self.activity.add("level", d.reason)
        self.decision = d
        try:
            self._eco_workers(d.level)
        except Exception as e:
            log(f"governor could not set efficiency mode: {type(e).__name__}", "warn")
        try:
            self._track_session(s)
        except Exception as e:
            log(f"governor session tracking failed: {type(e).__name__}", "warn")
        try:
            if self.watchdog is not None:
                self.watchdog.check()
        except Exception as e:
            log(f"watchdog failed: {type(e).__name__}", "warn")
        try:
            if self.release_idle is not None:
                self.release_idle()
        except Exception as e:
            log(f"releasing idle models failed: {type(e).__name__}", "warn")
        return d

    def _eco_workers(self, level):
        """Efficiency mode (EcoQoS) for Find's worker processes at Light and Paused (a game, a call, a busy PC):
        Windows keeps them on efficiency cores at low clocks. Not at Gentle or Full, where indexing should keep its
        speed: in one test a reader ran 1.6x slower under EcoQoS (docs/measurements.md). Only pids still in the
        worker job, never this process; each set once per change."""
        workers = getattr(self.jobs, "WORKERS", None)
        if workers is None or not hasattr(workers, "pids"):
            return
        want, me = level in ECO_LEVELS, os.getpid()
        pids = [p for p in workers.pids() if p != me]
        self._eco_set = {p: v for p, v in self._eco_set.items() if p in pids}
        for pid in pids:
            if self._eco_set.get(pid) is not want and self._eco(want, pid, getattr(workers, "handle", None)):
                self._eco_set[pid] = want

    def _read_usage(self):
        outer = getattr(self.jobs, "OUTER", None)
        if outer is not None:
            try:
                return outer.usage()
            except Exception as e:
                log(f"governor could not read usage: {type(e).__name__}", "warn")
        return {"cpu_seconds": 0.0, "memory_mb": 0}

    def _track_session(self, s):
        """A game session ends when another game comes to the front, or when its exe has not been in
        front for SESSION_GAP seconds (alt-tab does not end it). A session without lag counts as quiet."""
        cur = self._session
        if cur["exe"]:
            if s.foreground == cur["exe"]:
                cur["seen"] = s.t
            elif (s.game and s.foreground) or s.t - cur["seen"] >= SESSION_GAP:
                if not cur["lagged"]:
                    self.apps.quiet_session(cur["exe"])
                cur["exe"] = ""
        if cur["exe"]:
            if s.foreground == cur["exe"] and self.brain._lag_recorded:
                cur["lagged"] = True
        elif s.game and s.foreground:
            cur.update(exe=s.foreground, seen=s.t, lagged=self.brain._lag_recorded)

    # ---------- real sensors ----------
    def _real_sense(self):
        if self._cpu is None:
            self._cpu, self._gpu = winapi.CpuSampler(), winapi.GpuSampler()
        now = time.time()
        if now - self._slow[0] >= SLOW_SENSE_EVERY:
            self._slow = (now, winapi.on_battery(), winapi.in_call())
        load, free = winapi.memory_status()
        return Sample(t=now, cpu=self._cpu.percent(), gpu=self._gpu.percent(), mem_load=load, free_mb=free,
                      find_cpu=self._find_cpu(now), foreground=winapi.foreground_exe(),
                      game=winapi.fullscreen_game(), presentation=winapi.presentation_mode(),
                      hung=winapi.foreground_hung(), battery=self._slow[1], call=self._slow[2],
                      idle_s=winapi.idle_seconds(), foreground_is_self=self._front_is_self())

    @staticmethod
    def _front_is_self():
        hwnd = winapi.foreground_window()
        return bool(hwnd) and winapi.window_pid(hwnd) == os.getpid()

    def _find_cpu(self, now):
        secs = self._usage["cpu_seconds"]
        if not secs and getattr(self.jobs, "OUTER", None) is None:
            return 0.0
        last, self._last_cpu_s = self._last_cpu_s, (now, secs)
        if last is None or now <= last[0]:
            return 0.0
        return max(0.0, min(100.0, (secs - last[1]) / (now - last[0]) / (os.cpu_count() or 1) * 100))
