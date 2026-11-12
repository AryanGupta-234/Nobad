"""Release-readiness tests: start-up speed paths, single instance, splash, WireGuard bundling, update trust,
settings hardening, crash/diagnostics privacy, packaging files and the English-only lightweight UI."""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import types

import pytest

from nobadvpn import (autostart, boot, crash, diagnostics, firewall, lifecycle, settings as st, splash, updater,
                      wginstall)
from nobadvpn.const import CRASH_DIR, DEFAULTS, INSTANCE_PATH

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI = os.path.join(ROOT, "nobadvpn", "ui")
PKG = os.path.join(ROOT, "packaging")


def ns(stdout="", returncode=0):
    return types.SimpleNamespace(stdout=stdout, stderr="", returncode=returncode)


# ================================================================ firewall: one netsh call, any language
def test_installed_names_from_one_listing(monkeypatch):
    calls = []
    out = ("\nRule Name:   NobadKS4\n----\nEnabled: Yes\n\nRegelname:   NomadDNS4U\n\nRule Name:  Something Else\n"
           "Description: NobadKS6 mentioned in a description is not a rule name: no\n")

    def fake(cmd, timeout=15):
        calls.append(cmd)
        return ns(out)
    monkeypatch.setattr(firewall, "run", fake)
    found = firewall.installed_names()
    assert found == {"NobadKS4", "NomadDNS4U"} and len(calls) == 1
    assert firewall.present() == ["NobadKS4"]
    assert firewall.legacy_present() == ["NomadDNS4U"]


def test_installed_names_failure_falls_back(monkeypatch):
    monkeypatch.setattr(firewall, "run", lambda cmd, timeout=15: ns("", 1))
    assert firewall.installed_names() is None
    assert firewall.present() == []        # per-rule fallback: every `show rule` fails -> nothing present


def test_remove_skips_rules_known_to_be_absent(monkeypatch):
    calls = []
    monkeypatch.setattr(firewall, "run", lambda cmd, timeout=15: calls.append(cmd) or ns())
    firewall.remove(firewall.ALL_RULES, known={"NobadKS4"})
    assert [c[-1] for c in calls] == ["name=NobadKS4"]
    calls.clear()
    firewall.remove(firewall.ALL_RULES)    # unknown state: delete everything (safe default)
    assert len(calls) == len(firewall.ALL_RULES)


# ================================================================ single instance hand-off
@pytest.fixture
def instance_file():
    os.makedirs(os.path.dirname(INSTANCE_PATH), exist_ok=True)
    yield INSTANCE_PATH
    try:
        os.remove(INSTANCE_PATH)
    except OSError:
        pass


def _write(pid, port=5555, token="tok"):
    with open(INSTANCE_PATH, "w") as f:
        json.dump({"pid": pid, "port": port, "token": token}, f)


def test_handoff_no_instance(instance_file):
    if os.path.exists(instance_file):
        os.remove(instance_file)
    assert lifecycle.handoff_to_running() is False


def test_handoff_to_live_responsive_instance(instance_file, monkeypatch):
    _write(424242)
    posted = []
    killed = []
    monkeypatch.setattr(lifecycle, "run", lambda cmd, timeout=15: killed.append(cmd) or ns())
    ok = lifecycle.handoff_to_running(show=True, pid_alive=lambda p: True,
                                      post=lambda port, tok, path, body, t: posted.append((port, tok, path, body))
                                      or {"ok": True})
    assert ok is True and posted == [(5555, "tok", "/api/window", {"do": "show"})] and not killed


def test_handoff_background_launch_only_pings(instance_file):
    _write(424242)
    seen = []
    assert lifecycle.handoff_to_running(show=False, pid_alive=lambda p: True,
                                        post=lambda *a: seen.append(a[3]) or {"ok": True})
    assert seen == [{"do": "noop"}]


def test_handoff_replaces_hung_instance(instance_file, monkeypatch):
    _write(424242)
    killed = []
    monkeypatch.setattr(lifecycle, "run", lambda cmd, timeout=15: killed.append(cmd) or ns())

    def hung(*a):
        raise TimeoutError
    assert lifecycle.handoff_to_running(pid_alive=lambda p: True, post=hung) is False
    assert killed and killed[0][:3] == ["taskkill", "/PID", "424242"]


