"""Detects sleep/resume and network changes (Wi-Fi <-> Ethernet, new router, network lost/returned) and applies
trusted-network rules. Event driven where possible: Windows tells us when an address or route changes
(NotifyUnicastIpAddressChange / NotifyRouteChange2) so the thread sleeps otherwise. The 5-second tick only runs
while a tunnel is wanted, purely to notice that the machine was asleep (wall clock jumped)."""
import os
import threading
import time

from . import netinfo
from .logbus import log
from .notify import notify
from .syscmd import spawn

TICK = 5.0
RESUME_GAP = 25.0   # seconds of wall-clock jump that count as "the machine slept"
SETTLE = 3.0        # let DHCP / Wi-Fi association finish before reading the new fingerprint
IDLE_POLL = 15.0


class NetWatch:
    def __init__(self, tunnel, settings, clock=time.time, fp_fn=None, name_fn=None, use_events=True):
        self.tunnel = tunnel
        self.settings = settings
        self.listeners = []
        self.clock = clock
        self.fp_fn = fp_fn or netinfo.physical_fingerprint
        self.name_fn = name_fn or netinfo.current_network_name
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._ev = False
        self._last = clock()
        self._stable = None
        self._manual_off = False
        self._warned_hidden = False
        self._busy = threading.Lock()
        self.current = None
        self.events_ok = False
        self._cbs = []
        self._use_events = use_events
        self.history = []   # (time, kind, detail) — shown in diagnostics

    # ---- control
    def start(self):
        if self._use_events:
            self.events_ok = self._register_events()
        threading.Thread(target=self._loop, daemon=True).start()
        if self.settings.get("ssid_rules"):
            spawn(self.evaluate_rules, "startup")

    def stop(self):
        self._stop.set()
        self._wake.set()

    def poke(self):
        self._wake.set()

    def note_manual_disconnect(self):
        self._manual_off = True

    # ---- Windows change notifications
    def _register_events(self):
        if os.name != "nt":
            return False
        try:
            import ctypes
            iph = ctypes.WinDLL("iphlpapi")
            CB = ctypes.WINFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong)

            def on_event(_ctx, _row, _typ):
                self._ev = True
                self._wake.set()

            cb = CB(on_event)
            self._cbs.append(cb)  # keep alive
            ok = 0
            for fn_name in ("NotifyUnicastIpAddressChange", "NotifyRouteChange2"):
                fn = getattr(iph, fn_name)
                fn.argtypes = [ctypes.c_ushort, CB, ctypes.c_void_p, ctypes.c_ubyte, ctypes.POINTER(ctypes.c_void_p)]
                fn.restype = ctypes.c_ulong
                handle = ctypes.c_void_p()
                if fn(0, cb, None, 0, ctypes.byref(handle)) == 0:
                    ok += 1
                    self._cbs.append(handle)
            return ok == 2
        except Exception as e:  # pragma: no cover - Windows only
            log(f"network change notifications unavailable ({e}); polling instead", "warn")
            return False

    # ---- core logic (pure enough to unit-test with a fake clock/fingerprint)
    def read_fp(self):
        return self.fp_fn(self.tunnel.tunnel_ips())

    def _key(self, fp):
        if fp and self.settings.get("ssid_rules"):
            try:
                return (fp, self.name_fn())
            except Exception:
                return (fp, None)
        return fp

    def tick(self, event=False, need_tick=True):
        now = self.clock()
        gap = now - self._last
        self._last = now
        if need_tick and gap > RESUME_GAP:
            self.history.append((now, "resume", f"{int(gap)}s gap"))
            fp = self.read_fp()
            self._stable = self._key(fp)  # new baseline: the next real change is detected, not swallowed
            return self._fire("resume", fp, f"resumed after sleep ({int(gap)} s)")
        if not (event or not self.events_ok):
            return None
        fp = self.read_fp()
        key = self._key(fp)
        if self._stable is None:
            self._stable = key
            return None
        if key == self._stable:
            return None
        self._stable = key
        self.history.append((now, "change", "offline" if not fp else "uplink changed"))
        return self._fire("change", fp, "network changed" if fp else "network lost")

    def _fire(self, kind, fp, reason):
        if kind == "change":
            self._manual_off = False  # a new network gets a fresh decision
        acted = None
        try:
            acted = self.evaluate_rules(reason) if fp else None
        except Exception as e:
            log(f"trusted-network rule error: {e}", "warn")
        if acted is None:
            spawn(self.tunnel.on_network_event, kind, fp, reason)
        for fn in list(self.listeners):      # e.g. the Network Intelligence fix agent (per-network DNS fixes)
            spawn(fn)
        return kind

    def evaluate_rules(self, reason):
        s = self.settings
        if not s.get("ssid_rules"):
            return None
        name = self.name_fn()
        self.current = name
        if name is None:
            return None
        if name == netinfo.UNKNOWN_WIFI and not self._warned_hidden:
            self._warned_hidden = True
            log("Windows is hiding the Wi-Fi name (Settings → Privacy & security → Location → let desktop apps "
                "access your location). Until then every Wi-Fi network is treated as untrusted.", "warn")
        trusted = name != netinfo.UNKNOWN_WIFI and name in (s.get("trusted_networks") or [])
        t = self.tunnel
        if trusted:
            if (t.connected or t.connecting) and s.get("autodisconnect_trusted"):
                log(f'"{name}" is a trusted network — disconnecting ({reason})', "info")
                notify("Trusted network", f'Disconnected on "{name}".', "trusted", "info")
                spawn(t.disconnect, False)
                return "disconnect"
        elif not t.connected and not t.connecting and s.get("autoconnect_untrusted") and not self._manual_off:
            target = s.get("last_region") or (t.region_names()[0] if t.region_names() else None)
            if target and t.has_region(target):
                log(f'"{name}" is not a trusted network — connecting {target} ({reason})', "info")
                notify("Untrusted network", f'Connecting to {target} on "{name}".', "trusted", "info")
                spawn(t.connect, target)
                return "connect"
        return None

    def _loop(self):
        try:
            if self._stable is None:
                self._stable = self._key(self.read_fp())  # baseline now, so the FIRST change is acted on
        except Exception as e:
            log(f"network watcher baseline failed: {e}", "warn")
        while not self._stop.is_set():
            need_tick = bool(self.tunnel.want)
            idle_poll = (not self.events_ok) and bool(self.settings.get("ssid_rules"))
            timeout = TICK if need_tick else (IDLE_POLL if idle_poll else None)
            self._wake.wait(timeout)
            self._wake.clear()
            if self._stop.is_set():
                return
            event, self._ev = self._ev, False
            if not need_tick:  # the wait was untimed/long: it says nothing about sleep, so reset the baseline
                self._last = self.clock()
            if event and self._stop.wait(SETTLE):
                return
            try:
                with self._busy:
                    self.tick(event=event, need_tick=bool(self.tunnel.want))
            except Exception as e:
                log(f"network watcher error: {e}", "warn")
