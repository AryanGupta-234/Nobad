"""Local cache (SQLite) and the encrypted TMDB credential.

Every cached value keeps the time it was fetched, so the UI can show its age and stale data is never shown as
current. TMDB's terms forbid caching its content for longer than six months: `purge()` enforces that hard limit
on every start, independently of the much shorter per-kind freshness windows below."""
import json
import os
import sqlite3
import threading
import time

from .. import dpapi
from ..const import DATA_DIR

ROOT = os.path.join(DATA_DIR, "streamintel")
HARD_MAX_AGE = 180 * 86400          # TMDB API terms: no TMDB content cached for longer than 6 months

# How long a cached answer counts as fresh. Availability changes daily, so it is kept short.
TTL = {
    "search": 86400,
    "title": 3 * 86400,             # metadata, alternative titles, external ids, certifications
    "avail": 12 * 3600,             # watch providers per country (JustWatch via TMDB)
    "regions": 7 * 86400,           # countries the availability source covers
    "countries": 30 * 86400,
    "providers": 7 * 86400,
    "wiki_index": 7 * 86400,        # parsed Wikipedia restriction lists
    "wiki_title": 7 * 86400,        # Wikidata QID -> article title + redirects
}


class Cache:
    def __init__(self, path=None, clock=time.time):
        self.path = path or os.path.join(ROOT, "cache.sqlite")
        self.clock = clock
        self.lock = threading.Lock()
        if self.path != ":memory:":
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        with self.lock:
            self.db.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT NOT NULL, ts REAL NOT NULL, src TEXT)")
            self.db.commit()

    def get(self, key, kind, allow_stale=False):
        """(value, fetched_ts, fresh) or None. Stale values only come back with allow_stale=True (used as a
        clearly labelled fallback when a source is down) and never beyond the hard six-month limit."""
        with self.lock:
            row = self.db.execute("SELECT v, ts FROM kv WHERE k=?", (key,)).fetchone()
        if not row:
            return None
        age = self.clock() - row[1]
        if age > HARD_MAX_AGE:
            self.delete(key)
            return None
        fresh = age <= TTL[kind]
        if not fresh and not allow_stale:
            return None
        return json.loads(row[0]), row[1], fresh

    def put(self, key, value, source=""):
        ts = self.clock()
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO kv (k, v, ts, src) VALUES (?,?,?,?)",
                            (key, json.dumps(value, separators=(",", ":")), ts, source))
            self.db.commit()
        return ts

    def delete(self, key):
        with self.lock:
            self.db.execute("DELETE FROM kv WHERE k=?", (key,))
            self.db.commit()

    def purge(self, max_age=HARD_MAX_AGE):
        with self.lock:
            n = self.db.execute("DELETE FROM kv WHERE ts < ?", (self.clock() - max_age,)).rowcount
            self.db.commit()
        return n

    def clear(self):
        with self.lock:
            self.db.execute("DELETE FROM kv")
            self.db.commit()

    def stats(self):
        with self.lock:
            n, oldest = self.db.execute("SELECT COUNT(*), MIN(ts) FROM kv").fetchone()
        return {"entries": n, "oldest": oldest}


class Credential:
    """The user's own TMDB API key (v3) or Read Access Token (v4). Kept OUT of settings.json, because settings are
    pushed to the UI and included in diagnostics. Stored DPAPI-encrypted (machine scope) in the admin-only data
    folder. NOBAD_TMDB_TOKEN overrides it for development and CI."""
    DESC = "NOBAD streaming intelligence: TMDB credential"

    def __init__(self, path=None):
        self.path = path or os.path.join(ROOT, "tmdb.credential")

    def get(self):
        env = os.environ.get("NOBAD_TMDB_TOKEN", "").strip()
        if env:
            return env
        try:
            with open(self.path, "rb") as f:
                blob = f.read()
        except OSError:
            return None
        try:
            if blob.startswith(b"plain:"):
                return blob[6:].decode("utf-8").strip() or None
            return dpapi.unprotect(blob, self.DESC).decode("utf-8").strip() or None
        except Exception:
            return None

    def set(self, value):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        data = value.strip().encode("utf-8")
        try:
            blob = dpapi.protect(data, self.DESC)
        except Exception:
            blob = b"plain:" + data           # non-Windows dev runs; the folder is still admin-only on Windows
        dpapi.write_atomic(self.path, blob)

    def clear(self):
        try:
            dpapi.wipe_and_remove(self.path)
        except OSError:
            pass

    def source(self):
        if os.environ.get("NOBAD_TMDB_TOKEN", "").strip():
            return "environment"
        return "saved" if os.path.exists(self.path) else None


def mask(cred):
    if not cred:
        return None
    return cred[:4] + "…" + cred[-4:] if len(cred) > 12 else "…"