def test_handoff_ignores_dead_or_self(instance_file, monkeypatch):
    monkeypatch.setattr(lifecycle, "run", lambda *a, **k: pytest.fail("must not kill anything"))
    _write(424242)
    assert lifecycle.handoff_to_running(pid_alive=lambda p: False) is False
    _write(os.getpid())
    assert lifecycle.handoff_to_running(pid_alive=lambda p: True) is False


def test_instance_file_only_removed_by_its_owner(instance_file):
    _write(424242)
    lifecycle.remove_instance()
    assert os.path.exists(instance_file)            # a newer copy owns it
    lifecycle.write_instance(1234, "t")
    assert json.load(open(instance_file))["pid"] == os.getpid()
    lifecycle.remove_instance()
    assert not os.path.exists(instance_file)


def test_run_main_process_stops_after_handoff(monkeypatch):
    from nobadvpn import app
    monkeypatch.setattr(app.lifecycle, "handoff_to_running", lambda show=True: True)
    monkeypatch.setattr(app, "init", lambda *a, **k: pytest.fail("must not initialise a second copy"))
    monkeypatch.setattr(app.autostart, "consume_show_flag", lambda: False)
    app._run_main_process(types.SimpleNamespace(background=False))


# ================================================================ scheduled tasks (fast XML path)
TASK_XML = """<?xml version="1.0" encoding="UTF-16"?>
<Task><Actions Context="Author"><Exec><Command>"C:\\Program Files\\NOBAD VPN\\NobadVPN.exe"</Command>
<Arguments>--background &amp; more</Arguments></Exec></Actions></Task>"""


def test_parse_task_xml():
    assert autostart.parse_task_xml(TASK_XML) == ('"C:\\Program Files\\NOBAD VPN\\NobadVPN.exe"', "--background & more")
    assert autostart.parse_task_xml("<Task/>") is None


def test_action_matching_ignores_quotes_and_case():
    act = ('"C:\\PROGRAM FILES\\NOBAD VPN\\NobadVPN.exe"', '"--background"')
    assert autostart.action_matches(act, r"C:\Program Files\NOBAD VPN\NobadVPN.exe", "--background")
    assert not autostart.action_matches(act, r"D:\Old\NobadVPN.exe", "--background")
    assert not autostart.action_matches(None, "x", "")


def test_launcher_task_preferred_and_stale_tasks_skipped(monkeypatch):
    exe, args = autostart._launch_parts()
    good = f"<Exec><Command>{exe}</Command><Arguments>{args}</Arguments></Exec>"
    bad = "<Exec><Command>C:\\old\\NobadVPN.exe</Command><Arguments>--background</Arguments></Exec>"
    ran = []

    def fake(cmd, timeout=15):
        if "/XML" in cmd:
            return ns(bad if cmd[3] == autostart.LAUNCH_TASK else good)
        if cmd[1] == "/Run":
            ran.append(cmd[3])
        return ns()
    monkeypatch.setattr(autostart, "run", fake)
    monkeypatch.setattr(autostart.os, "name", "nt")
    assert autostart.launch_via_task(show_window=False)
    assert ran == [autostart.TASK_NAME]           # launcher task points elsewhere -> start-with-Windows task


def test_launcher_task_never_offered_for_source_runs():
    assert autostart.installed_location() is False     # not frozen: would run user-writable code elevated
    assert autostart.ensure_launcher_task() is False


def test_register_script_without_trigger_for_launcher():
    s = autostart.build_register_script("C:\\a.exe", "--background", "C:\\", name="X Launcher", at_logon=False)
    assert "-Trigger" not in s and "New-ScheduledTaskTrigger" not in s and "RunLevel Highest" in s
    s2 = autostart.build_register_script("C:\\a.exe", "--background", "C:\\")
    assert "-AtLogOn" in s2 and "-Trigger $t" in s2


# ================================================================ splash
@pytest.mark.parametrize("argv,admin,flag,want", [
    (["x"], True, False, True),
    (["x"], False, False, False),                    # the non-elevated stub only hands over
    (["x", "--background"], True, False, False),     # tray-only start
    (["x", "--background"], True, True, True),       # task start that was asked to show the window
    (["x", "--panic"], True, False, False),
    (["x", "--watchdog", "12"], True, False, False),
    (["x", "--version"], True, False, False),
])
def test_wants_splash(argv, admin, flag, want):
    assert boot.wants_splash(argv, admin, flag) is want


