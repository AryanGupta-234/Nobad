"""Folder ownership/permission hardening and the updater's refusal paths (no real ACLs, downloads or installs)."""
import hashlib
import io
import os
import threading
import time

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


def _capture_links(monkeypatch):
    """open_url_as_user inline, elevated: returns the PowerShell scripts it would run."""
    scripts = []
    monkeypatch.setattr(syscmd.os, "name", "nt")
    monkeypatch.setattr(syscmd, "OPEN_ASYNC", False)
    monkeypatch.setattr(syscmd, "is_admin", lambda: True)
    monkeypatch.setattr(syscmd.subprocess, "Popen", lambda cmd, **k: pytest.fail("fell back to explorer.exe"))
    monkeypatch.setattr(syscmd, "run", lambda cmd, **k: scripts.append(cmd[-1]) or type("R", (), {"returncode": 0, "stderr": ""})())
    return scripts


def test_links_open_in_the_users_browser_never_as_admin(monkeypatch):
    """explorer.exe <url> opened File Explorer on Windows 11; the link now runs as the signed-in user (limited)."""
    scripts = _capture_links(monkeypatch)
    assert syscmd.open_url_as_user("https://portal.example/login?a=1&b=2") is True
    ps = scripts[-1]
    assert "-RunLevel Limited" in ps and "-LogonType Interactive" in ps and "Unregister-ScheduledTask" in ps
    assert "'url.dll,FileProtocolHandler '+'https://portal.example/login?a=1&b=2'" in ps
    for bad in ("javascript:alert(1)", "file:///C:/Windows/system32/cmd.exe", 'https://x" /c calc', "https://x\n",
                "ms-settings:", "", None):
        assert syscmd.open_url_as_user(bad) is False, bad
    assert len(scripts) == 1


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


@pytest.mark.skipif(os.name != "nt", reason="Windows junctions")
def test_diagnostics_copy_refuses_links_and_never_overwrites(tmp_path):
    """#20: the elevated export never writes through a planted link or over an existing file."""
    from nobadvpn import diagnostics
    src = tmp_path / "nobad-diagnostics.zip"
    src.write_bytes(b"zip")
    desk = tmp_path / "Desktop"
    desk.mkdir()
    (desk / "nobad-diagnostics.zip").write_bytes(b"theirs")
    final = diagnostics.copy_to_user_folder(str(src), str(desk))
    assert os.path.basename(final) == "nobad-diagnostics (1).zip" and open(final, "rb").read() == b"zip"
    assert (desk / "nobad-diagnostics.zip").read_bytes() == b"theirs"
    victim = tmp_path / "victim"
    victim.mkdir()
    link = tmp_path / "LinkedDesktop"
    _junction(link, victim)
    with pytest.raises(OSError):
        diagnostics.copy_to_user_folder(str(src), str(link))
    assert not os.listdir(victim)
    pick = {"Desktop": str(link), "Downloads": str(desk)}
    assert diagnostics.user_destination(pick.get) == str(desk)          # the linked Desktop is skipped
    assert diagnostics.user_destination(lambda n: None) == diagnostics.EXPORT_DIR


@pytest.mark.skipif(os.name != "nt", reason="Windows named events")
def test_show_window_request_needs_no_file():
    """#20: the launcher asks for the window through a session event, not a file the elevated app deletes."""
    from nobadvpn import autostart
    assert not autostart.consume_show_flag()
    h = autostart.request_show()
    try:
        assert autostart.show_requested() and autostart.show_requested()   # peeking doesn't take it
        assert autostart.consume_show_flag() and not autostart.consume_show_flag()
        assert autostart.wait_show_taken(h, 1)
    finally:
        autostart._close(h)
    assert not autostart.show_requested()


def test_one_shared_authenticode_check(monkeypatch):
    """#9: the updater and the WireGuard installer use the same signature helper, and it is never cached."""
    from nobadvpn import wginstall
    calls = []

    def fake(cmd, timeout=15, input_text=None):
        calls.append(cmd)
        return type("R", (), {"stdout": "Valid\nCN=WireGuard LLC, O=WireGuard LLC\nab12\n", "returncode": 0})()
    monkeypatch.setattr(syscmd, "run", fake)
    monkeypatch.setattr(syscmd.os, "name", "nt")
    assert updater.Updater.signature_info("C:/x.exe") == {"status": "Valid", "subject": "CN=WireGuard LLC, O=WireGuard LLC",
                                                          "thumbprint": "AB12"}
    assert wginstall.signature("C:/x.msi") == ("Valid", "CN=WireGuard LLC, O=WireGuard LLC")
    assert wginstall.signature("C:/x.msi")[0] == "Valid" and len(calls) == 3
    syscmd.authenticode("C:/it's.msi")
    assert "-LiteralPath 'C:/it''s.msi'" in calls[-1][-1]          # a quote in the path can't break out


