"""Kill switch and DNS leak block for the tunnel controller (#8: split out of engine.py, no behaviour change).

ProtectionMixin is part of engine.Tunnel: it applies, re-applies and removes NOBAD's firewall rules according to
the settings and the tunnel state. The rules themselves are built and installed by firewall.py."""
import time

from . import firewall
from .ctx import ctx
from .logbus import log
from .notify import notify


class ProtectionMixin:
    def _fw_remove(self):
        firewall.remove()
        self.ks_active = False
        self.dns_active = False

    def _dns_possible(self, region):
        return bool(region["info"]["dns"] or self._dns_injected or self._runtime_has_dns(region))

    def _fw_apply(self, region):
        """Apply whichever protections the settings ask for. Returns (kill_switch_ok, dns_block_ok)."""
        s = ctx.settings
        ks, dns = bool(s.get("kill_switch")), bool(s.get("dns_leak_block"))
        if dns and not self._dns_possible(region):
            if not self._dns_warned:
                log("this config has no DNS line, so the DNS block was skipped (it would break name lookups). "
                    "Add 'DNS = 1.1.1.1' to the config or enable the fallback-DNS setting.", "warn")
                self._dns_warned = True
            dns = False
        if not ks and not dns:
            self._fw_remove()
            return False, False
        try:
            rules = firewall.build_rules(region["addrs"], self._all_endpoint_ips(), kill_switch=ks, dns_block=dns)
        except ValueError:
            log("kill switch / DNS block need an Address line in the config — not armed", "bad")
            self.ks_active = self.dns_active = False
            return False, False
        res = firewall.apply(rules)
        now = time.time()
        if now - self._fw_state[0] > 60:
            self._fw_state = (now, firewall.firewall_enabled())
        if self._fw_state[1] is False:
            if not self.fw_off:
                log("Windows Firewall is turned OFF for at least one network profile — the kill switch and DNS block "
                    "rules exist but are not enforced. Turn Windows Firewall on (or check your third-party firewall).",
                    "bad")
                notify("Protection not enforced", "Windows Firewall is off, so the kill switch can't block traffic.",
                       "ks", "bad")
            self.fw_off = True
            res = {k: False for k in res}
        else:
            self.fw_off = False
        self.ks_active = bool(ks and res.get(firewall.KS_RULES[0]))
        self.dns_active = bool(dns and res.get(firewall.DNS_RULES[0]) and res.get(firewall.DNS_RULES[1]))
        if ks and not res.get(firewall.KS_RULES[1]):
            log("IPv6 kill-switch rule failed (IPv6 may be off) — IPv4 rule is active", "warn")
        if ks and not self.ks_active:
            log("kill switch could NOT be armed — traffic is not protected", "bad")
            if not self.fw_off:
                notify("Kill switch failed", "Traffic is not protected — see the log.", "ks", "bad")
        if dns and not self.dns_active:
            log("DNS leak block could not be armed", "warn")
        return self.ks_active, self.dns_active

    def set_kill_switch(self, enabled):
        ctx.settings.set("kill_switch", bool(enabled))
        self._reapply_fw("kill switch")
        self.push()

    def set_dns_block(self, enabled):
        ctx.settings.set("dns_leak_block", bool(enabled))
        self._reapply_fw("DNS leak block")
        self.push()

    def _reapply_fw(self, what):
        with self.lock:
            if not self.connected and not self.connecting:
                s = ctx.settings
                holding = bool(s.get("kill_switch") and (s.get("ks_strict") or (self.want and self._was_up)))
                if (self.ks_active or self.dns_active or firewall.present()) and not holding:
                    self._fw_remove()
                    log(f"{what} changed — blocking rules removed", "warn")
                    notify("Kill switch released", "Internet access restored.", "ks", "warn")
                return
            if self.connected and self.active:
                region = self.region(self.active)
                if region:
                    was_ks, was_dns = self.ks_active, self.dns_active
                    self._fw_apply(region)
                    if self.ks_active != was_ks:
                        log("kill switch armed" if self.ks_active else "kill switch disarmed", "ok" if self.ks_active else "warn")
                        notify("Kill switch " + ("armed" if self.ks_active else "disarmed"), self.active or "", "ks",
                               "ok" if self.ks_active else "warn")
                    if self.dns_active != was_dns:
                        log("DNS leak block " + ("on" if self.dns_active else "off"), "ok" if self.dns_active else "warn")
