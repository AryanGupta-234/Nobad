"""Key-free Where to watch (Wikidata): entity parsing, platform links, and the search/report flow (offline)."""
import pytest

from nobadvpn.streamintel import net, wikidata as wd


def claim(v, rank="normal"):
    return {"rank": rank, "mainsnak": {"datavalue": {"value": v}}}


MATRIX = {"id": "Q83495", "labels": {"mul": {"value": "The Matrix"}},
          "descriptions": {"en": {"value": "1999 science fiction film"}},
          "sitelinks": {"enwiki": {"title": "The Matrix"}},
          "claims": {"P31": [claim({"id": "Q11424"})], "P577": [claim({"time": "+1999-03-31T00:00:00Z"})],
                     "P1874": [claim("20557937")], "P9586": [claim("umc.cmc.af8k9")], "P8298": [claim("feature/urn:hbo:x")],
                     "P7596": [claim("series-only")], "P6466": [claim("bad id with spaces")],
                     "P345": [claim("tt0133093")], "P4947": [claim("603")], "P2047": [claim({"amount": "+136"})]}}
TOWER = {"id": "Q1", "labels": {"en": {"value": "A tower"}}, "claims": {"P31": [claim({"id": "Q11303"})]}}


def test_summary_and_platform_links():
    s = wd.summarize(MATRIX)
    assert s == {"key": "wd:Q83495", "kind": "movie", "title": "The Matrix", "year": 1999, "overview": "1999 science fiction film",
                 "type": {"label": "Movie", "inferred": False}, "poster": None, "original_title": None, "source": "wikidata"}
    names = [(p["name"], p["url"]) for p in wd.platforms(MATRIX, "movie")]
    assert names == [("Netflix", "https://www.netflix.com/title/20557937"), ("Apple TV", "https://tv.apple.com/movie/umc.cmc.af8k9"),
                     ("Max", "https://play.hbomax.com/feature/urn:hbo:x")]     # series-only and malformed ids skipped
    assert wd.summarize(TOWER) is None


class FakeWD(wd.Wikidata):
    def __init__(self, entities, search_ids):
        super().__init__()
        self.ents, self.ids = entities, search_ids

    def _get(self, **p):
        if p["action"] == "wbsearchentities":
            return {"search": [{"id": i} for i in self.ids]}
        return {"entities": {i: self.ents[i] for i in p["ids"].split("|") if i in self.ents}}


def test_search_keeps_only_titles_and_report_has_ids():
    w = FakeWD({"Q83495": MATRIX, "Q1": TOWER}, ["Q1", "Q83495"])
    assert [r["key"] for r in w.search("matrix")] == ["wd:Q83495"]
    r = w.report("Q83495")
    assert r["ids"] == {"wikidata": "Q83495", "imdb": "tt0133093", "tmdb": "603"} and r["runtime"] == 136
    with pytest.raises(net.SourceError):
        w.report("Q1")


def test_platform_links_open_without_a_confirmation_prompt():
    from nobadvpn.streamintel.api_handlers import TRUSTED_HOSTS
    from urllib.parse import urlsplit
    for _p, _n, fmt, _k in wd.PLATFORMS:
        assert urlsplit(fmt.format("x")).hostname in TRUSTED_HOSTS
