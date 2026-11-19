"""The UI <-> engine contract (apps/find/contract): every handler against methods.schema.json, every event against
events.schema.json, and the recorded transcripts replayed against the real handlers and events.

Re-record the transcripts after a deliberate contract change (keeps the send/engine lines, rewrites the replies):
    python tests/test_rpc_contract.py --record
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nobadfind import api as api_mod, settings as settings_mod, wsearch  # noqa: E402
from nobadfind.activity import Activity  # noqa: E402
from nobadfind.governor import Decision  # noqa: E402
from nobadfind.rpc import events as events_mod, handlers, protocol  # noqa: E402
from nobadfind.rpc.events import Events  # noqa: E402
from nobadfind.store import Store  # noqa: E402

import contract_fake as fake  # noqa: E402
from schemacheck import Checker  # noqa: E402

CONTRACT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "contract")
TRANSCRIPTS = os.path.join(CONTRACT, "transcripts")
CHECK = Checker(CONTRACT)
METHODS = CHECK.doc("methods.schema.json")
EVENTS = CHECK.doc("events.schema.json")


def check(value, schema, doc="methods.schema.json"):
    errs = CHECK.errors(value, schema, doc)
    assert not errs, "\n".join(errs[:20])


def call(methods, method, params=None, conn=None, rid=1):
    req = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}
    return protocol.handle_line(json.dumps(req), methods, conn)


def engine():
    return fake.Engine()


def examples(spec):
    """The params examples of a method (its params schema may be a $ref to a shared one)."""
    s = spec["params"]
    if "$ref" in s:
        s = CHECK.resolve(s["$ref"], "methods.schema.json")[0]
    return s.get("examples") or []


# ---------- the files agree with the code ----------
def test_protocol_version_and_lists_match_the_code():
    e = engine()
    assert METHODS["protocol"] == EVENTS["protocol"] == protocol.PROTOCOL
    assert set(METHODS["methods"]) == set(e.methods)
    assert set(EVENTS["events"]) == events_mod.EVENTS
    hello = call(e.methods, "hello")["result"]
    assert hello["methods"] == sorted(METHODS["methods"]) and hello["events"] == sorted(EVENTS["events"])


def test_the_roadmap_api_surface_is_all_there():
    """ROADMAP §4: the 0.7.0 page's methods (heartbeat/page_visible/hide became ui_shown/ui_hidden and pipe
    liveness) and the bar's to_main."""
    surface = {"search", "open", "reveal", "thumbnail", "here_folder", "path_of", "forget", "status", "pause_for",
               "resume", "learned_apps", "reset_learned", "hardware", "get_settings", "set_settings", "pick_folder",
               "rescan", "wipe", "download_model", "download_photo_model", "wsearch_state", "wsearch_set",
               "use_instead_of_windows_search", "quit", "to_main", "ui_shown", "ui_hidden"}
    assert surface <= set(METHODS["methods"])


def test_settings_schema_has_every_setting():
    from nobadfind.const import DEFAULTS
    s = METHODS["$defs"]["settings"]
    assert set(s["properties"]) == set(s["required"]) == set(DEFAULTS)
    assert set(METHODS["$defs"]["settings_changes"]["properties"]) == set(DEFAULTS) - {"wsearch_prev", "turbo"}
    check(DEFAULTS, s)


def test_readme_describes_every_method_and_event():
    with open(os.path.join(CONTRACT, "README.md"), encoding="utf-8") as f:
        text = f.read()
    for name in list(METHODS["methods"]) + list(EVENTS["events"]):
        assert f"`{name}`" in text, name


def test_schemas_are_valid_json_schema():
    """Every params/result/event schema uses only what schemacheck checks; with jsonschema installed (dev PCs),
    they are also valid Draft 2020-12."""
    try:
        import jsonschema
    except ImportError:
        jsonschema = None
    schemas = [m[k] for m in METHODS["methods"].values() for k in ("params", "result")]
    schemas += list(EVENTS["events"].values()) + list(METHODS["$defs"].values()) + list(EVENTS["$defs"].values())
    for s in schemas:
        assert not CHECK.unknown_keywords(s), CHECK.unknown_keywords(s)
        if jsonschema is not None:
            jsonschema.Draft202012Validator.check_schema(s)


