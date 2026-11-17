import datetime as dt
import io
import os
import struct
import zipfile

import pytest

from nobadfind import embed, extract, search, settings, wsearch
from nobadfind.query import parse
from nobadfind.store import Store, fts_quote
from nobadfind.walker import Walker, profile_dir
from nobadfind.watcher import parse_notify

NOW = dt.datetime(2026, 11, 17, 10, 0)


# ---------- settings ----------
def test_settings_coerce_rejects_bad_values(tmp_path):
    assert settings.coerce("content_max_mb", "9999") == 500
    assert settings.coerce("content_max_mb", "x") == 25
    assert settings.coerce("hotkey", "ctrl+alt+k") == "ctrl+alt+k"
    assert settings.coerce("hotkey", "ctrl+`rm`") == "win+shift+space"
    assert settings.coerce("wsearch_prev", "auto; evil") == ""
    assert settings.coerce("roots", ["relative", "C:\\ok", 5]) == ["C:\\ok"]
    assert settings.coerce("semantic", "yes") is False
    s = settings.Settings(str(tmp_path / "s.json"))
    assert s.update({"content_max_mb": 10, "unknown": 1}) == ["content_max_mb"]
    assert settings.Settings(str(tmp_path / "s.json")).get("content_max_mb") == 10


# ---------- question parser ----------
@pytest.mark.parametrize("text,terms,kinds,when", [
    ("rent pdf from last week", ["rent"], {"pdf"}, "last week"),
    ("photos from the beach in march", ["beach"], {"image"}, "March 2026"),
    ("that thing i may have saved", [], set(), ""),
    ("sun photos", ["sun"], {"image"}, ""),
    ("notes from mar 2025", [], {"text"}, "March 2025"),
    ("code changed in the last 2 weeks", [], {"code"}, "last 2 weeks"),
    ("resume 2024", ["resume"], set(), "in 2024"),
])
def test_parse(text, terms, kinds, when):
    q = parse(text, NOW)
    assert q.terms == terms and q.kinds == kinds and q.when == when


def test_parse_phrases_exts_and_ranges():
    q = parse('"exact phrase" invoice .docx yesterday', NOW)
    assert q.phrases == ["exact phrase"] and q.terms == ["invoice"] and q.exts == {".docx"}
    assert dt.datetime.fromtimestamp(q.t0) == dt.datetime(2026, 11, 16)
    assert dt.datetime.fromtimestamp(q.t1) == dt.datetime(2026, 11, 17)


def test_fts_quote_keeps_syntax_out():
    assert fts_quote('a" OR name:*') == '"a"" OR name:*"'


# ---------- text extraction ----------
def _zip(path, files, compress=zipfile.ZIP_DEFLATED):
    with zipfile.ZipFile(path, "w", compress) as z:
        for n, data in files.items():
            z.writestr(n, data)