def test_splash_image_and_premultiply():
    from PIL import Image
    img = Image.new("RGBA", (1, 1), (200, 100, 50, 128))
    b, g, r, a = splash.premultiplied_bgra(img)
    assert (b, g, r, a) == (25, 50, 100, 128)        # BGRA, colour scaled by alpha
    full = splash.load_image(1.5)
    assert full.size == (round(splash.BASE_W * 1.5), round(splash.BASE_H * 1.5))


def test_splash_missing_file_is_harmless(tmp_path):
    s = splash.Splash(str(tmp_path / "nope.png"))
    assert s.show() is False and not s.visible
    s.close()


def test_brand_files_present():
    for fn in ("splash.png", "nobad.ico", "nobad-mark.png", "nobad-logo.png", "nobad-logo-light.png"):
        assert os.path.getsize(os.path.join(UI, "brand", fn)) > 1000, fn


# ================================================================ WireGuard
def test_wireguard_signer_check():
    good = lambda p: ("Valid", "CN=WireGuard LLC, O=WireGuard LLC, C=US")  # noqa: E731
    assert wginstall.signed_by_wireguard("x", good)
    assert not wginstall.signed_by_wireguard("x", lambda p: ("NotSigned", ""))
    assert not wginstall.signed_by_wireguard("x", lambda p: ("Valid", "CN=WireGuard LLC Fake, O=Evil"))
    assert not wginstall.signed_by_wireguard("x", lambda p: ("HashMismatch", "CN=WireGuard LLC, O=WireGuard LLC"))


def _wg(monkeypatch, tmp_path, bundled=True):
    if bundled:
        d = tmp_path / "redist"
        d.mkdir()
        (d / wginstall.msi_name()).write_bytes(b"msi")
    monkeypatch.setattr(wginstall, "BASE_DIR", str(tmp_path))
    state = {"installed": False, "ran": [], "downloaded": 0}

    def runner(p):
        state["ran"].append(os.path.basename(p))
        state["installed"] = True
        return True

    def downloader():
        state["downloaded"] += 1
        p = tmp_path / "dl.msi"
        p.write_bytes(b"msi")
        return str(p)
    return state, runner, downloader


def test_wireguard_uses_bundled_msi_first(monkeypatch, tmp_path):
    state, runner, dl = _wg(monkeypatch, tmp_path)
    ok, msg = wginstall.install(sig=lambda p: ("Valid", "CN=WireGuard LLC, O=x"), msi_runner=runner, downloader=dl,
                                winget=lambda: pytest.fail("no winget"), installed=lambda: state["installed"])
    assert ok and state["ran"] == [wginstall.msi_name()] and state["downloaded"] == 0


def test_wireguard_untrusted_bundle_falls_back_to_verified_download(monkeypatch, tmp_path):
    state, runner, dl = _wg(monkeypatch, tmp_path)
    sigs = {wginstall.msi_name(): ("Valid", "CN=Evil, O=Evil"), "dl.msi": ("Valid", "CN=WireGuard LLC, O=x")}
    ok, _ = wginstall.install(sig=lambda p: sigs[os.path.basename(p)], msi_runner=runner, downloader=dl,
                              winget=lambda: None, installed=lambda: state["installed"])
    assert ok and state["ran"] == ["dl.msi"] and not (tmp_path / "dl.msi").exists()   # temp download removed


def test_wireguard_everything_fails_gives_clear_message(monkeypatch, tmp_path):
    state, runner, dl = _wg(monkeypatch, tmp_path, bundled=False)
    ok, msg = wginstall.install(sig=lambda p: ("NotSigned", ""), msi_runner=runner, downloader=dl,
                                winget=lambda: ns("", 1), installed=lambda: False)
    assert not ok and "download page" in msg and not state["ran"]


def test_wireguard_already_installed_is_a_noop():
    ok, msg = wginstall.install(installed=lambda: True, msi_runner=lambda p: pytest.fail("no install"))
    assert ok and "already" in msg


def test_wireguard_version_matches_build_script():
    ps = open(os.path.join(PKG, "build.ps1"), encoding="ascii").read()
    assert "wginstall.py -Pattern 'WG_VERSION" in ps        # build reads the version from the module
    assert re.fullmatch(r"\d+\.\d+\.\d+", wginstall.WG_VERSION)