# ---------- every method, fake engine: examples in, schema-valid results out ----------
@pytest.mark.parametrize("name", sorted(METHODS["methods"]))
def test_each_method_example_gives_a_schema_valid_result(name):
    spec = METHODS["methods"][name]
    given = examples(spec)
    assert given, f"{name}: give params examples in the schema"
    for params in given:
        check(params, spec["params"])
        e = engine()
        r = call(e.methods, name, params, e.conn)
        assert "result" in r, (name, params, r)
        check(r["result"], spec["result"])


BAD = {
    "search": [{"text": 5}, {"text": "x", "filters": "kind=pdf"}, {"text": "x", "filters": {"kind": 5}},
               {"text": "x", "filters": {"kind": "exe"}}, {"text": "x", "filters": {"modified": "decade"}},
               {"text": "x", "filters": {"size": "huge"}}, {"text": "x", "filters": {"sort": "random"}},
               {"text": "x", "filters": {"colour": "red"}}, {"text": "x", "filters": None},
               {"text": "x" * 2001}, {"text": "x", "filters": {"folder": "x" * 2001}}],
    "to_main": [{"text": 5}, {"text": "x" * 2001}],
    "open": [{"id": "C:\\Windows\\notepad.exe"}, {"id": True}, {}, {"path": "C:\\Windows\\notepad.exe"}],
    "reveal": [{"id": "C:\\Windows"}, {"id": 1.5}, {}],
    "thumbnail": [{"id": "C:\\x.jpg"}, {}],
    "path_of": [{"id": "7"}, {}],
    "forget": [{"id": None}, {}],
    "pause_for": [{"seconds": "60"}, {"seconds": True}, {}, {"seconds": 0}, {"seconds": -60}],
    "reset_learned": [{"exe": 5}, {"exe": "x" * 261}],
    "set_settings": [{"changes": "theme=light"}, {}],
    "wipe": [{"confirm": 1}, {}],
    "quit": [{"confirm": True}, {}],
    "wsearch_set": [{"off": "yes"}, {}],
    "use_instead_of_windows_search": [{"on": 1}, {}],
    "turbo_set": [{"on": "yes"}, {"on": 1}, {}],
    "subscribe": [{"events": "status"}, {"events": [1]}, {}],
    "unsubscribe": [{"events": "status"}, {}],
    "ui_shown": [{"window": "desktop"}],
    "ui_hidden": [{"window": 3}],
}


@pytest.mark.parametrize("name", sorted(BAD))
def test_bad_params_are_refused_by_the_handler_and_the_schema(name):
    e = engine()
    for params in BAD[name]:
        assert CHECK.errors(params, METHODS["methods"][name]["params"], "methods.schema.json"), (name, params)
        r = call(e.methods, name, params, e.conn)
        assert r.get("error", {}).get("code") == protocol.INVALID_PARAMS, (name, params, r)
    assert not [c for c in e.api.calls if c[0] in ("open", "reveal", "forget", "wipe", "quit")]


def test_files_are_named_by_result_id_only():
    for m in ("open", "reveal", "thumbnail", "path_of", "forget"):
        props = CHECK.resolve(METHODS["methods"][m]["params"]["$ref"], "methods.schema.json")[0]["properties"]
        assert set(props) == {"id"} and props["id"]["type"] == "integer"


def test_wipe_and_quit_need_their_confirm_words():
    e = engine()
    assert call(e.methods, "wipe", {"confirm": "yes"})["result"]["ok"] is False
    assert call(e.methods, "quit", {"confirm": "yes"})["result"]["ok"] is False
    assert ("quit",) not in e.api.calls
    assert call(e.methods, "quit", {"confirm": "QUIT"})["result"]["ok"] is True
    assert ("quit",) in e.api.calls


# ---------- every method, the real Api: results still match the schema ----------
class Ix:
    embedder = photo_text = pindex = None
    drive_list = [{"root": "C:\\", "type": "fixed", "label": "Windows", "present": True}]

    def __init__(self):
        self.status = {"phase": "text", "files": 3, "texts": 0, "vectors": 0, "paused": "", "rate": 0, "errors": 0,
                       "plan": {}, "last_scan": 0}
        self.calls = []
        self.text_model = None

        class W:
            def set(self_):
                self.calls.append("wake")
        self.wake = W()

    def _load_embedder(self):
        pass

    def _load_photo(self):
        pass

    def models_loaded(self):
        return []

    def roots(self, drives=None):
        return ["C:\\Users\\me"]

    def worker_names(self):
        return {}

    def meaning_device(self):
        return "CPU"

    def rescan(self):
        self.calls.append("rescan")

    def stop(self, **k):
        self.calls.append("stop")

    def join(self, t=None):
        return True


