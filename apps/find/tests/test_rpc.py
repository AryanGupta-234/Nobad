"""The engine's pipe for the Flutter UI: protocol, handlers, and a real named pipe (Windows only)."""
import json
import sys
import time
import uuid

import pytest

from nobadfind import engine
from nobadfind.api import Api
from nobadfind.rpc import handlers, protocol
from nobadfind.rpc.events import Events

WIN = sys.platform == "win32"


class FakeApi:
    def __init__(self):
        self.calls = []

    def search(self, text, filters=None):
        self.calls.append(("search", text, filters))
        return {"results": [{"id": 7, "name": "notes \u2028 r\u00e9sum\u00e9.txt", "dir": "C:\\x", "kind": "text"}],
                "ms": 3}

    def open(self, file_id):
        self.calls.append(("open", file_id))
        return {"ok": True}

    def reveal(self, file_id):
        self.calls.append(("reveal", file_id))
        return {"ok": True}

    def thumbnail(self, file_id):
        return {"url": ""}

    def status_brief(self):
        return {"level": "gentle", "reason": "Gentle: you're using the PC", "phase": "names", "files": 12,
                "paused": ""}


def call(methods, method, params=None, rid=1):
    req = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params is not None:
        req["params"] = params
    return protocol.handle_line(json.dumps(req), methods)


# ---------- protocol ----------
def test_parse_error_and_invalid_requests():
    m = handlers.methods(FakeApi())
    assert protocol.handle_line(b"{nope", m)["error"]["code"] == protocol.PARSE_ERROR
    assert protocol.handle_line(b"\xff\xfe", m)["error"]["code"] == protocol.PARSE_ERROR
    assert protocol.handle_line("[1, 2]", m)["error"]["code"] == protocol.INVALID_REQUEST
    assert protocol.handle_line('{"id": 1, "method": "hello"}', m)["error"]["code"] == protocol.INVALID_REQUEST
    r = protocol.handle_line('{"jsonrpc": "2.0", "id": true, "method": "hello"}', m)
    assert r["error"]["code"] == protocol.INVALID_REQUEST and r["id"] is None
    r = protocol.handle_line('{"jsonrpc": "2.0", "id": [1], "method": "hello"}', m)
    assert r["error"]["code"] == protocol.INVALID_REQUEST


def test_unknown_method_and_bad_params():
    m = handlers.methods(FakeApi())
    assert call(m, "rm_rf")["error"]["code"] == protocol.METHOD_NOT_FOUND
    assert call(m, "open", {"id": "C:\\Windows\\notepad.exe"})["error"]["code"] == protocol.INVALID_PARAMS
    assert call(m, "open", {"id": True})["error"]["code"] == protocol.INVALID_PARAMS
    assert call(m, "open", [5])["error"]["code"] == protocol.INVALID_PARAMS
    assert call(m, "search", {"text": 5})["error"]["code"] == protocol.INVALID_PARAMS
    assert call(m, "search", {"text": "x", "filters": "kind=pdf"})["error"]["code"] == protocol.INVALID_PARAMS


def test_notifications_get_no_reply():
    api = FakeApi()
    m = handlers.methods(api)
    assert protocol.handle_line('{"jsonrpc": "2.0", "method": "open", "params": {"id": 3}}', m) is None
    assert protocol.handle_line('{"jsonrpc": "2.0", "method": "nope"}', m) is None
    assert api.calls == [("open", 3)]


def test_a_failing_handler_is_an_internal_error():
    def boom(params, conn=None):
        raise RuntimeError("secret path C:\\Users\\x")
    r = call({"boom": boom}, "boom")
    assert r["error"] == {"code": protocol.INTERNAL_ERROR, "message": "Internal error"}


def test_methods_call_the_api():
    api = FakeApi()
    m = handlers.methods(api)
    assert call(m, "hello")["result"]["protocol"] == protocol.PROTOCOL
    assert call(m, "search", {"text": "tax", "filters": {"kind": "pdf"}})["result"]["results"][0]["id"] == 7
    assert call(m, "open", {"id": 7})["result"] == {"ok": True}
    assert call(m, "reveal", {"id": 7}, rid="r")["id"] == "r"
    assert call(m, "status")["result"]["files"] == 12
    assert api.calls[0] == ("search", "tax", {"kind": "pdf"})


def test_encode_is_one_ascii_line():
    line = protocol.encode({"name": "a\u2028b\nc\u00e9"})
    assert line.endswith(b"\n") and line.count(b"\n") == 1
    assert json.loads(line) == {"name": "a\u2028b\nc\u00e9"}