# ================================================================ update trust
SIGNED = {"status": "Valid", "subject": "CN=NOBAD, O=NOBAD, C=IN", "thumbprint": "AA"}


@pytest.mark.parametrize("info,own,subjects,thumbs,ok", [
    (SIGNED, SIGNED, (), (), True),                                           # same publisher as running app
    (dict(SIGNED, thumbprint="BB"), SIGNED, (), (), True),                    # renewed certificate, same name
    (dict(SIGNED, subject="CN=Evil"), SIGNED, (), (), False),
    (dict(SIGNED, status="NotSigned"), SIGNED, (), (), False),
    (SIGNED, None, (), (), False),                                            # unsigned build: manual updates only
    (SIGNED, None, ("CN=NOBAD, O=NOBAD, C=IN",), (), True),                    # pinned subject
    (dict(SIGNED, subject="CN=Evil"), SIGNED, ("CN=NOBAD, O=NOBAD, C=IN",), (), False),
    (SIGNED, None, (), ("AA",), True),
    (SIGNED, None, (), ("CC",), False),
])
def test_update_signature_policy(info, own, subjects, thumbs, ok):
    assert updater.Updater.signature_acceptable(info, own, pinned=thumbs, subjects=subjects)[0] is ok


def test_manifest_with_bom_is_accepted(monkeypatch):
    body = ("\ufeff" + json.dumps({"version": "1.0.1", "url": "https://x/NobadVPN-Setup-1.0.1.exe",
                                     "sha256": "a" * 64})).encode("utf-8")

    class R(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda req, timeout=10: R(body))
    assert updater.fetch_manifest("https://x/latest.json")["version"] == "1.0.1"


# ================================================================ settings hardening + defaults
def test_lightweight_defaults():
    assert DEFAULTS["visual_effects"] is False and DEFAULTS["startup_checks"] is False
    assert "language" not in DEFAULTS                     # English only


def test_settings_file_values_are_revalidated(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"settings_version": 2, "fallback_dns": "1.1.1.1\nPostUp = calc.exe",
                             "kill_switch": "yes", "theme": "neon", "visual_effects": True,
                             "trusted_networks": ["Home", "Home", "x" * 200]}))
    s = st.Settings(str(p))
    assert s.get("fallback_dns") == DEFAULTS["fallback_dns"]       # injection attempt reset
    assert s.get("kill_switch") is True and s.get("theme") == DEFAULTS["theme"]
    assert s.get("visual_effects") is True and s.get("trusted_networks") == ["Home"]


# ================================================================ crash + diagnostics privacy
def test_thread_errors_are_not_reported_as_crashes():
    shutil.rmtree(CRASH_DIR, ignore_errors=True)
    try:
        raise ValueError("boom")
    except ValueError as e:
        for _ in range(23):
            crash.write_report(type(e), e, e.__traceback__, "thread:x", fatal=False)
        crash.write_report(type(e), e, e.__traceback__, "main", fatal=True)
    assert len(crash.pending()) == 1
    errs = [f for f in os.listdir(CRASH_DIR) if f.startswith("error-")]
    assert 1 <= len(errs) <= 20


def test_diagnostics_scrub_hides_keys_ssids_and_macs(keys):
    priv = keys[0]
    text = ("    SSID                   : Home Fibre 5G\n    Profile                : Home Fibre 5G\n"
            f'trusted network "Home Fibre 5G" -> disconnect\nPrivateKey = {priv}\nMAC 00-11-22-33-44-55\n')
    out = diagnostics.scrub_text(text, secrets={priv}, names={"Home Fibre 5G"})
    assert "Home Fibre 5G" not in out and priv not in out and "00-11-22-33-44-55" not in out


# ================================================================ packaging
def _pkg_files():
    return [os.path.join(PKG, f) for f in os.listdir(PKG) if f.endswith((".ps1", ".iss", ".spec", ".py"))]


def test_packaging_files_are_ascii():
    """Windows PowerShell 5.1 reads BOM-less UTF-8 as ANSI: one em dash broke build.ps1 once."""
    for p in _pkg_files():
        data = open(p, "rb").read()
        bad = [i for i, b in enumerate(data) if b > 127]
        assert not bad, f"{os.path.basename(p)} has non-ASCII bytes at {bad[:3]}"


