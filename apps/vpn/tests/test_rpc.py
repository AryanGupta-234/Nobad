"""The engine pipe for the Flutter UI: protocol, parameter allowlist, caller policy, events, launching the UI, and a
real named pipe on Windows (a development name, at normal rights: nothing on the PC changes)."""
import json
import os
import queue
import sys
import threading
import time
import uuid

import pytest

from nobadvpn.rpc import events as rpc_events
from nobadvpn.rpc import launch, methods, params, protocol, security

WIN = sys.platform == "win32"
USER = "S-1-5-21-1111111111-2222222222-3333333333-1001"


class FakeConn:
    def __init__(self, pid=4242):
        self.events, self.shown, self.serves = set(), set(), set()
        self.alive, self.checked, self.pid = True, True, pid
        self.sent = []

    def send(self, obj):
        self.sent.append(json.loads(obj) if isinstance(obj, bytes) else obj)
        return True


def handlers(calls):
    def rec(name, result=None):
        def fn(b):
            calls.append((name, b))
            return {"ok": True} if result is None else result
        return fn
    h = {name: rec(name) for name in params.SPEC if name not in methods.PIPE_ONLY}
    h["connect"] = lambda b: (calls.append(("connect", b)), {"ok": False, "error": "unknown server"})[1]
    h["usage"] = lambda b: "not a dict"
    h["probe"] = lambda b: {"ok": False}
    h["fastest"] = lambda b: 1 / 0
    return h


def call(m, method, p=None, conn=None, rid=1):
    req = {"jsonrpc": "2.0", "id": rid, "method": method}
    if p is not None:
        req["params"] = p
    return protocol.handle_line(json.dumps(req), m, conn)


def build(calls=None, **kw):
    calls = [] if calls is None else calls
    return methods.build(handlers(calls), lambda: {"connected": False, "regions": []}, **kw), calls


# ---------------------------------------------------------------- protocol
def test_parse_and_request_errors():
    m, _ = build()
    assert protocol.handle_line(b"{nope", m)["error"]["code"] == protocol.PARSE_ERROR
    assert protocol.handle_line(b"\xff\xfe", m)["error"]["code"] == protocol.PARSE_ERROR
    assert protocol.handle_line('{"jsonrpc":"2.0","id":1,"method":"state","params":{"x":NaN}}', m)["error"]["code"] \
        == protocol.PARSE_ERROR
    assert protocol.handle_line("[1,2]", m)["error"]["code"] == protocol.INVALID_REQUEST
    assert protocol.handle_line('{"id":1,"method":"state"}', m)["error"]["code"] == protocol.INVALID_REQUEST
    r = protocol.handle_line('{"jsonrpc":"2.0","id":true,"method":"state"}', m)
    assert r["error"]["code"] == protocol.INVALID_REQUEST and r["id"] is None
    assert call(m, "state", [1])["error"]["code"] == protocol.INVALID_PARAMS
    assert protocol.handle_line('{"jsonrpc":"2.0","method":"state"}', m) is None       # a notification: no reply


def test_only_listed_methods_exist():
    m, _ = build()
    for name in ("window", "ui_state", "rm_rf", "__class__", "h_connect"):
        assert call(m, name)["error"]["code"] == protocol.METHOD_NOT_FOUND
    assert set(m) == set(params.SPEC)


def test_a_failing_handler_never_leaks_its_exception():
    m, _ = build()
    r = call(m, "fastest")
    assert r["error"] == {"code": protocol.INTERNAL_ERROR, "message": "Internal error"}


def test_every_answer_is_ok_and_a_sentence():
    m, calls = build()
    assert call(m, "connect", {"name": "japan"})["result"] == {"ok": False, "error": "unknown server"}
    assert call(m, "usage", {})["result"] == {"ok": False, "error": methods.FALLBACK_ERROR}
    assert call(m, "probe")["result"] == {"ok": False, "error": methods.FALLBACK_ERROR}   # never a bare {"ok": false}
    assert call(m, "disconnect")["result"] == {"ok": True}
    assert ("connect", {"name": "japan"}) in calls


def test_line_buffer_caps_and_splits():
    b = protocol.LineBuffer(cap=10)
    assert b.feed(b'{"a":1}\r\n\n{"b"') == [b'{"a":1}']
    assert b.feed(b":2}\n") == [b'{"b":2}']
    with pytest.raises(ValueError):
        b.feed(b"x" * 11)
    with pytest.raises(ValueError):
        protocol.LineBuffer(cap=4).feed(b"12345\n")


