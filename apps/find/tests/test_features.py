"""Places (drives), apps, OCR, the gentle/full-speed plan, call detection and the uninstall hook."""
import io
import os
import struct
import time

import pytest

from nobadfind import extract, indexer, ocr, search, winapi
from nobadfind.query import parse
from nobadfind.store import Store

DRIVES = [{"root": "C:\\", "type": "fixed", "label": "OS", "present": True},
          {"root": "E:\\", "type": "removable", "label": "SANDISK", "present": False},
          {"root": "Z:\\", "type": "network", "label": "", "present": True}]


# ---------- the question: places and apps ----------
@pytest.mark.parametrize("text,terms,place", [
    ("photos on my usb stick", [], "removable"),
    ("rent pdf on d:", ["rent"], "D:"),
    ("budget on drive e", ["budget"], "E:"),
    ("scan on e drive", ["scan"], "E:"),
    ("notes on the network drive", [], "network"),
    ("report from my laptop", ["report"], "fixed"),
    ("beach on sandisk", ["beach"], "label:sandisk"),
    ("i was on a call about rent", ["call", "rent"], ""),      # "on a" is not drive A
    ("on demand video", ["demand"], ""),
])
def test_parse_places(text, terms, place):
    q = parse(text, labels=["SanDisk"])
    assert q.terms == terms and q.place == place


@pytest.mark.parametrize("text", [
    "notes in my computer science class", "budget in the network security doc", "logs from the server",
    "photos from the share", "files on the desktop", "economic outlook report", "keynote speech",
    "blender manual", "the affinity chart"])
def test_ordinary_sentences_are_not_filters(text):
    q = parse(text)
    assert not q.place and not q.apps and not q.app_exts


def test_ambiguous_app_needs_a_cue():
    q = parse("my blender projects")
    assert q.apps == {"blender"} and q.terms == []
    assert parse("outlook files from yesterday").app_exts == {".msg", ".pst"}


def test_reset_scanned_pdfs(tmp_path):
    s = _store(tmp_path)
    s.upsert_files([("C:\\scan.pdf", "scan.pdf", "C:\\", ".pdf", "pdf", 10, 1.0, 1.0, 1),
                    ("C:\\real.pdf", "real.pdf", "C:\\", ".pdf", "pdf", 10, 1.0, 1.0, 1)])
    ids = dict(s.q("SELECT name, id FROM files WHERE ext='.pdf'"))
    s.set_text(ids["scan.pdf"], 1.0, ["scan"])
    s.set_text(ids["real.pdf"], 1.0, ["word " * 100])
    assert s.reset_scanned_pdfs() == 1
    assert [r[1] for r in s.needs_text({".pdf"}, 100)] == ["C:\\scan.pdf"]
    s.close()


def test_huge_declared_image_is_not_decoded():
    assert ocr.MAX_PIXELS <= 50_000_000 and ocr.OCR_SIDE <= 4000
    assert ocr._raw_to_gray(bytes(range(256)) * 3 * 4096, 1024, 1024, 8, "/DeviceRGB") is not None


def test_parse_apps():
    q = parse("after effects project")
    assert q.apps == {"aftereffects"} and q.app_exts == {".aep"} and q.terms == []
    q = parse("photoshop files from last week")
    assert q.app_exts == {".psd", ".psb"} and "photoshop files" in q.understood() and q.when == "last week"


def _store(tmp_path):
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    rows = [("C:\\Users\\me\\rent.txt", "rent.txt", "C:\\Users\\me", ".txt", "text", 10, 1.0, 1.0, 1),
            ("E:\\photos\\rent.psd", "rent.psd", "E:\\photos", ".psd", "image", 10, 1.0, 1.0, 1),
            ("E_x\\rent.txt", "rent.txt", "E_x", ".txt", "text", 10, 1.0, 1.0, 1),          # LIKE '_' is escaped
            ("Z:\\share\\rent.doc", "rent.doc", "Z:\\share", ".doc", "document", 10, 1.0, 1.0, 1),
            ("\\\\nas\\docs\\rent.md", "rent.md", "\\\\nas\\docs", ".md", "text", 10, 1.0, 1.0, 1)]
    s.upsert_files(rows)
    return s


