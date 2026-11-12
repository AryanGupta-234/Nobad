"""Drives the real Tunnel/engine code against a fake Windows (netsh, sc, wireguard.exe)."""
import os

from nobadvpn import confparse, configstore, engine, netinfo
from nobadvpn.const import CONFIG_DIR, RUNTIME_DIR
from nobadvpn.ctx import ctx


def test_connect_arms_kill_switch_and_dns_block_then_cleans_up(win):
    t = ctx.tunnel
    assert t.connect("Home") and t.connected and t.active == "Home"
    assert {"NobadKS4", "NobadKS6", "NobadDNS4U", "NobadDNS4T", "NobadDNS6U", "NobadDNS6T"} <= win.rules
    assert t.ks_active and t.dns_active
    assert win.installed_conf["Home"].startswith(b"[Interface]")          # tuned runtime copy was used
    assert b"MTU = 1380" in win.installed_conf["Home"]
    assert os.listdir(RUNTIME_DIR)                                         # copy exists while connected
    t.disconnect()
    assert not win.rules and not win.services and not os.listdir(RUNTIME_DIR)


def test_dns_fallback_is_injected_when_config_has_none(win, sample):
    with open(os.path.join(CONFIG_DIR, "Home.conf"), "w", newline="") as f:
        f.write(sample.replace("DNS = 10.2.0.1\n", ""))
    ctx.tunnel.rescan()
    assert ctx.tunnel.connect("Home")
    assert b"DNS = 1.1.1.1, 1.0.0.1" in win.installed_conf["Home"] and ctx.tunnel.dns_active
    assert not confparse.parse_conf(os.path.join(CONFIG_DIR, "Home.conf"))["dns"]   # stored config untouched
    ctx.tunnel.disconnect()


def test_dns_block_skipped_when_it_would_break_lookups(win, sample):
    ctx.settings.update(force_tunnel_dns=False)
    with open(os.path.join(CONFIG_DIR, "Home.conf"), "w", newline="") as f:
        f.write(sample.replace("DNS = 10.2.0.1\n", ""))
    ctx.tunnel.rescan()
    assert ctx.tunnel.connect("Home")
    assert ctx.tunnel.ks_active and not ctx.tunnel.dns_active and "NobadDNS4U" not in win.rules
    ctx.tunnel.disconnect()


def test_dns_block_works_without_kill_switch(win):
    ctx.settings.update(kill_switch=False)
    assert ctx.tunnel.connect("Home")
    assert "NobadKS4" not in win.rules and "NobadDNS4U" in win.rules
    ctx.tunnel.disconnect()


def test_toggle_kill_switch_updates_rules_in_place(win):
    t = ctx.tunnel
    t.connect("Home")
    n_before = len(win.rules)
    t.set_kill_switch(False)
    assert "NobadKS4" not in win.rules and "NobadDNS4U" in win.rules and len(win.rules) < n_before
    t.set_kill_switch(True)
    assert "NobadKS4" in win.rules
    t.disconnect()


def test_handshake_failure_reports_actions_and_fails_open(win, monkeypatch):
    monkeypatch.setattr(engine.Tunnel, "_verify", lambda self, n, tgt: False)
    monkeypatch.setattr(netinfo, "captive_check", lambda timeout=4: {"status": "open", "portal": None})
    t = ctx.tunnel
    assert not t.connect("Home")
    err = t.last_error
    assert err["code"] == "handshake" and {"retry", "check_endpoint"} <= {a["id"] for a in err["actions"]}
    assert not win.rules and not win.services and not t.connected


def test_strict_kill_switch_keeps_blocking_after_failure(win, monkeypatch):
    ctx.settings.update(ks_strict=True)
    monkeypatch.setattr(engine.Tunnel, "_verify", lambda self, n, tgt: False)
    monkeypatch.setattr(netinfo, "captive_check", lambda timeout=4: {"status": "open", "portal": None})
    ctx.tunnel.connect("Home")
    assert "NobadKS4" in win.rules
    assert "panic" in {a["id"] for a in ctx.tunnel.last_error["actions"]}
    ctx.tunnel.panic_reset()
    assert not win.rules


def test_captive_portal_pauses_kill_switch_and_offers_signin(win, monkeypatch):
    monkeypatch.setattr(engine.Tunnel, "_verify", lambda self, n, tgt: False)
    monkeypatch.setattr(netinfo, "captive_check",
                        lambda timeout=4: {"status": "captive", "portal": "http://login.hotel.example/"})
    monkeypatch.setattr(engine.Tunnel, "_start_captive_wait", lambda self, n: None)
    ctx.tunnel.connect("Home")
    err = ctx.tunnel.last_error
    assert err["code"] == "captive" and err["portal"].startswith("http://login")
    assert not win.rules        # paused so the sign-in page can load