class Gov:
    decision = Decision("gentle", "Gentle: you are using the PC")
    history = [{"t": 1.0, "cpu": 5.0, "gpu": None, "find_cpu": 1.0, "find_mb": 100, "level": "gentle"}]

    def pause_for(self, s):
        pass

    def resume(self):
        pass


class Apps:
    def list(self):
        return [{"exe": "game.exe", "seen": 2, "lag_events": 0, "worst_cpu": None, "worst_gpu": None,
                 "start_level": None, "last_seen": None, "reason": "Nothing learned yet"}]

    def reset(self, exe=None):
        pass


@pytest.fixture
def real(tmp_path, monkeypatch):
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    s.upsert_files([("C:/p/a.docx", "a.docx", "C:/p", ".docx", "document", 10, 1.0, 1.0, 1),
                    ("C:/p/c.jpg", "c.jpg", "C:/p", ".jpg", "image", 50000, 1.0, 1.0, 1)])
    st = settings_mod.Settings(str(tmp_path / "s.json"))
    a = api_mod.Api(s, st, Ix(), None)
    a._governor, a._activity, a._apps = Gov(), Activity(), Apps()
    a._timer = lambda secs, fn: type("T", (), {"daemon": False, "start": lambda self: None})()
    a._exit = lambda code: None
    monkeypatch.setattr(wsearch, "state", lambda: {"start": "delayed-auto", "running": True})
    monkeypatch.setattr(wsearch, "request", lambda start: False)          # never a UAC prompt from a test
    monkeypatch.setattr(api_mod, "set_autostart", lambda on: None)
    yield a
    s.close()


@pytest.mark.parametrize("name", sorted(set(METHODS["methods"]) - {"subscribe", "unsubscribe"}))
def test_the_real_api_matches_the_schema(real, name):
    conn = fake.Conn()
    ev = Events(lambda: [conn], lambda c: None, real)
    m = handlers.methods(real, ev)
    spec = METHODS["methods"][name]
    for params in examples(spec):
        r = call(m, name, params, conn)
        assert "result" in r, (name, params, r)
        check(r["result"], spec["result"])


def test_the_real_status_and_events_match_the_schema(real):
    conn = fake.Conn()
    conn.events.update(events_mod.EVENTS)
    ev = Events(lambda: [conn], lambda c: None, real)
    real._model.update(state="downloading", got=1048576, size=23 * 1048576)
    ev.step(0.0)
    ev.step(2.0)
    real._activity.listen(ev.activity)
    real._activity.add("info", "You paused NOBAD Find for 60 min")

    class Paused:
        decision = Decision("paused", "Paused: you paused NOBAD Find for 60 min")
        history = []
    real._governor = Paused()                               # a real level change, through Api.status_brief
    ev.step(2.5)
    ev.notice("The hotkey is used by another app. Pick another one in Settings.")
    ev.show("bar")
    ev.here("C:\\Users\\me")
    ev.quitting()
    seen = set()
    for msg in conn.sent:
        seen.add(msg["method"])
        check(msg, EVENTS["$defs"]["notification"], "events.schema.json")
        check(msg["params"], EVENTS["events"][msg["method"]], "events.schema.json")
    assert {"status", "status_full", "level", "download", "activity", "notice", "show", "here", "quitting"} <= seen


def test_real_wipe_without_the_word_leaves_the_index(real):
    m = handlers.methods(real, None)
    before = real._store.one("SELECT count(*) FROM files")
    assert before == 2
    assert call(m, "wipe", {"confirm": "no"})["result"]["ok"] is False
    assert real._store.one("SELECT count(*) FROM files") == before and "rescan" not in real._indexer.calls


def test_set_settings_survives_infinity_and_is_all_or_nothing(real):
    m = handlers.methods(real, None)
    r = m["set_settings"]({"changes": {"theme": "light", "content_max_mb": float("inf"), "workers": float("-inf")}})
    assert r["settings"]["content_max_mb"] == 25 and r["settings"]["workers"] == 0
    assert r["changed"] == ["theme"]