def test_search_by_place_and_app(tmp_path):
    s = _store(tmp_path)

    def paths(q):
        return sorted(r["path"] for r in search.search(s, q, drives=DRIVES)["results"])
    assert paths("rent on my usb stick") == ["E:\\photos\\rent.psd"]
    assert paths("rent on sandisk") == ["E:\\photos\\rent.psd"]
    assert paths("rent on e:") == ["E:\\photos\\rent.psd"]
    assert paths("rent on the network drive") == ["Z:\\share\\rent.doc", "\\\\nas\\docs\\rent.md"]
    assert paths("rent on my pc") == ["C:\\Users\\me\\rent.txt"]
    assert paths("photoshop rent") == ["E:\\photos\\rent.psd"]
    assert paths("rent on drive q") == []                    # a drive this PC never had
    r = search.search(s, "rent on e:", drives=DRIVES)["results"][0]
    assert "on SANDISK, not connected now" in r["why"]
    s.close()


def test_needs_text_min_size(tmp_path):
    s = _store(tmp_path)
    assert s.needs_text({".txt"}, 100, min_bytes=11) == []
    assert len(s.needs_text({".txt"}, 100, min_bytes=10)) == 2
    s.close()


# ---------- indexer: roots and how hard to work ----------
class _S(dict):
    def get(self, k, d=None):
        return super().get(k, d)


def test_roots_follow_drive_settings(monkeypatch):
    drives = [{"root": "C:\\", "type": "fixed", "label": ""}, {"root": "E:\\", "type": "removable", "label": ""},
              {"root": "Z:\\", "type": "network", "label": ""}]
    ix = indexer.Indexer(store=None, settings=_S())
    assert "E:\\" not in ix.roots(drives) and "Z:\\" not in ix.roots(drives)
    ix.settings = _S(index_removable=True, index_network=True)
    assert {"E:\\", "Z:\\"} <= set(ix.roots(drives))
    ix.settings = _S(roots=["D:\\only"], index_removable=True)
    assert ix.roots(drives) == ["D:\\only"]


def test_plan_full_speed_when_away(monkeypatch):
    monkeypatch.setattr(indexer.os, "cpu_count", lambda: 12)
    monkeypatch.setattr(winapi, "is_ssd", lambda root: True)
    p = indexer.plan(_S(), ["C:\\"])
    assert p["text_workers"] == 8 and p["text_workers_idle"] == 11
    monkeypatch.setattr(winapi, "is_ssd", lambda root: False)
    p = indexer.plan(_S(), ["C:\\"])
    assert p["text_workers"] == 2 and p["text_workers_idle"] == 2       # a hard disk only seeks harder
    assert indexer.plan(_S(workers=3), ["C:\\"])["text_workers_idle"] == 3


def test_pause_during_calls(monkeypatch):
    ix = indexer.Indexer(store=None, settings=_S(pause_on_call=True))
    monkeypatch.setattr(winapi, "on_battery", lambda: False)
    monkeypatch.setattr(winapi, "busy_fullscreen", lambda: False)
    monkeypatch.setattr(winapi, "in_call", lambda: True)
    assert ix._pause_reason() == "microphone or camera in use"
    ix.settings = _S(pause_on_call=False)
    assert ix._pause_reason() == "microphone or camera in use"      # checked at most every few seconds
    ix._pause = (0.0, "")
    assert ix._pause_reason() == ""


@pytest.mark.skipif(not winapi.WIN, reason="Windows only")
def test_in_call_ignores_old_records():
    # every "in use" record is older than CALL_MAX_AGE ten days from now: none may count
    assert winapi.in_call(now=time.time() + 10 * 86400) is False


# ---------- OCR ----------
def test_gray_bmp_header():
    b = ocr.gray_bmp(5, 2, bytes(range(10)))
    assert b[:2] == b"BM" and struct.unpack_from("<I", b, 2)[0] == len(b)
    w, h, bpp = struct.unpack_from("<iiH", b, 18)[0], struct.unpack_from("<i", b, 22)[0], struct.unpack_from("<H", b, 28)[0]
    assert (w, h, bpp) == (5, -2, 8)
    assert len(b) == 14 + 40 + 1024 + 8 * 2                       # rows padded to 4 bytes


def test_raw_to_gray_bilevel_and_rgb():
    assert ocr._raw_to_gray(bytes([0b10100000]), 3, 1, 1, "/DeviceGray") == bytes([255, 0, 255])
    assert ocr._raw_to_gray(bytes([0b10100000]), 3, 1, 1, "/DeviceGray", True) == bytes([0, 255, 0])
    assert ocr._raw_to_gray(bytes([255, 255, 255, 0, 0, 0]), 2, 1, 8, "/DeviceRGB") == bytes([255, 0])
    assert ocr._raw_to_gray(b"\x00", 2, 2, 8, "/DeviceGray") is None        # too short: not guessed at
    assert ocr._raw_to_gray(b"\x00" * 8, 2, 2, 16, "/DeviceGray") is None


