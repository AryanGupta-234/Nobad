"""0.8.5 smart search: questions understood into parts, folders named in a question, the best guess, autocomplete
and the user's own search history. The last test runs tools/eval_search.py over its generated corpus (keywords only,
no models, no downloads) and holds it to its thresholds."""
import datetime as dt
import importlib.util
import os

import pytest

from nobadfind import history, search, suggest, winapi
from nobadfind.query import parse
from nobadfind.store import Store
from nobadfind.understand import best_guess, folder_finder, parts

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOW = dt.datetime(2026, 11, 19, 15, 0)


def folders(words):
    known = {"projects": ("Projects", [r"C:\Users\me\Documents\Projects"]),
             "tax papers": ("Tax Papers", [r"C:\Users\me\Documents\Tax Papers"])}
    return known.get(words)


def p(text, **k):
    return parse(text, now=NOW, find_folder=folders, **k)


# ---------- reading the question ----------
@pytest.mark.parametrize("text,folder,kinds,meaning", [
    ("2 boys in an image in downloads", "downloads", {"image"}, "2 boys"),
    ("two boys in a photo", "", {"image"}, "two boys"),
    ("photos of a dog on the beach", "", {"image"}, "dog on the beach"),
    ("find me a picture with a red car", "", {"image"}, "red car"),
    ("screenshot of the error on desktop", "desktop", {"image"}, "error"),
    ("pdf in documents", "documents", {"pdf"}, ""),
    ("songs in music", "music", {"audio"}, ""),
    ("video of the wedding in videos", "videos", {"video"}, "wedding"),
    ("excel sheet budget", "", {"spreadsheet"}, "budget"),
    ("word document about the lease", "", {"document"}, "lease"),
    ("slides for the quarterly review", "", {"slides"}, "quarterly review"),
    ("presentation in pictures", "pictures", {"slides"}, ""),
    ("python code for the scraper", "", {"code"}, "python scraper"),
    ("photos in pictures from last week", "pictures", {"image"}, ""),
])
def test_places_kinds_and_the_description(text, folder, kinds, meaning):
    q = p(text)
    assert q.folder == folder and q.kinds == kinds and q.meaning == meaning


def test_the_description_keeps_numbers_and_order():
    assert p("2 boys in an image in downloads").terms == ["2", "boys"]      # keywords as before
    assert p("2 boys in an image in downloads").meaning == "2 boys"          # photo meaning reads this
    assert p("three cats sleeping photo").meaning == "three cats sleeping"
    assert p("photos").meaning == "" and p("pdf in downloads").meaning == ""


@pytest.mark.parametrize("text,when", [
    ("pdf from today", "today"), ("notes yesterday", "yesterday"), ("photos last week", "last week"),
    ("bills last month", "last month"), ("report last year", "in 2025"), ("invoice in march", "March 2026"),
    ("photos from 2024", "in 2024"),
])
def test_times(text, when):
    assert p(text).when == when


@pytest.mark.parametrize("text,lo,hi,label", [
    ("big files", 100 << 20, None, "over 100 MB"), ("large videos", 100 << 20, None, "over 100 MB"),
    ("big photos", 10 << 20, None, "over 10 MB"), ("huge pdfs", 20 << 20, None, "over 20 MB"),
    ("small files", None, 1 << 20, "under 1 MB"), ("tiny images", None, 1 << 20, "under 1 MB"),
    ("videos over 100 mb", 100 << 20, None, "over 100 MB"), ("pdf under 2 mb", None, 2 << 20, "under 2 MB"),
])
def test_sizes(text, lo, hi, label):
    q = p(text)
    assert (q.min_size, q.max_size, q.size_label) == (lo, hi, label)


def test_size_words_keep_their_kind():
    assert p("big photos").kinds == {"image"} and p("small pdfs").kinds == {"pdf"}
    assert p("big files").terms == [] and p("small files").terms == []


@pytest.mark.parametrize("text,place", [
    ("pdf on d drive", "D:"), ("photos on drive e", "E:"), ("notes in d drive", "D:"), ("music on my usb", "removable"),
])
def test_drives(text, place):
    assert p(text).place == place


def test_folders_of_the_index_by_name():
    q = p("notes in projects")
    assert q.dirs == [r"C:\Users\me\Documents\Projects"] and q.dir_label == "Projects" and q.kinds == {"text"}
    q = p("everything inside the tax papers folder")
    assert q.dir_label == "Tax Papers" and q.terms == []
    # kind and filter words are never folder names; folders the index doesn't have stay words
    assert p("2 boys in an image").dirs == []
    q = p("notes in physics")
    assert q.dirs == [] and q.terms == ["physics"]