def test_links_are_encoded_and_quotes_cant_break_the_script(monkeypatch):
    scripts = _capture_links(monkeypatch)
    assert syscmd.open_url_as_user("https://en.wikipedia.org/wiki/List_of_banned_films#India,_2000s;x") is True
    assert "https://en.wikipedia.org/wiki/List_of_banned_films#India%2C_2000s%3Bx'" in scripts[-1]
    assert syscmd.open_url_as_user("https://x.org/a b/\u00e9") is True and "https://x.org/a%20b/%C3%A9'" in scripts[-1]
    assert syscmd.open_url_as_user("https://x.org/it's") is True and "https://x.org/it''s'" in scripts[-1]
    for bad in ("https://user:pw@x.org/", "https://x.org/|calc", "https://x.org/\\..\\x"):
        assert syscmd.open_url_as_user(bad) is False, bad


def test_crashed_task_tells_the_ui(monkeypatch):
    seen = []
    monkeypatch.setattr(syscmd, "broadcast", lambda t, p: seen.append((t, p)))
    monkeypatch.setattr(syscmd, "log", lambda *a, **k: None)
    done = threading.Event()
    def boom():
        try:
            raise RuntimeError("kaput")
        finally:
            done.set()
    assert syscmd.run_once("t_boom", boom)
    done.wait(2)
    for _ in range(100):
        if seen:
            break
        time.sleep(0.01)
    assert seen and seen[0][0] == "task_done" and seen[0][1]["key"] == "t_boom" and "kaput" in seen[0][1]["error"]


def test_toast_text_cannot_break_out_with_curly_quotes():
    from nobadvpn import notify
    ps = notify._toast_ps("Untrusted network", "on \u201cx\u2019;Start-Process calc;\u2019\u201d")
    assert "\u2019" not in ps and "x'';Start-Process calc;''" in ps


def test_dpapi_never_writes_or_wipes_through_a_link(monkeypatch, tmp_path):
    from nobadvpn import dpapi
    target = tmp_path / "a.conf"
    target.write_bytes(b"secret")
    monkeypatch.setattr(syscmd, "_is_reparse", lambda p: str(p).endswith("a.conf"))
    with pytest.raises(OSError):
        dpapi.write_atomic(str(target), b"x")
    dpapi.wipe_and_remove(str(target))
    assert target.read_bytes() == b"secret"


def test_planted_data_dir_is_moved_aside_not_adopted(monkeypatch, tmp_path):
    d = tmp_path / "NobadVPN"
    d.mkdir()
    (d / "netchanges.json").write_text("{}")
    monkeypatch.setattr(app, "DATA_DIR", str(d))
    monkeypatch.setattr(app, "SETTINGS_PATH", str(d / "settings.json"))
    monkeypatch.setattr(app.os, "name", "nt")
    monkeypatch.setattr(syscmd, "owned_by_admins", lambda p: False)
    moved = app.quarantine_untrusted_data_dir()
    assert moved and not d.exists() and os.path.exists(os.path.join(moved, "netchanges.json"))
    d.mkdir()
    monkeypatch.setattr(syscmd, "owned_by_admins", lambda p: True)
    assert app.quarantine_untrusted_data_dir() is None and d.exists()


