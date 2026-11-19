"""Whole-PC scale (about a million entries): short questions use an index, candidates are capped, and a newer
keystroke cancels the search still running for the same client (tools/bench_search.py measures it)."""
import threading
import time

from nobadfind import search
from nobadfind.store import Store


def _store(tmp_path, names):
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    s.upsert_files([(f"C:/d/{n}", n, "C:/d", "." + n.rsplit(".", 1)[-1], "text", 10, 1.0, 1.0, 1) for n in names])
    return s


def test_short_questions_find_names_by_the_start_of_a_word(tmp_path):
    s = _store(tmp_path, ["tax_2024.pdf", "budget report.xlsx", "Taxi receipt.txt", "status.txt", "x.txt"])
    s.upgrade_name_index()
    names = lambda q: {r["name"] for r in search.search(s, q)["results"]}     # noqa: E731
    assert names("ta") == {"tax_2024.pdf", "Taxi receipt.txt"}               # not "sTAtus": the start of a word
    assert names("re") == {"budget report.xlsx", "Taxi receipt.txt"}
    assert "x.txt" in names("x")


def test_the_name_index_follows_renames_and_deletes(tmp_path):
    s = _store(tmp_path, ["alpha.txt"])
    s.upgrade_name_index()
    s.upsert_files([("C:/d/zeta.txt", "zeta.txt", "C:/d", ".txt", "text", 10, 1.0, 1.0, 1)])
    assert {r["name"] for r in search.search(s, "ze")["results"]} == {"zeta.txt"}
    s.remove_paths(["C:/d/zeta.txt"])
    assert search.search(s, "ze")["results"] == []
    assert s.meta("name_index") == "2" and s.upgrade_name_index() is False      # once


def test_candidates_are_capped(tmp_path, monkeypatch):
    s = _store(tmp_path, [f"report {i}.txt" for i in range(300)])
    s.upgrade_name_index()
    monkeypatch.setattr(search, "NAME_CANDIDATES", 50)
    r = search.search(s, "re", limit=500)
    assert len(r["results"]) == 50
    r = search.search(s, "report", limit=500)
    assert len(r["results"]) == 50


def test_a_newer_search_cancels_the_older_one(tmp_path):
    s = _store(tmp_path, [f"file {i}.txt" for i in range(2000)])
    gate = threading.Event()
    calls = {"n": 0}

    def cancelled():
        calls["n"] += 1
        gate.set()
        return True                                       # a newer keystroke came in
    r = search.search(s, "file", cancelled=cancelled)
    assert r["results"] == [] and r.get("cancelled") is True and calls["n"] >= 1


def test_api_search_cancels_per_client(tmp_path):
    from test_api_status import make
    a, s = make(tmp_path)
    seen = []
    real = search.search

    def slow(*args, **kw):
        seen.append(kw.get("cancelled"))
        if len(seen) == 1:
            time.sleep(0.2)
        return real(*args, **{k: v for k, v in kw.items()})
    import nobadfind.api as api_mod
    api_mod_search = api_mod.search
    api_mod.search = slow
    try:
        t = threading.Thread(target=lambda: a.search("a", client="ui-1"))
        t.start()
        time.sleep(0.05)
        a.search("ab", client="ui-1")
        t.join(3)
        assert seen[0]() is True and seen[1]() is False   # the first is stale now, the second isn't
        a.search("x", client="ui-2")
        assert seen[1]() is False                          # another client doesn't cancel it
    finally:
        api_mod.search = api_mod_search
        s.close()


def test_listing_a_kind_newest_first_uses_an_index(tmp_path):
    s = _store(tmp_path, ["a.txt"])
    s.upgrade_name_index()
    plan = " ".join(str(r) for r in s.q("EXPLAIN QUERY PLAN SELECT f.id FROM files f WHERE f.kind IN (?) "
                                        "ORDER BY f.mtime DESC LIMIT 10", ("image",)))
    assert "files_kind_mtime" in plan and "TEMP B-TREE" not in plan.upper()
