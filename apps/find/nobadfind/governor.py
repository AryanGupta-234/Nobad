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

# Every tunable number lives here.
LIMITS = {
    "HOT_CPU": 85,
    "HOT_GPU": 85,
    "HOT_FOR": 10,
    "LOW_FREE_MB": 1500,
    "STEP_UP_AFTER": 30,
    "IDLE_AFTER": 120,
    "IDLE_CPU_MAX": 50,
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


def _app(exe):
    name = (exe or "").lower()
    if name.endswith(".exe"):
        name = name[:-4]
    return name or "a game"


def _prefix(level):
    return level.capitalize()


class Brain:
    def __init__(self, settings, apps):
        self.settings = settings
        self.apps = apps
        self.pause_until = 0.0
        self._level = None       # level currently applied
        self._up_since = None    # when a higher level became continuously allowed
        self._hot_since = None   # when CPU/GPU became continuously hot
        self._lag_recorded = False  # this lag episode already sent to record_lag

    def _games_mode(self):
        mode = self.settings.get("games_mode")
        return mode if mode in ("always", "smart", "off") else "smart"

    def _wanted(self, s):
        """The level the sensors allow right now, with its reason."""
        hot = ((s.cpu is not None and s.cpu >= LIMITS["HOT_CPU"])
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
            lag = f"Paused: the PC is busy (CPU {round(s.cpu)}%)" if (
                s.cpu is not None and s.cpu >= LIMITS["HOT_CPU"]
            ) else f"Paused: the PC is busy (graphics {round(s.gpu)}%)"
        elif s.free_mb < LIMITS["LOW_FREE_MB"]:
            lag = f"Paused: low on memory ({s.free_mb} MB free)"
        if lag:
            if not self._lag_recorded and s.foreground:
                self.apps.record_lag(s.foreground, s)
                self._lag_recorded = True
            return PAUSED, lag
        self._lag_recorded = False

        if s.game:
            mode = self._games_mode()
            if mode == "always":
                return PAUSED, f"Paused: {_app(s.foreground)} is running"
            if mode == "smart":
                learned = self.apps.start_level(s.foreground) if s.foreground else None
                if learned in ORDER and ORDER.index(learned) < ORDER.index(LIGHT):
                    return learned, (f"{_prefix(learned)}: NOBAD Find learned to "
                                     f"make room for {_app(s.foreground)}")
                return LIGHT, (f"Light: {_app(s.foreground)} is running, "
                               "so NOBAD Find uses 1 worker")
        if (s.idle_s >= LIMITS["IDLE_AFTER"] and s.cpu is not None
                and s.cpu < LIMITS["IDLE_CPU_MAX"]):
            return FULL, "Full: you're away"
        return GENTLE, "Gentle: you're using the PC"

    def decide(self, s):
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


class Governor(threading.Thread):
    def __init__(self, settings, apps, activity, sense=None, every=2.0, jobs=None):
        super().__init__(daemon=True, name="governor")
        self.settings, self.apps, self.activity = settings, apps, activity
        self.brain = Brain(settings, apps)
        self.every = every
        self.jobs = _jobs if jobs is None else jobs
        self.decision = Decision(GENTLE, "Gentle: starting up")
        self._history = deque(maxlen=HISTORY)
        self._stop_ev = threading.Event()
        self._applied = None
        self._session = {"exe": "", "game": False, "lagged": False}
        self._sense = sense or self._real_sense
        self._cpu, self._gpu = None, None
        self._slow = (0.0, False, False)         # (checked at, on battery, in call)
        self._last_cpu_s = None                  # (wall time, Find's CPU seconds)

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
        s = self._sense()
        d = self.brain.decide(s)
        self._track_session(s)
        outer = getattr(self.jobs, "OUTER", None)
        find_mb = outer.usage()["memory_mb"] if outer is not None else 0
        self._history.append({"t": s.t, "cpu": s.cpu, "gpu": s.gpu, "find_cpu": s.find_cpu,
                              "find_mb": find_mb, "level": d.level})
        if d.level != self._applied:
            self._applied = d.level
            workers = getattr(self.jobs, "WORKERS", None)
            if workers is not None:
                workers.set_cpu_cap(CPU_CAP[d.level])
            self.activity.add("level", d.reason)
        self.decision = d
        return d

    def _track_session(self, s):
        cur = self._session
        if s.foreground != cur["exe"]:
            if cur["exe"] and cur["game"] and not cur["lagged"]:
                self.apps.quiet_session(cur["exe"])
            cur.update(exe=s.foreground, game=False, lagged=False)
        if s.game:
            cur["game"] = True
        if self.brain._lag_recorded:
            cur["lagged"] = True

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
                      idle_s=winapi.idle_seconds())

    def _find_cpu(self, now):
        outer = getattr(self.jobs, "OUTER", None)
        if outer is None:
            return 0.0
        secs = outer.usage()["cpu_seconds"]
        last, self._last_cpu_s = self._last_cpu_s, (now, secs)
        if last is None or now <= last[0]:
            return 0.0
        return max(0.0, min(100.0, (secs - last[1]) / (now - last[0]) / (os.cpu_count() or 1) * 100))