def test_encode_is_one_ascii_line():
    line = protocol.encode({"name": "caf\u00e9 \u2028 x"})
    assert line.endswith(b"\n") and line.count(b"\n") == 1 and line.isascii()


# ---------------------------------------------------------------- parameters: an allowlist of shapes
@pytest.mark.parametrize("method,p", [
    ("connect", {"name": "..\\..\\Windows\\System32\\drivers\\etc\\hosts"}),
    ("connect", {"name": "C:\\x"}),
    ("connect", {"name": "a" * 33}),
    ("connect", {"name": 5}),
    ("connect", {}),
    ("connect", {"name": "japan", "extra": 1}),
    ("config_delete", {"name": "x/../y"}),
    ("free_import", {"files": ["..\\secret.conf"]}),
    ("free_import", {"files": ["C:\\Users\\me\\Downloads\\a.conf"]}),
    ("free_import", {"files": "a.conf"}),
    ("free_import", {"files": ["a.conf"] * 41}),
    ("import", {"name": "a.conf", "content": "x" * 400_001}),
    ("import", {"name": "a\\b.conf", "content": "[Interface]"}),
    ("import_url", {"url": "http://example.com/a.conf"}),
    ("import_url", {"url": "file:///C:/Windows/win.ini"}),
    ("net_repair", {"level": "nuke"}),
    ("open_url", {"key": "https://evil.example"}),
    ("settings", {"key": "kill_switch", "value": {"nested": True}}),
    ("settings", {"key": "kill_switch", "value": 1}),
    ("settings", {"key": "Kill Switch", "value": True}),
    ("settings", {"key": "trusted_networks", "value": [{"a": 1}]}),
    ("settings", {"key": "update_url", "value": "x" * 2001}),
    ("gaming_probe", {"host": "1.1.1.1; calc.exe"}),
    ("gaming_probe", {"host": "$(calc)"}),
    ("crash_send", {"file": "..\\..\\settings.json"}),
    ("crash_send", {"file": "crash-1.json\x00.exe"}),
    ("usage", {"days": True}),
    ("usage", {"days": 401}),
    ("quit", {"disconnect": "yes"}),
    ("ui_shown", {"window": "settings"}),
    ("subscribe", {"events": "state"}),
    ("trusted_add", {"name": "home\nwifi"}),
    ("si_open", {"url": "javascript:alert(1)"}),
    ("ni_fix", {"id": "1; rm"}),
])
def test_bad_parameters_are_refused_before_any_handler(method, p):
    m, calls = build()
    r = call(m, method, p)
    assert r["error"]["code"] == protocol.INVALID_PARAMS, r
    assert calls == []


@pytest.mark.parametrize("method,p", [
    ("connect", {"name": "JP-FREE.3_x=+"}),
    ("import", {"name": "wg-JP-FREE#3.conf", "content": "[Interface]\r\nPrivateKey = x\n\tAddress = 10.0.0.2/32"}),
    ("free_import", {"files": ["wg-JP-FREE#3.conf", "nl-free-1.conf"]}),
    ("config_validate", {"name": "", "text": "[Interface]"}),
    ("settings", {"key": "kill_switch", "value": True}),
    ("settings", {"key": "fallback_dns", "value": "1.1.1.1, 1.0.0.1"}),
    ("settings", {"key": "trusted_networks", "value": ["Home", "Office 5G"]}),
    ("smart", {}),
    ("smart", {"service": "netflix"}),
    ("report_problem", {"crash": True}),
    ("quit", {"disconnect": True}),
    ("open_url", {"key": "proton_downloads"}),
    ("gaming_probe", {"host": "151.106.246.1"}),
    ("crash_send", {"file": "crash-20261119-101010.json"}),
    ("si_title", {"key": "movie:603"}),
    ("si_title", {"key": "wd:Q83495", "force": True}),
])
def test_good_parameters_reach_the_handler_unchanged(method, p):
    m, calls = build()
    r = call(m, method, p)
    assert "result" in r, r
    assert calls[-1] == (method, p)


def test_settings_text_may_not_smuggle_control_characters():
    with pytest.raises(protocol.RpcError):
        params.validate("settings", {"key": "update_url", "value": "https://x\u2028y"})
    with pytest.raises(protocol.RpcError):
        params.validate("import_url", {"url": "https://x/a b"})


