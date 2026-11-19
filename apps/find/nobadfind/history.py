"""Your own search questions, kept for autocomplete (maintainer decision 2026-11-19).

Only what you typed into NOBAD Find and committed (Enter, opening a result, picking a suggestion), stored inside the
encrypted index (SQLCipher, table search_history), capped at CAP entries, oldest dropped first. Setting
search_history (on by default); turning it off deletes what was kept. "Clear search history" in Settings > Privacy,
and the x on a suggestion forgets one. This is not activity history: nothing from Windows, browsers or other
programs is read (that stays out of scope, apps/find/AGENTS.md).
"""
import re
import time

CAP = 200
MIN_LEN, MAX_LEN = 2, 200


def clean(text):
    """The question as it will be kept: one line, single spaces, at most MAX_LEN characters; "" if not worth it."""
    if not isinstance(text, str):
        return ""
    t = re.sub(r"\s+", " ", text).strip()[:MAX_LEN].strip()
    return t if len(t) >= MIN_LEN and any(ch.isalnum() for ch in t) else ""


def add(store, text, now=None):
    t = clean(text)
    if not t:
        return False
    now = time.time() if now is None else now
    with store.wlock:
        store.db.execute("INSERT INTO search_history(k, q, n, last) VALUES(?, ?, 1, ?) ON CONFLICT(k) DO UPDATE SET "
                         "q = excluded.q, n = n + 1, last = excluded.last", (t.lower(), t, now))
        store.db.execute("DELETE FROM search_history WHERE k NOT IN (SELECT k FROM search_history ORDER BY last DESC "
                         "LIMIT ?)", (CAP,))
        store.db.commit()
    return True


def forget(store, text):
    t = clean(text)
    if not t:
        return False
    with store.wlock:
        n = store.db.execute("DELETE FROM search_history WHERE k = ?", (t.lower(),)).rowcount
        store.db.commit()
    return n > 0


def clear(store):
    with store.wlock:
        store.db.execute("DELETE FROM search_history")
        store.db.commit()


def count(store):
    return store.one("SELECT count(*) FROM search_history") or 0


def _like(t):
    return t.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def match(store, text, limit=5):
    """Kept questions for what's typed: ones that start with it first (most recent first), then ones with a word
    that starts with it. Empty text: the most recent ones."""
    t = re.sub(r"\s+", " ", text or "").strip().lower()
    if not t:
        return [r[0] for r in store.q("SELECT q FROM search_history ORDER BY last DESC LIMIT ?", (limit,))]
    out = [r[0] for r in store.q("SELECT q FROM search_history WHERE k LIKE ? ESCAPE '\\' AND k != ? "
                                 "ORDER BY last DESC, n DESC LIMIT ?", (_like(t) + "%", t, limit))]
    if len(out) < limit:
        more = store.q("SELECT q FROM search_history WHERE k LIKE ? ESCAPE '\\' AND k NOT LIKE ? ESCAPE '\\' "
                       "ORDER BY last DESC LIMIT ?", ("% " + _like(t) + "%", _like(t) + "%", limit - len(out)))
        out += [r[0] for r in more]
    return out
