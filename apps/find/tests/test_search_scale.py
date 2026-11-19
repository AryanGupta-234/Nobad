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
    assert s.meta("name_index") == "4" and s.upgrade_name_index() is False      # once


def test_common_words_walk_the_shortest_names_first(tmp_path, monkeypatch):
    """A word in thousands of names: the walk in name-length order finds the best ones without joining them all."""
    names = [f"report {i:04d} final.txt" for i in range(300)] + ["report.txt", "my report.txt"]
    s = _store(tmp_path, names)
    s.upgrade_name_index()
    monkeypatch.setattr(search, "FTS_PROBE", 50)                 # 302 matches count as common here
    plan = " ".join(str(r) for r in s.q("EXPLAIN QUERY PLAN SELECT f.id FROM files f INDEXED BY files_namelen "
                                        "WHERE f.name LIKE '%report%' ORDER BY length(f.name), f.mtime DESC LIMIT 5"))
    assert "files_namelen" in plan and "TEMP B-TREE" not in plan.upper()
    got = [r["name"] for r in search.search(s, "report", limit=3)["results"]]
    assert got == ["report.txt", "my report.txt", "report 0000 final.txt"] or got[:2] == ["report.txt", "my report.txt"]
    assert [r["name"] for r in search.search(s, "re", limit=2)["results"]] == ["report.txt", "my report.txt"]


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


def _encrypted(tmp_path):
    s = Store(str(tmp_path / "e.db"), str(tmp_path / "e.key"))
    assert s.encrypted
    return s


def test_the_best_match_survives_the_cap(tmp_path):
    """Review H1: 2,500 reportN.dll indexed first, then the one report.pdf; the cap must not keep only the oldest."""
    s = _encrypted(tmp_path)
    s.upsert_files([(f"C:/Windows/sys/report{i}.dll", f"report{i}.dll", "C:/Windows/sys", ".dll", "app", 10, 1.0, 1.0, 1)
                    for i in range(2500)])
    s.upsert_files([("C:/Users/me/Documents/report.pdf", "report.pdf", "C:/Users/me/Documents", ".pdf", "pdf", 10,
                     2.0, 2.0, 1)])
    s.upgrade_name_index()
    assert search.search(s, "report")["results"][0]["name"] == "report.pdf"
    assert [r["name"] for r in search.search(s, "report pdf")["results"]] == ["report.pdf"]
    assert search.search(s, "re")["results"][0]["name"] == "report.pdf"
    s.close()


def test_short_terms_with_symbols_use_the_name_itself(tmp_path):
    """Review L2: "c#" or "++" aren't words the word index has: they go the LIKE way."""
    s = _store(tmp_path, ["c# notes.txt", "c notes.txt", "a++ guide.txt"])
    s.upgrade_name_index()
    assert [r["name"] for r in search.search(s, "c#")["results"]] == ["c# notes.txt"]
    assert [r["name"] for r in search.search(s, "++")["results"]] == ["a++ guide.txt"]


def test_a_real_interrupt_on_the_encrypted_index_is_a_cancel_not_a_failure(tmp_path):
    """Review M3: SQLCipher's OperationalError isn't sqlite3's; an interrupted query must still read as cancelled."""
    s = _encrypted(tmp_path)
    s.upsert_files([(f"C:/d/file {i}.txt", f"file {i}.txt", "C:/d", ".txt", "text", 10, 1.0, 1.0, 1)
                    for i in range(3000)])
    calls = {"n": 0}

    def cancelled():                                       # not yet at the start; then a newer keystroke came
        calls["n"] += 1
        return calls["n"] > 1
    r = search.search(s, "fi", cancelled=cancelled)          # the LIKE way (no word index yet): many VM steps
    assert r.get("cancelled") is True and r["results"] == [] and calls["n"] > 1
    s.close()


def test_cancelling_is_per_channel(tmp_path):
    """Review M4: the Home screen's list and the main search box on one connection don't cancel each other."""
    from test_api_status import make
    a, s = make(tmp_path)
    seen = []
    import nobadfind.api as api_mod
    real = api_mod.search
    api_mod.search = lambda *args, **kw: seen.append(kw.get("cancelled")) or real(*args, **kw)
    try:
        a.search("a", client="c1", channel="main")
        a.search("", {"sort": "newest"}, client="c1", channel="home")
        assert seen[0]() is False                          # the home list didn't cancel the main search
        a.search("ab", client="c1", channel="main")
        assert seen[0]() is True
    finally:
        api_mod.search = real
        s.close()


def test_the_pipe_says_a_search_was_cancelled():
    from nobadfind.rpc.handlers.search import _search_result
    assert _search_result({"results": [], "cancelled": True})["cancelled"] is True
    assert "cancelled" not in _search_result({"results": []})


def test_the_pipe_checks_the_channel():
    import json
    from nobadfind.rpc import protocol
    from nobadfind.rpc.handlers.search import methods
    seen = []

    class Api:
        def search(self, text, filters=None, client=None, channel="main"):
            seen.append(channel)
            return {"results": []}

    class Conn:
        pass
    m = methods(Api())
    ok = protocol.handle_line(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "search",
                                          "params": {"text": "x", "channel": "home"}}), m, Conn())
    bad = protocol.handle_line(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "search",
                                           "params": {"text": "x", "channel": "../../x"}}), m, Conn())
    assert "result" in ok and seen == ["home"] and bad["error"]["code"] == -32602
