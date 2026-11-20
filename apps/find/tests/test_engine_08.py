"""0.8.0 engine pieces: Open with, starting the UI, the tray."""
from nobadfind import api as api_mod, app, winapi

from test_api_status import make


def _file(s, tmp_path):
    f = tmp_path / "note.txt"
    f.write_text("hi")
    s.upsert_files([(str(f), "note.txt", str(tmp_path), ".txt", "text", 2, 1.0, 1.0, 1)])
    return s.one("SELECT id FROM files WHERE path=?", (str(f),)), str(f)


def test_open_with_starts_the_picker_outside_the_job_by_result_id(tmp_path, monkeypatch):
    a, s = make(tmp_path)
    fid, path = _file(s, tmp_path)
    started = []
    monkeypatch.setattr(api_mod.winapi, "start_outside_job", lambda argv: started.append(argv))
    assert a.open_with(fid) == {"ok": True, "error": ""}
    assert started == [winapi.self_command("--open-with", path)]
    assert a.open_with(fid + 999)["ok"] is False and len(started) == 1     # an id that isn't there
    assert a.open_with(r"C:\x.txt")["ok"] is False                          # never a path
    s.close()


def test_open_with_helper_shows_windows_picker(monkeypatch):
    seen = []
    monkeypatch.setattr(winapi, "open_with_dialog", lambda p: seen.append(p) or 0)
    assert app.main(["--open-with", r"C:\a b\c.txt"]) == 0
    assert seen == [r"C:\a b\c.txt"]


def test_start_outside_job_breaks_away_with_an_argument_list(monkeypatch):
    calls = []

    class P:
        def __init__(self, argv, **kw):
            calls.append((argv, kw))
    monkeypatch.setattr(winapi.subprocess, "Popen", P)
    winapi.start_outside_job([r"C:\x\ui.exe", "--page", "settings"])
    argv, kw = calls[0]
    assert argv == [r"C:\x\ui.exe", "--page", "settings"] and not kw.get("shell")
    assert kw["creationflags"] & winapi.CREATE_BREAKAWAY_FROM_JOB


def test_open_with_runs_the_picker_with_exec():
    assert winapi.OAIF_EXEC == 0x4
