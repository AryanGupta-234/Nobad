"""Fail-safe: boot guard policy, change journal, network repair levels, CLI wiring. No real system changes:
every Windows command goes through a recording fake."""
import json
import os
import types

import pytest

from nobadvpn import app, autostart, boot, netjournal, netrepair, recovery


class FakeRun:
    def __init__(self, codes=None, outputs=None):
        self.calls, self.codes, self.outputs = [], codes or {}, outputs or {}

    def __call__(self, cmd, timeout=15, input_text=None):
        self.calls.append(cmd)
        key = " ".join(cmd[:2])
        return types.SimpleNamespace(returncode=self.codes.get(key, 0), stdout=self.outputs.get(key, ""), stderr="")


@pytest.fixture
def journal(tmp_path, monkeypatch):
    monkeypatch.setattr(netjournal, "JOURNAL_PATH", str(tmp_path / "netchanges.json"))
    fake = FakeRun()
    monkeypatch.setattr(netjournal, "run", fake)
    return fake


# ------------------------------------------------------------------ boot guard policy
@pytest.mark.parametrize("clean,alive,tunnel,rules,autostart_on,failopen,expect", [
    (True, False, False, True, False, False, "leave"),     # clean exit: nothing to do
    (False, True, False, True, False, False, "leave"),     # NOBAD is running: it decides
    (False, False, True, True, False, False, "leave"),     # tunnel up: you are protected
    (False, False, False, False, False, False, "leave"),   # nothing left behind
    (False, False, False, True, True, False, "leave"),     # kill switch + NOBAD starts at sign-in: stay blocked
    (False, False, False, True, True, True, "restore"),    # ...unless the user chose fail-open
    (False, False, False, True, False, False, "restore"),  # nobody would ever remove the rules
])
def test_guard_policy(clean, alive, tunnel, rules, autostart_on, failopen, expect):
    assert recovery.guard_decide(clean, alive, tunnel, rules, autostart_on, failopen) == expect


def test_guard_task_runs_as_system_at_startup_with_low_priority():
    ps = autostart.build_guard_script(r"C:\Program Files\NOBAD VPN\NobadVPN.exe", '"--guard"', r"C:\Program Files\NOBAD VPN")
    assert "-AtStartup" in ps and "-UserId 'SYSTEM'" in ps and "-LogonType ServiceAccount" in ps
    assert "-Priority 7" in ps and "New-TimeSpan -Minutes 3" in ps and "'\"--guard\"'" in ps
    assert "NobadVPN Guard" in ps


def test_guard_task_only_for_installed_builds(monkeypatch):
    monkeypatch.setattr(autostart, "installed_location", lambda exe=None: False)
    called = []
    monkeypatch.setattr(autostart, "run", lambda *a, **k: called.append(a))
    assert autostart.ensure_guard_task() is False and not called   # a SYSTEM task never points at user-writable code


# ------------------------------------------------------------------ change journal
def test_journal_records_before_change_and_restores_static_dns(journal):
    eid = netjournal.record("dns", "Wi-Fi", {"if_index": 12, "alias": "Wi-Fi", "static_v4": ["192.168.1.1"], "static_v6": []},
                            {"servers": ["1.1.1.1"]}, "fix: ISP DNS filtering", doh_added=["1.1.1.1"])
    assert [e["id"] for e in netjournal.entries()] == [eid]
    out = netjournal.restore_all()
    assert out[0]["ok"] and netjournal.entries() == []
    script = journal.calls[-1][-1]
    assert "Set-DnsClientServerAddress -InterfaceIndex 12 -ServerAddresses @('192.168.1.1')" in script
    assert "Remove-DnsClientDohServerAddress -ServerAddress '1.1.1.1'" in script and "Clear-DnsClientCache" in script


def test_journal_restores_automatic_dns_and_keeps_failures(journal, monkeypatch):
    netjournal.record("dns", "Ethernet", {"if_index": 7, "static_v4": [], "static_v6": []}, {}, "fix")
    monkeypatch.setattr(netjournal, "run", lambda cmd, timeout=15: types.SimpleNamespace(returncode=1, stdout="", stderr="Access is denied."))
    out = netjournal.restore_all()
    assert not out[0]["ok"] and len(netjournal.entries()) == 1          # stays for the next reset to retry
    monkeypatch.setattr(netjournal, "run", journal)
    assert netjournal.restore_all()[0]["ok"] and netjournal.entries() == []
    assert "-InterfaceIndex 7 -ResetServerAddresses" in journal.calls[-1][-1]