def test_every_spec_method_has_a_real_engine_handler():
    from nobadvpn import api
    missing = [n for n in params.SPEC if n not in methods.PIPE_ONLY and n not in api.HANDLERS]
    assert missing == []
    assert "window" not in params.SPEC and "ui_state" not in params.SPEC   # WebView-only


def test_spec_url_keys_match_the_api():
    from nobadvpn import api
    assert set(params.URL_KEYS) == set(api.ALLOWED_URLS) | {"portal"}


def test_spec_services_match_settings():
    from nobadvpn import settings
    assert tuple(params.SERVICES) == tuple(settings.SERVICES_IDS)


def test_protection_changes_are_logged_with_the_caller(monkeypatch):
    got = []
    monkeypatch.setattr(methods, "log", lambda msg, level="info": got.append(msg))
    m, _ = build()
    call(m, "settings", {"key": "kill_switch", "value": False}, conn=FakeConn(pid=0))
    call(m, "settings", {"key": "kill_switch", "value": True}, conn=FakeConn(pid=0))
    call(m, "panic_reset", {}, conn=FakeConn(pid=0))
    assert got == ["kill_switch turned off from a program (pid 0)", "panic_reset requested by a program (pid 0)"]


# ---------------------------------------------------------------- the pipe's own methods
def test_hello_lists_methods_and_events():
    m, _ = build(about=lambda: {"app": "NOBAD VPN", "version": "9", "pid": 1})
    r = call(m, "hello")["result"]
    assert r["protocol"] == protocol.PROTOCOL and r["app"] == "NOBAD VPN"
    assert r["methods"] == sorted(params.SPEC) and "state" in r["events"]


def test_window_reports_drive_the_engines_pace():
    seen = []
    conn = FakeConn()
    ev = rpc_events.Events(lambda: [conn], lambda c: None, bus=FakeBus())
    m, _ = build(events=ev, on_visible=seen.append)
    call(m, "ui_shown", {"window": "main"}, conn=conn)
    call(m, "ui_shown", {"window": "mini"}, conn=conn)
    call(m, "ui_hidden", {"window": "main"}, conn=conn)
    call(m, "ui_hidden", {"window": "mini"}, conn=conn)
    assert seen == [True, True, True, False]
    assert conn.serves == {"main", "mini"}


def test_ui_show_goes_to_the_ui_that_serves_it_else_launches():
    launched = []
    conn = FakeConn()
    ev = rpc_events.Events(lambda: [conn], lambda c: None, bus=FakeBus())
    m, _ = build(events=ev, launch_ui=lambda w: (launched.append(w), True)[1])
    conn.events.add("show")
    r = call(m, "ui_show", {"window": "mini"}, conn=conn)["result"]
    assert r == {"ok": True, "shown": False, "launched": True} and launched == ["mini"]
    call(m, "ui_hidden", {"window": "mini"}, conn=conn)
    r = call(m, "ui_show", {"window": "mini"}, conn=conn)["result"]
    assert r["shown"] is True and conn.sent[-1] == {"jsonrpc": "2.0", "method": "show", "params": {"window": "mini"}}


# ---------------------------------------------------------------- events
class FakeBus:
    def __init__(self):
        self.subs = []

    def subscribe(self, maxsize=300):
        q = queue.Queue(maxsize)
        self.subs.append(q)
        return q

    def unsubscribe(self, q):
        self.subs.remove(q)


def test_events_go_only_to_subscribers_and_only_known_types():
    a, b = FakeConn(), FakeConn()
    ev = rpc_events.Events(lambda: [a, b], lambda c: None, bus=FakeBus())
    assert ev.subscribe(a, ["state", "traffic", "bogus"]) == ["state", "traffic"]
    assert ev.deliver(json.dumps({"type": "traffic", "payload": {"rx_bps": 1}})) == 1
    assert ev.deliver(json.dumps({"type": "secret_internal", "payload": {}})) == 0
    assert ev.deliver("not json") == 0
    assert a.sent == [{"jsonrpc": "2.0", "method": "traffic", "params": {"rx_bps": 1}}] and b.sent == []


