"""Orchestrates the data sources for the UI: search, a title report (metadata + availability + VPN match), and the
restriction records, each with its source, fetch time and freshness. When a source fails, a cached answer is used
only if one exists, and it is marked stale; otherwise the error is reported. Nothing is ever made up."""
import os
import re
import threading
import time

from . import availability, net, recommend, restrictions, servers, store, tmdb
from .countries import Countries

IMG_SIZES = {"w92", "w154", "w185", "w342"}
IMG_FILE = re.compile(r"[A-Za-z0-9_\-]{5,80}\.(jpg|png|svg)")
IMG_MAX = 2_000_000


class NoKey(Exception):
    pass


class StreamIntel:
    def __init__(self, cache=None, credential=None, tmdb_factory=None, wiki=None, clock=time.time, img_dir=None):
        self.cache = cache or store.Cache()
        self.cred = credential or store.Credential()
        self.tmdb_factory = tmdb_factory or (lambda key, lang: tmdb.TMDB(key, lang))
        self.wiki = wiki or restrictions.WikiSource()
        self.clock = clock
        self.img_dir = img_dir or os.path.join(store.ROOT, "img")
        self._index_lock = threading.Lock()
        self.cache.purge()

    # ---- credentials -------------------------------------------------------------------------------------
    def status(self):
        key = self.cred.get()
        return {"configured": bool(key), "key_hint": store.mask(key), "key_source": self.cred.source(),
                "cache": self.cache.stats(), "notice": tmdb.NOTICE, "watch_attribution": tmdb.WATCH_ATTRIBUTION,
                "restrictions_license": restrictions.LICENSE}

    def set_key(self, key, language="en-US"):
        key = (key or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9._\-]{16,600}", key):
            return {"ok": False, "error": "That doesn't look like a TMDB API key or Read Access Token."}
        try:
            self.tmdb_factory(key, language).validate()
        except net.SourceError as e:
            msg = {"auth": "TMDB rejected this key.", "rate": "TMDB is rate-limiting requests; try again in a minute.",
                   "unavailable": "Couldn't reach TMDB to check the key."}.get(e.kind, f"TMDB error: {e}")
            return {"ok": False, "error": msg}
        self.cred.set(key)
        return {"ok": True, "key_hint": store.mask(key)}

    def clear_key(self):
        self.cred.clear()
        return {"ok": True}

    def _api(self, language):
        key = self.cred.get()
        if not key:
            raise NoKey()
        return self.tmdb_factory(key, language)

    # ---- cached fetch helper --------------------------------------------------------------------------------
    def _cached(self, key, kind, fetch, source):
        hit = self.cache.get(key, kind)
        if hit:
            return hit[0], hit[1], True
        try:
            val = fetch()
        except net.SourceError as e:
            stale = self.cache.get(key, kind, allow_stale=True)
            if stale and e.kind != "auth":
                return stale[0], stale[1], False
            raise
        return val, self.cache.put(key, val, source), True

    def countries(self, language="en-US"):
        try:
            lst, _ts, _f = self._cached(f"countries:{language}", "countries", lambda: self._api(language).countries(), "tmdb")
        except (net.SourceError, NoKey):
            lst = []
        return Countries(lst)

    def covered_regions(self, language="en-US"):
        lst, _ts, _f = self._cached(f"regions:{language}", "regions", lambda: self._api(language).watch_regions(), "tmdb")
        return [r.get("iso_3166_1") for r in lst if r.get("iso_3166_1")]

    # ---- search -------------------------------------------------------------------------------------------
    def search(self, query, language="en-US"):
        q, year, is_imdb = tmdb.parse_query(query)
        if len(q) < 2:
            return {"ok": False, "error": "Type at least two characters."}
        api = self._api(language)
        ck = f"search:{language}:{q.casefold()}:{year or ''}"
        raw, ts, fresh = self._cached(ck, "search", (lambda: api.find_external(q)) if is_imdb else (lambda: api.search(q, year)), "tmdb")
        return {"ok": True, "query": q, "year": year, "results": tmdb.rank(raw, q, year)[:20], "fetched": ts, "fresh": fresh}

    # ---- title report -------------------------------------------------------------------------------------
    def report(self, kind, tmdb_id, tunnel, smart, settings, force=False):
        language = settings.get("si_language") or "en-US"
        api = self._api(language)
        ck = f"details:{language}:{kind}:{int(tmdb_id)}"
        if force:
            self.cache.delete(ck)
        raw, fetched, fresh = self._cached(ck, "avail", lambda: api.details(kind, tmdb_id), "tmdb")
        countries = self.countries(language)
        try:
            covered = self.covered_regions(language)
            coverage_ok = True
        except net.SourceError:
            covered, coverage_ok = [], False
        title = tmdb.normalize_details(raw, kind)
        av = availability.build(raw.get("watch/providers"), covered, countries, fetched, fresh=fresh and
                                (self.clock() - fetched) <= store.TTL["avail"])
        av["coverage_known"] = coverage_ok
        inv = servers.inventory(tunnel, smart, countries)
        home = ((getattr(tunnel, "home", None) or {}).get("country") or "").upper() or None
        rec = recommend.recommend(av, inv, None, settings.get("si_my_services") or [], home)
        return {"ok": True, "key": f"{kind}:{int(tmdb_id)}", "title": title, "availability": av,
                "certifications": [dict(c, name=countries.name(c["country"])) for c in tmdb.certifications(raw, kind)],
                "servers": inv, "recommendation": rec, "home_country": home,
                "restrictions": {"status": "loading"}, "generated": self.clock()}

    def restriction_doc(self, title, countries):
        qid = (title.get("ids") or {}).get("wikidata")
        if not qid:
            return {"status": "no-identity", "records": [],
                    "note": "TMDB has no Wikidata link for this title, so restriction records can't be matched safely."}
        try:
            with self._index_lock:
                idx, built, fresh = self._cached("wiki_index:v1", "wiki_index", lambda: self.wiki.build_index(countries),
                                                 "wikipedia")
            art, _ts, _f = self._cached(f"wiki_title:{qid}", "wiki_title", lambda: list(self.wiki.article_for(qid)), "wikidata")
        except net.SourceError as e:
            return {"status": "unavailable", "records": [], "error": str(e),
                    "note": "Restriction records couldn't be loaded. That is not the same as 'no restrictions'."}
        article, redirects = art[0], art[1]
        if not article:
            return {"status": "no-article", "records": [], "qid": qid,
                    "note": "This title has no English Wikipedia article, so no restriction records were matched."}
        recs = restrictions.match(idx, article, redirects)
        for r in recs:
            if not r.get("code") and r.get("country"):
                r["code"] = countries.code(r["country"])
        return {"status": "ok", "records": recs, "qid": qid, "article": article,
                "index_built": idx.get("built", built), "index_fresh": fresh, "pages": len(idx.get("pages", [])),
                "failed_pages": idx.get("failed", []),
                "note": "Documented in Wikipedia's banned-film lists (a secondary source); see each record's citations."}

    def with_restrictions(self, rep, tunnel, smart, settings):
        language = settings.get("si_language") or "en-US"
        countries = self.countries(language)
        doc = self.restriction_doc(rep["title"], countries)
        for r in doc["records"]:
            r["country_name"] = countries.name(r["code"]) if r.get("code") else r.get("country")
        rec = recommend.recommend(rep["availability"], rep["servers"], doc, settings.get("si_my_services") or [],
                                  rep["home_country"])
        return doc, rec

    # ---- provider catalogue for the "my services" picker ---------------------------------------------------
    def provider_catalog(self, region, language="en-US"):
        api = self._api(language)
        region = (region or "").upper() or None
        out = {}
        for kind in ("movie", "tv"):
            lst, _ts, _f = self._cached(f"providers:{language}:{kind}:{region or 'all'}", "providers",
                                        lambda k=kind: api.providers(k, region), "tmdb")
            for p in lst:
                try:
                    pid = int(p.get("provider_id"))
                except (TypeError, ValueError):
                    continue
                out.setdefault(pid, {"id": pid, "name": p.get("provider_name"),
                                                  "family": availability.family(p.get("provider_name")),
                                                  "logo": (p.get("logo_path") or "").lstrip("/") or None})
        return sorted(out.values(), key=lambda p: (p["name"] or "").casefold())

    # ---- images (served through the local server; the UI's CSP blocks remote images) -------------------------
    def image(self, size, name, opener=None):
        if size not in IMG_SIZES or not IMG_FILE.fullmatch(name or ""):
            return None
        path = os.path.join(self.img_dir, f"{size}_{name}")
        try:
            if self.clock() - os.path.getmtime(path) < store.HARD_MAX_AGE:
                with open(path, "rb") as f:
                    return f.read()
        except OSError:
            pass
        try:
            data = net.get_bytes(f"{tmdb.IMG}/{size}/{name}", headers={"Accept": "image/*"}, opener=opener, max_bytes=IMG_MAX)
        except net.SourceError:
            return None
        if not (data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n" or data.lstrip()[:4] in (b"<svg", b"<?xm")):
            return None
        try:
            os.makedirs(self.img_dir, exist_ok=True)
            with open(path + ".tmp", "wb") as f:
                f.write(data)
            os.replace(path + ".tmp", path)
        except OSError:
            pass
        return data

    def clear_cache(self):
        self.cache.clear()
        try:
            for n in os.listdir(self.img_dir):
                os.remove(os.path.join(self.img_dir, n))
        except OSError:
            pass
        return {"ok": True}
