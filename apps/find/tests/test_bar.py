"""The quick find bar: placement, the 8-result cap, its own hotkey id, and its page."""
import re
from pathlib import Path

import pytest

from nobadfind import bar, hotkey, winapi

UI = Path(__file__).resolve().parent.parent / "nobadfind" / "ui"


def test_place_centers_in_upper_third():
    assert bar.place((0, 0, 1920, 1040)) == (640, 314)


def test_place_on_second_monitor():
    assert bar.place((1920, 0, 3840, 1080)) == (2560, 328)


class _Api:
    def __init__(self, n):
        self.n = n

    def search(self, text, filters=None):
        rows = [{"id": i, "path": f"C:/x/f{i}.txt", "name": f"f{i}.txt", "dir": "C:/x", "kind": "text",
                 "size": 1, "snippet": "secret"} for i in range(self.n)]
        return {"results": rows, "understood": []}


def test_bar_search_caps_at_8():
    out = bar.BarApi(_Api(30), None, lambda t: None).search("f")
    assert len(out) == 8
    assert set(out[0]) == {"id", "name", "folder", "kind"}
    assert out[0]["folder"] == "C:/x"
    assert bar.BarApi(_Api(3), None, lambda t: None).search("f") != []
    assert bar.BarApi(_Api(3), None, lambda t: None).search(5) == []


class _FakeUser32:
    def __init__(self, fail_ids):
        self.fail_ids, self.registered = fail_ids, []

    def RegisterHotKey(self, hwnd, hk_id, mods, vk):
        self.registered.append(hk_id)
        return 0 if hk_id in self.fail_ids else 1

    def GetMessageW(self, *a):
        return 0

    def UnregisterHotKey(self, *a):
        return 1


@pytest.mark.skipif(not winapi.WIN, reason="Windows only")
def test_two_hotkeys_use_different_ids(monkeypatch):
    fake = _FakeUser32(set())
    monkeypatch.setattr(hotkey, "_user32", lambda: fake)
    a, b = hotkey.Hotkey("win+shift+space", lambda: None), hotkey.Hotkey("ctrl+alt+space", lambda: None, hk_id=2)
    assert a.start() and b.start()
    assert sorted(fake.registered) == [1, 2]


@pytest.mark.skipif(not winapi.WIN, reason="Windows only")
def test_bar_hotkey_taken_keeps_main_hotkey(monkeypatch):
    fake = _FakeUser32({2})
    monkeypatch.setattr(hotkey, "_user32", lambda: fake)
    notices = []
    main = hotkey.Hotkey("win+shift+space", lambda: None)
    assert main.start()
    bar_hk = bar.start_hotkey("ctrl+alt+space", lambda: None, notices.append)
    assert main.ok is True and bar_hk.ok is False
    assert len(notices) == 1 and "quick find bar" in notices[0].lower()


def test_bar_html_csp_and_no_inline():
    html = (UI / "bar.html").read_text(encoding="utf-8")
    main = (UI / "index.html").read_text(encoding="utf-8")
    csp = lambda h: re.search(r'Content-Security-Policy" content="([^"]+)"', h).group(1)
    assert csp(html).startswith("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:")
    assert "unsafe" not in csp(html)
    for m in re.finditer(r"<script\b([^>]*)>", html, re.IGNORECASE):
        assert "src=" in m.group(1)
    assert not re.search(r"\son[a-z]+\s*=", html, re.IGNORECASE) and 'style="' not in html
    js = (UI / "bar.js").read_text(encoding="utf-8")
    assert "heartbeat" not in js and "page_visible" not in js      # the watchdog watches the main window only
    assert "innerHTML" not in js                                   # file names are untrusted: text nodes only
    assert "bar.css" in html and "bar.js" in html and "app.css" in html
    # pywebview wraps every call it sends back to a page in `var value` / `var keys`: a page-level const or let
    # of the same name makes that a SyntaxError and every answer from Python is silently lost
    top_level = [ln for ln in js.splitlines() if re.match(r"(?:const|let|var)\s", ln)]
    assert top_level
    for ln in top_level:
        assert not re.search(r"(?:keys|value)\s*=", ln), ln
    assert main  # the main page is untouched by the bar