def test_images_skipped_without_ocr(tmp_path):
    p = tmp_path / "shot.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    fid, _mt, chunks, err = extract.work((1, str(p), ".png", 0, 10**6))
    assert chunks == [] and err == "image"


def test_broken_image_is_not_an_error(tmp_path):
    p = tmp_path / "broken.jpg"
    p.write_bytes(b"\xff\xd8 not really a jpeg" * 50)
    import faulthandler
    on = faulthandler.is_enabled()
    faulthandler.disable()          # Windows reports the decoder's own handled exception as "fatal" otherwise
    try:
        _fid, _mt, chunks, err = extract.work((1, str(p), ".jpg", 0, 10**6, True))
    finally:
        if on:
            faulthandler.enable()
    assert chunks == [] and (err is None or "OCR" in err or "language" in err)


@pytest.mark.skipif(not ocr.available(), reason="Windows OCR not available")
def test_ocr_reads_words(tmp_path):
    PIL = pytest.importorskip("PIL.Image")
    from PIL import ImageDraw, ImageFont
    im = PIL.new("RGB", (900, 160), "white")
    ImageDraw.Draw(im).text((20, 40), "Lease agreement for the flat", fill="black",
                            font=ImageFont.truetype("arial.ttf", 48))
    p = tmp_path / "scan.png"
    buf = io.BytesIO()
    im.save(buf, "PNG")
    p.write_bytes(buf.getvalue() + b"\x00" * ocr.MIN_IMAGE_BYTES)     # PNG readers ignore trailing bytes
    _fid, _mt, chunks, err = extract.work((1, str(p), ".png", 0, 10**7, True))
    assert err is None and "Lease agreement" in " ".join(chunks)


# ---------- uninstall ----------
def test_uninstall_restores_windows_search(monkeypatch, tmp_path):
    from nobadfind import app, settings as st_mod, wsearch
    import nobadfind.api as api_mod
    path = tmp_path / "s.json"
    st_mod.Settings(str(path)).update({"wsearch_prev": "delayed-auto", "autostart": True})
    monkeypatch.setattr(app, "SETTINGS_PATH", str(path))
    calls = []
    monkeypatch.setattr(api_mod, "set_autostart", lambda on: calls.append(("autostart", on)))
    monkeypatch.setattr(wsearch, "state", lambda: {"start": "disabled", "running": False})
    monkeypatch.setattr(wsearch, "request", lambda start: calls.append(("wsearch", start)) or True)
    assert app.main(["--uninstall"]) == 0
    assert calls == [("autostart", False), ("wsearch", "delayed-auto")]
    assert st_mod.Settings(str(path)).get("wsearch_prev") == ""
    # Windows Search already back on (the user did it): nothing to ask for
    calls.clear()
    st_mod.Settings(str(path)).update({"wsearch_prev": "auto"})
    monkeypatch.setattr(wsearch, "state", lambda: {"start": "auto", "running": True})
    assert app.main(["--uninstall"]) == 0 and calls == [("autostart", False)]


def test_ocr_ext_not_in_text_pass():
    from nobadfind.kinds import READABLE_EXT
    assert not (ocr.OCR_EXT & READABLE_EXT)
    assert os.path.splitext("a.PNG")[1].lower() in ocr.OCR_EXT


def test_read_texts_loop_with_real_workers(tmp_path, monkeypatch):
    from nobadfind.walker import Walker
    docs = tmp_path / "docs"
    docs.mkdir()
    for i in range(12):
        (docs / f"note{i}.txt").write_text(f"note number {i} about the garden")
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    Walker([str(docs)], gen=1, on_batch=s.upsert_files).run()
    ix = indexer.Indexer(s, _S(content=True, content_max_mb=1, ocr=False, src_mail=True))
    ix.status["plan"] = {"text_workers": 2, "text_workers_idle": 3}
    monkeypatch.setattr(ix, "_check_pause", lambda: "")
    monkeypatch.setattr(ix, "_away", lambda: False)
    ix._read_texts()
    assert ix.status["texts"] == 12 and s.needs_text({".txt"}, 10**6) == []
    assert len(search.search(s, "garden")["results"]) == 12
    s.close()


def test_ocr_then_meaning_search_in_one_process():
    """winrt ships an old C++ runtime; loading OCR first must not stop onnxruntime from loading."""
    import subprocess
    import sys
    code = "from nobadfind import ocr; ocr.available(); import onnxruntime; print('ok')"
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120,
                       cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    assert r.stdout.strip().endswith("ok"), r.stderr[-500:]