def test_line_buffer_splits_and_caps():
    b = protocol.LineBuffer(cap=10)
    assert b.feed(b'{"a":1}\n{"b"') == [b'{"a":1}']
    assert b.feed(b":2}\r\n\n") == [b'{"b":2}']
    with pytest.raises(ValueError):
        b.feed(b"x" * 11)
    with pytest.raises(ValueError):
        protocol.LineBuffer(cap=4).feed(b"12345\n")


# ---------- events ----------
class FakeConn:
    def __init__(self, ok=True):
        self.events, self.sent, self.ok = set(), [], ok

    def send(self, obj):
        self.sent.append(obj)
        return self.ok


def test_events_go_only_to_subscribers_and_bad_clients_are_dropped():
    a, b, bad = FakeConn(), FakeConn(), FakeConn(ok=False)
    dropped = []
    ev = Events(lambda: [a, b, bad], dropped.append, FakeApi().status_brief)
    assert ev.subscribe(a, ["status", "show", "everything"]) == ["show", "status"]
    ev.subscribe(bad, ["show"])
    assert ev.push("show", {"what": "bar"}) == 1
    assert a.sent == [{"jsonrpc": "2.0", "method": "show", "params": {"what": "bar"}}]
    assert b.sent == [] and dropped == [bad]


def test_subscribe_method():
    a = FakeConn()
    ev = Events(lambda: [a], lambda c: None, FakeApi().status_brief)
    m = handlers.methods(FakeApi(), ev)
    r = protocol.handle_line('{"jsonrpc":"2.0","id":1,"method":"subscribe","params":{"events":["status"]}}', m, a)
    assert r["result"] == {"events": ["status"]} and a.events == {"status"}
    r = protocol.handle_line('{"jsonrpc":"2.0","id":1,"method":"subscribe","params":{"events":"status"}}', m, a)
    assert r["error"]["code"] == protocol.INVALID_PARAMS


def test_status_events_tick():
    a = FakeConn()
    a.events.add("status")
    ev = Events(lambda: [a], lambda c: None, FakeApi().status_brief, every=0.05)
    ev.start()
    try:
        deadline = time.time() + 3
        while not a.sent and time.time() < deadline:
            time.sleep(0.02)
    finally:
        ev.stop()
    assert a.sent and a.sent[0]["method"] == "status" and a.sent[0]["params"]["level"] == "gentle"


# ---------- Api.status_brief ----------
class _Ind:
    status = {"phase": "text", "files": 42, "paused": "", "level": "light", "reason": "Light: on battery"}


class _Gov:
    class decision:
        level, reason = "gentle", "Gentle: you're using the PC"


def test_status_brief():
    api = Api.__new__(Api)
    api._indexer, api._governor = _Ind(), None
    assert api.status_brief() == {"level": "light", "reason": "Light: on battery", "phase": "text", "files": 42,
                                  "paused": ""}
    api._governor = _Gov()
    assert api.status_brief()["level"] == "gentle"


# ---------- engine single-instance rule ----------
def test_engine_lock_name():
    assert engine.lock_name("C:\\U\\NOBAD\\Find", "C:\\U\\NOBAD\\Find") == "Local\\NOBAD-Find"
    other = engine.lock_name("D:\\tmp\\find-measure", "C:\\U\\NOBAD\\Find")
    assert other.startswith("Local\\NOBAD-Find-engine-") and other != engine.lock_name("D:\\x", "C:\\U\\NOBAD\\Find")


# ---------- the real pipe ----------
win_only = pytest.mark.skipif(not WIN, reason="named pipes are Windows only")


@pytest.fixture
def served():
    from nobadfind.rpc import Rpc
    from nobadfind.rpc import server as srv
    name = srv.pipe_name() + "-test-" + uuid.uuid4().hex[:8]      # never the real engine's pipe
    api = FakeApi()
    rpc = Rpc(api, name=name, status_every=0.1)
    assert rpc.start()
    yield rpc, name, api
    rpc.stop()


class Client:
    def __init__(self, name):
        deadline = time.time() + 5
        while True:
            try:
                self.f = open(name, "r+b", buffering=0)
                break
            except OSError:
                if time.time() > deadline:
                    raise
                time.sleep(0.05)
        self.buf = b""

    def send(self, obj_or_bytes):
        data = obj_or_bytes if isinstance(obj_or_bytes, bytes) else (json.dumps(obj_or_bytes) + "\n").encode()
        self.f.write(data)

    def line(self):
        while b"\n" not in self.buf:
            chunk = self.f.read(65536)
            if not chunk:
                raise EOFError
            self.buf += chunk
        line, self.buf = self.buf.split(b"\n", 1)
        return json.loads(line)

    def reply(self, rid):
        while True:
            msg = self.line()
            if msg.get("id") == rid:
                return msg

    def close(self):
        self.f.close()


