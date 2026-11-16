"""Key-free source for Where to watch: Wikidata (CC0, no account, no key).

Wikidata records which streaming platforms carry a title, as the platform's own ID (Netflix ID, Disney+ movie ID,
Apple TV movie ID, ...). Each property's official link format (P1630) turns the ID into a link. That is enough to say
"this is on Netflix, Max and Apple TV" with a direct link, and to match the title to Wikipedia's restriction lists,
without the user setting anything up. It does NOT say in which countries a platform lists the title; that per-country
view stays the TMDB/JustWatch upgrade (a free personal key). The UI says which mode it is in."""
import re

from . import net

API = "https://www.wikidata.org/w/api.php"

# property -> (platform, link format, kinds). Verified against Wikidata's own P1630 formatter URLs.
PLATFORMS = [
    ("P1874", "Netflix", "https://www.netflix.com/title/{}", ("movie", "tv")),
    ("P7595", "Disney+", "https://www.disneyplus.com/movies/wd/{}", ("movie",)),
    ("P7596", "Disney+", "https://www.disneyplus.com/series/wp/{}", ("tv",)),
    ("P14440", "Prime Video", "https://www.primevideo.com/detail/{}", ("movie", "tv")),
    ("P8055", "Prime Video", "https://www.amazon.com/gp/video/detail/{}", ("movie", "tv")),
    ("P9586", "Apple TV", "https://tv.apple.com/movie/{}", ("movie",)),
    ("P9751", "Apple TV", "https://tv.apple.com/show/{}", ("tv",)),
    ("P8298", "Max", "https://play.hbomax.com/{}", ("movie", "tv")),
    ("P6466", "Hulu", "https://www.hulu.com/movie/{}", ("movie",)),
    ("P6467", "Hulu", "https://www.hulu.com/series/{}", ("tv",)),
    ("P11330", "Crunchyroll", "https://crunchyroll.com/series/{}", ("tv",)),
]
PLATFORM_HOSTS = {"www.netflix.com", "www.disneyplus.com", "www.primevideo.com", "www.amazon.com", "tv.apple.com",
                  "play.hbomax.com", "www.hulu.com", "crunchyroll.com"}
MOVIE = {"Q11424", "Q202866", "Q24869", "Q506240", "Q93204", "Q20650540", "Q229390", "Q1054574", "Q24862"}
TV = {"Q5398426", "Q63952888", "Q581714", "Q526877", "Q1259759", "Q117467246", "Q15416", "Q21191270"}
ANIME = {"Q63952888", "Q20650540", "Q1107"}
_QID = re.compile(r"Q\d{1,12}")
_ID_OK = re.compile(r"[A-Za-z0-9:._/\-]{1,160}")


def _label(ent, lang="en"):
    for src in ("labels",):
        d = ent.get(src) or {}
        for k in (lang, "en", "mul"):
            if d.get(k, {}).get("value"):
                return d[k]["value"]
    return None


def _vals(ent, prop):
    out = []
    for c in (ent.get("claims") or {}).get(prop, []):
        if c.get("rank") == "deprecated":
            continue
        v = (c.get("mainsnak") or {}).get("datavalue", {}).get("value")
        if v is not None:
            out.append(v)
    return out


def _year(ent):
    years = []
    for v in _vals(ent, "P577") + _vals(ent, "P580"):
        m = re.match(r"[+-](\d{4})", (v or {}).get("time", "") if isinstance(v, dict) else "")
        if m:
            years.append(int(m.group(1)))
    return min(years) if years else None


def kind_of(ent):
    types = {v.get("id") for v in _vals(ent, "P31") if isinstance(v, dict)}
    if types & TV:
        return "tv", bool(types & ANIME)
    if types & MOVIE:
        return "movie", bool(types & ANIME)
    return None, False


def platforms(ent, kind):
    """[{name, url, id}] - one entry per platform (first valid ID), in PLATFORMS order."""
    out, seen = [], set()
    for prop, name, fmt, kinds in PLATFORMS:
        if kind not in kinds or name in seen:
            continue
        for v in _vals(ent, prop):
            if isinstance(v, str) and _ID_OK.fullmatch(v):
                out.append({"name": name, "url": fmt.format(v), "id": v, "property": prop})
                seen.add(name)
                break
    return out


def summarize(ent, lang="en"):
    kind, anime = kind_of(ent)
    if not kind:
        return None
    title = _label(ent, lang) or ((ent.get("sitelinks") or {}).get("enwiki") or {}).get("title")
    if not title:
        return None
    desc = ((ent.get("descriptions") or {}).get(lang) or (ent.get("descriptions") or {}).get("en") or {}).get("value")
    label = "Anime" if anime else "Series" if kind == "tv" else "Movie"
    return {"key": f"wd:{ent['id']}", "kind": kind, "title": title, "year": _year(ent), "overview": desc,
            "type": {"label": label, "inferred": False}, "poster": None, "original_title": None, "source": "wikidata"}


class Wikidata:
    def __init__(self, opener=None, sleep=None):
        self.opener, self.sleep = opener, sleep

    def _get(self, **params):
        kw = {"opener": self.opener}
        if self.sleep:
            kw["sleep"] = self.sleep
        return net.get_json(API, dict(params, format="json"), **kw)

    def entities(self, ids, lang="en"):
        ids = [i for i in ids if _QID.fullmatch(i)][:50]
        if not ids:
            return {}
        d = self._get(action="wbgetentities", ids="|".join(ids), props="labels|descriptions|claims|sitelinks",
                      languages=f"{lang}|en|mul", sitefilter="enwiki")
        return d.get("entities") or {}

    def search(self, q, lang="en"):
        """Titles (movies, series, anime) matching `q`, best first."""
        d = self._get(action="wbsearchentities", search=q[:120], language=lang, uselang=lang, type="item", limit=20)
        ids = [x.get("id") for x in d.get("search") or [] if x.get("id")]
        ents = self.entities(ids, lang)
        out = []
        for i in ids:
            s = summarize(ents.get(i) or {}, lang) if ents.get(i) else None
            if s:
                out.append(s)
        return out

    def report(self, qid, lang="en"):
        ent = self.entities([qid], lang).get(qid)
        if not ent or ent.get("missing") is not None:
            raise net.SourceError("notfound", "Wikidata doesn't know this title.")
        s = summarize(ent, lang)
        if not s:
            raise net.SourceError("notfound", "This Wikidata item isn't a movie or series.")
        ids = {"wikidata": qid,
               "imdb": next((v for v in _vals(ent, "P345") if isinstance(v, str) and re.fullmatch(r"tt\d{5,10}", v)), None),
               "tmdb": next((v for v in _vals(ent, "P4947" if s["kind"] == "movie" else "P4983")
                             if isinstance(v, str) and v.isdigit()), None)}
        runtime = next((int(float(v["amount"])) for v in _vals(ent, "P2047") if isinstance(v, dict) and v.get("amount")), None)
        return {"summary": s, "ids": ids, "runtime": runtime, "platforms": platforms(ent, s["kind"]),
                "article": ((ent.get("sitelinks") or {}).get("enwiki") or {}).get("title")}