def test_journal_treats_vanished_adapter_as_restored(journal, monkeypatch):
    netjournal.record("dns", "USB LAN", {"if_index": 30, "static_v4": [], "static_v6": []}, {}, "fix")
    err = "No MSFT_DNSClientServerAddress objects found with property 'InterfaceIndex' equal to '30'. ObjectNotFound"
    monkeypatch.setattr(netjournal, "run", lambda cmd, timeout=15: types.SimpleNamespace(returncode=1, stdout="", stderr=err))
    assert netjournal.restore_all()[0]["ok"] and netjournal.entries() == []


def test_journal_file_is_written_atomically(journal):
    netjournal.record("dns", "Wi-Fi", {"if_index": 1}, {}, "x")
    assert not os.path.exists(netjournal.JOURNAL_PATH + ".tmp")
    assert json.load(open(netjournal.JOURNAL_PATH))[0]["state"] == "pending"


# ------------------------------------------------------------------ repair levels
@pytest.fixture
def repair_env(journal, monkeypatch):
    fake = FakeRun()
    monkeypatch.setattr(netrepair, "run", fake)
    panic = lambda: {"rules_removed": ["NOBAD-KS"], "rules_left": [], "services_removed": ["japan"]}
    return fake, panic


def test_undo_only_touches_nobad_changes(repair_env):
    fake, panic = repair_env
    res = netrepair.repair("undo", panic=panic)
    assert res["ok"] and not fake.calls and not res["restart_needed"]


def test_quick_repair_runs_real_commands_and_reports_codes(repair_env):
    fake, panic = repair_env
    fake.codes["ipconfig /registerdns"] = 1
    res = netrepair.repair("quick", panic=panic)
    ran = [" ".join(c[:2]) for c in fake.calls]
    assert ran == ["ipconfig /flushdns", "ipconfig /registerdns", "netsh interface", "ipconfig /renew"]
    assert not res["ok"] and [s for s in res["steps"] if not s["ok"]][0]["step"] == "Re-register DNS names"
    assert "netsh winsock" not in " ".join(" ".join(c) for c in fake.calls)   # never a stack reset on 'quick'


def test_full_reset_adds_stack_resets_and_needs_restart(repair_env):
    fake, panic = repair_env
    res = netrepair.repair("full", panic=panic)
    flat = [" ".join(c) for c in fake.calls]
    assert "netsh winsock reset" in flat and "netsh int ipv4 reset" in flat and "netsh int ipv6 reset" in flat
    assert res["ok"] and res["restart_needed"]


def test_renew_without_dhcp_is_not_a_failure(repair_env):
    fake, panic = repair_env
    fake.codes["ipconfig /renew"] = 1
    fake.outputs["ipconfig /renew"] = "The operation failed as no adapter is in the state permissible. DHCP is not enabled on Ethernet."
    assert netrepair.repair("quick", panic=panic)["ok"]


def test_unknown_level_is_rejected():
    with pytest.raises(ValueError):
        netrepair.repair("nuke")


# ------------------------------------------------------------------ wiring
def test_cli_flags_and_no_window():
    a = app.parse_args(["--repair-network", "full", "--show-result"])
    assert a.repair_network == "full" and a.show_result and not a.panic
    assert app.parse_args(["--guard"]).guard
    for flag in ("--panic", "--repair-network", "--guard"):
        assert not boot.wants_splash(["NobadVPN.exe", flag], True, False)


def test_installer_has_offline_restore_shortcut_and_removes_guard():
    iss = open(os.path.join(os.path.dirname(__file__), "..", "packaging", "installer.iss"), encoding="utf-8").read()
    assert 'Parameters: "--panic --show-result"' in iss and "Restore internet (NOBAD)" in iss
    assert '/Delete /TN ""NobadVPN Guard"" /F' in iss
    assert 'Parameters: "--panic"; Flags: runhidden' in iss         # uninstall stays silent (no message box)


def test_api_net_repair_rejects_unknown_level():
    from nobadvpn import api
    assert api.HANDLERS["net_repair"]({"level": "nuke"})["ok"] is False
    assert "net_changes" in api.HANDLERS


def test_every_cli_repair_is_reachable_without_a_terminal():
    """--panic / --repair-network quick|full must also be buttons (Intel tab card + Settings) and a tray item."""
    ui = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "nobadvpn", "ui")
    js = open(os.path.join(ui, "netintel.js"), encoding="utf-8").read()
    for lvl in netrepair.LEVELS:
        assert f'row("{lvl}"' in js
    assert 'NX.netRepair(el.dataset.level)' in js
    tray = open(os.path.join(os.path.dirname(ui), "tray.py"), encoding="utf-8").read()
    assert "Repair network (quick)" in tray and 'run_once("net_repair"' in tray


