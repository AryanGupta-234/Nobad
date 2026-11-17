"""Folders typed in the question, "here", size and order words, and the filter bar."""
import pytest

from nobadfind import search
from nobadfind.query import parse
from nobadfind.store import Store

DIRS = {r"C:\Users\me\Downloads", r"C:\Users\me\Downloads\Tax 2024", r"C:\My Files", "C:\\", r"\\nas\share",
        r"D:\Work"}


def is_dir(p):
    return p in DIRS or p.rstrip("\\") in {d.rstrip("\\") for d in DIRS}


@pytest.mark.parametrize("text,path,terms", [
    (r"pdf in C:\Users\me\Downloads", r"C:\Users\me\Downloads", []),
    (r"pdf in C:\Users\me\Downloads\Tax 2024 from march", r"C:\Users\me\Downloads\Tax 2024", []),   # spaces
    (r'invoices "C:\My Files"', r"C:\My Files", ["invoices"]),
    (r"everything in \\nas\share", r"\\nas\share", []),
    (r"budget D:/Nope", "", ["budget"]),                             # looks like a path, isn't a folder
    (r"report C:\Nope\x", "", ["report"]),                           # not a folder: left out, with a note
    (r"files on C:\ last week", "C:\\", []),
])
def test_paths_in_the_question(text, path, terms):
    q = parse(text, is_dir=is_dir)
    assert q.path == path and q.terms == terms
    if "Nope" in text:  # both "not a folder" cases
        assert q.notes


def test_path_spelled_with_forward_slashes():
    q = parse("budget D:/Work", is_dir=lambda p: p.replace("/", "\\") in DIRS)
    assert q.path == "D:\\Work" and q.terms == ["budget"]           # stored like the index stores paths


@pytest.mark.parametrize("text,terms,here", [
    ("here comes the sun", ["here", "comes", "sun"], False),     # a song, not a folder
    ("list", ["list"], False),                                    # a file called list
    ("search", ["search"], False),
    ("pdf from here", [], True),
])
def test_review_cases(text, terms, here):
    q = parse(text)
    assert q.terms == terms and q.here == here


def test_newest_alone_lists_and_odd_filters_are_ignored(tmp_path):
    s = _store(tmp_path)
    assert _names(search.search(s, "newest"))[0] == "rent-notes.txt"
    r = search.search(s, "rent", filters={"kind": ["pdf"], "size": {"x": 1}, "folder": 7, 3: "pdf"})
    assert set(_names(r)) == {"rent.pdf", "rent-notes.txt"}
    assert parse("less than 5 m").max_size is None and parse("under 5 mb").max_size == 5 << 20
    s.close()


@pytest.mark.parametrize("text,here,sizes,sort,terms", [
    ("list all pdf here", True, (None, None), "", []),
    ("photos in this folder", True, (None, None), "", []),
    ("videos bigger than 1.5 gb", False, (int(1.5 * 2 ** 30), None), "", []),
    ("notes under 20kb newest", False, (None, 20 * 1024), "newest", []),
    ("big videos", False, (100 << 20, None), "", []),
    ("latest invoice", False, (None, None), "newest", ["invoice"]),
    ("where is my cv", False, (None, None), "", ["cv"]),             # "where" is not "here"
])
def test_here_size_and_order(text, here, sizes, sort, terms):
    q = parse(text)
    assert q.here == here and (q.min_size, q.max_size) == sizes and q.sort == sort and q.terms == terms


def _store(tmp_path):
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    d = r"C:\Users\me\Downloads"
    s.upsert_files([
        (d + r"\a.pdf", "a.pdf", d, ".pdf", "pdf", 5 << 20, 100.0, 100.0, 1),
        (d + r"\Tax 2024\b.pdf", "b.pdf", d + r"\Tax 2024", ".pdf", "pdf", 1000, 300.0, 300.0, 1),
        (d + r"\c.txt", "c.txt", d, ".txt", "text", 10, 200.0, 200.0, 1),
        (r"C:\Users\me\Downloads2\d.pdf", "d.pdf", r"C:\Users\me\Downloads2", ".pdf", "pdf", 10, 400.0, 400.0, 1),
        (r"C:\Other\rent.pdf", "rent.pdf", r"C:\Other", ".pdf", "pdf", 200 << 20, 50.0, 50.0, 1),
        (d + r"\rent-notes.txt", "rent-notes.txt", d, ".txt", "text", 10, 500.0, 500.0, 1),
    ])
    return s


