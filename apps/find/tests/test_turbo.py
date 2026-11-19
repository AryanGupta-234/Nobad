"""The engine side of the turbo index (nobadfind/turbo.py) over a fake helper link: no pipe, no UAC prompt."""
import json
import os
import sys
import threading

import pytest

from nobadfind import scope, turbo
from nobadfind.const import DEFAULTS
from nobadfind.settings import Settings
from nobadfind.store import Store

PROF = scope.profile_dir()
DRIVE = os.path.splitdrive(PROF)[0] + "\\"


class Link:
    """What the helper would do, scripted: answers scan requests with the rows given."""

    def __init__(self, t, drives=(DRIVE,), rows=None, full=True, fail=None):
        self.t, self.sent, self.alive = t, [], True
        self.rows, self.full, self.fail = rows if rows is not None else {}, full, fail
        self.t.on_message({"t": "hello", "protocol": 1, "pid": 4242,
                           "volumes": [{"drive": d, "ntfs": True} for d in drives]})

    def send(self, msg):
        self.sent.append(msg)
        if msg["t"] == "scan":
            d = msg["drive"]
            threading.Thread(target=self._answer, args=(d,), daemon=True).start()

    def _answer(self, d):
        if self.fail:
            self.t.on_message({"t": "failed", "drive": d, "error": self.fail})
            return
        if self.full:
            self.t.on_message({"t": "rows", "drive": d, "rows": self.rows.get(d, [])})
        self.t.on_message({"t": "scanned", "drive": d, "full": self.full, "files": len(self.rows.get(d, [])),
                           "journal": 77, "usn": 1000, "usn_ok": True})

    def close(self):
        self.alive = False


class Ix:
    def __init__(self, roots):
        self._roots, self.changes, self.rescans = roots, [], 0

    def roots(self, drives=None):
        return list(self._roots)

    def rules(self):
        return scope.Rules.from_settings(DEFAULTS)

    def _on_changes(self, root, paths):
        self.changes.append(sorted(paths))

    def rescan(self):
        self.rescans += 1


@pytest.fixture
def env(tmp_path):
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    st = Settings(str(tmp_path / "s.json"))
    pushed = []
    ix = Ix([PROF, DRIVE])
    t = turbo.Turbo(st, s, ix, push=pushed.append, ntfs_drive=lambda d: d.upper() == DRIVE.upper(),
                    drives=lambda: [{"root": DRIVE, "type": "fixed", "label": ""}])
    yield t, s, st, ix, pushed
    s.close()


def start(t, **kw):
    holder = {}

    def launch():
        holder["link"] = Link(t, **kw)
        return holder["link"]
    t._launch = launch
    r = t.turn_on()
    return r, holder.get("link")


def test_off_by_default_and_state_shape(env):
    t, _s, st, _ix, _p = env
    assert DEFAULTS["turbo"] is False
    s = t.state()
    assert s == {"available": True, "enabled": False, "running": False,
                 "volumes": [{"drive": DRIVE, "ntfs": True, "files": 0, "usn_ok": False, "last_scan": None}],
                 "error": ""}


def test_turning_on_saves_the_setting_and_sends_the_scope(env):
    t, _s, st, _ix, pushed = env
    r, link = start(t)
    assert r == {"ok": True, "error": ""}
    assert st.get("turbo") is True and t.state()["running"] is True
    cfg = [m for m in link.sent if m["t"] == "config"][0]
    assert cfg["roots"] == [PROF, DRIVE] and cfg["include_secrets"] is False
    assert pushed and pushed[-1]["running"] is True


def test_uac_declined_leaves_it_off_with_a_sentence(env):
    t, _s, st, _ix, _p = env

    def no():
        raise turbo.Declined()
    t._launch = no
    r = t.turn_on()
    assert r["ok"] is False and "permission" in r["error"].lower()
    assert st.get("turbo") is False and t.state()["running"] is False


def test_turning_off_ends_the_helper(env):
    t, _s, st, _ix, _p = env
    _r, link = start(t)
    assert t.turn_off() == {"ok": True, "error": ""}
    assert not link.alive and st.get("turbo") is False and not t.state()["running"]


