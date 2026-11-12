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