def test_missing_wireguard_and_admin_errors(win, monkeypatch):
    monkeypatch.setattr(engine, "wg_tool", lambda exe: None)
    assert not ctx.tunnel.connect("Home")
    assert ctx.tunnel.last_error["code"] == "wg_missing"
    assert "install_wg" in {a["id"] for a in ctx.tunnel.last_error["actions"]}


def test_encrypted_config_prefers_dpapi_runtime_then_falls_back(win, fake_dpapi, sample):
    r = configstore.set_encryption(True)
    assert r["ok"] and os.path.exists(os.path.join(CONFIG_DIR, "Home.conf.dpapi"))
    assert not os.path.exists(os.path.join(CONFIG_DIR, "Home.conf"))     # plaintext removed
    ctx.tunnel.rescan()
    assert ctx.tunnel.region("Home")["enc"]
    assert ctx.tunnel.connect("Home") and b"PrivateKey" not in win.installed_conf["Home"]   # encrypted copy used
    ctx.tunnel.disconnect()
    win.reject_dpapi = True       # WireGuard refuses .dpapi on this machine
    assert ctx.tunnel.connect("Home")
    assert ctx.settings.get("dpapi_runtime_ok") is False and b"PrivateKey" in win.installed_conf["Home"]
    ctx.tunnel.disconnect()
    assert not os.listdir(RUNTIME_DIR)                                    # temp plaintext is wiped


def test_clean_reconnect_never_drops_the_firewall(win, monkeypatch):
    monkeypatch.setattr(engine.Tunnel, "_wait_online", lambda self, t=45: True)
    t = ctx.tunnel
    t.connect("Home")
    win.cmds.clear()
    assert t.reconnect_clean("resumed after sleep") and t.connected
    assert not any(c[:4] == ["netsh", "advfirewall", "firewall", "delete"] for c in win.cmds)
    assert {"NobadKS4", "NobadDNS4U"} <= win.rules
    t.disconnect()


def test_network_event_only_acts_when_a_tunnel_is_wanted(win, monkeypatch):
    called = []
    monkeypatch.setattr(engine.Tunnel, "reconnect_clean", lambda self, r: called.append(r))
    t = ctx.tunnel
    t.on_network_event("change", frozenset({1}), "network changed")
    assert called == []
    t.connect("Home")
    t.on_network_event("change", frozenset({1}), "network changed")
    t.on_network_event("change", frozenset(), "network lost")       # lost network: wait, don't reconnect
    assert called == ["network changed"]
    t.disconnect()


def test_panic_reset_restores_everything(win):
    t = ctx.tunnel
    t.connect("Home")
    summary = t.panic_reset()
    assert not win.rules and not win.services and not t.connected and not t.want
    assert summary["rules_left"] == [] and "Home" in summary["services_removed"]


def test_config_editor_roundtrip_keeps_hidden_keys(win, keys):
    priv = keys[0]
    got = configstore.read("Home")
    assert priv not in got["text"] and "(hidden)" in got["text"]
    edited = got["text"].replace("vpn.example.com", "other.example.com")
    r = configstore.save("Home", edited)
    assert r["ok"], r
    with open(os.path.join(CONFIG_DIR, "Home.conf")) as f:
        disk = f.read()
    assert priv in disk and "other.example.com" in disk
    bad = configstore.save("Home", edited.replace("51820", "0"))
    assert not bad["ok"]


def test_import_validation_and_untrusted_hooks(win, sample):
    assert configstore.import_text("New one.conf", sample)["name"] == "New_one"
    assert not configstore.import_text("New_one", sample)["ok"]                      # duplicate
    hook = sample.replace("DNS = 10.2.0.1", "DNS = 10.2.0.1\nPostUp = calc.exe")
    assert not configstore.import_text("evil", hook, untrusted=True)["ok"]
    assert not configstore.import_url("http://insecure.example/x.conf")["ok"]
    assert not configstore.import_text("junk", "not a config")["ok"]


def test_traffic_and_session_accounting(win, monkeypatch):
    t = ctx.tunnel
    t.connect("Home")
    n0 = len(ctx.usage.summary(0)["sessions"])
    t.disconnect()
    assert len(ctx.usage.summary(0)["sessions"]) == n0 + 1