def _names(r):
    return [x["name"] for x in r["results"]]


def test_list_all_pdf_here(tmp_path):
    s = _store(tmp_path)
    here = r"C:\Users\me\Downloads"
    r = search.search(s, "list all pdf here", here=here, is_dir=is_dir)
    assert _names(r) == ["b.pdf", "a.pdf"]                      # newest first; not Downloads2
    r = search.search(s, "list all pdf here", here="", is_dir=is_dir)
    assert r["notes"] and "File Explorer" in r["notes"][0]      # no folder to go on: says how
    s.close()


def test_typed_path_and_sort(tmp_path):
    s = _store(tmp_path)
    r = search.search(s, r"pdf in C:\Users\me\Downloads oldest", is_dir=is_dir)
    assert _names(r) == ["a.pdf", "b.pdf"]
    r = search.search(s, "rent largest", is_dir=is_dir)
    assert _names(r)[0] == "rent.pdf"                           # matches, biggest first
    s.close()


def test_filter_bar(tmp_path):
    s = _store(tmp_path)
    now = 1000.0
    r = search.search(s, "", filters={"kind": "pdf", "folder": r"C:\Users\me\Downloads", "sort": "name"}, now=now)
    assert _names(r) == ["a.pdf", "b.pdf"]
    r = search.search(s, "", filters={"size": "large"}, now=now)
    assert _names(r) == ["rent.pdf"] and "over 100 MB" in r["understood"]
    r = search.search(s, "rent", filters={"kind": "text"}, now=now)
    assert _names(r) == ["rent-notes.txt"]
    # the page is untrusted: nonsense values are ignored, not used
    r = search.search(s, "rent", filters={"kind": "x'; DROP TABLE files", "folder": "relative\\path",
                                         "size": 5, "sort": "evil", "modified": None}, now=now)
    assert set(_names(r)) == {"rent.pdf", "rent-notes.txt"}
    s.close()


def test_listing_says_when_there_is_more(tmp_path, monkeypatch):
    s = _store(tmp_path)
    monkeypatch.setattr(search, "LIST_LIMIT", 2)
    r = search.search(s, "", filters={"folder": r"C:\Users\me\Downloads"})
    assert len(r["results"]) == 2 and r["more"] is True
    s.close()


def test_network_paths_never_touch_the_network(tmp_path, monkeypatch):
    s = _store(tmp_path)
    s.upsert_files([(r"\\nas\share\docs", "docs", r"\\nas\share", "", "folder", 0, 1.0, 1.0, 1),
                    (r"\\nas\share\docs\rent.pdf", "rent.pdf", r"\\nas\share\docs", ".pdf", "pdf", 1, 1.0, 1.0, 1)])
    touched = []
    monkeypatch.setattr(search.os.path, "isdir", lambda p: touched.append(p) or True)
    drives = [{"root": "C:\\", "type": "fixed", "label": "", "present": True}]
    check = search.folder_checker(s, drives, roots=[r"\\nas\share"])
    assert check(r"\\nas\share") and check(r"\\nas\share\docs")      # a folder to search / an indexed folder
    assert not check(r"\\evil-host\x")                                # unknown server: not looked up
    assert check(r"C:\Users")                                         # this PC's own drive: checked on disk
    assert touched == [r"C:\Users"]
    r = search.search(s, r"pdf in \\nas\share\docs", drives=drives, roots=[r"\\nas\share"])
    assert [x["name"] for x in r["results"]] == ["rent.pdf"]
    r = search.search(s, r"pdf in \\evil-host\x", drives=drives)
    assert r["notes"] and touched == [r"C:\Users"]
    s.close()