def test_scan_feeds_rows_through_the_engine_rules(env):
    t, s, _st, _ix, _p = env
    keep = os.path.join(PROF, "Documents", "a.txt")
    rows = {DRIVE: [[keep, 0, 5, 1.0, 1.0],
                    [os.path.join(PROF, "Documents"), 1, 0, 1.0, 1.0],
                    [os.path.join(os.path.dirname(PROF), "Bob", "x.txt"), 0, 1, 1.0, 1.0],   # the engine drops it too
                    [os.path.join(PROF, ".ssh", "id_rsa"), 0, 1, 1.0, 1.0],                   # secrets off
                    ["relative\\path", 0, 1, 1.0, 1.0], [5, 0, 1, 1.0, 1.0], [keep], [keep, 0, -1, 1.0, 1.0]]}
    start(t, rows=rows)
    got = []
    full, caught = t.scan([PROF, DRIVE], 3, got.extend, threading.Event())
    assert full == {DRIVE} and caught == set()
    assert [(r[0], r[4], r[5], r[8]) for r in got] == [(keep, "text", 5, 3), (os.path.join(PROF, "Documents"),
                                                                                  "folder", 0, 3)]
    v = t.state()["volumes"][0]
    assert v["files"] == 2 and v["usn_ok"] is True and v["last_scan"]
    saved = json.loads(s.meta("turbo"))[DRIVE]
    assert saved["journal"] == 77 and saved["usn"] == 1000


def test_next_scan_catches_up_from_the_saved_place(env):
    t, s, _st, _ix, _p = env
    _r, link = start(t)
    t.scan([PROF, DRIVE], 1, lambda rows: None, threading.Event())
    link.full = False
    link.sent.clear()
    full, caught = t.scan([PROF, DRIVE], 2, lambda rows: None, threading.Event())
    assert caught == {DRIVE} and full == set()
    assert [m for m in link.sent if m["t"] == "scan"][0]["since"] == {"journal": 77, "usn": 1000}


def test_a_changed_scope_reads_everything_again(env):
    t, s, st, ix, _p = env
    _r, link = start(t)
    t.scan([PROF, DRIVE], 1, lambda rows: None, threading.Event())
    st.update({"include_system": False})
    link.sent.clear()
    t.scan([PROF, DRIVE], 2, lambda rows: None, threading.Event())
    assert [m for m in link.sent if m["t"] == "scan"][0]["since"] is None


def test_a_failed_drive_falls_back_to_the_walk(env):
    t, _s, _st, _ix, _p = env
    start(t, fail="OSError 5")
    full, caught = t.scan([PROF, DRIVE], 1, lambda rows: None, threading.Event())
    assert full == caught == set()
    assert "OSError" not in t.state()["error"] and t.state()["error"]


def test_no_helper_means_no_cover(env):
    t, _s, _st, _ix, _p = env
    assert t.scan([PROF, DRIVE], 1, lambda rows: None, threading.Event()) == (set(), set())


def test_changes_go_to_the_indexer_and_bad_ones_are_dropped(env):
    t, _s, _st, ix, _p = env
    start(t)
    a = os.path.join(PROF, "new.txt")
    t.on_message({"t": "changes", "drive": DRIVE, "paths": [a, 5, "Z:\\elsewhere.txt", "rel"]})
    assert ix.changes == [[a]]


def test_journal_lost_rescans(env):
    t, _s, _st, ix, pushed = env
    start(t)
    t.scan([PROF, DRIVE], 1, lambda rows: None, threading.Event())
    t.on_message({"t": "journal", "drive": DRIVE, "usn_ok": False, "error": "reset"})
    assert ix.rescans == 1 and t.state()["volumes"][0]["usn_ok"] is False
    assert pushed[-1]["volumes"][0]["usn_ok"] is False


def test_helper_gone_is_reported_and_follows_nothing(env):
    t, _s, _st, _ix, _p = env
    start(t)
    t.scan([PROF, DRIVE], 1, lambda rows: None, threading.Event())
    assert t.follows(os.path.join(PROF, "x"))
    t.link_closed()
    s = t.state()
    assert s["running"] is False and s["enabled"] is True and s["error"]
    assert not t.follows(os.path.join(PROF, "x"))


def test_ensure_asks_once_per_run(env):
    t, _s, st, _ix, _p = env
    st.update({"turbo": True})
    asked = []

    def no():
        asked.append(1)
        raise turbo.Declined()
    t._launch = no
    t.ensure()
    t.ensure()
    assert asked == [1]
    assert st.get("turbo") is True                     # declined at start-up: asked again next run


def test_unknown_and_malformed_messages_are_ignored(env):
    t, _s, _st, _ix, _p = env
    start(t)
    for m in ({"t": "nope"}, {"t": "rows", "drive": DRIVE, "rows": "x"}, {"t": "scanned", "drive": 5},
              {"t": "changes", "drive": DRIVE, "paths": None}, {}):
        t.on_message(m)
    assert t.state()["running"] is True


def test_not_available_without_ntfs(tmp_path):
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    t = turbo.Turbo(Settings(str(tmp_path / "s.json")), s, Ix([PROF]), ntfs_drive=lambda d: False,
                    drives=lambda: [{"root": DRIVE, "type": "fixed", "label": ""}])
    assert t.state()["available"] is False
    r = t.turn_on()
    assert r["ok"] is False and r["error"]
    s.close()