def test_hindi_and_hinglish_still_work():
    q = p("pichle hafte ki rent wali pdf")
    assert q.when == "last week" and q.kinds == {"pdf"} and q.terms == ["rent"]
    q = p("पिछले हफ्ते की पीडीएफ")
    assert q.when == "last week" and q.kinds == {"pdf"}
    q = p("downloads में बिजली बिल")
    assert q.folder == "downloads" and q.terms == ["बिजली", "बिल"]


def test_filler_and_linking_words_from_062_still_work():
    q = p("pdf in downloads having appreciation")
    assert q.folder == "downloads" and q.kinds == {"pdf"} and q.terms == ["appreciation"]
    assert p("list").terms == ["list"]                      # alone, a word to look for
    assert p("list all pdf").terms == []


# ---------- parts (chips) ----------
def labels(text, meaning_on=True):
    return [(x["kind"], x["label"]) for x in parts(p(text), meaning_on)]


def test_parts_for_the_maintainers_example():
    out = parts(p("2 boys in an image in downloads"), meaning_on=True)
    assert [(x["kind"], x["label"]) for x in out] == [("folder", "Downloads"), ("kind", "Images"),
                                                      ("meaning", "2 boys")]
    by = {x["label"]: x["without"] for x in out}
    assert by["Downloads"] == "2 boys in an image"
    assert by["Images"] == "2 boys in downloads"
    assert by["2 boys"] == "in an image in downloads"
    # each without is a question the parser reads without that part
    assert p(by["Images"]).kinds == set() and p(by["Images"]).folder == "downloads"
    assert p(by["Downloads"]).folder == "" and p(by["Downloads"]).kinds == {"image"}
    assert p(by["2 boys"]).terms == [] and p(by["2 boys"]).kinds == {"image"}


def test_parts_of_every_kind():
    assert labels("big pdfs from last week on d drive, newest") == [
        ("drive", "D:"), ("kind", "PDFs"), ("time", "Last week"), ("size", "Over 20 MB"), ("sort", "Newest first")]
    assert labels("budget in projects", meaning_on=False) == [("folder", "Projects"), ("words", "budget")]
    q = p(r"notes in C:\Work", is_dir=lambda x: x == "C:\\Work")
    assert [(x["kind"], x["label"]) for x in parts(q)] == [("folder", "Work"), ("kind", "Notes and text")]


def test_parts_keep_the_users_casing_and_hindi_falls_back_to_english():
    out = parts(p("Rent PDF in Downloads"), meaning_on=False)
    assert {x["label"]: x["without"] for x in out}["PDFs"] == "Rent in Downloads"
    out = parts(p("पिछले हफ्ते की पीडीएफ"), meaning_on=False)
    time_part = next(x for x in out if x["kind"] == "time")
    assert time_part["without"] == "pdf"                         # read as English, cut from that


# ---------- the best guess ----------
def r(fid, name, weak=False, why=("name matches",)):
    return {"id": fid, "name": name, "weak": weak, "why": list(why)}


def test_best_guess_rules():
    q = p("budget.xlsx")
    assert best_guess(q, [r(1, "budget 2019.xlsx"), r(2, "budget.xlsx")], {1: .02, 2: .02}) == (2, "Exact name")
    q = p("washing mach")
    assert best_guess(q, [r(1, "washing machine manual.pdf"), r(2, "machine washing.txt")], {})[1] == \
        "The only name that starts like this"
    q = p("report")
    assert best_guess(q, [r(1, "report a.txt"), r(2, "report b.txt")], {1: .02, 2: .019}) is None   # unsure
    assert best_guess(q, [r(1, "x.txt", weak=True)], {1: .01}) is None                            # only weak
    q = p("dentist")
    assert best_guess(q, [r(1, "todo.txt", why=["text inside matches"])], {1: .01}) == (1, "The only match")
    # one sure match among loose ones is a guess only when it's sure on two counts
    q = p("job application letter")
    rows = [r(1, "letter from hmrc.txt", why=["name has a close meaning"]), r(2, "cv.pdf", weak=True)]
    assert best_guess(q, rows, {1: .02, 2: .01}) is None
    q = p("2 boys in an image")
    rows = [r(1, "IMG_1.jpg", why=["the picture shows something like it"]),
            r(2, "IMG_2.jpg", why=["the picture shows something like it"])]
    assert best_guess(q, rows, {1: .03, 2: .02}, {1: 0.12, 2: 0.10}) == (1, "The picture fits best")
    assert best_guess(q, rows, {1: .03, 2: .02}, {1: 0.12, 2: 0.115}) is None