def test_the_pump_listens_to_logbus_only_while_someone_is_connected():
    conns = []
    bus = FakeBus()
    ev = rpc_events.Events(lambda: list(conns), lambda c: None, bus=bus)
    ev.clients_changed()
    assert bus.subs == []
    c = FakeConn()
    c.events.add("log")
    conns.append(c)
    ev.clients_changed()
    assert len(bus.subs) == 1
    bus.subs[0].put(json.dumps({"type": "log", "payload": {"msg": "hi"}}))
    for _ in range(100):
        if c.sent:
            break
        time.sleep(0.01)
    assert c.sent[0]["params"] == {"msg": "hi"}
    conns.clear()
    ev.clients_changed()
    assert bus.subs == []


def test_a_client_that_cant_take_an_event_is_dropped():
    dropped = []
    c = FakeConn()
    c.send = lambda obj: False
    c.events.add("state")
    ev = rpc_events.Events(lambda: [c], dropped.append, bus=FakeBus())
    ev.push("state", {})
    assert dropped == [c]


def test_event_list_covers_every_engine_broadcast():
    import re
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "nobadvpn")
    names = set()
    for dirpath, _d, files in os.walk(root):
        for f in files:
            if f.endswith(".py"):
                with open(os.path.join(dirpath, f), encoding="utf-8") as fh:
                    names |= set(re.findall(r'broadcast\("([a-z_]+)"', fh.read()))
    assert names - rpc_events.EVENTS == set()


# ---------------------------------------------------------------- who may connect
def test_sddl_allows_only_the_user_system_and_admins_at_medium():
    s = security.sddl_for(USER)
    assert s == f"D:P(D;;GA;;;NU)(A;;GA;;;{USER})(A;;GA;;;SY)(A;;GA;;;BA)S:(ML;;NW;;;ME)"
    for bad in ("", "WD", "S-1-1-0)(A;;GA;;;WD", "S-1-5-21-1(A;;GA;;;WD)", None, 5):
        with pytest.raises(ValueError):
            security.sddl_for(bad)


def test_pipe_names():
    assert security.pipe_name(USER) == "\\\\.\\pipe\\NOBADVPN-" + USER
    assert security.pipe_name(USER, dev=True) == "\\\\.\\pipe\\NOBADVPN-dev-" + USER
    with pytest.raises(ValueError):
        security.pipe_name("..\\x")


ENGINE = {"user_sid": USER, "session": 1}
GOOD = {"sid": USER, "session": 1, "integrity": 0x2000, "appcontainer": False,
        "image": "C:\\Program Files\\NOBAD VPN\\ui\\nobad_vpn_ui.exe"}
PINNED = ["C:\\Program Files\\NOBAD VPN\\ui\\nobad_vpn_ui.exe", "C:\\Program Files\\NOBAD VPN\\NobadVPN.exe"]


@pytest.mark.parametrize("change,why", [
    ({}, None),
    ({"integrity": 0x3000}, None),                                   # an elevated NOBAD helper
    ({"sid": "S-1-5-21-9-9-9-1002"}, "another account"),
    ({"sid": None}, "another account"),
    ({"session": 2}, "another Windows session"),
    ({"integrity": 0x1000}, "low integrity"),
    ({"integrity": None}, "low integrity"),
    ({"appcontainer": True}, "an app container"),
    ({"image": "C:\\Users\\me\\AppData\\Local\\Temp\\nobad_vpn_ui.exe"}, "not NOBAD's own program"),
    ({"image": None}, "not NOBAD's own program"),
    ({"image": "c:\\program files\\nobad vpn\\UI\\NOBAD_VPN_UI.EXE"}, None),
    ({"sid": security.SYSTEM, "session": 0}, None),
])
def test_caller_policy(change, why):
    assert security.decide(dict(GOOD, **change), ENGINE, PINNED) == why


def test_source_runs_dont_pin_the_program():
    assert security.decide(dict(GOOD, image="D:\\dev\\x.exe"), ENGINE, None) is None
    assert security.allowed_images() is None                         # tests run from source


# ---------------------------------------------------------------- which UI, and starting it as the user
def test_ui_mode(tmp_path):
    exe = str(tmp_path / "nobad_vpn_ui.exe")
    assert launch.ui_mode({}, exe=exe) == "webview"
    assert launch.ui_mode({"NOBAD_VPN_UI": "flutter"}, exe=exe) == "flutter"
    assert launch.ui_mode({"NOBAD_VPN_UI": "BOTH"}, exe=exe) == "both"
    assert launch.ui_mode({"NOBAD_VPN_UI": "flutter"}, exe="") == "webview"     # no Flutter UI: stays WebView
    assert launch.ui_mode({"NOBAD_VPN_UI": "chrome"}, exe=exe) == "webview"