@pytest.mark.skipif(not shutil.which("powershell"), reason="Windows PowerShell not available")
def test_build_script_parses_in_windows_powershell():
    path = os.path.join(PKG, "build.ps1")
    cmd = ("$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile('" + path +
           "',[ref]$null,[ref]$e); if($e){$e|%{$_.ToString()}; exit 1}")
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd], capture_output=True,
                       text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr


def test_installer_bundles_and_checks_wireguard():
    iss = open(os.path.join(PKG, "installer.iss"), encoding="ascii").read()
    for needle in ("redist\\wireguard-amd64.msi", "redist\\wireguard-arm64.msi", "Check: NeedsWireGuard",
                   "DO_NOT_LAUNCH=1", "IsArm64", "--panic", "NobadVPN Launcher", "SetupIconFile", "Check: WizardSilent"):
        assert needle in iss, needle


def test_manifest_tool_writes_utf8_without_bom(tmp_path):
    exe = tmp_path / "NobadVPN-Setup-1.2.3.exe"
    exe.write_bytes(b"installer")
    out = tmp_path / "latest.json"
    subprocess.run([sys.executable, os.path.join(PKG, "make_manifest.py"), str(exe), "https://h/x.exe", "n",
                    "--out", str(out)], check=True)
    raw = out.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf") and json.loads(raw)["version"] == "1.2.3"
    r = subprocess.run([sys.executable, os.path.join(PKG, "make_manifest.py"), str(exe), "http://h/x.exe"],
                       capture_output=True, text=True)
    assert r.returncode != 0                               # plain http is refused


def test_version_info_generator(tmp_path):
    out = tmp_path / "vi.txt"
    subprocess.run([sys.executable, os.path.join(PKG, "make_version_info.py"), "1.2.3", str(out)], check=True)
    text = out.read_text()
    assert "filevers=(1, 2, 3, 0)" in text and "NOBAD VPN" in text


# ================================================================ UI: English only, lightweight
def test_no_locales_shipped_and_no_translation_layer():
    assert not os.path.exists(os.path.join(UI, "locales"))
    js = open(os.path.join(UI, "app_ext.js"), encoding="utf-8").read()
    assert "MutationObserver" not in js and "/static/locales" not in js and '"language"' not in js