def _store(tmp_path, rows):
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    s.upsert_files(rows)
    s.upgrade_name_index()
    return s


def _f(path, kind, mtime=1.0e9, size=1000, folder=False):
    name = path.rsplit("\\", 1)[1]
    d = path.rsplit("\\", 1)[0]
    ext = "" if folder else os.path.splitext(name)[1].lower()
    return (path, name, d, ext, "folder" if folder else kind, size, mtime, mtime, 1)


HOME = r"C:\Users\me"
ROWS = [_f(HOME + r"\Documents", "", folder=True), _f(HOME + r"\Documents\Projects", "", folder=True),
        _f(HOME + r"\Documents\Projects\budget.xlsx", "spreadsheet"),
        _f(HOME + r"\Documents\Projects\budget_calc.py", "code"),
        _f(HOME + r"\Documents\Old\budget 2019.txt", "text"),
        _f(HOME + r"\AppData\Local\App\x\y\Projects", "", folder=True),
        _f(HOME + r"\AppData\Local\App\x\y\Projects\budget.log", "text"),
        _f(HOME + r"\Downloads\invoices 2023.xlsx", "spreadsheet", mtime=1.75e9),
        _f(HOME + r"\Downloads\invoice may.pdf", "pdf", mtime=1.70e9)]


def test_search_answers_with_parts_and_the_guess_first(tmp_path):
    s = _store(tmp_path, ROWS)
    r1 = search.search(s, "budget in projects", roots=[HOME])
    names = [x["name"] for x in r1["results"]]
    assert set(names) == {"budget.xlsx", "budget_calc.py"}          # not the deep AppData "Projects"
    assert r1["best"] == {"id": r1["results"][0]["id"], "reason": "Exact name"} and names[0] == "budget.xlsx"
    assert [x["label"] for x in r1["parts"]] == ["Projects", "budget"]
    # a file named exactly what was typed wins over the year read as a time
    r2 = search.search(s, "invoices 2023", roots=[HOME])
    assert r2["results"][0]["name"] == "invoices 2023.xlsx" and r2["best"]["reason"] == "Exact name"
    # nothing sure: no guess
    r3 = search.search(s, "budget", roots=[HOME])
    assert r3["best"] is None or r3["results"][0]["name"] == "budget.xlsx"
    s.close()


def test_a_soft_kind_word_is_read_again_as_a_word(tmp_path):
    s = _store(tmp_path, [_f(HOME + r"\Documents\cover letter.txt", "text")])
    r1 = search.search(s, "cover letter", roots=[HOME])
    assert [x["name"] for x in r1["results"]] == ["cover letter.txt"]
    assert "read as a word" in r1["notes"][0]
    s.close()


def test_a_plural_finds_the_singular_name(tmp_path):
    s = _store(tmp_path, [_f(HOME + r"\Documents\letter from hmrc.txt", "text")])
    assert [x["name"] for x in search.search(s, "letters hmrc")["results"]] == ["letter from hmrc.txt"]
    s.close()


def test_folder_finder_only_counts_folders_near_the_top(tmp_path):
    s = _store(tmp_path, ROWS)
    find = folder_finder(s, [HOME, HOME + r"\Documents"])
    assert find("projects") == ("Projects", [HOME + r"\Documents\Projects"])
    assert find("old") is None                      # not a folder in the index (only a file's parent)
    assert find("y") is None
    s.close()


# ---------- history and suggestions ----------
def test_history_is_kept_capped_and_forgotten(tmp_path):
    s = _store(tmp_path, [])
    assert history.add(s, "  tax   pdf ") and history.match(s, "tax pdf") == []   # what's typed isn't offered
    assert history.match(s, "t") == ["tax pdf"]
    assert not history.add(s, "x") and not history.add(s, "  ") and not history.add(s, "!!")
    history.add(s, "Tax PDF", now=2e9)                                         # one entry, newest spelling
    assert history.count(s) == 1 and history.match(s, "") == ["Tax PDF"]
    for i in range(history.CAP + 20):
        history.add(s, f"question {i}", now=1e9 + i)
    assert history.count(s) == history.CAP and "Tax PDF" in history.match(s, "", limit=1)
    assert history.match(s, "pdf") == ["Tax PDF"]                              # a word inside
    assert history.forget(s, "tax pdf") and not history.forget(s, "tax pdf")
    history.clear(s)
    assert history.count(s) == 0
    s.close()


