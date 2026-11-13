import json
import zipfile

from nobadvpn import crash, diagnostics, updater
from nobadvpn.logbus import scrub


def test_scrub_removes_keys(keys):
    priv, _p, _s = keys
    assert priv not in scrub(f"PrivateKey = {priv}")
    assert scrub("presharedkey: abc").endswith("(hidden)")


def test_diagnostics_bundle_has_no_keys(tmp_path, keys, monkeypatch):
    priv, pub, psk = keys
    files = {"configs_redacted/x.txt": f"PrivateKey = {priv}\nPublicKey = {pub}",
             "system/ipconfig.txt": f"Physical Address. . . : AA-BB-CC-DD-EE-FF\nleaked {priv} here",
             "logs/nobad.log": f"something PresharedKey={psk}"}
    monkeypatch.setattr(diagnostics, "_secret_values", lambda: {priv, psk})
    path = diagnostics.build_bundle(str(tmp_path), files=files)
    with zipfile.ZipFile(path) as z:
        blob = "".join(z.read(n).decode() for n in z.namelist())
    assert priv not in blob and psk not in blob
    assert "AA-BB-CC-DD-EE-FF" not in blob and pub in blob


def test_version_compare():
    assert updater.is_newer("2026.11.10-g17", "2026.11.10-g16")
    assert not updater.is_newer("2026.11.10-g16", "2026.11.10-g16")
    assert updater.is_newer("2027.1.1", "2026.12.31-g99") and not updater.is_newer("2026.9.30", "2026.11.1")


def test_manifest_validation():
    import pytest
    ok = {"version": "2026.12.1", "url": "https://x/y.exe", "sha256": "a" * 64}
    assert updater.validate_manifest(ok)["version"] == "2026.12.1"
    for bad in ({**ok, "url": "http://x/y.exe"}, {**ok, "sha256": "zz"}, {**ok, "version": "abc"}, []):
        with pytest.raises(ValueError):
            updater.validate_manifest(bad)


def test_crash_report_is_local_and_scrubbed(monkeypatch, keys):
    import os
    import sys
    priv = keys[0]
    try:
        raise RuntimeError(f"boom PrivateKey = {priv} in {os.path.expanduser('~')}")
    except RuntimeError:
        path = crash.write_report(*sys.exc_info())
    rep = crash.preview(path)
    assert priv not in json.dumps(rep) and os.path.expanduser("~") not in json.dumps(rep)
    from nobadvpn.ctx import ctx
    from nobadvpn.settings import Settings
    ctx.settings = Settings(os.path.join(os.path.dirname(path), "s.json"))
    ok, msg = crash.send(path)                     # opt-in only: no URL => nothing is sent
    assert not ok and "No crash-report server" in msg


def test_raw_key_without_label_is_scrubbed(keys):
    """#18: a bare base64 key inside an exception message never reaches a log or a crash report."""
    import os
    import sys
    from nobadvpn.logbus import scrub
    priv = keys[0]
    assert priv not in scrub(f"bad value {priv!r} for interface") and "(hidden key)" in scrub(f"x {priv} y")
    assert scrub(f"PublicKey = {priv}") == f"PublicKey = {priv}"          # a labelled public key is kept
    assert scrub("A" * 60) == "A" * 60                                    # longer base64 blobs are not keys
    try:
        raise ValueError(f"wg rejected {priv}")
    except ValueError:
        path = crash.write_report(*sys.exc_info(), fatal=False)
    blob = json.dumps(crash.preview(path))
    assert priv not in blob
    os.remove(path)


def test_crash_report_removes_real_config_keys_too(monkeypatch, keys):
    """Second line of defence: the actual key values from the configs are removed, whatever their shape."""
    import sys
    secret = "not-base64-but-secret-" + "x" * 10
    monkeypatch.setattr(crash, "_config_secrets", lambda: {secret})
    try:
        raise RuntimeError(f"oops {secret}")
    except RuntimeError:
        path = crash.write_report(*sys.exc_info(), fatal=False)
    assert secret not in json.dumps(crash.preview(path))


def test_report_problem_link_carries_no_network_details(monkeypatch):
    """The pre-filled GitHub issue holds only the version, Windows build, crash count and the zip's name."""
    from urllib.parse import parse_qs, urlsplit
    from nobadvpn import api
    from nobadvpn.const import APP_VER
    u = urlsplit(api.report_issue_url("NobadDiagnostics-20261113-120000.zip", 2, "Other"))
    assert (u.scheme, u.netloc, u.path) == ("https", "github.com", "/AryanGupta-234/Nobad/issues/new")
    q = {k: v[0] for k, v in parse_qs(u.query).items()}
    assert q["template"] == "bug_report.yml" and q["version"] == APP_VER and "2 crash report" in q["diag"]
    assert set(q) <= {"template", "labels", "title", "version", "windows", "diag", "area"}
    full = u.query.lower()
    for leak in ("192.168", "10.2.", "endpoint", "ssid", "privatekey", "%5cusers%5c", "users\\"):
        assert leak not in full, leak
    assert " " not in api.report_issue_url() and '"' not in api.report_issue_url()   # open_url_as_user refuses those


def test_diagnostics_include_recent_crash_reports(monkeypatch, tmp_path):
    from nobadvpn import diagnostics
    monkeypatch.setattr(diagnostics, "CRASH_DIR", str(tmp_path))
    (tmp_path / "crash-1.json").write_text('{"traceback": "boom"}', encoding="utf-8")
    (tmp_path / "notes.txt").write_text("ignore", encoding="utf-8")
    monkeypatch.setattr(diagnostics, "run", lambda *a, **k: type("R", (), {"stdout": "", "returncode": 0})())
    files = diagnostics.collect()
    assert files.get("crash/crash-1.json") == '{"traceback": "boom"}' and not any(k.endswith("notes.txt") for k in files)


def test_report_problem_is_an_api_action():
    from nobadvpn import api
    assert api.HANDLERS["report_problem"] is api.h_report_problem


def test_diagnostics_hide_home_folder_and_user_name(monkeypatch):
    from nobadvpn import diagnostics
    monkeypatch.setattr(diagnostics.os.path, "expanduser", lambda p: "C:" + chr(92) + "Users" + chr(92) + "Asha")
    monkeypatch.setenv("USERNAME", "Asha")
    line = "diagnostics saved: c:" + chr(92) + "users" + chr(92) + "asha" + chr(92) + "Desktop" + chr(92) + "x.zip by Asha (Ashanti stays)"
    out = diagnostics.scrub_text(line)
    assert "asha" not in out.lower().replace("ashanti", "") and "<home>" in out and "<user>" in out and "Ashanti" in out
