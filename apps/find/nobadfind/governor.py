"""The governor's brain: turns one sensor sample into a work level and a reason.

Pure logic. No Windows calls, and time comes only from ``Sample.t`` (seconds;
``Brain.pause_until`` is on the same clock and is shown as a wall-clock time,
so callers should feed ``time.time()``).
"""
import datetime
from dataclasses import dataclass

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