@win_only
def test_pipe_round_trip(served):
    rpc, name, api = served
    c = Client(name)
    try:
        c.send({"jsonrpc": "2.0", "id": 1, "method": "hello"})
        assert c.reply(1)["result"]["protocol"] == 1
        c.send({"jsonrpc": "2.0", "id": 2, "method": "search", "params": {"text": "notes"}})
        r = c.reply(2)["result"]
        assert r["results"][0]["name"] == "notes \u2028 r\u00e9sum\u00e9.txt"
        c.send(b"this is not json\n")
        assert c.line()["error"]["code"] == protocol.PARSE_ERROR
        c.send({"jsonrpc": "2.0", "id": 3, "method": "no_such_thing"})
        assert c.reply(3)["error"]["code"] == protocol.METHOD_NOT_FOUND
        c.send({"jsonrpc": "2.0", "id": 4, "method": "open", "params": {"id": 7}})
        assert c.reply(4)["result"] == {"ok": True}
        assert ("open", 7) in api.calls
    finally:
        c.close()


@win_only
def test_pipe_events(served):
    rpc, name, api = served
    c = Client(name)
    try:
        c.send({"jsonrpc": "2.0", "id": 1, "method": "subscribe", "params": {"events": ["status", "show"]}})
        assert c.reply(1)["result"]["events"] == ["show", "status"]
        msg = c.line()
        while msg.get("method") != "status":
            msg = c.line()
        assert msg["params"]["files"] == 12
        assert rpc.show("bar") == 1
        msg = c.line()
        while msg.get("method") != "show":
            msg = c.line()
        assert msg["params"] == {"what": "bar"}
    finally:
        c.close()


@win_only
def test_pipe_several_clients_and_reconnect(served):
    rpc, name, api = served
    clients = [Client(name) for _ in range(3)]
    try:
        for i, c in enumerate(clients):
            c.send({"jsonrpc": "2.0", "id": i, "method": "status"})
        for i, c in enumerate(clients):
            assert c.reply(i)["result"]["phase"] == "names"
    finally:
        for c in clients:
            c.close()
    c = Client(name)                    # after they all left, a new one still gets in
    try:
        c.send({"jsonrpc": "2.0", "id": 9, "method": "hello"})
        assert c.reply(9)["result"]["version"]
    finally:
        c.close()


@win_only
def test_pipe_too_big_message_drops_only_that_client(served):
    rpc, name, api = served
    c = Client(name)
    try:
        c.send(b"x" * (protocol.MAX_MESSAGE + 10))
        assert c.line()["error"]["message"] == "Message too big"
        with pytest.raises((EOFError, OSError)):
            c.line()
    finally:
        try:
            c.close()
        except OSError:
            pass
    c = Client(name)
    try:
        c.send({"jsonrpc": "2.0", "id": 1, "method": "hello"})
        assert c.reply(1)["result"]["protocol"] == 1
    finally:
        c.close()


@win_only
def test_pipe_name_already_taken_is_refused(served):
    from nobadfind.rpc.server import Server
    rpc, name, api = served
    other = Server(name=name)
    assert other.start() is False


@win_only
def test_pipe_security():
    from nobadfind.rpc import server as srv
    sid = srv.user_sid()
    assert sid.startswith("S-1-5-")
    assert srv.pipe_name(sid) == "\\\\.\\pipe\\NOBADFind-" + sid
    assert srv.sddl_for(sid) == f"D:P(D;;GA;;;NU)(A;;GA;;;{sid})"
    with pytest.raises(ValueError):
        srv.sddl_for("S-1-1-0)(A;;GA;;;WD")


@win_only
def test_pipe_stop_ends_the_threads(served):
    rpc, name, api = served
    c = Client(name)
    c.send({"jsonrpc": "2.0", "id": 1, "method": "hello"})
    c.reply(1)
    rpc.stop()
    assert not rpc.server.thread.is_alive()
    with pytest.raises((EOFError, OSError)):
        c.line()
    c.close()


def test_engine_flag_parses():
    from nobadfind.app import parse_args
    assert parse_args(["--engine"]).engine is True
    assert parse_args([]).engine is False
