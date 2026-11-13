"""TMDB API v3 client (https://developer.themoviedb.org). Needs the user's own key: a v3 API key (query parameter)
or a v4 Read Access Token (Bearer). TMDB's licence is non-transferable, so NOBAD never ships a shared key.

Attribution required by TMDB is shown in the UI: the TMDB notice for all TMDB data, and "JustWatch" for the
watch-provider data, which TMDB sources from JustWatch."""
import math
import re

from . import net

# TMDB serves the API on two names. Some ISPs (seen on Indian networks) reset TLS connections by the name
# 'themoviedb.org' while 'tmdb.org' on the same servers works, so tmdb.org goes first and the other is the fallback.
APIS = ("https://api.tmdb.org/3", "https://api.themoviedb.org/3")
IMG = "https://image.tmdb.org/t/p"
NOTICE = "This product uses the TMDB API but is not endorsed or certified by TMDB."
WATCH_ATTRIBUTION = "Streaming availability data provided by JustWatch (via TMDB)."
KINDS = ("movie", "tv")

# TMDB genre ids that are stable across the API (documented in /genre/movie/list and /genre/tv/list).
G_ANIMATION, G_DOCUMENTARY, G_KIDS, G_FAMILY = 16, 99, 10762, 10751


class TMDB:
    def __init__(self, credential, language="en-US", opener=None, sleep=None):
        if not credential:
            raise net.SourceError("auth", "No TMDB key configured")
        self.cred = credential.strip()
        self.language = language or "en-US"
        self.opener, self.sleep = opener, sleep

    _preferred = 0      # index into APIS that worked last (shared: the network is the same for every instance)

    def _get(self, path, **params):
        headers = {}
        if self.cred.startswith("eyJ"):                   # v4 Read Access Token (a JWT)
            headers["Authorization"] = "Bearer " + self.cred
        else:
            params["api_key"] = self.cred
        kw = {"opener": self.opener}
        if self.sleep:
            kw["sleep"] = self.sleep
        clean = {k: v for k, v in params.items() if v is not None}
        order = [TMDB._preferred] + [i for i in range(len(APIS)) if i != TMDB._preferred]
        last = None
        for i in order:
            try:
                d = net.get_json(APIS[i] + path, clean, headers, **kw)
                TMDB._preferred = i
                return d
            except net.SourceError as e:
                if e.kind != "unavailable":          # auth / not found / rate limit: same answer on the other name
                    raise
                last = e
        raise last

    # ---- calls -------------------------------------------------------------------------------------------
    def validate(self):
        d = self._get("/authentication")
        return bool(d.get("success", True))

    def search(self, query, year=None, page=1):
        """Movies and series together. With a year, the typed endpoints are used because multi-search ignores it."""
        common = {"query": query, "include_adult": "false", "language": self.language, "page": page}
        if year:
            out = []
            for kind, yk in (("movie", "primary_release_year"), ("tv", "first_air_date_year")):
                d = self._get(f"/search/{kind}", **common, **{yk: year})
                out += [dict(r, media_type=kind) for r in d.get("results", [])]
            return out
        d = self._get("/search/multi", **common)
        return [r for r in d.get("results", []) if r.get("media_type") in KINDS]

    def find_external(self, imdb_id):
        d = self._get(f"/find/{imdb_id}", external_source="imdb_id", language=self.language)
        return ([dict(r, media_type="movie") for r in d.get("movie_results", [])] +
                [dict(r, media_type="tv") for r in d.get("tv_results", [])])

    def details(self, kind, tmdb_id):
        """One request: metadata + alternative titles + external ids + certifications + watch providers."""
        if kind not in KINDS:
            raise net.SourceError("bad", f"unknown kind {kind!r}")
        extra = "alternative_titles,external_ids,watch/providers," + ("release_dates" if kind == "movie" else "content_ratings")
        return self._get(f"/{kind}/{int(tmdb_id)}", language=self.language, append_to_response=extra)

    def watch_regions(self):
        return self._get("/watch/providers/regions", language=self.language).get("results", [])

    def countries(self):
        return self._get("/configuration/countries", language=self.language)

    def providers(self, kind, region=None):
        return self._get(f"/watch/providers/{kind}", language=self.language, watch_region=region).get("results", [])


# ---- normalisation -----------------------------------------------------------------------------------------
YEAR_RE = re.compile(r"^(?P<q>.+?)\s*[\(\[]?(?P<y>(?:19|20)\d{2})[\)\]]?$")
IMDB_RE = re.compile(r"(tt\d{6,10})")


def parse_query(q):
    """'Dune (2021)' -> ('Dune', 2021); an IMDb id or URL -> ('tt1160419', None, imdb=True)."""
    q = " ".join((q or "").split())[:200]
    m = IMDB_RE.search(q)
    if m:
        return m.group(1), None, True
    m = YEAR_RE.match(q)
    if m and len(m.group("q")) >= 2:
        return m.group("q").strip(" -:"), int(m.group("y")), False
    return q, None, False


def fold(s):
    s = (s or "").casefold()
    s = re.sub(r"[’'`]", "", s)
    return " ".join(re.sub(r"[^\w]+", " ", s).split())


def year_of(r):
    d = r.get("release_date") or r.get("first_air_date") or ""
    return int(d[:4]) if d[:4].isdigit() else None


