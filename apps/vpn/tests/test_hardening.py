"""Folder ownership/permission hardening and the updater's refusal paths (no real ACLs, downloads or installs)."""
import hashlib
import io
import os

import pytest

from nobadvpn import app, syscmd, updater
from nobadvpn.const import UPDATE_DIR


class _R:
    def __init__(self, code=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = code, out, err


@pytest.fixture
def real_lock(monkeypatch):
    """The real lock_dir (conftest replaces it with a no-op), with icacls calls recorded instead of run."""
    import conftest
    calls, codes = [], {}
    monkeypatch.setattr(syscmd, "lock_dir", conftest._real_lock_dir)
    monkeypatch.setattr(syscmd.os, "name", "nt")

    def fake_run(cmd, timeout=15, input_text=None):
        calls.append(cmd)
        return _R(codes.get(cmd[2] if len(cmd) > 2 else "", 0))
    monkeypatch.setattr(syscmd, "run", fake_run)
    return calls, codes


def test_lock_dir_takes_ownership_and_resets_children(tmp_path, real_lock):
    calls, _ = real_lock
    (tmp_path / "planted.exe").write_bytes(b"x")
    assert syscmd.lock_dir(str(tmp_path), allow_user=False) is True
    owner, acl, reset = calls
    assert owner[:4] == ["icacls", str(tmp_path), "/setowner", syscmd.ADMINS_SID] and "/T" in owner
    assert "/inheritance:r" in acl and not any("(OI)(CI)M" in a for a in acl)   # no user access unless asked
    assert reset[1] == os.path.join(str(tmp_path), "*") and "/reset" in reset


def test_lock_dir_reports_failure(tmp_path, real_lock):
    _calls, codes = real_lock
    codes["/setowner"] = 5                        # e.g. not elevated
    assert syscmd.lock_dir(str(tmp_path)) is False


def test_private_workdir_is_fresh_each_time_and_refuses_unlockable(tmp_path, monkeypatch):
    a = syscmd.private_workdir(str(tmp_path), "update-")
    b = syscmd.private_workdir(str(tmp_path), "update-")
    assert a != b and os.path.isdir(a) and os.path.dirname(a) == str(tmp_path)
    monkeypatch.setattr(syscmd, "lock_dir", lambda path, allow_user=False: False)
    with pytest.raises(PermissionError):
        syscmd.private_workdir(str(tmp_path), "update-")
    assert len(os.listdir(tmp_path)) == 2         # the folder that couldn't be locked was removed


class _Resp(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def _updater_with(monkeypatch, payload, sha):
    app.init()
    u = updater.Updater()
    u._manifest = {"version": "99.0.0", "url": "https://example.invalid/setup.exe", "sha256": sha}
    monkeypatch.setattr(updater.reach, "urlopen", lambda req, timeout=30: _Resp(payload))
    ran = []
    monkeypatch.setattr(updater.subprocess, "Popen", lambda *a, **k: ran.append(a))
    return u, ran


def test_update_with_wrong_hash_is_deleted_and_not_run(monkeypatch):
    u, ran = _updater_with(monkeypatch, b"evil installer", "0" * 64)
    u.download_and_install()
    assert not ran and "SHA-256" in u.snapshot()["error"]
    assert not [d for d in os.listdir(UPDATE_DIR) if d.startswith("update-")]


def test_unsigned_update_is_refused_even_with_matching_hash(monkeypatch):
    data = b"unsigned but correct hash"
    u, ran = _updater_with(monkeypatch, data, hashlib.sha256(data).hexdigest())
    monkeypatch.setattr(updater.Updater, "signature_info", staticmethod(lambda p: {"status": "NotSigned",
                                                                                 "subject": "", "thumbprint": ""}))
    u.download_and_install()
    assert not ran and "not installed" in u.snapshot()["error"].lower()


# ================================================================ firewall: replacing a rule never leaves a gap
class _Netsh:
    """A tiny in-memory Windows Firewall: tracks which rule names exist and checks there is always a block rule."""
    def __init__(self, existing, fail_set=True, fail_add=()):
        self.rules = set(existing)
        self.fail_set, self.fail_add = fail_set, set(fail_add)
        self.gap = False

    def __call__(self, cmd, timeout=15, input_text=None):
        verb = cmd[3] if len(cmd) > 3 else ""
        name = next((c[5:] for c in cmd if c.startswith("name=")), "")
        if verb == "show":
            return _R(0, "".join(f"Rule Name: {n}\n" for n in sorted(self.rules)))
        if verb == "set":
            return _R(1 if self.fail_set else 0)
        if verb == "add":
            if name in self.fail_add:
                return _R(1)
            self.rules.add(name)
            return _R(0)
        if verb == "delete":
            self.rules.discard(name)
            if not any(n.startswith("NobadKS4") for n in self.rules):
                self.gap = True
            return _R(0)
        return _R(0)


def _ks_rule():
    from nobadvpn import firewall
    return [r for r in firewall.build_rules(["10.2.0.2/32"], ["1.2.3.4"], dns_block=False) if r["name"] == "NobadKS4"]


def test_recreated_rule_is_bridged_and_bridge_removed(monkeypatch):
    from nobadvpn import firewall
    fw = _Netsh({"NobadKS4"})
    monkeypatch.setattr(firewall, "run", fw)
    assert firewall.apply(_ks_rule()) == {"NobadKS4": True}
    assert fw.rules == {"NobadKS4"} and not fw.gap


def test_bridge_keeps_blocking_when_re_adding_fails(monkeypatch):
    from nobadvpn import firewall
    monkeypatch.setattr(firewall.time, "sleep", lambda s: None)
    fw = _Netsh({"NobadKS4"}, fail_add={"NobadKS4"})
    monkeypatch.setattr(firewall, "run", fw)
    assert firewall.apply(_ks_rule()) == {"NobadKS4": True}
    assert fw.rules == {"NobadKS4b"} and not fw.gap
    assert "NobadKS4b" in firewall.ALL_RULES          # so stop/panic/recovery clean it up


def test_add_is_retried(monkeypatch):
    from nobadvpn import firewall
    monkeypatch.setattr(firewall.time, "sleep", lambda s: None)
    tries = []

    def flaky(cmd, timeout=15, input_text=None):
        if cmd[3] == "add":
            tries.append(1)
            return _R(0 if len(tries) == 3 else 1)
        return _R(0, "")
    monkeypatch.setattr(firewall, "run", flaky)
    assert firewall.apply(_ks_rule()) == {"NobadKS4": True} and len(tries) == 3


# ================================================================ junctions can't redirect the folder locking
def _junction(link, target):
    import subprocess
    r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip("can't create a junction here: " + (r.stderr or r.stdout))


@pytest.mark.skipif(os.name != "nt", reason="Windows junctions")
def test_lock_dir_refuses_a_junction_and_removes_planted_ones(tmp_path, real_lock):
    calls, _ = real_lock
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "keep.txt").write_text("important")
    data = tmp_path / "data"
    data.mkdir()
    _junction(data / "evil", victim)                     # planted inside the folder before NOBAD locks it
    assert syscmd.lock_dir(str(data)) is True
    assert not (data / "evil").exists() and (victim / "keep.txt").read_text() == "important"   # link gone, target kept
    calls.clear()
    linked = tmp_path / "linked"
    _junction(linked, victim)                            # the folder itself is a junction to somewhere else
    assert syscmd.lock_dir(str(linked)) is False and calls == []      # no icacls ran at all


def test_installed_app_ignores_env_data_dir(monkeypatch):
    import importlib
    from nobadvpn import const
    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setenv("NOBAD_DATA_DIR", r"C:\Windows")
    monkeypatch.setenv("ProgramData", r"C:\Users\Public\evil")
    try:
        importlib.reload(const)
        assert const.DATA_DIR.lower() != r"c:\windows"
        assert "evil" not in const.DATA_DIR.lower() and const.DATA_DIR.lower().endswith("nobadvpn")
    finally:
        monkeypatch.undo()
        importlib.reload(const)


def test_start_with_windows_refused_outside_program_files(monkeypatch):
    from nobadvpn import autostart
    monkeypatch.setattr(autostart.os, "name", "nt")
    monkeypatch.setattr(autostart, "installed_location", lambda exe=None: False)
    monkeypatch.setattr(autostart, "_register", lambda *a: pytest.fail("must not register an elevated task"))
    ok, msg = autostart.enable()
    assert ok is False and "Program Files" in msg


def test_links_open_through_explorer_never_as_admin(monkeypatch):
    started = []
    monkeypatch.setattr(syscmd.os, "name", "nt")
    monkeypatch.setattr(syscmd.subprocess, "Popen", lambda cmd, **k: started.append(cmd))
    assert syscmd.open_url_as_user("https://portal.example/login?a=1&b=2") is True
    assert started[-1][0].lower().endswith("explorer.exe") and started[-1][1] == "https://portal.example/login?a=1&b=2"
    for bad in ("javascript:alert(1)", "file:///C:/Windows/system32/cmd.exe", 'https://x" /c calc', "https://x\n",
                "ms-settings:", "", None):
        assert syscmd.open_url_as_user(bad) is False, bad
    assert len(started) == 1


def test_tampered_journal_never_reaches_powershell(monkeypatch):
    from nobadvpn import netjournal
    ran = []
    monkeypatch.setattr(netjournal, "_ps", lambda script: ran.append(script) or _R(0))
    evil = {"kind": "dns", "before": {"if_index": 7, "static_v4": ["1.1.1.1"]}, "doh_added": ["1.1.1.1'; calc; '"]}
    assert netjournal.restore_entry(evil) == (False, "journal entry has an invalid DNS address — not restored")
    assert netjournal.restore_entry({"kind": "dns", "before": {"if_index": "7; calc"}})[0] is False
    assert not ran
    ok, _ = netjournal.restore_entry({"kind": "dns", "before": {"if_index": 7, "static_v4": ["9.9.9.9"]},
                                      "doh_added": ["9.9.9.9"]})
    assert ok and "'9.9.9.9'" in ran[0] and "-InterfaceIndex 7" in ran[0]


def test_oversized_update_is_stopped_and_removed(monkeypatch):
    u, ran = _updater_with(monkeypatch, b"x" * 2048, "0" * 64)
    monkeypatch.setattr(updater, "MAX_INSTALLER", 1024)
    u.download_and_install()
    assert not ran and "larger than any NOBAD installer" in u.snapshot()["error"]
    assert not [d for d in os.listdir(UPDATE_DIR) if d.startswith("update-")]


def test_https_links_never_redirect_to_http():
    import urllib.error
    import urllib.request
    from nobadvpn import reach
    h = reach.NoDowngradeRedirect()
    req = urllib.request.Request("https://example.com/a.conf")
    for target in ("http://evil.example/a.conf", "ftp://evil.example/a", "file:///C:/x"):
        with pytest.raises(urllib.error.HTTPError):
            h.redirect_request(req, None, 302, "Found", {}, target)
    assert h.redirect_request(req, None, 302, "Found", {}, "https://cdn.example.com/a.conf").full_url == "https://cdn.example.com/a.conf"


def test_import_url_refuses_local_and_private_addresses(monkeypatch):
    from nobadvpn import configstore, reach
    monkeypatch.setattr(configstore.urllib.request, "urlopen", lambda *a, **k: pytest.fail("must not fetch"))
    for ip in ("127.0.0.1", "192.168.1.1", "169.254.169.254", "10.0.0.5", "::1"):
        monkeypatch.setattr(reach, "system_resolve", lambda host, ip=ip: [ip])
        r = configstore.import_url("https://looks-public.example/a.conf")
        assert r["ok"] is False and "local network" in r["error"], ip


def test_image_proxy_requires_a_signed_in_window():
    import http.client
    import threading
    from nobadvpn import server
    app.init()
    s = server.make_server()
    threading.Thread(target=s.serve_forever, daemon=True).start()
    try:
        port = s.server_address[1]
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request("GET", "/si/img/w92/abcdef.png", headers={"Host": f"127.0.0.1:{port}"})
        assert c.getresponse().status == 401
    finally:
        s.shutdown()


def test_system_tools_run_by_full_path(monkeypatch):
    """#19: bare tool names resolve under System32; the installed app never searches PATH."""
    if os.name != "nt":
        pytest.skip("Windows only")
    seen = []
    monkeypatch.setattr(syscmd.subprocess, "run", lambda cmd, **k: seen.append(cmd) or type("R", (), {"returncode": 0})())
    syscmd.run(["netsh", "advfirewall", "show"])
    syscmd.run(["schtasks.exe", "/Query"])
    sys32 = syscmd.system32().lower()
    assert [c[0].lower() for c in seen] == [os.path.join(sys32, "netsh.exe"), os.path.join(sys32, "schtasks.exe")]
    assert seen[0][1:] == ["advfirewall", "show"]
    monkeypatch.setattr(syscmd, "FROZEN", True)
    seen.clear()
    for bad in (["winget", "install"], [r"..\netsh"], [r"sub\ping.exe"]):
        r = syscmd.run(bad)
        assert r.returncode == 1 and "refusing" in r.stderr
    assert not seen
    abs_tool = [os.path.join(sys32, "ping.exe"), "-n", "1"]
    syscmd.run(abs_tool)
    assert seen == [abs_tool]                                          # full paths are used as given


def test_wg_tool_ignores_path_when_installed(monkeypatch):
    monkeypatch.setattr(syscmd, "wg_dirs", lambda: [])
    monkeypatch.setattr(syscmd.shutil, "which", lambda exe: r"C:\Users\x\evil" + "\\" + exe)
    monkeypatch.setattr(syscmd, "FROZEN", True)
    assert syscmd.wg_tool("wireguard.exe") is None
    monkeypatch.setattr(syscmd, "FROZEN", False)
    assert syscmd.wg_tool("wireguard.exe").endswith("wireguard.exe")    # a source checkout may use PATH


def test_installed_app_never_runs_winget(monkeypatch):
    from nobadvpn import wginstall
    calls = []
    monkeypatch.setattr(wginstall, "FROZEN", True)
    monkeypatch.setattr(wginstall, "run", lambda cmd, **k: calls.append(cmd))
    monkeypatch.setattr(wginstall, "bundled_msi", lambda: None, raising=False)
    ok, msg = wginstall.install(sig=lambda p: False, downloader=lambda: (_ for _ in ()).throw(OSError("offline")),
                                installed=lambda: False)
    assert not ok and not any("winget" in str(c) for c in calls) and "winget skipped" in msg
