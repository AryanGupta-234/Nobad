import os
import re
import sys
import tempfile
import types

_tmp = tempfile.mkdtemp(prefix="nobad-test-")
os.environ["NOBAD_DATA_DIR"] = _tmp
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from nobadvpn import engine as _engine  # noqa: E402

# ensure_dirs() / the runtime folder are locked with icacls to SYSTEM + Administrators. In an unelevated test run
# that would lock the test process out of its own temp folder, so tests never touch real ACLs.
_engine._lock_dir = lambda path, allow_user: None
_engine.Tunnel._secure_runtime_dir = lambda self: os.makedirs(_engine.RUNTIME_DIR, exist_ok=True)

PRIV = "yAnz5TF+lXXJte14tji3zlMNq+hd2rYUIgJBgB3fBmk="
PUB = "xTIBA5rboUvnH4htodjb6e697QjLERt1NAB4mZqp8Dg="
PSK = "FpCyhws9cxwWoV4xELtfJvjJN+zQVRPISllRWgeopVE="

SAMPLE = f"""[Interface]
PrivateKey = {PRIV}
Address = 10.2.0.2/32, fd00::2/128
DNS = 10.2.0.1

[Peer]
PublicKey = {PUB}
PresharedKey = {PSK}
AllowedIPs = 0.0.0.0/0, ::/0
Endpoint = vpn.example.com:51820
"""


@pytest.fixture
def sample():
    return SAMPLE


@pytest.fixture
def keys():
    return PRIV, PUB, PSK


@pytest.fixture
def fake_dpapi():
    from nobadvpn import dpapi

    def prot(data, descr):
        return b"ENC1|" + descr.encode() + b"|" + bytes(b ^ 0x5A for b in data)

    def unprot(blob, expected=None):
        tag, descr, body = blob.split(b"|", 2)
        if expected is not None and descr.decode() != expected:
            raise dpapi.DpapiError("different tunnel name")
        return bytes(b ^ 0x5A for b in body)

    dpapi._backend = (prot, unprot)
    yield
    dpapi._backend = None


# ---------------------------------------------------------------- fake Windows shared by engine/reliability tests
class FakeWin:
    def __init__(self):
        self.cmds = []
        self.services = {}
        self.rules = set()
        self.installed_conf = {}
        self.reject_dpapi = False
        self.handshake_ok = True
        self.captive = None

    def run(self, cmd, timeout=15, input_text=None):
        self.cmds.append(list(cmd))
        r = types.SimpleNamespace(stdout="", stderr="", returncode=0)
        c = " ".join(cmd)
        if "/installtunnelservice" in c:
            path = cmd[-1]
            name = re.sub(r"\.conf(\.dpapi)?$", "", os.path.basename(path))
            if path.endswith(".dpapi") and self.reject_dpapi:
                r.returncode = 1
                return r
            self.services[name] = True
            with open(path, "rb") as f:
                self.installed_conf[name] = f.read()
        elif "/uninstalltunnelservice" in c:
            self.services.pop(cmd[-1], None)
        elif cmd[:2] == ["sc", "query"] and "type=" not in cmd:
            n = cmd[2].split("$", 1)[1]
            r.stdout = "STATE : 4 RUNNING" if self.services.get(n) else "STATE : 1 STOPPED"
        elif cmd[0].endswith("wg.exe") and "latest-handshakes" in cmd:
            r.stdout = "PUBKEY\t1700000000\n" if self.handshake_ok else "PUBKEY\t0\n"
        elif cmd[:4] == ["netsh", "advfirewall", "firewall", "add"]:
            self.rules.add(next(x for x in cmd if x.startswith("name=")).split("=", 1)[1])
        elif cmd[:4] == ["netsh", "advfirewall", "firewall", "set"]:
            n = next(x for x in cmd if x.startswith("name=")).split("=", 1)[1]
            r.returncode = 0 if n in self.rules else 1
        elif cmd[:4] == ["netsh", "advfirewall", "firewall", "delete"]:
            self.rules.discard(next(x for x in cmd if x.startswith("name=")).split("=", 1)[1])
        elif cmd[:4] == ["netsh", "advfirewall", "firewall", "show"]:
            n = next(x for x in cmd if x.startswith("name=")).split("=", 1)[1]
            if n == "all":   # one listing of every rule, like the real (English) netsh output
                block = ("\nRule Name:                            {}\n" + "-" * 70 + "\n"
                         "Enabled:                              Yes\nDirection:                            Out\n")
                r.stdout = "".join(block.format(x) for x in sorted(self.rules | {"Some Other App"}))
                r.returncode = 0
            else:
                r.returncode = 0 if n in self.rules else 1
        return r


@pytest.fixture
def win(monkeypatch, sample):
    from nobadvpn import app, engine, firewall, netinfo, syscmd
    from nobadvpn.const import CONFIG_DIR, RUNTIME_DIR
    from nobadvpn.ctx import ctx
    fw = FakeWin()
    for mod in (syscmd, engine, firewall, netinfo, __import__("nobadvpn.recovery", fromlist=["x"])):
        monkeypatch.setattr(mod, "run", fw.run, raising=False)
    monkeypatch.setattr(engine, "wg_tool", lambda exe: exe)
    monkeypatch.setattr(engine, "service_running", lambda n: bool(fw.services.get(n)))
    monkeypatch.setattr("nobadvpn.recovery.wg_tool", lambda exe: exe)
    monkeypatch.setattr(engine, "is_admin", lambda: True)
    monkeypatch.setattr(engine, "ping_stats", lambda *a, **k: {"rtt": 20, "loss": 0, "jitter": 2})
    monkeypatch.setattr(engine, "SERVICE_WAIT", 0.5)
    monkeypatch.setattr(engine, "notify", lambda *a, **k: None)
    monkeypatch.setattr(engine.Tunnel, "geo_refresh", lambda self: None)
    monkeypatch.setattr("nobadvpn.tools.fetch_ipinfo", lambda: None)
    monkeypatch.setattr(engine.Tunnel, "_resolve", lambda self, h: ["203.0.113.9"] if h else [])
    for d in (CONFIG_DIR, RUNTIME_DIR):
        os.makedirs(d, exist_ok=True)
        for f in os.listdir(d):
            os.remove(os.path.join(d, f))
    engine._dirs.update(done=False, config_dir=CONFIG_DIR)
    app.init()
    ctx.settings.update(kill_switch=True, dns_leak_block=True, stream_tuned=True, ks_strict=False,
                        encrypt_configs=False, dpapi_runtime_ok=True, ip_lookup=False)
    with open(os.path.join(CONFIG_DIR, "Home.conf"), "w", newline="") as f:
        f.write(sample)
    ctx.tunnel.rescan()
    return fw
