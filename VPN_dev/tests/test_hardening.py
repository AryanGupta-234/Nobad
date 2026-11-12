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