def test_task_command_takes_only_a_fixed_program_and_argument():
    ps = launch.task_ps("C:\\Program Files\\NOBAD VPN\\ui\\nobad_vpn_ui.exe", "--mini")
    assert "-RunLevel Limited" in ps and "-Argument '--mini'" in ps
    for exe, arg in (("C:\\x\\a'b.exe", ""), ("C:\\x\\$(calc).exe", ""), ("\\\\server\\share\\a.exe", ""),
                     ("C:\\x\\a.exe", "--anything"), ("C:\\x\\a.exe", "; calc")):
        with pytest.raises(ValueError):
            launch.task_ps(exe, arg)


def test_launch_unelevated_starts_directly_elevated_uses_the_shell_token():
    started = []
    exe = "C:\\Program Files\\NOBAD VPN\\ui\\nobad_vpn_ui.exe"
    assert launch.launch("mini", exe=exe, admin=False, popen=lambda a, **k: started.append(a))
    assert started == [[exe, "--mini"]]
    assert launch.launch("main", exe=exe, admin=True, shell_start=lambda e, a: started.append((e, a)) or True)
    assert started[-1] == (exe, "")
    ran = []

    class R:
        returncode, stderr = 0, ""
    assert launch.launch("main", exe=exe, admin=True, shell_start=lambda e, a: False,
                         runner=lambda cmd, timeout: (ran.append(cmd), R())[1])
    assert ran and ran[0][0] == "powershell" and "-RunLevel Limited" in ran[0][-1]
    assert not launch.launch("settings", exe=exe, admin=False, popen=lambda a, **k: None)
    assert not launch.launch("main", exe=None, admin=False) or launch.ui_exe()