# ---------- the real pieces against the contract ----------
def test_state_matches_the_contract_schema(env):
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from schemacheck import Checker
    t, _s, _st, _ix, _p = env
    chk = Checker(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "contract"))
    schema = chk.doc("methods.schema.json")["$defs"]["turbo_state"]
    for state in (t.state(), (start(t), t.state())[1]):
        assert not chk.errors(state, schema, "methods.schema.json")


def test_the_command_line_takes_only_the_fixed_words():
    from nobadfind import app
    assert app.parse_args(["--turbo", "serve"]).turbo == "serve"
    assert app.parse_args(["--turbo", "selftest"]).turbo == "selftest"
    for bad in ("delete", "serve;calc", ""):
        with pytest.raises(SystemExit):
            app.parse_args(["--turbo", bad])


# ---------- the indexer uses turbo where it can ----------
class FakeTurbo:
    def __init__(self, read=(), caught=()):
        self.read, self.caught, self.calls, self.forgot = set(read), set(caught), [], 0

    def scan(self, roots, gen, on_rows, stop):
        self.calls.append(list(roots))
        return set(self.read), set(self.caught)

    def ensure(self):
        pass

    def forget_place(self):
        self.forgot += 1

    def follows(self, path):
        return turbo.drive_of(path) in self.read | self.caught


def _indexer(tmp_path, monkeypatch, fake):
    from nobadfind import indexer, winapi
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    root = tmp_path / "r"
    root.mkdir()
    (root / "walked.txt").write_text("a")
    drive = turbo.drive_of(str(root))
    monkeypatch.setattr(winapi, "drives", lambda: [{"root": drive, "type": "fixed", "label": ""}])

    class S(dict):
        def get(self, k, d=None):
            return super().get(k, DEFAULTS.get(k) if d is None else d)
    ix = indexer.Indexer(s, S(scope="custom", roots=[str(root)]))
    ix.status["plan"] = {"walk_threads": 2}
    ix.turbo = fake
    return ix, s, root, drive


def test_a_drive_read_by_turbo_isnt_walked(tmp_path, monkeypatch):
    fake = FakeTurbo()
    ix, s, root, drive = _indexer(tmp_path, monkeypatch, fake)
    fake.read = {drive}
    ix._scan_names()
    assert fake.calls == [[str(root)]]
    assert s.one("SELECT count(*) FROM files WHERE name='walked.txt'") == 0      # turbo had it (it sent nothing)
    s.close()


def test_a_drive_turbo_caught_up_keeps_its_rows(tmp_path, monkeypatch):
    fake = FakeTurbo()
    ix, s, root, drive = _indexer(tmp_path, monkeypatch, fake)
    old = os.path.join(str(root), "old.txt")
    s.upsert_files([(old, "old.txt", str(root), ".txt", "text", 1, 1.0, 1.0, 1)])
    s.set_meta("gen", 1)
    fake.caught = {drive}
    ix._scan_names()
    assert s.one("SELECT count(*) FROM files WHERE name='old.txt'") == 1        # not read again, not dropped
    s.close()


def test_without_turbo_cover_the_walk_runs(tmp_path, monkeypatch):
    ix, s, root, drive = _indexer(tmp_path, monkeypatch, FakeTurbo())
    ix._scan_names()
    assert s.one("SELECT count(*) FROM files WHERE name='walked.txt'") == 1
    s.close()


def test_rescan_forgets_the_journal_place_and_overflow_trusts_the_journal(tmp_path, monkeypatch):
    fake = FakeTurbo()
    ix, s, root, drive = _indexer(tmp_path, monkeypatch, fake)
    ix.rescan()
    assert fake.forgot == 1
    s.set_meta("last_scan", 123)
    fake.read = {drive}
    ix._on_overflow(str(root))
    assert s.meta("last_scan") == "123"                 # the journal has every change: no rescan
    fake.read = set()
    ix._on_overflow(str(root))
    assert s.meta("last_scan") == "0"
    s.close()


def test_a_catch_up_is_at_most_a_day_after_a_full_read(env):
    t, s, _st, _ix, _p = env
    now = [1_000_000.0]
    t._clock = lambda: now[0]
    _r, link = start(t)
    t.scan([PROF, DRIVE], 1, lambda rows: None, threading.Event())
    link.full = False
    now[0] += turbo.FULL_EVERY + 1
    link.sent.clear()
    t.scan([PROF, DRIVE], 2, lambda rows: None, threading.Event())
    assert [m for m in link.sent if m["t"] == "scan"][0]["since"] is None