def test_history_lives_in_the_index_and_wipe_clears_it(tmp_path):
    s = _store(tmp_path, [])
    history.add(s, "rent pdf")
    assert s.one("SELECT q FROM search_history") == "rent pdf"
    s.wipe()
    assert history.count(s) == 0
    s.close()


def test_suggestions_from_history_phrases_and_names(tmp_path):
    s = _store(tmp_path, ROWS + [_f(HOME + r"\Downloads\washing machine manual.pdf", "pdf")])
    history.add(s, "invoice pdf in downloads")
    out = suggest.suggest(s, "inv")
    kinds = [i["kind"] for i in out["items"]]
    assert out["items"][0] == {"text": "invoice pdf in downloads", "kind": "history",
                               "label": "invoice pdf in downloads", "detail": ""}
    assert "file" in kinds and out["complete"] == "invoice pdf in downloads"
    out = suggest.suggest(s, "2 boys in d")
    assert out["items"][0]["text"] == "2 boys in downloads" and out["complete"] == "2 boys in downloads"
    assert any(i["text"] == "2 boys in documents" for i in out["items"])
    assert suggest.suggest(s, "photos last w")["complete"] == "photos last week"
    assert suggest.suggest(s, "ima")["items"][0]["text"] == "images"
    out = suggest.suggest(s, "wash")
    assert out["items"][0]["label"] == "washing machine manual.pdf"
    assert out["complete"] == "washing machine manual.pdf"          # Tab takes the whole name: the best guess
    assert isinstance(out["items"][0]["id"], int)
    # history off: none of it
    assert all(i["kind"] != "history" for i in suggest.suggest(s, "inv", history_on=False)["items"])
    # empty box: recent questions only
    assert [i["kind"] for i in suggest.suggest(s, "")["items"]] == ["history"]
    s.close()


def test_suggestions_offer_folders_under_your_folders(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "Documents" / "Projects").mkdir(parents=True)
    s = _store(tmp_path, [_f(str(home / "Documents"), "", folder=True),
                          _f(str(home / "Documents" / "Projects"), "", folder=True)])
    out = suggest.suggest(s, "notes in pro", bases=[str(home / "Documents")])
    assert out["items"][0]["text"] == "notes in projects"
    out = suggest.suggest(s, "pdf on d", drives=[{"root": "D:\\"}])
    assert any(i["text"] == "pdf on d drive" for i in out["items"])
    s.close()


def test_suggest_is_safe_with_odd_input(tmp_path):
    s = _store(tmp_path, ROWS)
    for t in ('"', "*", "a OR b", "name:x", "\\\\server\\share", "%_", "ऀ", " " * 50, "x" * 500):
        out = suggest.suggest(s, t)
        assert isinstance(out["items"], list) and isinstance(out["complete"], str)
    s.close()


def test_the_api_keeps_history_only_with_the_setting_on(tmp_path, monkeypatch):
    from test_api_status import make                # the shared Api test helper
    a, s = make(tmp_path)
    s.upsert_files(ROWS)
    assert a.history_add("budget in projects") == {"ok": True, "saved": True}
    assert a.suggest("bud")["items"][0]["kind"] == "history"
    assert a.history_forget("budget in projects") == {"ok": True}
    a.history_add("rent pdf")
    monkeypatch.setattr("nobadfind.api.set_autostart", lambda on: None)
    a.set_settings({"search_history": False})                 # off deletes what was kept
    assert history.count(s) == 0 and a.history_add("rent pdf") == {"ok": True, "saved": False}
    assert a.suggest(None) == {"items": [], "complete": ""}
    s.close()


# ---------- the evaluation harness, keywords only ----------
def test_eval_search_corpus_meets_its_thresholds():
    """tools/eval_search.py over its generated corpus (no models): recall@1/@5, MRR, parts and the best guess's
    precision hold their thresholds. With models it runs from the command line (docs/measurements.md)."""
    spec = importlib.util.spec_from_file_location("eval_search", os.path.join(APP, "tools", "eval_search.py"))
    ev = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ev)
    old = winapi.known_folder
    rep = ev.run(None, verbose=False, pictures=False)
    assert winapi.known_folder is old                          # put back
    assert rep["models"] == [] and rep["keywords"]["n"] >= 35
    assert ev.failures(rep) == [], rep["keywords"]
    bad = [x["q"] for x in rep["rows"] if not x["parts_ok"]]
    assert not bad
