"""Panic reset and start-up takeover for the tunnel controller (#8: split out of engine.py, no behaviour change).

FailsafeMixin is part of engine.Tunnel: "Restore internet" (panic_reset), backing out of a connect that a panic
interrupted, and, at start-up, attaching to a tunnel that is still running or deciding whether rules left by a
crash stay armed. System-wide cleanup that works without a running engine lives in recovery.py."""
import time

from . import firewall, recovery
from .ctx import ctx
from .logbus import log
from .notify import notify
from .syscmd import run, service_running, spawn


class FailsafeMixin:
    def _abort_for_panic(self, wg, name):
        run([wg, "/uninstalltunnelservice", name], timeout=25)
        self._rm_tmp()
        firewall.remove()
        self.ks_active = self.dns_active = False
        self.connected = False
        self.connecting = None
        self.active = None
        self.gen += 1
        log("connect cancelled by panic reset", "warn")
        self.push()
        return False

    def panic_reset(self):
        """Restore the internet no matter what state we're in. Deliberately does not wait for the lock."""
        log("PANIC RESET requested", "warn")
        self._panic_gen += 1
        self.want = False
        self._was_up = False
        self.giveup = False
        self._captive_gen += 1
        self._captive_pending = False
        got = self.lock.acquire(timeout=3)  # a connect in progress sees _panic_gen and backs out
        try:
            summary = recovery.panic_reset_system(self.region_names())
        finally:
            if got:
                self.lock.release()
        from . import netjournal   # explicit reset: also put back adapter DNS the fix agent changed
        summary["dns_restored"] = netjournal.restore_all()
        self.connected = False
        self.connecting = None
        self.active = None
        self.since = None
        self.ks_active = self.dns_active = False
        self.health = None
        self.exit = None
        self._tmp = None
        self.note = ""
        self.last_error = None
        self.gen += 1
        self._up.clear()
        self.push()
        notify("Internet restored", "Firewall rules and tunnel services removed.", "panic", "ok")
        return summary

    def _adopt(self):
        for r in self._regions:
            if service_running(r["name"]):
                self.active, self.connected, self.want, self._was_up = r["name"], True, True, True
                self.since = time.time()
                self._up.set()
                log(f"found {r['name']} already running — attached", "ok")
                self._fw_apply(r)
                if ctx.settings.get("ip_lookup"):
                    from .tools import fetch_ipinfo
                    spawn(fetch_ipinfo)
                return
        self._clean_runtime_dir()  # nothing is running, so any runtime copies are leftovers
        present = firewall.present()
        if not present:
            return
        from . import lifecycle
        s = ctx.settings
        target = s.get("last_region")
        crashed = not lifecycle.previous_exit_clean()
        keep = bool(s.get("kill_switch") and target and self.has_region(target)
                    and (s.get("ks_strict") or (crashed and not s.get("watchdog_failopen"))))
        if keep:
            self.ks_active = any(n in present for n in firewall.KS_RULES)
            self.dns_active = any(n in present for n in firewall.DNS_RULES)
            self.want = self._was_up = True
            self._up.set()
            why = "strict kill switch" if s.get("ks_strict") else "NOBAD did not exit cleanly"
            log(f"kill switch kept armed at start ({why}) — reconnecting {target}", "warn")
            spawn(self.connect, target)
        else:
            firewall.remove(known=set(present))   # stale rules from a cleanly-ended session would block the internet