W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def test_docx_xlsx_pptx(tmp_path):
    d = tmp_path / "a.docx"
    _zip(d, {"word/document.xml": f'<w:document {W}><w:body><w:p><w:r><w:t>Lease agreement</w:t></w:r></w:p>'
                                  f'<w:p><w:r><w:t>Deposit 500</w:t></w:r></w:p></w:body></w:document>'})
    t = extract.extract(str(d), ".docx", 10**7)
    assert "Lease agreement" in t and "Deposit 500" in t
    x = tmp_path / "b.xlsx"
    _zip(x, {"xl/sharedStrings.xml": '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                                     '<si><t>Budget 2026</t></si></sst>',
             "xl/worksheets/sheet1.xml": '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                                         '<sheetData><row><c><v>0</v></c></row></sheetData></worksheet>'})
    assert "Budget 2026" in extract.extract(str(x), ".xlsx", 10**7)
    p = tmp_path / "c.pptx"
    _zip(p, {"ppt/slides/slide2.xml": '<p:sld xmlns:p="p" xmlns:a="a"><a:p><a:t>Second</a:t></a:p></p:sld>',
             "ppt/slides/slide1.xml": '<p:sld xmlns:p="p" xmlns:a="a"><a:p><a:t>First</a:t></a:p></p:sld>'})
    t = extract.extract(str(p), ".pptx", 10**7)
    assert t.index("First") < t.index("Second")


def test_zip_bomb_and_size_limits(tmp_path):
    b = tmp_path / "bomb.docx"
    _zip(b, {"word/document.xml": "<a>" + "A" * (5 * 1024 * 1024) + "</a>"})
    with pytest.raises(extract.SkipFile, match="suspicious"):
        extract.extract(str(b), ".docx", 10**8)
    big = tmp_path / "big.txt"
    big.write_bytes(b"x" * 2000)
    with pytest.raises(extract.SkipFile, match="too big"):
        extract.extract(str(big), ".txt", 1000)


def test_xml_external_entities_not_loaded(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("TOPSECRET")
    d = tmp_path / "x.docx"
    xml = (f'<?xml version="1.0"?><!DOCTYPE d [<!ENTITY e SYSTEM "file:///{secret.as_posix()}">]>'
           f'<w:document {W}><w:p><w:t>&e;</w:t></w:p></w:document>')
    _zip(d, {"word/document.xml": xml})
    assert "TOPSECRET" not in extract.extract(str(d), ".docx", 10**7)


def test_text_encodings_and_binary(tmp_path):
    u = tmp_path / "u.txt"
    u.write_bytes("héllo wörld".encode("utf-16"))
    assert extract.extract(str(u), ".txt", 10**6) == "héllo wörld"
    b = tmp_path / "b.txt"
    b.write_bytes(bytes(range(256)) * 50)
    with pytest.raises(extract.SkipFile):
        extract.extract(str(b), ".txt", 10**6)


def test_html_and_email(tmp_path):
    h = tmp_path / "p.html"
    h.write_text("<html><script>alert(1)</script><p>Visible &amp; kept</p></html>")
    t = extract.extract(str(h), ".html", 10**6)
    assert "Visible & kept" in t and "alert" not in t
    e = tmp_path / "m.eml"
    e.write_bytes(b"Subject: Deposit refund\r\nFrom: sam@example.com\r\n\r\nThe deposit will be returned.\r\n")
    t = extract.extract(str(e), ".eml", 10**6)
    assert "Deposit refund" in t and "returned" in t


def test_chunks_overlap_and_cover_everything():
    text = " ".join(f"word{i}." for i in range(800))
    cs = extract.chunks(text, size=300, overlap=50)
    assert len(cs) > 5 and "word0." in cs[0] and "word799." in cs[-1]
    assert all(len(c) <= 300 for c in cs)


def test_work_never_raises(tmp_path):
    fid, mt, chunks, err = extract.work((1, str(tmp_path / "missing.txt"), ".txt", 0, 10**6))
    assert chunks == [] and err.startswith("gone")


# ---------- store + search ----------
def _index(tmp_path, encrypt):
    docs = tmp_path / "docs"
    (docs / "sub").mkdir(parents=True)
    (docs / "rent-notes.txt").write_text("Monthly rent is due on the first. Landlord: Sam.")
    (docs / "sub" / "holiday.txt").write_text("Beach trip, sunscreen, flights.")
    (docs / "budget-2026.csv").write_text("item,amount\nrent,900\n")
    (docs / ".ssh").mkdir()
    (docs / ".ssh" / "id").write_text("PRIVATE")
    (docs / "server.pem").write_text("PRIVATE")
    s = Store(str(tmp_path / "db" / "i.db"), str(tmp_path / "db" / "i.key"), encrypt=encrypt)
    Walker([str(docs)], threads=3, gen=1, on_batch=s.upsert_files).run()
    for fid, p, ext, _size, mt in s.needs_text(extract_exts(), 10**7):
        s.set_text(*extract.work((fid, p, ext, mt, 10**7)))
    return s, docs


def extract_exts():
    from nobadfind.kinds import READABLE_EXT
    return READABLE_EXT


@pytest.mark.parametrize("encrypt", [False, True])
def test_search_names_text_and_secrets(tmp_path, encrypt):
    s, docs = _index(tmp_path, encrypt)
    names = {r["name"] for r in search.search(s, "rent")["results"]}
    assert {"rent-notes.txt", "budget-2026.csv"} <= names
    r = search.search(s, "landlords")["results"]
    assert r and r[0]["name"] == "rent-notes.txt" and "text inside matches" in r[0]["why"]
    assert "\x02" in r[0]["snippet"]
    assert search.search(s, "PRIVATE")["results"] == []          # .ssh and .pem never indexed
    assert search.search(s, "hol")["results"][0]["name"] == "holiday.txt"
    assert search.search(s, '" OR *')["results"] == []            # query syntax is data
    st = s.stats()
    assert st["encrypted"] == (encrypt and st["encrypted"])
    s.close()
    if st["encrypted"]:
        assert not open(tmp_path / "db" / "i.db", "rb").read(16).startswith(b"SQLite format 3")


def test_search_kind_and_forget(tmp_path):
    s, docs = _index(tmp_path, False)
    r = search.search(s, "spreadsheet")["results"]
    assert [x["name"] for x in r] == ["budget-2026.csv"]
    s.forget_path(str(docs / "sub"))
    assert search.search(s, "beach")["results"] == []


def test_drop_unseen_after_rescan(tmp_path):
    s, docs = _index(tmp_path, False)
    os.remove(docs / "rent-notes.txt")
    Walker([str(docs)], gen=2, on_batch=s.upsert_files).run()
    s.drop_unseen(str(docs), 2)
    assert all(r["name"] != "rent-notes.txt" for r in search.search(s, "rent")["results"])


def test_meaning_search_with_fake_embedder(tmp_path):
    import numpy as np
    s, docs = _index(tmp_path, False)

    class Fake:
        def encode(self, texts):
            return np.array([[1.0 if "beach" in t.lower() or "seaside" in t.lower() else 0.0, 0.1] + [0] * 382
                             for t in texts], np.float32)

    vi = embed.VectorIndex()
    rows = s.chunks_without_vectors()
    vecs = Fake().encode([r[1] for r in rows])
    vecs = vecs / np.linalg.norm(vecs, axis=1, keepdims=True)
    s.add_vectors([(r[0], embed.to_blob(v)) for r, v in zip(rows, vecs)])
    vi.load(s)
    r = search.search(s, "seaside", embedder=Fake(), vindex=vi)["results"]
    assert r[0]["name"] == "holiday.txt" and "text has a close meaning" in r[0]["why"]


# ---------- walker ----------
def test_walker_exclusions():
    p = profile_dir()
    w = Walker([p, "C:\\"])
    assert not w.excluded(os.path.join(p, "Documents", "a.txt"))
    assert w.excluded(os.path.join(p, ".ssh", "id_rsa"))
    assert w.excluded(os.path.join(p, "AppData", "Local", "x.txt"))
    assert w.excluded(os.path.join(os.path.dirname(p), "SomeoneElse", "Desktop", "s.txt"))
    assert w.excluded(os.path.join("C:\\", "Projects", "key.pem"))
    assert not w.excluded(os.path.join("C:\\", "Projects", "readme.md"))
    assert w.excluded(os.path.join(p, "proj", "node_modules", "x.js"))
    # a root that itself sits inside a "temp" folder: only names below the root count
    root = os.path.join(p, "AppData", "Local", "Temp", "docs")
    w2 = Walker([root])
    assert not w2.excluded(os.path.join(root, "new.txt"))
    assert w2.excluded(os.path.join(root, "cache", "x.txt"))


# ---------- watcher ----------
def test_parse_notify():
    def rec(action, name, last=False):
        b = name.encode("utf-16-le")
        size = 12 + len(b)
        size += (-size) % 4
        return struct.pack("<III", 0 if last else size, action, len(b)) + b + b"\0" * ((-(12 + len(b))) % 4)
    buf = rec(1, "a.txt") + rec(3, "sub\\b.docx", last=True)
    assert list(parse_notify(buf, len(buf))) == [(1, "a.txt"), (3, "sub\\b.docx")]
    assert list(parse_notify(b"\x01\x02", 2)) == []


# ---------- Windows Search switch ----------
def test_wsearch_parse_and_helper_refuses_unknown():
    qc = "SERVICE_NAME: WSearch\n        START_TYPE         : 2   AUTO_START  (DELAYED)\n"
    assert wsearch.parse_qc(qc) == "delayed-auto"
    assert wsearch.parse_qc("START_TYPE : 4   DISABLED") == "disabled"
    assert wsearch.parse_query("STATE              : 4  RUNNING") == "running"
    assert wsearch.helper_main("auto & calc") == 2
    with pytest.raises(ValueError):
        wsearch.request("boot")


# ---------- model download ----------
def test_model_download_rejects_wrong_checksum(tmp_path, monkeypatch):
    class Resp(io.BytesIO):
        def geturl(self):
            return "https://huggingface.co/x"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(embed, "MODEL_FILES", {"tokenizer.json": ("tokenizer.json", 4, "0" * 64)})
    monkeypatch.setattr(embed.urllib.request, "urlopen", lambda *a, **k: Resp(b"evil"))
    with pytest.raises(IOError, match="checksum"):
        embed.download_model(str(tmp_path))
    assert not os.listdir(tmp_path)
