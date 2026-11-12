"""Streaming Region Intelligence: parsing, availability states, restriction matching, server inventory, the
recommender, caching rules, credentials and the API boundary. No real network: every HTTP call goes through a
fake opener keyed by URL, so the real request/parse code paths run."""
import io
import json
import os
import types
import urllib.error
from urllib.parse import parse_qs, urlsplit

import pytest

from nobadvpn.streamintel import availability, net, recommend, restrictions, servers, store, tmdb
from nobadvpn.streamintel.countries import Countries
from nobadvpn.streamintel.service import NoKey, StreamIntel

COUNTRIES = [{"iso_3166_1": c, "english_name": n} for c, n in [
    ("US", "United States of America"), ("GB", "United Kingdom"), ("IN", "India"), ("JP", "Japan"), ("DE", "Germany"),
    ("MY", "Malaysia"), ("SG", "Singapore"), ("IR", "Iran"), ("FR", "France"), ("CN", "China"), ("KR", "South Korea")]]
CTRY = Countries(COUNTRIES)


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeWeb:
    """routes: {(host, path): payload | callable(query) | Exception}. Records every request."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def __call__(self, req, timeout=None):
        u = urlsplit(req.full_url)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        self.calls.append((u.hostname, u.path, q, dict(req.header_items())))
        r = self.routes.get((u.hostname, u.path))
        if r is None:
            raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, None)
        if callable(r):
            r = r(q)
        if isinstance(r, Exception):
            raise r
        return Resp(r if isinstance(r, bytes) else json.dumps(r).encode())


WATCH = {"results": {
    "US": {"link": "https://www.themoviedb.org/movie/1/watch?locale=US",
           "flatrate": [{"provider_id": 8, "provider_name": "Netflix", "logo_path": "/n.jpg", "display_priority": 1},
                        {"provider_id": 1796, "provider_name": "Netflix Standard with Ads", "logo_path": "/na.jpg", "display_priority": 2}],
           "rent": [{"provider_id": 2, "provider_name": "Apple TV", "logo_path": "/a.jpg", "display_priority": 3}]},
    "JP": {"link": "https://www.themoviedb.org/movie/1/watch?locale=JP",
           "free": [{"provider_id": 300, "provider_name": "Pluto TV", "logo_path": "/p.jpg", "display_priority": 5}]},
    "IN": {"link": "x", "buy": [{"provider_id": 2, "provider_name": "Apple TV", "logo_path": "/a.jpg", "display_priority": 3}]},
    "DE": {"link": "x"},                                       # entry without offers: not a listing
}}
COVERED = ["US", "JP", "IN", "DE", "GB", "FR"]


def details_payload(qid="Q220192"):
    return {"id": 1, "title": "Zoolander", "original_title": "Zoolander", "release_date": "2001-09-28",
            "genres": [{"id": 35, "name": "Comedy"}], "overview": "A model.", "runtime": 89, "poster_path": "/z.jpg",
            "alternative_titles": {"titles": [{"iso_3166_1": "DE", "title": "Zoolander", "type": ""},
                                              {"iso_3166_1": "FR", "title": "Zoolander le mannequin", "type": ""}]},
            "external_ids": {"imdb_id": "tt0196229", "wikidata_id": qid},
            "release_dates": {"results": [{"iso_3166_1": "US", "release_dates": [{"certification": "PG-13"}]},
                                          {"iso_3166_1": "DE", "release_dates": [{"certification": ""}]}]},
            "watch/providers": WATCH}


# ---- net ---------------------------------------------------------------------------------------------------
def test_net_retries_twice_on_429_then_reports_rate_limit():
    waits = []

    def opener(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 429, "slow", {"Retry-After": "9"}, None)
    with pytest.raises(net.SourceError) as e:
        net.get_json("https://x.test/a", opener=opener, sleep=waits.append)
    assert e.value.kind == "rate" and waits == [net.MAX_RETRY_WAIT] * 2  # capped, retried twice


def test_net_auth_errors_are_not_retried():
    n = []

    def opener(req, timeout=None):
        n.append(1)
        raise urllib.error.HTTPError(req.full_url, 401, "no", {}, None)
    with pytest.raises(net.SourceError) as e:
        net.get_json("https://x.test/a", opener=opener, sleep=lambda s: None)
    assert e.value.kind == "auth" and len(n) == 1


def test_net_sends_an_honest_user_agent():
    web = FakeWeb({("x.test", "/a"): {"ok": 1}})
    net.get_json("https://x.test/a", opener=web)
    assert web.calls[0][3]["User-agent"].startswith("NOBAD-VPN/")


# ---- tmdb --------------------------------------------------------------------------------------------------
def test_tmdb_auth_style_v3_key_vs_v4_token():
    web = FakeWeb({("api.tmdb.org", "/3/authentication"): {"success": True}})
    tmdb.TMDB("abcdef0123456789abcdef", opener=web).validate()
    tmdb.TMDB("eyJhbGciOiJIUzI1NiJ9.payload.sig", opener=web).validate()
    assert web.calls[0][2]["api_key"] == "abcdef0123456789abcdef" and "Authorization" not in web.calls[0][3]
    assert "api_key" not in web.calls[1][2] and web.calls[1][3]["Authorization"].startswith("Bearer eyJ")


def test_tmdb_without_key_refuses():
    with pytest.raises(net.SourceError):
        tmdb.TMDB("")


@pytest.mark.parametrize("q,want", [("Dune (2021)", ("Dune", 2021, False)), ("Spirited Away 2001", ("Spirited Away", 2001, False)),
                                    ("https://www.imdb.com/title/tt0245429/", ("tt0245429", None, True)),
                                    ("2001", ("2001", None, False)), ("  blade   runner ", ("blade runner", None, False))])
def test_parse_query(q, want):
    assert tmdb.parse_query(q) == want


def test_search_with_year_uses_typed_endpoints_and_ranks_exact_match_first():
    web = FakeWeb({("api.tmdb.org", "/3/search/movie"): lambda q: {"results": [
        {"id": 2, "title": "Dune Drifter", "release_date": "2020-01-01", "vote_count": 10},
        {"id": 1, "title": "Dune", "release_date": "2021-09-15", "vote_count": 9000, "poster_path": "/dune21.jpg"}]},
        ("api.tmdb.org", "/3/search/tv"): {"results": [{"id": 1, "name": "Dune", "first_air_date": "2000-12-03"}]}})
    api = tmdb.TMDB("k" * 20, opener=web)
    raw = api.search("Dune", 2021)
    ranked = tmdb.rank(raw, "Dune", 2021)
    assert {c[1] for c in web.calls} == {"/3/search/movie", "/3/search/tv"}
    assert web.calls[0][2]["primary_release_year"] == "2021" and web.calls[1][2]["first_air_date_year"] == "2021"
    assert ranked[0]["key"] == "movie:1" and ranked[0]["poster"] == "dune21.jpg"
    assert [r["key"] for r in ranked].count("movie:1") == 1 and "tv:1" in [r["key"] for r in ranked]


def test_multi_search_drops_people():
    web = FakeWeb({("api.tmdb.org", "/3/search/multi"): {"results": [
        {"id": 5, "media_type": "person", "name": "Someone"}, {"id": 6, "media_type": "tv", "name": "Show"}]}})
    assert [r["id"] for r in tmdb.TMDB("k" * 20, opener=web).search("show")] == [6]


@pytest.mark.parametrize("r,kind,label,inferred", [
    ({"genre_ids": [16], "original_language": "ja"}, "tv", "Anime", True),
    ({"genre_ids": [16], "origin_country": ["JP"], "original_language": "en"}, "movie", "Anime", True),
    ({"genre_ids": [16, 10751], "original_language": "en"}, "movie", "Animated film", False),
    ({"genre_ids": [16], "original_language": "en"}, "tv", "Animated series", False),
    ({"genre_ids": [99]}, "movie", "Documentary", False), ({"genre_ids": [10762]}, "tv", "Kids series", False),
    ({"genres": [{"id": 18}]}, "tv", "Series", False), ({}, "movie", "Movie", False)])
def test_content_type(r, kind, label, inferred):
    t = tmdb.content_type(r, kind)
    assert (t["label"], t["inferred"]) == (label, inferred)


def test_poster_paths_are_validated():
    assert tmdb.poster("/abcDEF123.jpg") == "abcDEF123.jpg"
    for bad in ("/../etc/passwd", "/a.jpg", "abc.jpg", "/x" * 50 + ".jpg", "/ok12345.exe", None):
        assert tmdb.poster(bad) is None


def test_normalize_details_identity_alt_titles_and_certifications():
    d = details_payload()
    t = tmdb.normalize_details(d, "movie")
    assert t["ids"] == {"tmdb": 1, "imdb": "tt0196229", "wikidata": "Q220192", "tvdb": None}
    assert [a["title"] for a in t["alternative_titles"]] == ["Zoolander le mannequin"]     # same-as-title deduped
    assert tmdb.certifications(d, "movie") == [{"country": "US", "rating": "PG-13"}]      # empty ones dropped
    tv = tmdb.certifications({"content_ratings": {"results": [{"iso_3166_1": "KR", "rating": "15"}]}}, "tv")
    assert tv == [{"country": "KR", "rating": "15", "descriptors": []}]


def test_details_is_one_request_with_everything_appended():
    web = FakeWeb({("api.tmdb.org", "/3/movie/1"): details_payload()})
    tmdb.TMDB("k" * 20, opener=web).details("movie", 1)
    assert len(web.calls) == 1
    assert web.calls[0][2]["append_to_response"] == "alternative_titles,external_ids,watch/providers,release_dates"
    with pytest.raises(net.SourceError):
        tmdb.TMDB("k" * 20, opener=web).details("person", 1)


# ---- availability --------------------------------------------------------------------------------------------
def test_availability_keeps_listed_not_listed_and_unknown_apart():
    av = availability.build(WATCH, COVERED, CTRY, fetched=1000.0)
    assert [c["code"] for c in av["listed"]] == ["US", "JP", "IN"]          # best offer type first
    assert {c["code"] for c in av["not_listed"]} == {"DE", "GB", "FR"}       # covered, no offer (DE had only a link)
    us = av["listed"][0]
    assert us["offers"] == {"subscription": [8, 1796], "rent": [2]} and us["best"] == "subscription"
    assert av["listed"][1]["best"] == "free"
    assert availability.state_for(av, "us")[0] == "listed"
    assert availability.state_for(av, "GB")[0] == "not_listed"
    assert availability.state_for(av, "KR")[0] == "unknown"                   # not covered: unknown, never "unavailable"
    apple = next(p for p in av["providers"] if p["id"] == 2)
    assert apple["countries"] == {"US": ["rent"], "IN": ["buy"]}


def test_provider_families_and_my_services_filter():
    assert availability.family("Netflix Standard with Ads") == "Netflix"
    assert availability.family("Netflix basic with Ads") == "Netflix"
    assert availability.family("Starz Amazon Channel") == "Starz Amazon Channel"
    av = availability.build(WATCH, COVERED, CTRY, 0)
    us = av["listed"][0]
    assert availability.matches_services(us, [], av["providers"]) is None
    assert availability.matches_services(us, [8], av["providers"]) == [8, 1796]      # same family counts
    assert availability.matches_services(us, [2], av["providers"]) == []              # rent doesn't count as "have"


def test_unknown_future_offer_types_are_kept():
    av = availability.build({"results": {"US": {"link": "", "lease": [{"provider_id": 9, "provider_name": "X"}]}}}, ["US"], CTRY, 0)
    assert av["listed"][0]["offers"] == {"lease": [9]}


# ---- countries + servers -------------------------------------------------------------------------------------
@pytest.mark.parametrize("name,code", [("India", "IN"), ("the People's Republic of China", "CN"), ("United States", "US"),
                                       ("UK", "GB"), ("Soviet Union", None), ("Czechoslovakia", None), ("Narnia", None),
                                       ("South Korea", "KR"), ("Iran", "IR")])
def test_country_names(name, code):
    assert CTRY.code(name) == code


class Tun:
    def __init__(self, regions, geo=None, pings=None, active=None, connected=False, home=None):
        self._regions, self.geo, self.pings = regions, geo or {}, pings or {}
        self.active, self.connected, self.home = active, connected, home


class Smart:
    def __init__(self, svc=None):
        self.d = {"svc": svc or {}}

    def snapshot(self):
        return self.d


def test_server_inventory_uses_real_engine_data_with_country_evidence():
    t = Tun([{"name": "usa", "host": "1.2.3.4"}, {"name": "japan", "host": "5.6.7.8"}, {"name": "de-fra", "host": "h"},
             {"name": "my-vpn", "host": "m"}, {"name": "home", "host": None}],
            geo={"1.2.3.4": {"country": "US", "city": "Ashburn"}},
            pings={"usa": {"rtt": 210, "loss": 0}, "japan": {"rtt": None, "loss": 100}, "de-fra": {"rtt": 40, "loss": 0, "est": True}},
            active="usa", connected=True)
    inv = {s["name"]: s for s in servers.inventory(t, Smart({"usa": {"netflix": {"ok": 3, "bad": 0}}}), CTRY, now=100)}
    assert (inv["usa"]["country"], inv["usa"]["country_basis"], inv["usa"]["city"]) == ("US", "ip-geolocation", "Ashburn")
    assert (inv["japan"]["country"], inv["japan"]["country_basis"], inv["japan"]["reach"]) == ("JP", "name", "not answering")
    assert (inv["de-fra"]["country"], inv["de-fra"]["rtt_estimated"]) == ("DE", True)
    assert inv["my-vpn"]["country"] is None and inv["my-vpn"]["country_basis"] == "none"   # 'my' is not Malaysia
    assert inv["home"]["country"] is None and inv["home"]["reach"] == "unknown"
    assert inv["usa"]["active"] and inv["usa"]["service_history"]["netflix"]["ok"] == 3


def test_check_ids_map_only_platforms_nobad_can_check():
    assert servers.check_id_for("Netflix Standard with Ads") == "netflix"
    assert servers.check_id_for("Amazon Prime Video") == "prime"
    assert servers.check_id_for("Disney Plus") == "disney"
    assert servers.check_id_for("Crunchyroll") is None


# ---- recommender ---------------------------------------------------------------------------------------------
def _inv(**over):
    base = [{"name": "usa", "country": "US", "country_basis": "ip-geolocation", "rtt": 180, "rtt_estimated": False,
             "reach": "answering", "service_history": {}, "city": None, "country_name": "United States of America",
             "loss": 0, "active": False, "favorite": False},
            {"name": "japan", "country": "JP", "country_basis": "name", "rtt": 90, "rtt_estimated": False,
             "reach": "answering", "service_history": {}, "city": None, "country_name": "Japan", "loss": 0,
             "active": False, "favorite": False}]
    for s in base:
        s.update(over.get(s["name"], {}))
    return base


def test_recommendation_needs_a_real_server_and_explains_itself():
    av = availability.build(WATCH, COVERED, CTRY, 0)
    rec = recommend.recommend(av, _inv(), {"status": "ok", "records": []}, home_country="IN")
    assert rec["verdict"] == "recommend"
    assert [o["code"] for o in rec["options"]] == ["US", "JP"]
    us = rec["options"][0]
    assert us["server"] == "usa" and us["offer"] == "subscription" and us["reasons"] and 0 < us["score"] <= 100
    assert any("load" in c for c in us["caveats"])                                  # never guessed
    assert any("estimated from its name" in c for c in rec["options"][1]["caveats"])
    assert rec["listed_without_server"] == [{"code": "IN", "name": "India", "best": "buy"}]
    assert rec["home"] == {"code": "IN", "listed": True, "best": "buy"}
    assert "guarantee" in rec["disclaimer"]


def test_no_matching_server_is_said_plainly():
    av = availability.build(WATCH, COVERED, CTRY, 0)
    rec = recommend.recommend(av, [dict(_inv()[0], country="GB")], None)
    assert rec["verdict"] == "no-matching-server" and rec["options"] == []
    assert {c["code"] for c in rec["listed_without_server"]} == {"US", "JP", "IN"}


def test_not_listed_anywhere_and_unknown_servers():
    av = availability.build({"results": {}}, COVERED, CTRY, 0)
    rec = recommend.recommend(av, [dict(_inv()[0], country=None, country_basis="none")], None)
    assert rec["verdict"] == "not-listed-anywhere" and rec["servers_unknown"] == ["usa"]


def test_documented_restriction_demotes_and_blocks_connect():
    av = availability.build(WATCH, COVERED, CTRY, 0)
    doc = {"status": "ok", "records": [{"code": "US", "tags": []}]}
    rec = recommend.recommend(av, _inv(), doc)
    assert [o["code"] for o in rec["options"]] == ["JP", "US"] and rec["options"][1]["restricted"]
    lifted = {"status": "ok", "records": [{"code": "US", "tags": ["later lifted"]}]}
    assert not recommend.recommend(av, _inv(), lifted)["options"][0]["restricted"]
    only = recommend.recommend(availability.build({"results": {"US": WATCH["results"]["US"]}}, COVERED, CTRY, 0), _inv(), doc)
    assert only["verdict"] == "only-restricted"


def test_service_history_my_services_freshness_and_dead_servers_matter():
    av = availability.build(WATCH, COVERED, CTRY, 0)
    good = recommend.recommend(av, _inv(usa={"service_history": {"netflix": {"ok": 4, "bad": 0, "blocked_now": False}}}), None)
    bad = recommend.recommend(av, _inv(usa={"service_history": {"netflix": {"ok": 0, "bad": 3, "blocked_now": True}}}), None)
    g, b = good["options"][0], next(o for o in bad["options"] if o["code"] == "US")
    assert g["score"] > b["score"] and any("blocked or VPN-detected" in c for c in b["caveats"])
    assert g["verify_services"] == ["netflix"]
    mine = recommend.recommend(av, _inv(), None, my_services=[300])               # Pluto TV (free in JP)
    assert mine["options"][0]["code"] == "JP"
    stale = recommend.recommend(dict(av, fresh=False), _inv(), None)
    assert any("older than 12 hours" in c for c in stale["options"][0]["caveats"])
    dead = recommend.recommend(av, _inv(usa={"reach": "not answering", "rtt": None}), None)
    assert dead["options"][0]["code"] == "JP"
    assert any("Restriction records couldn't be checked" in c for c in dead["options"][0]["caveats"])


# ---- restrictions (wikitext) ---------------------------------------------------------------------------------
WIKI_ROOT = """Intro {{dynamic list}}
==Iran==
{| class="wikitable sortable"
|-
! Date !! Title !! Notes
|-
| 2001 || ''[[Zoolander]]'' || Banned for perceived support of gay rights.<ref name="z">{{cite web|url=https://example.org/z|title=Iran bans|publisher=Example News}}</ref>
|-
| rowspan="2" | 2006
| ''[[The Da Vinci Code (film)|The Da Vinci Code]]''
| Banned for blasphemy.<ref>{{cite news |url=https://news.test/dvc |title=DVC ban}}</ref>
|-
| style="background:#b6fcb6;" | ''[[Some Other Film]]''
| The ban was later lifted after cuts were made.
|}
==Malaysia==
{{Main|List of films banned in Malaysia}}
==Soviet Union==
{| class="wikitable"
|-
! Year
! Film
! Reason
|-
| 1975
| [[Old Film]]
| Refused classification.<ref name="z"/>
|}
"""
WIKI_MY = """Text
{| class="wikitable"
|-
! Date
! Film
! Notes
|-
| 2001
| ''[[Zoolander]]''
| Banned for its depiction of Malaysia.
Second line of notes.
|}
"""


def wiki_web(fail_my=False):
    pages = {"List of banned films": WIKI_ROOT, "List of films banned in Malaysia": WIKI_MY}

    def parse(q):
        if fail_my and q["page"] == "List of films banned in Malaysia":
            return urllib.error.HTTPError("u", 503, "down", {}, None)
        if q["page"] not in pages:
            return {"error": {"info": "missing"}}
        return {"parse": {"title": q["page"], "wikitext": pages[q["page"]], "revid": 7}}

    def wd(q):
        return {"entities": {q["ids"]: {"sitelinks": {"enwiki": {"title": "Zoolander"}}}}} if q["ids"] == "Q220192" else {"entities": {q["ids"]: {}}}

    def query(q):
        return {"query": {"pages": [{"title": "Zoolander", "redirects": [{"title": "Zoolander (film)"}]}]}}

    def api(q):
        return parse(q) if q["action"] == "parse" else query(q)
    return FakeWeb({("en.wikipedia.org", "/w/api.php"): api, ("www.wikidata.org", "/w/api.php"): wd})


def test_wikitext_tables_rowspan_refs_and_tags():
    rows = restrictions.rows_from_page("List of banned films", WIKI_ROOT, CTRY)
    by = {r["film"]: r for r in rows}
    z = by["Zoolander"]
    assert (z["country"], z["code"], z["date"], z["target"]) == ("Iran", "IR", "2001", "Zoolander")
    assert z["sources"] == [{"url": "https://example.org/z", "title": "Iran bans", "publisher": "Example News", "date": None, "text": None}]
    assert z["verification"] == "documented, secondary source with 1 citation"
    assert z["url"].endswith("List_of_banned_films#Iran")
    dvc = by["The Da Vinci Code"]
    assert dvc["target"] == "The Da Vinci Code (film)" and dvc["date"] == "2006"
    other = by["Some Other Film"]
    assert other["date"] == "2006"                                                   # rowspan carried down
    assert set(other["tags"]) == {"later lifted", "cuts or edited release"}
    assert other["verification"].endswith("without a citation in the list")
    old = by["Old Film"]
    assert old["code"] is None and old["tags"] == ["certification refused"]          # historical state: no code
    assert old["sources"][0]["url"] == "https://example.org/z"                       # named ref resolved


def test_restriction_index_follows_main_pages_and_matches_by_identity_only():
    w = restrictions.WikiSource(opener=wiki_web(), sleep=lambda s: None)
    doc = w.build_index(CTRY, clock=lambda: 5.0)
    assert [p["title"] for p in doc["pages"]] == ["List of banned films", "List of films banned in Malaysia"]
    art, reds = w.article_for("Q220192")
    assert (art, reds) == ("Zoolander", ["Zoolander (film)"])
    recs = restrictions.match(doc, art, reds)
    assert sorted((r["country"], r["code"]) for r in recs) == [("Iran", "IR"), ("Malaysia", "MY")]
    my = next(r for r in recs if r["code"] == "MY")
    assert "Second line of notes." in my["notes"]                                     # multi-line cell
    assert w.article_for("Q1") == (None, []) and w.article_for("not-a-qid") == (None, [])
    assert restrictions.match(doc, "Zoolander 2", []) == []                           # no fuzzy title matching


def test_restriction_index_survives_a_failing_sub_page():
    doc = restrictions.WikiSource(opener=wiki_web(fail_my=True), sleep=lambda s: None).build_index(CTRY)
    assert doc["failed"] and doc["failed"][0]["title"] == "List of films banned in Malaysia"
    assert "Zoolander" in doc["index"]


# ---- store ---------------------------------------------------------------------------------------------------
def test_cache_freshness_stale_fallback_and_six_month_limit():
    now = [1000.0]
    c = store.Cache(":memory:", clock=lambda: now[0])
    c.put("a", {"x": 1})
    assert c.get("a", "avail")[2] is True
    now[0] += store.TTL["avail"] + 1
    assert c.get("a", "avail") is None
    v, ts, fresh = c.get("a", "avail", allow_stale=True)
    assert v == {"x": 1} and ts == 1000.0 and fresh is False
    now[0] = 1000.0 + store.HARD_MAX_AGE + 1
    assert c.get("a", "avail", allow_stale=True) is None                              # TMDB terms: never > 6 months
    c.put("b", 1)
    now[0] += store.HARD_MAX_AGE + 5
    assert c.purge() == 1


def test_credential_is_kept_out_of_settings_and_masked(tmp_path, monkeypatch):
    monkeypatch.delenv("NOBAD_TMDB_TOKEN", raising=False)
    from nobadvpn import dpapi
    monkeypatch.setattr(dpapi, "protect", lambda data, d: b"ENC" + data[::-1])
    monkeypatch.setattr(dpapi, "unprotect", lambda blob, d=None: blob[3:][::-1])
    cr = store.Credential(str(tmp_path / "k"))
    assert cr.get() is None and cr.source() is None
    cr.set("  abcdef0123456789abcd  ")
    assert open(tmp_path / "k", "rb").read() != b"abcdef0123456789abcd"               # not stored in clear
    assert cr.get() == "abcdef0123456789abcd" and cr.source() == "saved"
    assert store.mask(cr.get()) == "abcd…abcd"
    monkeypatch.setenv("NOBAD_TMDB_TOKEN", "envtoken0123456789")
    assert cr.get() == "envtoken0123456789" and cr.source() == "environment"
    cr.clear()
    assert not os.path.exists(tmp_path / "k")
    from nobadvpn.const import DEFAULTS
    assert not any("tmdb" in k and "key" in k for k in DEFAULTS)


# ---- service (end to end over fakes) ---------------------------------------------------------------------------
class Settings(dict):
    def get(self, k, d=None):
        return super().get(k, d)


def make_service(tmp_path, web, key="k" * 20, now=None):
    cred = types.SimpleNamespace(get=lambda: key, source=lambda: "saved", set=lambda v: None, clear=lambda: None)
    clock = (lambda: now[0]) if now else (lambda: 1000.0)
    return StreamIntel(cache=store.Cache(":memory:", clock=clock), credential=cred,
                       tmdb_factory=lambda k, lang: tmdb.TMDB(k, lang, opener=web, sleep=lambda s: None),
                       wiki=restrictions.WikiSource(opener=web, sleep=lambda s: None), clock=clock, img_dir=str(tmp_path / "img"))


def full_web(details=None, fail_details=False):
    w = wiki_web()
    w.routes.update({
        ("api.tmdb.org", "/3/movie/1"): (urllib.error.HTTPError("u", 503, "down", {}, None) if fail_details else (details or details_payload())),
        ("api.tmdb.org", "/3/configuration/countries"): COUNTRIES,
        ("api.tmdb.org", "/3/watch/providers/regions"): {"results": [{"iso_3166_1": c} for c in COVERED]},
    })
    return w


def test_report_then_restrictions_end_to_end(tmp_path):
    web = full_web()
    si = make_service(tmp_path, web)
    t = Tun([{"name": "usa", "host": "1.2.3.4"}, {"name": "japan", "host": "5.6.7.8"}], geo={"1.2.3.4": {"country": "US"}},
            pings={"usa": {"rtt": 150, "loss": 0}, "japan": {"rtt": 60, "loss": 0}}, home={"country": "IN"})
    rep = si.report("movie", 1, t, Smart(), Settings())
    assert rep["key"] == "movie:1" and rep["title"]["title"] == "Zoolander" and rep["home_country"] == "IN"
    assert rep["availability"]["fresh"] and rep["availability"]["coverage"] == len(COVERED)
    assert rep["restrictions"] == {"status": "loading"}
    assert rep["certifications"] == [{"country": "US", "rating": "PG-13", "name": "United States of America"}]
    doc, rec = si.with_restrictions(rep, t, Smart(), Settings())
    assert doc["status"] == "ok" and {r["code"] for r in doc["records"]} == {"IR", "MY"}
    assert all(r["country_name"] for r in doc["records"])
    assert rec["verdict"] == "recommend" and rec["options"][0]["code"] in ("US", "JP")
    n = len(web.calls)
    si.report("movie", 1, t, Smart(), Settings())                                     # cached: no new TMDB calls
    assert len(web.calls) == n


def test_stale_cache_is_used_and_marked_when_tmdb_is_down(tmp_path):
    now = [1000.0]
    good = full_web()
    si = make_service(tmp_path, good, now=now)
    t = Tun([])
    si.report("movie", 1, t, Smart(), Settings())
    now[0] += store.TTL["avail"] + 60
    good.routes[("api.tmdb.org", "/3/movie/1")] = urllib.error.HTTPError("u", 503, "down", {}, None)
    rep = si.report("movie", 1, t, Smart(), Settings())
    assert rep["availability"]["fresh"] is False and rep["availability"]["fetched"] == 1000.0


def test_tmdb_down_without_cache_is_an_error_not_an_empty_result(tmp_path):
    si = make_service(tmp_path, full_web(fail_details=True))
    with pytest.raises(net.SourceError):
        si.report("movie", 1, Tun([]), Smart(), Settings())


def test_restrictions_unavailable_or_unmatchable_is_never_no_restrictions(tmp_path):
    web = full_web()
    si = make_service(tmp_path, web)
    assert si.restriction_doc({"ids": {"wikidata": None}}, CTRY)["status"] == "no-identity"
    assert si.restriction_doc({"ids": {"wikidata": "Q1"}}, CTRY)["status"] == "no-article"
    web.routes[("en.wikipedia.org", "/w/api.php")] = urllib.error.HTTPError("u", 503, "down", {}, None)
    si2 = make_service(tmp_path, web)
    d = si2.restriction_doc({"ids": {"wikidata": "Q220192"}}, CTRY)
    assert d["status"] == "unavailable" and "not the same" in d["note"]


def test_search_needs_a_key_and_validates_input(tmp_path):
    web = FakeWeb({("api.tmdb.org", "/3/search/multi"): {"results": [{"id": 3, "media_type": "movie", "title": "Akira"}]}})
    si = make_service(tmp_path, web)
    assert si.search("a")["ok"] is False
    r = si.search("Akira")
    assert r["ok"] and r["results"][0]["key"] == "movie:3"
    nokey = make_service(tmp_path, web, key=None)
    with pytest.raises(NoKey):
        nokey.search("Akira")


def test_set_key_validates_with_tmdb_before_saving(tmp_path):
    saved = []
    web = FakeWeb({("api.tmdb.org", "/3/authentication"): urllib.error.HTTPError("u", 401, "no", {}, None)})
    si = make_service(tmp_path, web)
    si.cred = types.SimpleNamespace(get=lambda: None, source=lambda: None, set=saved.append, clear=lambda: None)
    assert si.set_key("short")["ok"] is False
    r = si.set_key("abcdef0123456789abcdef")
    assert r == {"ok": False, "error": "TMDB rejected this key."} and saved == []
    web.routes[("api.tmdb.org", "/3/authentication")] = {"success": True}
    assert si.set_key("abcdef0123456789abcdef")["ok"] and saved == ["abcdef0123456789abcdef"]


def test_image_proxy_validates_and_caches(tmp_path):
    jpg = b"\xff\xd8\xff\xe0" + b"0" * 50
    web = FakeWeb({("image.tmdb.org", "/t/p/w92/abcde.jpg"): jpg, ("image.tmdb.org", "/t/p/w92/htmlx.jpg"): b"<html>"})
    si = make_service(tmp_path, web)
    assert si.image("w92", "abcde.jpg", opener=web) == jpg
    assert si.image("w92", "abcde.jpg", opener=web) == jpg and len(web.calls) == 1        # disk cache
    assert si.image("w92", "htmlx.jpg", opener=web) is None                              # not an image
    for size, name in (("w9999", "abcde.jpg"), ("w92", "../x.jpg"), ("w92", "a.jpg"), ("w92", "abcde.exe")):
        assert si.image(size, name, opener=web) is None


# ---- API boundary ----------------------------------------------------------------------------------------------
def test_api_handlers_registered_and_input_checked(monkeypatch):
    from nobadvpn import api
    from nobadvpn.streamintel import api_handlers as h
    for k in ("si_status", "si_key", "si_search", "si_title", "si_providers", "si_prefs", "si_verify", "si_open", "si_cache_clear"):
        assert k in api.HANDLERS
    assert h.h_title({"key": "person:1"})["ok"] is False
    assert h.h_title({"key": "movie:1;rm"})["ok"] is False
    assert h.h_prefs({"my_services": ["8"]})["ok"] is False
    assert h.h_verify({"country": "usa"})["ok"] is False
    assert h.h_providers({"region": "EVIL"})["ok"] is False


@pytest.mark.parametrize("url,ok", [("https://www.themoviedb.org/movie/1", True), ("https://en.wikipedia.org/wiki/X", True),
                                    ("javascript:alert(1)", False), ("file:///C:/x", False), ("https://u:p@evil.test/", False),
                                    ("https://news.example.com/a", "confirm")])
def test_si_open_only_opens_safe_links(monkeypatch, url, ok):
    from nobadvpn import syscmd
    from nobadvpn.streamintel import api_handlers as h
    opened = []
    monkeypatch.setattr(syscmd, "open_url_as_user", lambda u: opened.append(u) or True)
    r = h.h_open({"url": url})
    if ok == "confirm":
        assert r == {"ok": False, "error": "confirm", "host": "news.example.com"} and not opened
        assert h.h_open({"url": url, "confirm": True})["ok"] and opened == [url]
    else:
        assert r["ok"] is ok and (opened == [url]) is ok


def test_ui_assets_are_wired_and_keep_attribution():
    ui = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "nobadvpn", "ui")
    html = open(os.path.join(ui, "index.html"), encoding="utf-8").read()
    js = open(os.path.join(ui, "streamintel.js"), encoding="utf-8").read()
    assert "/static/streamintel.js" in html and "/static/streamintel.css" in html
    assert "not endorsed or certified by TMDB" in js and "JustWatch" in js
    assert 'api("connect", { name: server })' in js                                     # existing connect API only
    assert "img-src 'self' data: blob:" in open(os.path.join(os.path.dirname(ui), "server.py"), encoding="utf-8").read()


@pytest.mark.parametrize("name,code", [("us", "US"), ("de-fra", "DE"), ("us-east-1", "US"), ("my-vpn", None), ("in-home", None),
                                       ("my-kul", "MY"), ("japan", "JP"), ("uk-london", "GB"), ("vpn", None), ("wg-us", None)])
def test_server_name_country_hints(name, code):
    assert servers._name_country(name, CTRY) == code


@pytest.mark.parametrize("name,code", [("Frankfurt", "DE"), ("NewYork", "US"), ("new-york-2", "US"), ("hong_kong", "HK"),
                                       ("Mumbai", "IN"), ("tokyo-01", "JP"), ("London", "GB"), ("Paris", "FR"), ("Atlantis", None)])
def test_server_city_names(name, code):
    assert servers._name_country(name, CTRY) == code


def test_tmdb_falls_back_to_the_other_api_name_when_the_network_resets_one():
    calls = []

    def opener(req, timeout=None):
        host = urlsplit(req.full_url).hostname
        calls.append(host)
        if host == "api.tmdb.org":
            raise urllib.error.URLError(ConnectionResetError(10054, "reset"))
        return Resp(json.dumps({"success": True}).encode())
    tmdb.TMDB._preferred = 0
    assert tmdb.TMDB("k" * 20, opener=opener, sleep=lambda s: None).validate()
    assert calls == ["api.tmdb.org"] * 3 + ["api.themoviedb.org"] and tmdb.TMDB._preferred == 1
    calls.clear()
    tmdb.TMDB("k" * 20, opener=opener, sleep=lambda s: None).validate()
    assert calls == ["api.themoviedb.org"]                                   # remembers the name that works
    tmdb.TMDB._preferred = 0


def test_tmdb_auth_errors_do_not_try_the_other_name():
    calls = []

    def opener(req, timeout=None):
        calls.append(urlsplit(req.full_url).hostname)
        raise urllib.error.HTTPError(req.full_url, 401, "no", {}, None)
    tmdb.TMDB._preferred = 0
    with pytest.raises(net.SourceError):
        tmdb.TMDB("k" * 20, opener=opener, sleep=lambda s: None).validate()
    assert calls == ["api.tmdb.org"]


def test_ui_never_uses_the_globally_hidden_warn_class():
    """index.html hides `.warn` globally; caveats must not inherit that (they carry the honesty warnings)."""
    ui = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "nobadvpn", "ui")
    js = open(os.path.join(ui, "streamintel.js"), encoding="utf-8").read()
    assert 'class="warn"' not in js and '"warn"}' not in js and 'class="si-warn"' in js
