"""The UI <-> engine contract (apps/vpn/contract): the method schema is the one params.SPEC generates, the event
schema lists real events, and the recorded transcripts replay against the REAL api handlers (with a fake tunnel:
nothing on the PC changes). The Flutter tests replay the same transcripts (ui_flutter/test/contract/).

Re-record after a deliberate contract change (keeps the send/engine lines, rewrites the replies):
    python tests/test_rpc_contract.py --record
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nobadvpn.rpc import events as rpc_events, methods, params, protocol  # noqa: E402

CONTRACT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "contract")
TRANSCRIPTS = os.path.join(CONTRACT, "transcripts")

STATE = {
    "connected": False, "connecting": None, "note": None, "active": None, "since": None, "ks_active": False,
    "dns_active": False, "fw_off": False, "giveup": False,
    "settings": {"kill_switch": True, "dns_leak_block": True, "theme": "dark", "wizard_done": True,
                 "last_region": "JP-FREE-3", "favorites": ["NL-FREE-1"]},
    "regions": [
        {"name": "JP-FREE-3", "host": "jp-free-3.example.net", "port": 51820,
         "ping": {"rtt": 61.0, "loss": 0, "jitter": 2.1}, "geo": {"country": "JP", "city": "Tokyo"}, "full": True,
         "v6": False, "dns": True, "enc": False},
        {"name": "NL-FREE-1", "host": "nl-free-1.example.net", "port": 51820, "ping": None,
         "geo": {"country": "NL"}, "full": True, "v6": True, "dns": True, "enc": True}],
    "admin": True, "wireguard": True, "wg_installing": False, "wg_cli": True, "exit": None, "health": None,
    "home": None, "sessions": [], "error": None, "log": [{"ts": "10:00:00", "msg": "ready", "level": "info"}],
    "tray": True, "autostart": False, "update": None, "crash_pending": 0,
    "network": {"name": "Home-WiFi", "events": True, "pending": None}, "frozen": False, "eviltwin": None}


class FakeTunnel:
    def __init__(self):
        self.calls = []
        self.last_error = None
        self._regions = [{"name": r["name"], "host": r["host"], "port": r["port"]} for r in STATE["regions"]]
        self.connected, self.active = False, None

    def has_region(self, name):
        return name in {r["name"] for r in self._regions}

    def region(self, name):
        return next((r for r in self._regions if r["name"] == name), None)

    def region_names(self):
        return [r["name"] for r in self._regions]

    def __getattr__(self, name):                 # connect, disconnect, set_kill_switch, push, panic_reset, ...
        def rec(*a, **k):
            self.calls.append((name, a))
        return rec

    def state(self):
        return json.loads(json.dumps(STATE))


class FakeConn:
    def __init__(self):
        self.events, self.shown, self.serves = set(), set(), set()
        self.alive, self.checked, self.pid = True, True, 4242
        self.sent = []

    def send(self, obj):
        self.sent.append(json.loads(obj) if isinstance(obj, bytes) else obj)
        return True


@pytest.fixture
def engine(monkeypatch, tmp_path):
    return make_engine(monkeypatch, tmp_path)


def make_engine(monkeypatch, tmp_path):
    from nobadvpn import api, configstore, settings as settings_mod, syscmd
    from nobadvpn.ctx import ctx
    s = settings_mod.Settings(str(tmp_path / "settings.json"))
    for k, v in STATE["settings"].items():
        s.set(k, v)
    t = FakeTunnel()
    monkeypatch.setattr(ctx, "settings", s)
    monkeypatch.setattr(ctx, "tunnel", t)
    monkeypatch.setattr(ctx, "netwatch", None)
    monkeypatch.setattr(ctx, "tray", None)
    monkeypatch.setattr(api, "spawn", lambda fn, *a: fn(*a))
    monkeypatch.setattr(api, "open_url_as_user", lambda url: url.startswith("https://"))
    monkeypatch.setattr(syscmd, "OPEN_ASYNC", False, raising=False)
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    monkeypatch.setattr(configstore, "_downloads_dir", lambda: str(downloads))
    conn = FakeConn()
    ev = rpc_events.Events(lambda: [conn], lambda c: None)
    m = methods.build(api.HANDLERS, t.state, ev, on_visible=lambda v: None, launch_ui=lambda w: False,
                      about=lambda: {"app": "NOBAD VPN", "version": "0.0.0-contract", "pid": 4242})
    return m, conn, ev, t


def load(name):
    with open(os.path.join(TRANSCRIPTS, name), encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def replay(items, m, conn, ev):
    """Run the transcript; returns it with every recv as the engine answers now."""
    out = []
    for it in items:
        if "send" in it:
            out.append(it)
            reply = protocol.handle_line(json.dumps(it["send"]), m, conn)
            for n in conn.sent:                  # events the call produced come before its reply
                out.append({"recv": n})
            conn.sent.clear()
            if reply is not None:
                r = json.loads(protocol.encode(reply))
                if isinstance(r.get("result"), dict) and "folder" in r["result"]:
                    r["result"]["folder"] = "<Downloads>"          # this PC's folder: not part of the contract
                out.append({"recv": r})
        elif "engine" in it:
            out.append(it)
            e = it["engine"]
            ev.deliver(json.dumps({"type": e["broadcast"], "payload": e["payload"]}))
            for n in conn.sent:
                out.append({"recv": n})
            conn.sent.clear()
        elif "note" in it:
            out.append(it)
    return out


def transcripts():
    return sorted(f for f in os.listdir(TRANSCRIPTS) if f.endswith(".jsonl"))


# ---------------------------------------------------------------- the files agree with the code
def test_method_schema_is_generated_from_the_spec():
    with open(os.path.join(CONTRACT, "methods.schema.json"), encoding="utf-8") as f:
        assert json.load(f) == params.json_schema(), "run: python -m nobadvpn.rpc.params > contract/methods.schema.json"


def test_event_schema_names_real_events():
    with open(os.path.join(CONTRACT, "events.schema.json"), encoding="utf-8") as f:
        doc = json.load(f)
    assert doc["protocol"] == protocol.PROTOCOL
    assert set(doc["events"]) <= rpc_events.EVENTS


def test_state_snapshot_has_every_key_the_schema_requires():
    with open(os.path.join(CONTRACT, "events.schema.json"), encoding="utf-8") as f:
        st = json.load(f)["$defs"]["State"]
    assert set(st["required"]) <= set(STATE)
    assert set(STATE) <= set(st["properties"])


def test_real_engine_state_keys_are_in_the_schema(win):
    """engine.Tunnel.state() + api.extra_state(): nothing the UI may get is undocumented."""
    from nobadvpn.ctx import ctx
    with open(os.path.join(CONTRACT, "events.schema.json"), encoding="utf-8") as f:
        props = set(json.load(f)["$defs"]["State"]["properties"])
    assert set(ctx.tunnel.state()) <= props


@pytest.mark.parametrize("name", transcripts())
def test_transcript_replays(name, engine):
    m, conn, ev, _t = engine
    items = load(name)
    got = replay(items, m, conn, ev)
    assert [json.dumps(x, sort_keys=True) for x in got] == [json.dumps(x, sort_keys=True) for x in items]


def test_transcripts_only_send_what_the_schema_allows():
    for name in transcripts():
        for it in load(name):
            if "send" in it and not it.get("expect_error"):
                s = it["send"]
                if s["method"] in params.SPEC:
                    params.validate(s["method"], s.get("params") or {})


def test_transcript_calls_reach_the_tunnel(engine):
    m, conn, ev, t = engine
    replay(load("02-connect-and-settings.jsonl"), m, conn, ev)
    names = [c[0] for c in t.calls]
    assert "connect" in names and "set_kill_switch" in names
    assert ("connect", ("..",)) not in t.calls


if __name__ == "__main__" and "--record" in sys.argv:
    import tempfile
    os.environ.setdefault("NOBAD_DATA_DIR", tempfile.mkdtemp(prefix="nobad-contract-"))

    class MP:
        def setattr(self, obj, name, value, raising=True):
            setattr(obj, name, value)
    tmp = __import__("pathlib").Path(tempfile.mkdtemp(prefix="nobad-contract-"))
    for n in transcripts():
        d = tmp / n.replace(".", "_")
        d.mkdir()
        m, conn, ev, _t = make_engine(MP(), d)
        kept = [x for x in load(n) if "recv" not in x]
        with open(os.path.join(TRANSCRIPTS, n), "w", encoding="utf-8", newline="\n") as f:
            for x in replay(kept, m, conn, ev):
                f.write(json.dumps(x, ensure_ascii=True) + "\n")
        print("recorded", n)