def test_settings_update_applies_nothing_if_one_value_fails(tmp_path, monkeypatch):
    st = settings_mod.Settings(str(tmp_path / "s.json"))
    real_coerce = settings_mod.coerce

    def coerce(k, v):
        if k == "workers":
            raise RuntimeError("boom")
        return real_coerce(k, v)
    monkeypatch.setattr(settings_mod, "coerce", coerce)
    with pytest.raises(RuntimeError):
        st.update({"theme": "light", "workers": 3})
    assert st.get("theme") == "dark" and not os.path.exists(tmp_path / "s.json")


def test_nan_and_infinity_are_not_json():
    m = engine().methods
    for bad in ("Infinity", "-Infinity", "NaN"):
        line = '{"jsonrpc":"2.0","id":1,"method":"pause_for","params":{"seconds":' + bad + '}}'
        assert protocol.handle_line(line, m)["error"]["code"] == protocol.PARSE_ERROR


def test_after_reply_runs_after_the_handler_or_at_once_outside_a_request():
    done = []
    m = {"x": lambda params, conn=None: (protocol.after_reply(lambda: done.append("after")), done.append("h"))[1]}
    after = []
    protocol.handle_line('{"jsonrpc":"2.0","id":1,"method":"x"}', m, None, after=after)
    assert done == ["h"] and len(after) == 1
    protocol.handle_line('{"jsonrpc":"2.0","id":1,"method":"x"}', m)      # nobody collects: run when done
    assert done == ["h", "h", "after"]
    protocol.after_reply(lambda: done.append("now"))
    assert done[-1] == "now"


# ---------- events ----------
def test_level_events_only_on_change():
    e = engine()
    e.conn.events.add("level")
    e.events.step(0.0)
    assert e.conn.sent == []                                # the first look is the baseline
    e.api.gov.level, e.api.gov.reason = "light", "Light: on battery"
    e.events.step(0.5)
    e.events.step(1.0)
    assert [m["params"] for m in e.conn.sent] == [{"level": "light", "reason": "Light: on battery", "paused": ""}]


def test_status_events_every_period_and_full_only_when_asked():
    e = engine()
    e.conn.events.add("status")
    for t in (0.0, 0.5, 1.0, 2.0, 2.5, 4.0):
        e.events.step(t)
    assert [m["method"] for m in e.conn.sent] == ["status", "status", "status"]
    e.conn.sent.clear()
    call(e.methods, "subscribe", {"events": ["status_full"]}, e.conn)
    e.events.step(6.0)
    assert sorted(m["method"] for m in e.conn.sent if "method" in m) == ["status", "status_full"]
    r = call(e.methods, "unsubscribe", {"events": ["status_full", "status"]}, e.conn)
    assert r["result"] == {"events": []}
    e.conn.sent.clear()
    e.events.step(8.0)
    assert e.conn.sent == []


def test_nobody_listening_means_no_status_work():
    e = engine()
    asked = []
    e.api.status = lambda: asked.append(1)
    e.api.status_brief = lambda: asked.append(1)
    e.events.step(0.0)
    e.events.step(5.0)
    assert asked == []


def test_download_progress_events():
    e = engine()
    e.conn.events.add("download")
    e.events.step(0.0)
    assert e.conn.sent == []
    e.api.dl["meaning"].update(state="downloading", got=2 * 1048576, size=23 * 1048576)
    e.events.step(1.0)
    e.api.dl["meaning"]["got"] = 4 * 1048576
    e.events.step(2.0)
    e.events.step(2.5)                                      # nothing new: no event
    e.api.dl["meaning"].update(state="ready", got=23 * 1048576)
    e.events.step(3.0)
    got = [m["params"] for m in e.conn.sent]
    assert [g["state"] for g in got] == ["downloading", "downloading", "ready"]
    assert got[1] == {"id": "meaning", "state": "downloading", "got_mb": 4.0, "size_mb": 23.0, "mb_s": 2.0,
                      "error": ""}
    assert got[2]["mb_s"] == 0.0