def content_type(r, kind):
    """Movie / Series / Anime / Animated series / Animated film / Documentary / Kids. 'Anime' is an inference
    (Japanese-language animation), so it is flagged as such."""
    genres = set(r.get("genre_ids") or [g.get("id") for g in r.get("genres", [])])
    lang = (r.get("original_language") or "").lower()
    origin = [c.upper() for c in (r.get("origin_country") or [])] + \
             [c.get("iso_3166_1", "").upper() for c in (r.get("production_countries") or [])]
    if G_ANIMATION in genres and (lang == "ja" or "JP" in origin):
        return {"label": "Anime", "inferred": True, "basis": "Japanese animation (genre + original language/origin)"}
    if G_ANIMATION in genres:
        return {"label": "Animated series" if kind == "tv" else "Animated film", "inferred": False, "basis": "TMDB genre"}
    if G_DOCUMENTARY in genres:
        return {"label": "Documentary series" if kind == "tv" else "Documentary", "inferred": False, "basis": "TMDB genre"}
    if G_KIDS in genres:
        return {"label": "Kids series", "inferred": False, "basis": "TMDB genre"}
    return {"label": "Series" if kind == "tv" else "Movie", "inferred": False, "basis": "TMDB type"}


def poster(path):
    """Local proxy path (the UI's CSP only allows same-origin images); None when TMDB has no poster."""
    if not path or not re.fullmatch(r"/[A-Za-z0-9_\-]{5,80}\.(jpg|png|svg)", path):
        return None
    return path.lstrip("/")


def summary(r):
    kind = r.get("media_type")
    title = r.get("title") or r.get("name") or ""
    original = r.get("original_title") or r.get("original_name") or ""
    return {"key": f"{kind}:{int(r['id'])}", "kind": kind, "id": int(r["id"]), "title": title,
            "original_title": original if fold(original) != fold(title) else None,
            "year": year_of(r), "type": content_type(r, kind), "poster": poster(r.get("poster_path")),
            "overview": (r.get("overview") or "")[:400], "popularity": r.get("popularity") or 0,
            "votes": r.get("vote_count") or 0, "language": r.get("original_language")}


def rank(results, query, year=None):
    """De-duplicate by TMDB identity, then order: exact title match, year match, then TMDB relevance/popularity."""
    fq, seen, out = fold(query), set(), []
    for i, r in enumerate(results):
        if r.get("media_type") not in KINDS or not r.get("id"):
            continue
        s = summary(r)
        if s["key"] in seen:
            continue
        seen.add(s["key"])
        exact = fq in (fold(s["title"]), fold(s["original_title"] or ""))
        starts = not exact and fold(s["title"]).startswith(fq + " ")
        # an exact title helps, but an obscure exact match must not bury the famous title people mean
        fame = math.log10(1 + s["votes"]) * 0.8 + math.log10(1 + s["popularity"]) * 0.4
        score = (1.5 if exact else 0.8 if starts else 0) + (3 if year and s["year"] == year else 0) - i * 0.05 + fame
        out.append((score, s))
    return [s for _sc, s in sorted(out, key=lambda x: -x[0])]


def normalize_details(d, kind):
    alt = (d.get("alternative_titles") or {})
    alts = alt.get("titles") or alt.get("results") or []
    title = d.get("title") or d.get("name") or ""
    seen, alt_titles = {fold(title)}, []
    for a in alts:
        t = (a.get("title") or "").strip()
        if t and fold(t) not in seen:
            seen.add(fold(t))
            alt_titles.append({"title": t, "country": a.get("iso_3166_1"), "type": a.get("type") or None})
    ext = d.get("external_ids") or {}
    base = dict(d, media_type=kind)
    s = summary(base)
    s["overview"] = d.get("overview") or ""
    s.update({
        "alternative_titles": alt_titles[:60],
        "genres": [g.get("name") for g in d.get("genres", []) if g.get("name")],
        "runtime": d.get("runtime") or (d.get("episode_run_time") or [None])[0],
        "seasons": d.get("number_of_seasons"), "episodes": d.get("number_of_episodes"),
        "status": d.get("status"), "origin_countries": d.get("origin_country") or
        [c.get("iso_3166_1") for c in d.get("production_countries", [])],
        "ids": {"tmdb": int(d["id"]), "imdb": ext.get("imdb_id") or d.get("imdb_id"), "wikidata": ext.get("wikidata_id"),
                "tvdb": ext.get("tvdb_id")},
        "tmdb_url": f"https://www.themoviedb.org/{kind}/{int(d['id'])}",
    })
    return s


def certifications(d, kind):
    """Per-country age certifications as published on TMDB (community-maintained from rating boards)."""
    out = []
    if kind == "movie":
        for c in (d.get("release_dates") or {}).get("results", []):
            certs = sorted({x.get("certification", "").strip() for x in c.get("release_dates", []) if x.get("certification")})
            if certs:
                out.append({"country": c.get("iso_3166_1"), "rating": " / ".join(certs)})
    else:
        for c in (d.get("content_ratings") or {}).get("results", []):
            if (c.get("rating") or "").strip():
                out.append({"country": c.get("iso_3166_1"), "rating": c["rating"].strip(),
                            "descriptors": c.get("descriptors") or []})
    return out