def test_environment_cannot_steer_webview_or_powershell(monkeypatch):
    monkeypatch.setattr(syscmd.os, "name", "nt")
    monkeypatch.setenv("WEBVIEW2_BROWSER_EXECUTABLE_FOLDER", "C:/Users/u/evil")
    monkeypatch.setenv("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "--remote-debugging-port=9222")
    monkeypatch.setenv("PSModulePath", "C:/Users/u/mods")
    syscmd.harden_environment()
    assert not [k for k in os.environ if k.upper().startswith("WEBVIEW2_")]
    assert os.environ["PSModulePath"].lower().replace("\\", "/").endswith("system32/windowspowershell/v1.0/modules")


def test_import_folder_is_read_only_for_nobad(monkeypatch):
    """The configs folder is admin-only; .conf files dropped in the user-writable import folder are imported with
    the normal checks on Rescan, links are skipped, and nothing in the import folder is ever changed."""
    from conftest import SAMPLE
    from nobadvpn import configstore, const, engine
    engine.ensure_dirs()
    os.makedirs(const.INBOX_DIR, exist_ok=True)
    good = os.path.join(const.INBOX_DIR, "Dropped1.conf")
    link = os.path.join(const.INBOX_DIR, "Linked1.conf")
    for p in (good, link):
        with open(p, "w", encoding="utf-8") as f:
            f.write(SAMPLE)
    monkeypatch.setattr(syscmd, "_is_reparse", lambda p: str(p).endswith("Linked1.conf"))
    r = configstore.import_inbox()
    assert r["imported"] == ["Dropped1.conf"] and os.path.exists(good) and os.path.exists(link)
    assert configstore.import_inbox()["skipped"] == ["Dropped1.conf"]     # already imported: left alone
    assert not any(n.startswith("Linked1") for n in os.listdir(engine.config_dir()))


PROTON = """[Interface]
PrivateKey = {priv}
Address = 10.2.0.2/32
DNS = 10.2.0.1

[Peer]
# JP-FREE#27
PublicKey = {pub}
AllowedIPs = 0.0.0.0/0, ::/0
Endpoint = 212.102.51.115:51820
"""


def test_free_servers_found_in_downloads_and_imported_read_only(win, monkeypatch, tmp_path):
    """Free servers: WireGuard files the user downloaded are offered and imported with the normal checks; the
    Downloads folder is only read, links and old or oversized files are ignored."""
    from conftest import PRIV, PUB
    from nobadvpn import configstore, engine
    engine.ensure_dirs()
    dl = tmp_path / "Downloads"
    dl.mkdir()
    (dl / "wg-JP-FREE-27.conf").write_text(PROTON.format(priv=PRIV, pub=PUB), encoding="utf-8")
    (dl / "notes.conf").write_text("not a wireguard file", encoding="utf-8")
    (dl / "big.conf").write_text("[Interface]\n[Peer]\n" + "#" * 70000, encoding="utf-8")
    (dl / "linked.conf").write_text(PROTON.format(priv=PRIV, pub=PUB).replace("212.102.51.115", "1.2.3.4"), encoding="utf-8")
    old = dl / "old.conf"
    old.write_text(PROTON.format(priv=PRIV, pub=PUB).replace("212.102.51.115", "5.6.7.8"), encoding="utf-8")
    os.utime(old, (1, 1))
    monkeypatch.setattr(configstore, "_downloads_dir", lambda: str(dl))
    monkeypatch.setattr(syscmd, "_is_reparse", lambda p: str(p).endswith("linked.conf"))
    found = configstore.downloads_scan()["files"]
    assert [(f["file"], f["name"], f["country"]) for f in found] == [("wg-JP-FREE-27.conf", "JP-FREE-27", "Japan")]
    r = configstore.downloads_import(["wg-JP-FREE-27.conf", "../secret.conf", "linked.conf"])
    assert r["imported"] == ["JP-FREE-27"] and len(r["errors"]) == 2
    assert sorted(os.listdir(dl)) == ["big.conf", "linked.conf", "notes.conf", "old.conf", "wg-JP-FREE-27.conf"]


def test_import_folder_is_outside_the_recursively_locked_data_folder():
    from nobadvpn import const
    data = os.path.normcase(os.path.abspath(const.DATA_DIR))
    inbox = os.path.normcase(os.path.abspath(const.INBOX_DIR))
    assert not inbox.startswith(data + os.sep) and inbox != data


def test_planted_settings_file_no_longer_skips_the_quarantine(monkeypatch, tmp_path):
    d = tmp_path / "NobadVPN"
    (d / "configs").mkdir(parents=True)
    (d / "settings.json").write_text('{"auto_connect": true}')
    (d / "configs" / "evil.conf").write_text("[Interface]")
    monkeypatch.setattr(app, "DATA_DIR", str(d))
    monkeypatch.setattr(app.os, "name", "nt")
    monkeypatch.setattr(syscmd, "_is_reparse", lambda p: False)
    monkeypatch.setattr(syscmd, "owned_by_admins", lambda p: not str(p).endswith("evil.conf"))   # one planted file
    assert app.quarantine_untrusted_data_dir() and not d.exists()


def test_environment_cannot_load_a_dotnet_profiler_into_admin_powershell(monkeypatch):
    monkeypatch.setattr(syscmd.os, "name", "nt")
    for k in ("COR_ENABLE_PROFILING", "COR_PROFILER_PATH", "COMPLUS_X", "CORECLR_PROFILER", "DOTNET_X",
              "PSExecutionPolicyPreference"):
        monkeypatch.setenv(k, "1")
    syscmd.harden_environment()
    assert not [k for k in os.environ if k.upper().startswith(("COR_", "COMPLUS_", "CORECLR_", "DOTNET_"))]
    assert "PSExecutionPolicyPreference" not in os.environ


def test_links_open_only_in_this_session_and_cant_expand_variables(monkeypatch):
    scripts = _capture_links(monkeypatch)
    assert syscmd.open_url_as_user("https://x.org/a?q=%USERNAME%&ok=%41") is True
    ps = scripts[-1]
    assert "SessionId=$sid" in ps and "ExecutablePath -ieq $exp" in ps
    assert "q=%25USERNAME%25&ok=%41'" in ps