def test_activity_events_go_out_on_the_next_tick():
    e = engine()
    e.conn.events.add("activity")
    e.activity.add("kill", "Stopped a text reader using 1.2 GB; the file is skipped")
    assert e.conn.sent == []                                # the adding thread never waits on a client
    e.events.step(0.0)
    assert e.conn.sent[0]["params"] == {"t": 1763400000.0, "kind": "kill",
                                        "text": "Stopped a text reader using 1.2 GB; the file is skipped"}


def test_a_failing_listener_never_breaks_activity():
    a = Activity()
    a.listen(lambda item: 1 / 0)
    a.add("info", "x")
    assert a.recent(1)[0]["text"] == "x"


def test_notices_wait_for_a_listener():
    e = engine()
    e.events.notice("The hotkey is used by another app. Pick another one in Settings.")
    assert e.conn.sent == []
    r = call(e.methods, "subscribe", {"events": ["notice"]}, e.conn)
    assert [m["method"] for m in e.conn.sent] == ["notice"]          # delivered once, before the reply
    assert r["result"] == {"events": ["notice"]}
    e.conn.sent.clear()
    call(e.methods, "unsubscribe", {"events": ["notice"]}, e.conn)
    call(e.methods, "subscribe", {"events": ["notice"]}, e.conn)
    assert e.conn.sent == []


def test_show_to_main_and_here_events():
    e = engine()
    e.conn.events.update({"show", "here"})
    e.events.show("bar")
    call(e.methods, "to_main", {"text": "tax pdf"}, e.conn)
    e.events.here("C:\\Users\\me\\Downloads")
    assert [m["params"] for m in e.conn.sent if "method" in m] == [
        {"what": "bar", "text": None}, {"what": "main", "text": "tax pdf"}, {"path": "C:\\Users\\me\\Downloads"}]


def test_download_speed_counts_from_the_last_change():
    """Looks that find nothing new don't move the speed's starting point (that overstated the speed)."""
    e = engine()
    e.conn.events.add("download")
    e.api.dl["meaning"].update(state="downloading", got=2 * 1048576, size=23 * 1048576)
    e.events.step(1.0)
    e.events.step(1.5)
    e.events.step(2.0)
    e.api.dl["meaning"]["got"] = 4 * 1048576
    e.events.step(3.0)
    assert [m["params"]["mb_s"] for m in e.conn.sent] == [0.0, 1.0]


def test_a_notice_whose_send_fails_waits_again():
    e = engine()
    e.events.notice("first")
    e.events.notice("second")
    bad = fake.Conn()
    bad.send = lambda obj: False
    e.events.subscribe(bad, ["notice"])
    call(e.methods, "subscribe", {"events": ["notice"]}, e.conn)
    assert [m["params"]["text"] for m in e.conn.sent if m.get("method") == "notice"] == ["first", "second"]


def test_events_are_sent_outside_the_ticker_lock():
    """A client that takes long to read must not hold the lock other senders need."""
    e = engine()
    held = []
    real_send = e.conn.send
    e.conn.send = lambda obj: (held.append(e.events._lock.locked()), real_send(obj))[1]
    e.conn.events.update({"status", "level", "activity", "download", "status_full"})
    e.events.step(0.0)
    e.api.gov.level = "light"
    e.activity.add("info", "x")
    e.api.dl["photo"].update(state="downloading", got=1, size=2)
    e.events.step(2.0)
    assert len(held) >= 6 and not any(held)


# ---------- the window as the engine sees it ----------
def test_ui_shown_on_a_dropped_connection_changes_nothing():
    """The reader saw the pipe close before the queued ui_shown ran: it must not resume indexing."""
    e = engine()
    e.conn.alive = False
    call(e.methods, "ui_shown", {}, e.conn)
    assert e.conn.shown == set() and ("ui_shown",) not in e.api.calls


def test_gone_and_shown_take_turns():
    e = engine()
    call(e.methods, "ui_shown", {}, e.conn)
    e.conn.alive = False
    e.events.gone(e.conn, e.api.hide)
    assert e.api.calls == [("ui_shown",), ("hide",)]
    e.events.gone(e.conn, e.api.hide)                       # only once per connection
    assert e.api.calls.count(("hide",)) == 1


def test_pick_folder_says_when_a_dialog_is_already_open():
    e = engine()
    e.api.pick_folder = lambda: {"path": "", "busy": True}
    assert call(e.methods, "pick_folder")["result"] == {"path": "", "busy": True}
