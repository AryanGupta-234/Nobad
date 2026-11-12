"""Regression tests for the kill-switch / reconnect / trust fixes made for the production release."""
import os
import socket

from nobadvpn import confparse, configstore, engine, firewall, lifecycle, netinfo
from nobadvpn.const import CONFIG_DIR
from nobadvpn.ctx import ctx

_real_resolve = engine.Tunnel.__dict__["_resolve"]


def _fail_verify(monkeypatch):
    monkeypatch.setattr(engine.Tunnel, "_verify", lambda self, n, tgt: False)
    monkeypatch.setattr(netinfo, "captive_check", lambda timeout=4: {"status": "open", "portal": None})


# ---------------------------------------------------------------- endpoint resolution while blocked
def test_runtime_copy_pins_hostname_endpoint_to_resolved_ip(win):
    assert ctx.tunnel.connect("Home")
    conf = win.installed_conf["Home"].decode()
    assert "Endpoint = 203.0.113.9:51820" in conf and "vpn.example.com" not in conf
    with open(os.path.join(CONFIG_DIR, "Home.conf")) as f:
        assert "vpn.example.com" in f.read()          # stored config untouched
    ctx.tunnel.disconnect()


def test_pin_ipv6_endpoint_uses_brackets(sample):
    info = confparse.parse_conf_text(sample)
    out = confparse.tuned_conf_text(sample, info, stream=False, endpoint_ip="2001:db8::5")
    assert "Endpoint = [2001:db8::5]:51820" in out


def test_resolve_falls_back_to_last_known_address(win, monkeypatch):
    t = ctx.tunnel
    t._ep_cache = {"vpn.example.com": (0.0, ["198.51.100.7"])}       # expired entry

    def boom(*a, **k):
        raise OSError("DNS blocked")
    monkeypatch.setattr(socket, "getaddrinfo", boom)
    assert _real_resolve(t, "vpn.example.com") == ["198.51.100.7"]
    assert _real_resolve(t, "unknown.example.com") == []
    assert _real_resolve(t, "192.0.2.1") == ["192.0.2.1"]


def test_unresolvable_endpoint_fails_with_actions(win, monkeypatch):
    monkeypatch.setattr(engine.Tunnel, "_resolve", lambda self, h: [])
    assert not ctx.tunnel.connect("Home")
    assert ctx.tunnel.last_error["code"] == "dns_endpoint" and not win.rules


# ---------------------------------------------------------------- kill switch semantics
def test_kill_switch_keeps_blocking_while_reconnecting_after_a_drop(win, monkeypatch):
    t = ctx.tunnel
    assert t.connect("Home")
    _fail_verify(monkeypatch)
    assert not t.connect("Home")                       # the reconnect attempt fails
    assert "NobadKS4" in win.rules and t.want         # ...but traffic stays blocked


def test_give_up_releases_non_strict_kill_switch(win, monkeypatch):
    t = ctx.tunnel
    assert t.connect("Home")
    _fail_verify(monkeypatch)
    t.connect("Home")
    t._give_up()
    assert not win.rules and t.giveup and t.last_error["code"] == "reconnect_failed"
    t.connect("Home")                                  # later failures after giving up don't re-block
    assert not win.rules


def test_give_up_keeps_strict_kill_switch(win, monkeypatch):
    ctx.settings.update(ks_strict=True)
    t = ctx.tunnel
    assert t.connect("Home")
    _fail_verify(monkeypatch)
    t.connect("Home")
    t._give_up()
    assert "NobadKS4" in win.rules
    t.panic_reset()
    assert not win.rules


def test_strict_mode_never_pauses_for_captive_check(win, monkeypatch):
    ctx.settings.update(ks_strict=True)
    monkeypatch.setattr(engine.Tunnel, "_verify", lambda self, n, tgt: False)
    called = []
    monkeypatch.setattr(netinfo, "captive_check", lambda timeout=4: called.append(1) or {"status": "captive"})
    ctx.tunnel.connect("Home")
    assert not called and "NobadKS4" in win.rules
    ctx.tunnel.panic_reset()


def test_turning_strict_off_while_blocked_releases_rules(win, monkeypatch):
    ctx.settings.update(ks_strict=True)
    _fail_verify(monkeypatch)
    ctx.tunnel.connect("Home")
    assert "NobadKS4" in win.rules
    ctx.settings.update(ks_strict=False)
    ctx.tunnel._reapply_fw("strict kill switch")
    assert not win.rules


