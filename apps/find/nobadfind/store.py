"""The index: one SQLite database, encrypted with SQLCipher when available, key protected with Windows DPAPI.

Tables
  files   every file and folder seen (path, name, size, times, kind)        + names  (FTS5 trigram: any part of a name)
  chunks  pieces of text read from inside files                           + text   (FTS5 words, with stemming)
  vecs    meaning-search vectors for chunks (float16)
"""
import os
import secrets
import sqlite3
import threading
import time

from . import winapi
from .log import log

try:
    import sqlcipher3 as _cipher
except ImportError:          # development without SQLCipher: the UI says plainly that the index isn't encrypted
    _cipher = None

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS files(
  id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE, name TEXT NOT NULL, dir TEXT NOT NULL, ext TEXT,
  kind TEXT, size INTEGER, mtime REAL, ctime REAL, gen INTEGER DEFAULT 0, text_mtime REAL, text_err TEXT);
CREATE INDEX IF NOT EXISTS files_mtime ON files(mtime);
CREATE INDEX IF NOT EXISTS files_kind ON files(kind);
CREATE VIRTUAL TABLE IF NOT EXISTS names USING fts5(name, dir, content='files', content_rowid='id',
  tokenize='trigram');
CREATE TRIGGER IF NOT EXISTS files_ai AFTER INSERT ON files BEGIN
  INSERT INTO names(rowid, name, dir) VALUES (new.id, new.name, new.dir); END;
CREATE TRIGGER IF NOT EXISTS files_ad AFTER DELETE ON files BEGIN
  INSERT INTO names(names, rowid, name, dir) VALUES ('delete', old.id, old.name, old.dir);
  DELETE FROM chunks WHERE file_id = old.id; END;
CREATE TRIGGER IF NOT EXISTS files_au AFTER UPDATE OF name, dir ON files BEGIN
  INSERT INTO names(names, rowid, name, dir) VALUES ('delete', old.id, old.name, old.dir);
  INSERT INTO names(rowid, name, dir) VALUES (new.id, new.name, new.dir); END;
CREATE TABLE IF NOT EXISTS chunks(id INTEGER PRIMARY KEY, file_id INTEGER NOT NULL, ord INTEGER, body TEXT);
CREATE INDEX IF NOT EXISTS chunks_file ON chunks(file_id);
CREATE VIRTUAL TABLE IF NOT EXISTS text USING fts5(body, content='chunks', content_rowid='id',
  tokenize='porter unicode61 remove_diacritics 2');
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
  INSERT INTO text(rowid, body) VALUES (new.id, new.body); END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
  INSERT INTO text(text, rowid, body) VALUES ('delete', old.id, old.body);
  DELETE FROM vecs WHERE chunk_id = old.id; END;