def test_ui_shown_and_hidden_reach_the_api():
    e = engine()
    call(e.methods, "ui_shown", {}, e.conn)
    call(e.methods, "ui_shown", {"window": "bar"}, e.conn)
    call(e.methods, "ui_hidden", {"window": "bar"}, e.conn)           # the bar going away changes nothing
    assert e.api.calls == [("ui_shown",)]
    call(e.methods, "ui_hidden", {}, e.conn)
    assert e.api.calls == [("ui_shown",), ("hide",)]


def test_main_window_hidden_only_when_no_client_shows_it():
    api = fake.FakeApi()
    a, b = fake.Conn(), fake.Conn()
    ev = Events(lambda: [a, b], lambda c: None, api)
    m = handlers.methods(api, ev)
    call(m, "ui_shown", {}, a)
    call(m, "ui_shown", {}, b)
    call(m, "ui_hidden", {}, a)
    assert ("hide",) not in api.calls
    assert ev.ui_gone(a) is False                           # a wasn't showing it any more
    left = Events(lambda: [a], lambda c: None, api)         # b's pipe closed, a (hidden) is left
    assert left.ui_gone(b) is True                          # the last UI showing the window went away
    call(m, "ui_shown", {}, a)
    assert left.ui_gone(b) is False


# ---------- transcripts ----------
def transcript_files():
    return sorted(f for f in os.listdir(TRANSCRIPTS) if f.endswith(".jsonl"))


def read_transcript(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def play(lines, record=False):
    """Run the send/engine lines; return the lines with every recv the engine produced in its place."""
    e = engine()
    out = []
    for line in lines:
        if "recv" in line:
            continue
        out.append(line)
        if "send" in line:
            reply = protocol.handle_line(json.dumps(line["send"]), e.methods, e.conn)
            if reply is not None:
                e.conn.sent.append(reply)
        elif "engine" in line:
            e.trigger(line["engine"])
        for msg in e.conn.sent:
            out.append({"recv": msg})
        e.conn.sent.clear()
    return out


def test_there_are_transcripts():
    assert len(transcript_files()) >= 3


@pytest.mark.parametrize("name", transcript_files())
def test_transcript_replays_exactly(name):
    lines = read_transcript(os.path.join(TRANSCRIPTS, name))
    assert play(lines) == lines, f"{name} changed: if that's intended, run python tests/test_rpc_contract.py --record"


@pytest.mark.parametrize("name", transcript_files())
def test_transcript_lines_match_the_schemas(name):
    pending = {}
    for line in read_transcript(os.path.join(TRANSCRIPTS, name)):
        assert set(line) <= {"send", "recv", "engine", "note"} and len(set(line) - {"note"}) <= 1, line
        if "send" in line:
            req = line["send"]
            check(req, METHODS["$defs"]["request"])
            pending[req["id"]] = req
        elif "recv" in line:
            msg = line["recv"]
            if "method" in msg:
                check(msg, EVENTS["$defs"]["notification"], "events.schema.json")
                check(msg["params"], EVENTS["events"][msg["method"]], "events.schema.json")
                continue
            req = pending.pop(msg["id"])
            spec = METHODS["methods"].get(req["method"])
            if "error" in msg:                  # a deliberately bad request: the schema must refuse it too
                check(msg, METHODS["$defs"]["error_response"])
                code = msg["error"]["code"]
                assert code in (protocol.METHOD_NOT_FOUND, protocol.INVALID_PARAMS), msg
                assert (spec is None) == (code == protocol.METHOD_NOT_FOUND)
                if spec is not None:
                    assert CHECK.errors(req.get("params", {}), spec["params"], "methods.schema.json"), req
            else:
                check(req.get("params", {}), spec["params"])
                check(msg, METHODS["$defs"]["response"])
                check(msg["result"], spec["result"])
    assert not pending, f"requests with no reply: {sorted(pending)}"


def record():
    for name in transcript_files():
        path = os.path.join(TRANSCRIPTS, name)
        out = play(read_transcript(path), record=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            for line in out:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
        print(f"recorded {name}: {len(out)} lines")


if __name__ == "__main__" and "--record" in sys.argv:
    record()