# ---------------------------------------------------------------- a real pipe (Windows, normal rights)
@pytest.mark.skipif(not WIN, reason="named pipes are Windows only")
class TestRealPipe:
    def _open(self, name):
        import ctypes
        from ctypes import wintypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateFileW.restype = wintypes.HANDLE
        k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                  wintypes.DWORD, wintypes.HANDLE]
        for _ in range(50):
            h = k.CreateFileW(name, 0xC0000000, 0, None, 3, 0x00100000 | 0x00010000, None)   # SQOS identification
            if h and h != ctypes.c_void_p(-1).value:
                import msvcrt
                return os.fdopen(msvcrt.open_osfhandle(h, 0), "r+b", buffering=0)
            time.sleep(0.05)
        raise AssertionError("pipe didn't open")

    def _server(self, check=None, **kw):
        from nobadvpn.rpc import Rpc
        calls = []
        sid = security.own_user_sid()
        name = "\\\\.\\pipe\\NOBADVPN-test-" + uuid.uuid4().hex
        rpc = Rpc(handlers=handlers(calls), state=lambda: {"connected": False, "regions": []}, name=name,
                  user_sid=sid, check=check or (lambda h, pid: None), launch_ui=lambda w: False, **kw)
        assert rpc.start()
        return rpc, name, calls

    @staticmethod
    def _ask(f, obj):
        f.write((json.dumps(obj) + "\n").encode())
        return json.loads(TestRealPipe._readline(f))

    @staticmethod
    def _readline(f):
        out = b""
        while not out.endswith(b"\n"):
            c = f.read(1)
            if not c:
                break
            out += c
        return out

    def test_round_trip_state_and_events(self):
        rpc, name, calls = self._server()
        try:
            f = self._open(name)
            r = self._ask(f, {"jsonrpc": "2.0", "id": 1, "method": "hello"})
            assert r["result"]["protocol"] == 1 and r["result"]["pid"] == os.getpid()
            assert self._ask(f, {"jsonrpc": "2.0", "id": 2, "method": "state"})["result"]["connected"] is False
            assert self._ask(f, {"jsonrpc": "2.0", "id": 3, "method": "subscribe", "params": {"events": ["log"]}}) \
                ["result"] == {"events": ["log"]}
            from nobadvpn.logbus import log
            log("hello from the engine", "ok")
            ev = json.loads(self._readline(f))
            assert ev["method"] == "log" and ev["params"]["msg"] == "hello from the engine"
            r = self._ask(f, {"jsonrpc": "2.0", "id": 4, "method": "connect", "params": {"name": "..\\x"}})
            assert r["error"]["code"] == protocol.INVALID_PARAMS and calls == []
            f.close()
        finally:
            rpc.stop()

    def test_too_big_a_message_is_answered_then_dropped(self):
        rpc, name, _ = self._server()
        try:
            f = self._open(name)
            f.write(b'{"jsonrpc":"2.0","id":1,"method":"import","params":{"content":"' + b"x" * protocol.MAX_MESSAGE)
            r = json.loads(self._readline(f))
            assert r["error"]["message"] == "Message too big"
            assert self._readline(f) == b""                     # dropped
        finally:
            rpc.stop()

    def test_a_refused_caller_gets_nothing_but_the_refusal(self):
        rpc, name, calls = self._server(check=lambda h, pid: "another account")
        try:
            f = self._open(name)
            f.write(b'{"jsonrpc":"2.0","id":1,"method":"disconnect"}\n')
            r = json.loads(self._readline(f))
            assert r["error"]["code"] == protocol.NOT_ALLOWED
            assert self._readline(f) == b"" and calls == []
        finally:
            rpc.stop()

    def test_the_real_caller_check_admits_this_process(self):
        """security.client_facts by impersonation: this test process is the same user, session, Medium or above."""
        from nobadvpn.rpc.server import default_check
        seen = {}

        def check(h, pid):
            seen["facts"] = security.client_facts(h, pid)
            return default_check(security.own_user_sid())(h, pid)
        rpc, name, _ = self._server(check=check)
        try:
            f = self._open(name)
            r = self._ask(f, {"jsonrpc": "2.0", "id": 1, "method": "hello"})
            assert "result" in r, r
            facts = seen["facts"]
            assert facts["sid"] == security.own_user_sid() and facts["integrity"] >= security.MEDIUM_RID
            assert facts["session"] == security.own_session()
            assert os.path.basename(facts["image"]).lower().startswith("python")
        finally:
            rpc.stop()

    def test_the_name_is_never_shared(self):
        rpc, name, _ = self._server()
        try:
            from nobadvpn.rpc import Rpc
            other = Rpc(handlers=handlers([]), state=lambda: {}, name=name, user_sid=security.own_user_sid(),
                        check=lambda h, pid: None, launch_ui=lambda w: False)
            assert other.start() is False                       # FILE_FLAG_FIRST_PIPE_INSTANCE
        finally:
            rpc.stop()

    def test_session_user_is_this_user(self):
        assert security.session_user_sid() == security.own_user_sid()

    def test_concurrent_clients(self):
        rpc, name, _ = self._server()
        try:
            out = []

            def one():
                f = self._open(name)
                out.append(self._ask(f, {"jsonrpc": "2.0", "id": 7, "method": "state"})["result"])
                f.close()
            ts = [threading.Thread(target=one) for _ in range(4)]
            for t in ts:
                t.start()
            for t in ts:
                t.join(10)
            assert len(out) == 4
        finally:
            rpc.stop()


# ---------------------------------------------------------------- the engine picks its window
def test_webview_stays_the_default_window(monkeypatch):
    from nobadvpn import app, window
    from nobadvpn.ctx import ctx
    monkeypatch.setattr(launch, "ui_mode", lambda: "webview")
    monkeypatch.setattr(ctx, "rpc", None)
    assert isinstance(app._windows("http://127.0.0.1:1"), window.WindowManager) and ctx.rpc is None


def test_flutter_mode_hands_windows_to_the_pipe(monkeypatch):
    from nobadvpn import app, rpc
    from nobadvpn.ctx import ctx
    shown = []

    class FakeRpc:
        def show(self, w):
            shown.append(w)
    monkeypatch.setattr(launch, "ui_mode", lambda: "flutter")
    monkeypatch.setattr(rpc, "start", lambda mode: FakeRpc())
    monkeypatch.setattr(ctx, "rpc", None)
    wm = app._windows("http://127.0.0.1:1")
    assert isinstance(wm, rpc.FlutterWindows) and wm.revealed_event.is_set()
    wm.toggle_mini()
    wm.show_main()
    for _ in range(100):
        if len(shown) == 2:
            break
        time.sleep(0.01)
    assert sorted(shown) == ["main", "mini"]
    monkeypatch.setattr(rpc, "start", lambda mode: None)                       # no pipe: the classic window
    from nobadvpn import window
    assert isinstance(app._windows("http://127.0.0.1:1"), window.WindowManager)