CREATE TABLE IF NOT EXISTS vecs(chunk_id INTEGER PRIMARY KEY, v BLOB NOT NULL);
"""


def fts_quote(term):
    """One FTS5 string literal: the term is always data, never query syntax."""
    return '"' + term.replace('"', '""') + '"'


def _load_key(key_path):
    """32 random bytes, stored only DPAPI-protected (readable by this Windows account on this PC)."""
    if os.path.exists(key_path):
        with open(key_path, "rb") as f:
            return winapi.dpapi_unprotect(f.read())
    key = secrets.token_bytes(32)
    os.makedirs(os.path.dirname(key_path), exist_ok=True)
    tmp = key_path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(winapi.dpapi_protect(key))
    os.replace(tmp, key_path)
    return key


class Store:
    def __init__(self, db_path, key_path=None, encrypt=True):
        self.db_path = db_path
        self.encrypted = bool(encrypt and _cipher and winapi.WIN)
        self._key = None
        if self.encrypted:
            try:
                self._key = _load_key(key_path or db_path + ".key")
            except OSError as e:
                # the key belongs to another account or PC: keep the old index aside and start a new one
                log(f"index key unreadable ({e}); starting a new index", "warn")
                stamp = time.strftime("%Y%m%d-%H%M%S")
                for p in (db_path, key_path):
                    if p and os.path.exists(p):
                        os.replace(p, f"{p}.unreadable-{stamp}")
                self._key = _load_key(key_path or db_path + ".key")
        self._local = threading.local()
        self.wlock = threading.RLock()
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        with self.wlock:
            self.db.executescript(SCHEMA)

    # ---------- connections: one per thread ----------
    @property
    def db(self):
        c = getattr(self._local, "c", None)
        if c is None:
            mod = _cipher if self.encrypted else sqlite3
            c = mod.connect(self.db_path, timeout=30, check_same_thread=False)
            if self.encrypted:
                c.execute(f"PRAGMA key = \"x'{self._key.hex()}'\"")
            c.execute("PRAGMA foreign_keys=OFF")
            c.execute("PRAGMA busy_timeout=30000")
            self._local.c = c
        return c

    def close(self):
        c = getattr(self._local, "c", None)
        if c is not None:
            c.close()
            self._local.c = None

    def q(self, sql, args=()):
        return self.db.execute(sql, args).fetchall()

    def one(self, sql, args=()):
        r = self.db.execute(sql, args).fetchone()
        return r[0] if r else None

    def meta(self, k, default=None):
        v = self.one("SELECT v FROM meta WHERE k=?", (k,))
        return default if v is None else v

    def set_meta(self, k, v):
        with self.wlock:
            self.db.execute("INSERT INTO meta(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v)))
            self.db.commit()

    # ---------- files ----------
    def upsert_files(self, rows):
        """rows: (path, name, dir, ext, kind, size, mtime, ctime, gen). A changed mtime makes the text stale."""
        if not rows:
            return
        with self.wlock:
            self.db.executemany(
                "INSERT INTO files(path,name,dir,ext,kind,size,mtime,ctime,gen) VALUES(?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(path) DO UPDATE SET size=excluded.size, mtime=excluded.mtime, ctime=excluded.ctime, "
                "gen=excluded.gen, kind=excluded.kind, name=excluded.name, dir=excluded.dir, ext=excluded.ext",
                rows)
            self.db.commit()

    def drop_unseen(self, root, gen):
        """Delete files under root that the latest full scan (generation gen) didn't see."""
        like = root.rstrip("\\/").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "\\\\%"
        with self.wlock:
            n = self.db.execute("DELETE FROM files WHERE gen < ? AND (path LIKE ? ESCAPE '\\' OR path = ?)",
                                (gen, like, root)).rowcount
            self.db.commit()
        return n

    def remove_paths(self, paths):
        with self.wlock:
            for p in paths:
                like = p.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "\\\\%"
                self.db.execute("DELETE FROM files WHERE path = ? OR path LIKE ? ESCAPE '\\'", (p, like))
            self.db.commit()

    def needs_text(self, kinds_ext, max_bytes, limit=500):
        marks = ",".join("?" * len(kinds_ext))
        return self.q(
            f"SELECT id, path, ext, size, mtime FROM files WHERE ext IN ({marks}) AND size <= ? "
            "AND (text_mtime IS NULL OR text_mtime <> mtime) ORDER BY mtime DESC LIMIT ?",
            (*sorted(kinds_ext), max_bytes, limit))

    def set_text(self, file_id, mtime, chunks, err=None):
        with self.wlock:
            self.db.execute("DELETE FROM chunks WHERE file_id=?", (file_id,))
            self.db.executemany("INSERT INTO chunks(file_id, ord, body) VALUES(?,?,?)",
                                [(file_id, i, c) for i, c in enumerate(chunks)])
            self.db.execute("UPDATE files SET text_mtime=?, text_err=? WHERE id=?", (mtime, err, file_id))
            self.db.commit()

    def chunks_without_vectors(self, limit=256):
        return self.q("SELECT c.id, c.body FROM chunks c LEFT JOIN vecs v ON v.chunk_id=c.id "
                      "WHERE v.chunk_id IS NULL LIMIT ?", (limit,))

    def add_vectors(self, rows):
        with self.wlock:
            self.db.executemany("INSERT OR REPLACE INTO vecs(chunk_id, v) VALUES(?,?)", rows)
            self.db.commit()

    # ---------- forgetting ----------
    def forget_path(self, path):
        self.remove_paths([path])

    def wipe(self):
        with self.wlock:
            for t in ("vecs", "chunks", "files", "meta"):
                self.db.execute(f"DELETE FROM {t}")
            self.db.execute("INSERT INTO names(names) VALUES('rebuild')")
            self.db.execute("INSERT INTO text(text) VALUES('rebuild')")
            self.db.commit()
            self.db.execute("VACUUM")

    def stats(self):
        return {
            "files": self.one("SELECT count(*) FROM files") or 0,
            "with_text": self.one("SELECT count(*) FROM files WHERE text_mtime IS NOT NULL AND text_err IS NULL") or 0,
            "chunks": self.one("SELECT count(*) FROM chunks") or 0,
            "vectors": self.one("SELECT count(*) FROM vecs") or 0,
            "encrypted": self.encrypted,
            "db_bytes": sum(os.path.getsize(p) for p in (self.db_path, self.db_path + "-wal") if os.path.exists(p)),
        }