def test_helper_command_line(monkeypatch):
    import subprocess
    import sys
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert turbo.helper_argv() == [sys.executable, "--turbo", "serve"]
    monkeypatch.setattr(sys, "frozen", False)
    argv = turbo.helper_argv()
    assert argv[:3] == [sys.executable, "-I", "-c"] and argv[-2:] == ["--turbo", "serve"]
    # from source, isolated (-I: no user site, no current folder), the package found by an explicit path
    out = subprocess.run(argv[:4] + ["--version"], capture_output=True, text=True, timeout=120,
                         cwd=os.path.expanduser("~"))
    assert out.returncode == 0 and "NOBAD Find" in out.stdout


# ---------- security review of #79: the real pipe (Windows, no elevation needed) ----------
win = pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows named pipes")


@pytest.fixture
def pipe_pair():
    import ctypes
    from nobadfind import ntfs
    from nobadfind.rpc import server as srv
    sid = srv.user_sid()
    name = ntfs.pipe_name(sid, os.getpid()) + f"-test-{threading.get_ident()}"
    h = turbo.make_pipe(name, sid)
    k = ntfs._k32()
    c = k.CreateFileW(name, ntfs.GENERIC_READ | 0x40000000, 0, None, ntfs.OPEN_EXISTING, 0x00100000 | 0x00010000, None)
    assert c and c != ntfs.INVALID_HANDLE, ctypes.get_last_error()
    yield h, c, sid
    k.CloseHandle(c)
    k.CloseHandle(h)


@win
def test_the_pipe_dacl_is_this_user_only(pipe_pair):
    import ctypes
    from ctypes import wintypes
    h, _c, sid = pipe_pair
    a = ctypes.WinDLL("advapi32", use_last_error=True)
    a.GetSecurityInfo.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p,
                                  ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    a.GetSecurityInfo.restype = wintypes.DWORD
    a.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(wintypes.LPWSTR), ctypes.c_void_p]
    dacl, sd = ctypes.c_void_p(), ctypes.c_void_p()
    assert a.GetSecurityInfo(h, 6, 4, None, None, ctypes.byref(dacl), None, ctypes.byref(sd)) == 0
    text = wintypes.LPWSTR()
    assert a.ConvertSecurityDescriptorToStringSecurityDescriptorW(sd, 1, 4, ctypes.byref(text), None)
    d = text.value
    ctypes.windll.kernel32.LocalFree(sd)
    assert d.startswith("D:P")                                       # protected: nothing inherited
    allows = [ace for ace in d[3:].strip("()").split(")(") if ace.startswith("A;")]
    assert len(allows) == 1 and allows[0].endswith(";" + sid)      # one allow: this user
    assert any(ace.startswith("D;") and ace.endswith(";NU") for ace in d[3:].strip("()").split(")("))
    for other in (";WD", ";BA", ";SY", ";AU", ";BU", ";AN"):
        assert other not in d, other


@win
def test_the_engine_checks_the_clients_pid_and_session(pipe_pair):
    from nobadfind import ntfs
    h, _c, _sid = pipe_pair
    me, sess = os.getpid(), ntfs.session_of(os.getpid())
    assert turbo.client_ok(h, me, sess)
    assert not turbo.client_ok(h, me + 4, sess)                     # not the process the engine started
    assert not turbo.client_ok(h, me, sess + 1)                     # another session


@win
def test_the_helper_checks_the_servers_pid_and_session(pipe_pair):
    from nobadfind import ntfs
    _h, c, _sid = pipe_pair
    me, sess = os.getpid(), ntfs.session_of(os.getpid())
    assert ntfs.server_ok(c, me, sess)
    assert not ntfs.server_ok(c, me + 4, sess)                      # not its parent
    assert not ntfs.server_ok(c, me, sess + 1)


@win
def test_only_one_pipe_of_that_name(pipe_pair):
    """FILE_FLAG_FIRST_PIPE_INSTANCE and one instance: nobody can take the name next to the engine."""
    from nobadfind import ntfs
    h, _c, sid = pipe_pair
    name = ntfs.pipe_name(sid, os.getpid()) + f"-test-{threading.get_ident()}"
    with pytest.raises(OSError):
        turbo.make_pipe(name, sid)


def test_from_source_the_engine_asks_for_no_permission_without_the_dev_switch(tmp_path, monkeypatch):
    from nobadfind import ntfs
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.delenv(ntfs.DEV_ENV, raising=False)
    asked = []
    monkeypatch.setattr(turbo, "start_elevated", lambda argv: asked.append(argv))
    monkeypatch.setattr(turbo, "make_pipe", lambda name, sid: asked.append(name))
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    t = turbo.Turbo(Settings(str(tmp_path / "s.json")), s, Ix([PROF]), ntfs_drive=lambda d: True,
                    drives=lambda: [{"root": DRIVE, "type": "fixed", "label": ""}])
    r = t.turn_on()
    assert r["ok"] is False and ntfs.DEV_ENV in r["error"] and asked == []
    s.close()
