"""Search: name matches + text matches + meaning matches, merged by reciprocal rank fusion.

Each result says why it matched, in plain words, and only claims what was actually measured.
Snippets mark matches with \\x02 ... \\x03; the UI escapes the text first and only then turns those into <mark>.
"""
import time

from .query import parse
from .store import fts_quote

RRF_K = 60
W_NAME, W_TEXT, W_MEANING = 1.3, 1.0, 0.8
MIN_MEANING = 0.35             # below this cosine similarity a "meaning" match isn't worth showing


def _filters(q, alias="f"):
    sql, args = [], []
    if q.kinds:
        sql.append(f"{alias}.kind IN ({','.join('?' * len(q.kinds))})")
        args += sorted(q.kinds)
    if q.exts:
        sql.append(f"{alias}.ext IN ({','.join('?' * len(q.exts))})")
        args += sorted(q.exts)
    if q.t0 is not None:
        sql.append(f"(({alias}.mtime BETWEEN ? AND ?) OR ({alias}.ctime BETWEEN ? AND ?))")
        args += [q.t0, q.t1, q.t0, q.t1]
    return (" AND " + " AND ".join(sql)) if sql else "", args


def _name_hits(store, q, limit):
    long_terms = [t for t in q.terms + q.phrases if len(t) >= 3]
    short = [t for t in q.terms if len(t) < 3]
    if not long_terms and not short:
        return []
    where, args = _filters(q)
    parts, pargs = [], []
    if long_terms:
        parts.append("f.id IN (SELECT rowid FROM names WHERE names MATCH ?)")
        pargs.append(" ".join("name:" + fts_quote(t) for t in long_terms))
    for t in short:
        parts.append("f.name LIKE ? ESCAPE '\\'")
        pargs.append("%" + t.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
    # shorter names and recently changed files first among equal matches
    rows = store.q(f"SELECT f.id FROM files f WHERE {' AND '.join(parts)}{where} "
                   "ORDER BY length(f.name), f.mtime DESC LIMIT ?", (*pargs, *args, limit))
    return [r[0] for r in rows]


def _text_hits(store, q, limit):
    words = [t for t in q.terms if len(t) >= 2] + q.phrases
    if not words:
        return [], {}
    match = " AND ".join(fts_quote(w) for w in words)
    where, args = _filters(q)
    # bm25() can't sit inside GROUP BY, so rank chunks first and keep each file's best chunk here
    rows = store.q(
        "SELECT c.file_id, t.score, t.snip FROM (SELECT rowid, bm25(text) AS score, "
        "snippet(text, 0, char(2), char(3), '…', 14) AS snip FROM text WHERE text MATCH ? ORDER BY score LIMIT ?) t "
        f"JOIN chunks c ON c.id = t.rowid JOIN files f ON f.id = c.file_id WHERE 1=1{where} ORDER BY t.score",
        (match, limit * 5, *args))
    order, snips = [], {}
    for fid, _score, snip in rows:
        if fid not in snips:
            snips[fid] = snip
            order.append(fid)
    return order[:limit], snips


def _meaning_hits(store, q, embedder, vindex, limit):
    if not embedder or not vindex or not q.text.strip():
        return [], {}
    qv = embedder.encode([q.text])[0]
    hits = [(cid, s) for cid, s in vindex.search(qv, k=limit * 4) if s >= MIN_MEANING]
    if not hits:
        return [], {}
    marks = ",".join("?" * len(hits))
    where, args = _filters(q)
    rows = store.q(f"SELECT c.id, c.file_id, substr(c.body, 1, 240) FROM chunks c JOIN files f ON f.id = c.file_id "
                   f"WHERE c.id IN ({marks}){where}", (*[h[0] for h in hits], *args))
    by_chunk = {r[0]: (r[1], r[2]) for r in rows}
    best, order = {}, []
    for cid, s in hits:
        if cid in by_chunk:
            fid, body = by_chunk[cid]
            if fid not in best:
                best[fid] = (s, body)
                order.append(fid)
    return order[:limit], best


def _ago(ts, now):
    d = now - ts
    if d < 0:
        return "in the future"
    for n, unit in ((86400 * 365, "year"), (86400 * 30, "month"), (86400 * 7, "week"), (86400, "day"),
                    (3600, "hour"), (60, "minute")):
        if d >= n:
            k = int(d // n)
            return f"{k} {unit}{'s' if k != 1 else ''} ago"
    return "just now"


def search(store, text, embedder=None, vindex=None, limit=60, now=None):
    t_start = time.perf_counter()
    q = parse(text)
    now = now or time.time()
    lists = []
    names = _name_hits(store, q, 300)
    lists.append((W_NAME, names))
    texts, snippets = _text_hits(store, q, 300)
    lists.append((W_TEXT, texts))
    meaning, best = _meaning_hits(store, q, embedder, vindex, 150)
    lists.append((W_MEANING, meaning))

    score = {}
    for w, ids in lists:
        for rank, fid in enumerate(ids):
            score[fid] = score.get(fid, 0.0) + w / (RRF_K + rank + 1)

    if not score and not q.terms and not q.phrases and (q.kinds or q.exts or q.t0 is not None):
        where, args = _filters(q)
        ids = [r[0] for r in store.q(f"SELECT f.id FROM files f WHERE 1=1{where} ORDER BY f.mtime DESC LIMIT ?",
                                     (*args, limit))]
        score = {fid: 1.0 / (i + 1) for i, fid in enumerate(ids)}

    top = sorted(score, key=score.get, reverse=True)[:limit]
    if not top:
        return {"results": [], "understood": q.understood(), "terms": q.terms + q.phrases,
                "ms": round((time.perf_counter() - t_start) * 1000)}
    marks = ",".join("?" * len(top))
    info = {r[0]: r for r in store.q(f"SELECT id, path, name, dir, kind, size, mtime, ctime FROM files "
                                     f"WHERE id IN ({marks})", top)}
    name_set, text_set = set(names), set(texts)
    out = []
    for fid in top:
        r = info.get(fid)
        if not r:
            continue
        why = []
        if fid in name_set:
            why.append("name matches")
        if fid in text_set:
            why.append("text inside matches")
        if fid in best:
            why.append(f"similar meaning ({best[fid][0]:.0%})")
        if q.t0 is not None:
            why.append(f"changed {_ago(r[6], now)}" if r[6] else "date matches")
        snippet = snippets.get(fid) or (best[fid][1] if fid in best else "")
        out.append({"id": fid, "path": r[1], "name": r[2], "dir": r[3], "kind": r[4], "size": r[5], "mtime": r[6],
                    "ago": _ago(r[6], now) if r[6] else "", "why": why, "snippet": snippet})
    return {"results": out, "understood": q.understood(), "terms": q.terms + q.phrases,
            "ms": round((time.perf_counter() - t_start) * 1000)}