def test_lightweight_css_and_frame_budget():
    css = open(os.path.join(UI, "app_ext.css"), encoding="utf-8").read()
    assert "body:not(.fx) *,body:not(.fx) *::before,body:not(.fx) *::after{backdrop-filter:none!important" in css
    assert "prefers-reduced-motion" in css
    html = open(os.path.join(UI, "index.html"), encoding="utf-8").read()
    # map: no permanent frame loop. A still layer redrawn on change + an effects layer that animates in bursts.
    assert "requestAnimationFrame(frame)" not in html and "function frame(" not in html
    fxf = html[html.index("function fxFrame(t)"):]
    fxf = fxf[:fxf.index("function pulse(")]
    assert "if(t<FX.until)FX.raf=requestAnimationFrame(fxFrame)" in fxf      # loop only while a burst plays
    assert "if(document.hidden)return" in fxf                                # never while hidden / minimised
    assert "const ambientOk=()=>!document.hidden&&document.hasFocus()" in html  # ambient motion only when focused
    assert "function invalidate(){if(DIRTY)return;" in html                  # coalesced still-layer redraws
    assert 'filter="blur(' not in html                                       # no GPU blur filter on the map
    g = html[html.index("function gaugeLoop()"):]
    g = g[:g.index("gaugeWake();$$")]
    assert "if(S.speed!==S.speedTarget)gaugeWake()" in g and "if(k===GAUGE_KEY)return" in g and "setTimeout" not in g
    draw = html[html.index("function drawFx(t)"):]
    draw = draw[:draw.index("</script>")]
    assert "getComputedStyle" not in draw.split("function cssv")[0]   # no style recalculation per frame


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_ui_scripts_are_valid_javascript(tmp_path):
    chk = tmp_path / "chk.js"
    chk.write_text(
        "const fs=require('fs');const [,,idx,ext,mini]=process.argv;"
        "for(const f of [idx,mini]){const h=fs.readFileSync(f,'utf8');"
        "for(const m of h.matchAll(/<script>([\\s\\S]*?)<\\/script>/g))new Function(m[1]);}"
        "new Function(fs.readFileSync(ext,'utf8'));")
    r = subprocess.run(["node", str(chk), os.path.join(UI, "index.html"), os.path.join(UI, "app_ext.js"),
                        os.path.join(UI, "mini.html")], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr


def test_ui_has_no_old_brand_even_split_by_markup():
    """'NO<b>MAD</b>' once survived the rename because the word was split by a tag."""
    for fn in ("index.html", "mini.html", "app_ext.js", "app_ext.css"):
        text = open(os.path.join(UI, fn), encoding="utf-8").read()
        flat = re.sub(r"<[^>]+>", "", text)
        assert "nomad" not in flat.lower(), fn


def test_installer_sets_up_tasks_while_elevated():
    iss = open(os.path.join(PKG, "installer.iss"), encoding="ascii").read()
    assert '--install-tasks --autostart on"' in iss and "Tasks: autostart" in iss and "Tasks: not autostart" in iss
    assert iss.index("NeedsWireGuard") < iss.index("--install-tasks") < iss.index("postinstall")


def test_install_tasks_cli_requires_admin(monkeypatch):
    from nobadvpn import app
    monkeypatch.setattr(app, "is_admin", lambda: False)
    monkeypatch.setattr(app.os, "name", "nt")
    assert app.install_tasks("on") == 2


def test_install_tasks_cli_registers_autostart(monkeypatch):
    from nobadvpn import app
    calls = []
    monkeypatch.setattr(app, "is_admin", lambda: True)
    monkeypatch.setattr(app.autostart, "installed_location", lambda: True)
    monkeypatch.setattr(app.autostart, "ensure_launcher_task", lambda: calls.append("launcher") or True)
    monkeypatch.setattr(app.autostart, "ensure_guard_task", lambda: calls.append("guard") or True)
    monkeypatch.setattr(app.autostart, "enable", lambda: calls.append("enable") or (True, ""))
    assert app.install_tasks("on") == 0 and calls == ["launcher", "guard", "enable"]


def test_map_fades_softly_and_is_precomposited():
    html = open(os.path.join(UI, "index.html"), encoding="utf-8").read()
    assert "function fadeMask(g)" in html and "[g1,g2,g3].forEach(fadeMask)" in html
    m = re.search(r"const MFADE_TOP=([.\d]+),MFADE_BOT=([.\d]+)", html)
    # a thin band only: the map blends into the background without dimming (or appearing to crop) the continents
    assert m and 0.04 <= float(m.group(1)) <= 0.12 and 0 < float(m.group(2)) <= 0.15
    draw = html[html.index("function drawMap()"):]
    draw = draw[:draw.index("const col=")]
    assert "BASEC" in draw and "GLOWC" not in draw and "MAPC" not in draw   # one blit for the static base


def test_helper_processes_run_below_normal_priority():
    from nobadvpn import syscmd
    if os.name == "nt":
        assert syscmd._NOWIN & subprocess.BELOW_NORMAL_PRIORITY_CLASS
        assert syscmd._NOWIN & subprocess.CREATE_NO_WINDOW


def test_background_startup_waits_for_first_paint():
    import inspect
    from nobadvpn import app
    src = inspect.getsource(app._background_start)
    assert src.index("revealed_event.wait") < src.index("_legacy_cleanup()") < src.index("tunnel.start()")


def test_error_notice_is_an_overlay_not_a_layout_item():
    """Regression: the notice host was inserted into the .app grid next to #stage, which shifted the aside into the
    map column until Retry was pressed. It must live inside #stage, be closable and failed attempts must expire."""
    ui = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "nobadvpn", "ui")
    js = open(os.path.join(ui, "app_ext.js"), encoding="utf-8").read()
    css = open(os.path.join(ui, "app_ext.css"), encoding="utf-8").read()
    assert 'stage.parentNode.insertBefore' not in js
    assert '$("#stage").prepend(c)' in js
    assert re.search(r"#nxbars\{[^}]*position:absolute", css)
    assert "close: ACTIONS.dismiss" in js and "ttl: transient ? 15000" in js
    transient = re.search(r'ERR_TRANSIENT = new Set\(\[([^\]]*)\]\)', js).group(1)
    assert '"handshake"' in transient and '"wg_missing"' not in transient   # setup problems stay until fixed