def test_tray_quick_repair_runs_and_reports(monkeypatch):
    from nobadvpn import tray, syscmd
    seen, notes = [], []
    monkeypatch.setattr(netrepair, "repair", lambda level, panic=None: seen.append(level) or {"ok": True, "steps": [{"step": "dns", "ok": True}]})
    monkeypatch.setattr(syscmd, "run_once", lambda key, fn, *a: (fn(*a), True)[1])
    obj = types.SimpleNamespace(notify=lambda t, m: notes.append(t))
    monkeypatch.setattr(tray.ctx, "tunnel", types.SimpleNamespace(panic_reset=lambda: None), raising=False)
    tray.Tray._quick_repair(obj)
    assert seen == ["quick"] and notes == ["Network repaired"]


def _wg_env(monkeypatch, admin=True, on=True):
    from nobadvpn import api, syscmd
    started = []
    monkeypatch.setattr(syscmd, "is_admin", lambda: admin)
    monkeypatch.setattr(api, "run_once", lambda key, fn, *a: started.append((key, a)) or True)
    monkeypatch.setattr(api.ctx, "settings", types.SimpleNamespace(get=lambda k, d=None: on if k == "auto_install_wg" else d), raising=False)
    monkeypatch.setattr(os, "name", "nt")
    return api, started


def test_auto_install_wireguard_only_when_missing_elevated_and_enabled(monkeypatch):
    api, started = _wg_env(monkeypatch)
    assert api.auto_install_wireguard(installed=lambda: False) is True and started == [("install_wg", (True,))]
    api, started = _wg_env(monkeypatch)
    assert api.auto_install_wireguard(installed=lambda: True) is False and not started
    api, started = _wg_env(monkeypatch, admin=False)
    assert api.auto_install_wireguard(installed=lambda: False) is False and not started
    api, started = _wg_env(monkeypatch, on=False)
    assert api.auto_install_wireguard(installed=lambda: False) is False and not started


def test_auto_install_reports_result_and_clears_wg_error(monkeypatch):
    from nobadvpn import api
    notes, pushed, sent = [], [], []
    tun = types.SimpleNamespace(last_error={"code": "wg_missing"}, push=lambda: pushed.append(1))
    tun.clear_error = lambda: setattr(tun, "last_error", None)
    monkeypatch.setattr(api.ctx, "tunnel", tun, raising=False)
    monkeypatch.setattr(api.ctx, "tray", types.SimpleNamespace(notify=lambda t, m: notes.append(t)), raising=False)
    monkeypatch.setattr(api, "broadcast", lambda k, p: sent.append(p["message"]))
    assert api.install_wireguard_work(True, installer=lambda: (True, "WireGuard is installed.")) == (True, "WireGuard is installed.")
    assert tun.last_error is None and notes == ["WireGuard installed"] and sent[0].startswith("WireGuard is missing")


def test_system_reset_paths_also_restore_journaled_dns(monkeypatch):
    """Boot guard and watchdog fail-open reset as SYSTEM without the engine: they must still undo journaled DNS."""
    from nobadvpn import firewall
    calls = []
    monkeypatch.setattr(recovery, "wg_tool", lambda exe: None)
    monkeypatch.setattr(firewall, "installed_names", lambda: [])
    monkeypatch.setattr(firewall, "remove", lambda names, known=None: None)
    monkeypatch.setattr(recovery, "clean_runtime_dir", lambda: None)
    monkeypatch.setattr(netjournal, "restore_all", lambda: calls.append(1) or [{"id": "x", "ok": True}])
    assert "dns_restored" not in recovery.panic_reset_system()
    assert recovery.panic_reset_system(restore_dns=True)["dns_restored"] == [{"id": "x", "ok": True}] and calls == [1]
    src = open(recovery.__file__, encoding="utf-8").read() + open(os.path.join(os.path.dirname(recovery.__file__), "watchdog.py"), encoding="utf-8").read()
    assert src.count("panic_reset_system(restore_dns=True)") == 2


def test_leftover_runtime_copies_are_wiped_not_just_deleted(monkeypatch, tmp_path):
    """#21: plaintext leftovers are overwritten before removal."""
    from nobadvpn import dpapi
    monkeypatch.setattr(recovery, "RUNTIME_DIR", str(tmp_path))
    (tmp_path / "Home.conf").write_text("[Interface]\nPrivateKey = secret\n")
    (tmp_path / "Work.conf.dpapi").write_bytes(b"blob")
    (tmp_path / "notes.txt").write_text("keep")
    wiped = []
    real = dpapi.wipe_and_remove
    monkeypatch.setattr(dpapi, "wipe_and_remove", lambda p: wiped.append(os.path.basename(p)) or real(p))
    recovery.clean_runtime_dir()
    assert sorted(wiped) == ["Home.conf", "Work.conf.dpapi"]
    assert os.listdir(tmp_path) == ["notes.txt"]