def test_start_after_crash_keeps_rules_and_reconnects(win, monkeypatch):
    t = ctx.tunnel
    assert t.connect("Home")
    ctx.settings.update(last_region="Home")
    win.services.clear()                               # app (and tunnel) died; rules are still there
    monkeypatch.setitem(lifecycle._prev, "clean", False)
    spawned = []
    monkeypatch.setattr(engine, "spawn", lambda fn, *a: spawned.append((fn, a)))
    t2 = engine.Tunnel()
    t2._adopt()
    assert "NobadKS4" in win.rules and t2.want and spawned and spawned[0][1] == ("Home",)


def test_start_after_clean_exit_removes_stale_rules(win, monkeypatch):
    t = ctx.tunnel
    assert t.connect("Home")
    win.services.clear()
    monkeypatch.setitem(lifecycle._prev, "clean", True)
    t2 = engine.Tunnel()
    t2._adopt()
    assert not win.rules and not t2.want


def test_firewall_disabled_means_not_armed(win, monkeypatch):
    monkeypatch.setattr(firewall, "firewall_enabled", lambda: False)
    t = ctx.tunnel
    t._fw_state = (0, None)
    assert t.connect("Home")
    assert not t.ks_active and t.fw_off
    t.disconnect()


def test_firewall_state_parser(monkeypatch):
    import types
    out_on = "Domain Profile Settings:\nState                                 ON\nPrivate Profile Settings:\nState   ON\n"
    out_off = out_on.replace("Private Profile Settings:\nState   ON", "Private Profile Settings:\nState   OFF")
    for text, want in ((out_on, True), (out_off, False), ("Ok.\n", None)):
        monkeypatch.setattr(firewall, "run", lambda c, timeout=15, t=text: types.SimpleNamespace(
            stdout=t, stderr="", returncode=0))
        assert firewall.firewall_enabled() is want


# ---------------------------------------------------------------- health target / panic
def test_health_target_for_split_tunnel(win, sample):
    t = ctx.tunnel
    full = t.region("Home")
    assert t.health_target(full) == "1.1.1.1"
    split = sample.replace("AllowedIPs = 0.0.0.0/0, ::/0", "AllowedIPs = 10.2.0.0/24")
    info = confparse.parse_conf_text(split)
    reg = {"addrs": info["addrs"], "info": info}
    assert t.health_target(reg) == "10.2.0.1"         # the config's DNS server is inside the tunnel
    info["dns_servers"] = []
    assert t.health_target(reg) == "10.2.0.1"         # first host of the routed network


def test_panic_aborts_connect_in_flight(win, monkeypatch):
    t = ctx.tunnel

    def verify_then_panic(self, n, tgt):
        self._panic_gen += 1                           # panic pressed while we were verifying
        return True
    monkeypatch.setattr(engine.Tunnel, "_verify", verify_then_panic)
    assert not t.connect("Home")
    assert not t.connected and not win.rules and not win.services


# ---------------------------------------------------------------- config names / trusted Wi-Fi
def test_config_api_rejects_path_traversal(win):
    for bad in ("..\\..\\Windows\\x", "../x", "C:\\x", "a/b", "", ".."):
        assert not configstore.read(bad)["ok"]
        assert not configstore.delete(bad)["ok"]
    assert configstore.read("Home")["ok"]


def test_hidden_wifi_name_is_never_trusted(monkeypatch):
    from test_netwatch_watchdog import make
    nw, t, c = make([frozenset({1})], names=netinfo.UNKNOWN_WIFI, ssid_rules=True,
                    trusted_networks=[netinfo.UNKNOWN_WIFI, "Ethernet"], autodisconnect_trusted=True)
    assert nw.evaluate_rules("test") != "disconnect" and not t.disconnected


def test_same_addressing_different_ssid_is_a_change():
    from test_netwatch_watchdog import make, WIFI
    nw, t, c = make([WIFI, WIFI, WIFI], ssid_rules=True)
    names = iter(["Home", "Home", "Cafe"])
    nw.name_fn = lambda: next(names)
    assert nw.tick() is None
    c.t += 5
    assert nw.tick() is None
    c.t += 5
    assert nw.tick() == "change"
