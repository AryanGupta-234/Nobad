"""Search: name matches + text matches + meaning matches, merged by reciprocal rank fusion.

Each result says why it matched, in plain words, and only claims what was actually measured.
Snippets mark matches with \\x02 ... \\x03; the UI escapes the text first and only then turns those into <mark>.
"""
import os
import time

from .query import parse
from .store import fts_quote

RRF_K = 60
W_NAME, W_TEXT, W_MEANING = 1.3, 1.0, 0.8
# Meaning matches (cosine similarity, all-MiniLM-L6-v2). Measured on a test set: right answers score 0.32-0.65,
# unrelated text mostly stays under 0.22. A match must clear the floor AND be near the best one for this question
# (names and titles are short, so their scores run lower than full sentences).
MIN_MEANING = 0.24
MEANING_SPREAD = 0.13
# A name is only a few words ("car", "garden"), so its score says less: a name match must be close to the best
# match for this question, or strong on its own.
NAME_SPREAD = 0.08
NAME_STRONG = 0.32
VARIANTS = set()        # ranking variants switched on by tools/eval_text.py to measure them one at a time
# Words people use for the same personal files (both ways). Only for the keyword side: the meaning model knows these.
_SYN_GROUPS = [("flat", "apartment"), ("invoice", "bill", "receipt"), ("cv", "resume", "résumé"),
               ("rent", "lease", "tenancy"), ("salary", "payslip", "wage", "pay"), ("doctor", "gp", "physician"),
               ("car", "vehicle", "auto"), ("insurance", "policy", "cover"), ("holiday", "vacation", "trip"),
               ("flight", "plane", "airline"), ("phone", "mobile", "cell"), ("tax", "hmrc", "irs"),
               ("electricity", "power", "energy"), ("internet", "broadband", "wifi"), ("bank", "account"),
               ("medicine", "prescription", "medication"), ("job", "work", "employment"), ("school", "class"),
               ("recipe", "cook", "cooking"), ("photo", "picture", "image"), ("notes", "minutes")]
SYNONYMS = {}
for _g in _SYN_GROUPS:
    for _w in _g:
        SYNONYMS.setdefault(_w, set()).update(x for x in _g if x != _w)


def floors(model_id):
    """(min score, spread, name spread, name strong) for a text model: every model scores on its own scale
    (multilingual-e5 puts unrelated text near 0.75), so the catalog carries each one's measured floors."""
    from .models import get
    m = get(model_id) or {}
    return (m.get("min_score", MIN_MEANING), m.get("spread", MEANING_SPREAD), m.get("name_spread", NAME_SPREAD),
            m.get("name_strong", NAME_STRONG))


UNC = "\\\\"                    # \\server\share paths (folders added by hand)


def like_prefix(root):
    """A LIKE pattern (ESCAPE '\\') for everything inside root."""
    if root == UNC:
        return "\\\\\\\\%"
    return root.rstrip("\\/").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "\\\\%"


def place_roots(place, drives):
    """Drive roots a place means. drives: [{'root': 'E:\\', 'type': 'removable', 'label': ...}, ...]."""
    if not place:
        return None
    if place.startswith("label:"):
        name = place[6:]
        return [d["root"] for d in drives if (d.get("label") or "").strip().lower() == name]
    if len(place) == 2 and place[1] == ":":
        return [place + "\\"]
    roots = [d["root"] for d in drives if d.get("type") == place]
    if place == "network":
        roots.append(UNC)
    return roots


def _filters(q, alias="f"):
    sql, args = [], []
    roots = place_roots(q.place, q.drives)
    if roots is not None:
        if not roots:
            sql.append("0")                         # a drive this PC has never seen: nothing can match
        else:
            sql.append("(" + " OR ".join(f"{alias}.path LIKE ? ESCAPE '\\'" for _ in roots) + ")")
            args += [like_prefix(r) for r in roots]
    if q.kinds:
        sql.append(f"{alias}.kind IN ({','.join('?' * len(q.kinds))})")
        args += sorted(q.kinds)
    if q.folder:
        from .winapi import known_folder
        path = known_folder(q.folder)
        if path:
            sql.append(f"{alias}.path LIKE ? ESCAPE '\\'")
            args.append(like_prefix(path))
        else:
            sql.append("0")
    if q.path:                                      # a typed path, "here", or the Folder filter
        sql.append(f"{alias}.path LIKE ? ESCAPE '\\'")
        args.append(like_prefix(q.path))
    if q.min_size is not None:
        sql.append(f"{alias}.size >= ?")
        args.append(q.min_size)
    if q.max_size is not None:
        sql.append(f"{alias}.size <= ?")
        args.append(q.max_size)
    exts = q.all_exts()
    if exts:
        sql.append(f"{alias}.ext IN ({','.join('?' * len(exts))})")
        args += sorted(exts)
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
    if "fts_or" in VARIANTS or "synonyms" in VARIANTS:
        alts = [[w] + (sorted(SYNONYMS.get(w, ())) if "synonyms" in VARIANTS else []) for w in words]
        groups = ["(" + " OR ".join(fts_quote(a) for a in alt) + ")" for alt in alts]
        match = (" OR " if "fts_or" in VARIANTS else " AND ").join(groups)
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
    model, asked = getattr(vindex, "model", None), getattr(embedder, "model_id", None)
    if model and asked and model != asked:
        return [], {}                        # vectors and question from different models: never compared
    from .embed import is_name
    qv = embedder.encode([q.text])[0]
    hits = vindex.search(qv, k=limit * 4)
    if not hits:
        return [], {}
    min_score, spread, name_spread, name_strong = floors(model or asked or "")
    best_score = hits[0][1]
    floor = max(min_score, best_score - spread)
    name_floor = min(name_strong, max(min_score, best_score - name_spread))
    if "nofloor" in VARIANTS:
        floor = name_floor = min_score
    hits = [(key, s) for key, s in hits if s >= (name_floor if is_name(key) else floor)]
    chunk_ids = [k for k, _s in hits if not is_name(k)]
    file_ids = [-k for k, _s in hits if is_name(k)]
    where, args = _filters(q)
    by_chunk, by_name = {}, set()
    if chunk_ids:
        marks = ",".join("?" * len(chunk_ids))
        rows = store.q(f"SELECT c.id, c.file_id, substr(c.body, 1, 240) FROM chunks c JOIN files f ON f.id = c.file_id "
                       f"WHERE c.id IN ({marks}){where}", (*chunk_ids, *args))
        by_chunk = {r[0]: (r[1], r[2]) for r in rows}
    if file_ids:
        marks = ",".join("?" * len(file_ids))
        no_folders = "" if "folder_meaning" in VARIANTS or "folder" in q.kinds else " AND f.kind != 'folder'"
        by_name = {r[0] for r in store.q(f"SELECT f.id FROM files f WHERE f.id IN ({marks}){where}{no_folders}",
                                         (*file_ids, *args))}
    best, order = {}, []                     # file id -> (score, snippet, "text" | "name")
    for key, s in hits:
        if is_name(key):
            fid, body, how = -key, "", "name"
            if fid not in by_name:
                continue
        elif key in by_chunk:
            (fid, body), how = by_chunk[key], "text"
        else:
            continue                         # a vector for text that has since changed or gone
        if fid not in best:
            best[fid] = (s, body, how)
            order.append(fid)
    return order[:limit], best


# Photo matches (SigLIP cosine similarity: a much smaller scale than the text model's). Tuned on 55 real photos in
# 19 topics: precision 0.82, recall 0.84 (was 0.73 / 0.87). A photo must clear the floor, be within the spread of
# the best match and score at least PHOTO_RATIO of it.
PHOTO_MIN = 0.04
PHOTO_SPREAD = 0.04
PHOTO_RATIO = 0.6
PHOTO_SURE = 0.85
W_PHOTO = 1.0
W_PHOTO_ASKED = 1.8


def _photo_hits(store, q, photo_text, pindex, limit):
    if not photo_text or pindex is None or not pindex.n or not q.text.strip():
        return [], {}
    model, asked = getattr(pindex, "model", None), getattr(photo_text, "model_id", None)
    if model and asked and model != asked:
        return [], {}                                 # photo vectors and question from different models
    if q.kinds and "image" not in q.kinds:
        return [], {}                                 # "pdf ..." isn't asking about photos
    hits = pindex.search(photo_text.encode(q.text), k=limit * 3)
    if not hits:
        return [], {}
    floor = max(PHOTO_MIN, hits[0][1] - PHOTO_SPREAD, hits[0][1] * PHOTO_RATIO)
    hits = [(fid, s) for fid, s in hits if s >= floor]
    if not hits:
        return [], {}
    where, args = _filters(q)
    marks = ",".join("?" * len(hits))
    ok = {r[0] for r in store.q(f"SELECT f.id FROM files f WHERE f.id IN ({marks}){where}",
                                (*[h[0] for h in hits], *args))}
    order, best = [], {}
    for fid, s in hits:
        if fid in ok and fid not in best:
            best[fid] = s
            order.append(fid)
    return order[:limit], best


def _closeness(score):
    """Plain words for a similarity score (it isn't a percentage of anything, so none is shown)."""
    return "close" if score >= 0.5 else "related" if score >= 0.38 else "loosely related"


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


FILTER_KINDS = {"pdf", "document", "spreadsheet", "slides", "text", "code", "email", "image", "video", "audio",
                "archive", "ebook", "app", "folder"}
FILTER_DAYS = {"today": 1, "week": 7, "month": 30, "year": 365}
FILTER_SIZES = {"small": (None, 1 << 20, "under 1 MB"), "medium": (1 << 20, 100 << 20, "1 to 100 MB"),
                "large": (100 << 20, None, "over 100 MB")}
SORTS = {"", "newest", "oldest", "largest", "name"}
LIST_LIMIT = 500                # "list all ..." shows up to this many files
SORT_POOL = 100                 # "newest budget": the best 100 matches, newest first
SORT_SQL = {"": "f.mtime DESC", "newest": "f.mtime DESC", "oldest": "f.mtime ASC", "largest": "f.size DESC",
            "name": "f.name COLLATE NOCASE ASC"}


def apply_filters(q, filters, now):
    """The filter bar's choices on top of what the question says. Every value is checked; unknown ones are
    ignored (the page is untrusted like everything else)."""
    if not isinstance(filters, dict):
        return
    filters = {k: v for k, v in filters.items() if isinstance(k, str) and isinstance(v, str)}
    kind = filters.get("kind")
    if kind in FILTER_KINDS:
        q.kinds = {kind}
    days = FILTER_DAYS.get(filters.get("modified"))
    if days and q.t0 is None:
        q.t0, q.t1 = now - days * 86400, now + 60
        q.when = {1: "today", 7: "last 7 days", 30: "last 30 days", 365: "last 12 months"}[days]
    size = FILTER_SIZES.get(filters.get("size"))
    if size:
        q.min_size, q.max_size, q.size_label = size
    folder = filters.get("folder")
    if isinstance(folder, str) and 2 < len(folder) < 1024 and "\x00" not in folder and os.path.isabs(folder):
        q.path = os.path.normpath(folder)
    if filters.get("sort") in SORTS and filters.get("sort"):
        q.sort = filters["sort"]


def folder_checker(store, drives=(), roots=()):
    """is_dir for typed paths, without ever reaching out over the network.

    A network path (\\\\server\\share) is only accepted when it's a folder already in the index or in the
    folders to search: looking it up on disk would make Windows contact that server, and a server you don't
    know could collect your sign-in hash that way. Paths on this PC's own drives are checked on disk."""
    local = {d["root"].upper() for d in drives if d.get("type") in ("fixed", "removable", "cd", "ram")}
    known_roots = {os.path.normcase(r.rstrip("\\/")) for r in roots}

    def is_dir(p):
        p = p.replace("/", "\\")
        if p.startswith("\\\\"):
            if os.path.normcase(p.rstrip("\\")) in known_roots:
                return True
            return bool(store.one("SELECT 1 FROM files WHERE path = ? AND kind = 'folder'", (p.rstrip("\\"),)))
        if p[:3].upper() in local or (not drives and len(p) >= 3 and p[1] == ":"):
            return os.path.isdir(p)
        return bool(store.one("SELECT 1 FROM files WHERE path = ? AND kind = 'folder'", (p.rstrip("\\"),)))
    return is_dir


def search(store, text, embedder=None, vindex=None, limit=60, now=None, drives=None, here="", filters=None,
           is_dir=None, roots=(), photo_text=None, pindex=None):
    """drives: every drive the index knows, [{'root', 'type', 'label', 'present'}] (indexer.known_drives).
    here: the File Explorer folder NOBAD Find was opened from ("" if none). filters: the filter bar.

    A time in the question ("electricity bill march") is first a filter on when the file changed. When nothing
    changed then, it is read as words instead (the bill *for* March), and a note says so."""
    t_start = time.perf_counter()
    args = dict(embedder=embedder, vindex=vindex, limit=limit, now=now, drives=drives, here=here, filters=filters,
                is_dir=is_dir, roots=roots, photo_text=photo_text, pindex=pindex)
    r = _search(store, text, **args)
    if not r["results"] and r.get("_time_from_text") and "hard_time" not in VARIANTS:
        when = r["_time_from_text"]
        r = _search(store, text, times=False, **args)
        if r["results"]:
            r["notes"] = [f"Nothing changed {when}, so these match the words instead."] + r["notes"]
    r.pop("_time_from_text", None)
    r["ms"] = round((time.perf_counter() - t_start) * 1000)
    return r


def _search(store, text, embedder=None, vindex=None, limit=60, now=None, drives=None, here="", filters=None,
            is_dir=None, roots=(), photo_text=None, pindex=None, times=True):
    t_start = time.perf_counter()
    drives = drives or []
    now = now or time.time()
    is_dir = is_dir or folder_checker(store, drives, roots)
    q = parse(text, labels=[d.get("label") or "" for d in drives], is_dir=is_dir, times=times)
    time_from_text = q.when if q.t0 is not None else ""
    q.drives = drives
    if q.here and not q.path:
        if here:
            q.path = os.path.normpath(here)
        else:
            q.notes.append("“Here” is the folder you're looking at in File Explorer when you press the hotkey. "
                           "Open NOBAD Find that way to search a folder.")
    apply_filters(q, filters, now)
    lists = []
    w_name, w_text, w_meaning = W_NAME, W_TEXT, W_MEANING
    if "rrf_equal" in VARIANTS:
        w_name = w_text = w_meaning = 1.0
    if "meaning_up" in VARIANTS:
        w_meaning = 1.6
    names = _name_hits(store, q, 300)
    lists.append((w_name, names))
    texts, snippets = _text_hits(store, q, 300)
    lists.append((w_text, texts))
    meaning, best = _meaning_hits(store, q, embedder, vindex, 150)
    lists.append((w_meaning, meaning))
    photos, pbest = _photo_hits(store, q, photo_text, pindex, 100)
    # asking for photos ("beach photos", the Images filter): what's in the picture counts most
    lists.append((W_PHOTO_ASKED if "image" in q.kinds else W_PHOTO, photos))

    score = {}
    for w, ids in lists:
        for rank, fid in enumerate(ids):
            score[fid] = score.get(fid, 0.0) + w / (RRF_K + rank + 1)

    listing = False
    if not score and not q.terms and not q.phrases and q.has_filters():
        # only filters ("list all pdf here"): every matching file, in the chosen order
        listing, limit = True, LIST_LIMIT
        where, args = _filters(q)
        ids = [r[0] for r in store.q(f"SELECT f.id FROM files f WHERE 1=1{where} ORDER BY {SORT_SQL[q.sort]} "
                                     "LIMIT ?", (*args, limit + 1))]
        score = {fid: 1.0 / (i + 1) for i, fid in enumerate(ids)}

    ranked = sorted(score, key=score.get, reverse=True)
    if not ranked:
        return {"results": [], "understood": q.understood(), "terms": q.terms + q.phrases, "notes": q.notes,
                "ms": round((time.perf_counter() - t_start) * 1000), "_time_from_text": time_from_text}
    # with an order asked for, the best matches are put in that order (weak matches don't jump ahead)
    pool = ranked[:max(limit + 1, SORT_POOL)] if (q.sort and not listing) else ranked[:limit + 1]
    info = {}
    for i in range(0, len(pool), 900):                  # SQLite takes at most 999 parameters at once
        part = pool[i:i + 900]
        info.update({r[0]: r for r in store.q(f"SELECT id, path, name, dir, kind, size, mtime, ctime FROM files "
                                              f"WHERE id IN ({','.join('?' * len(part))})", part)})
    if q.sort and not listing:                          # matches first, then the order asked for
        key = {"newest": lambda f: -(info[f][6] or 0), "oldest": lambda f: info[f][6] or 0,
               "largest": lambda f: -(info[f][5] or 0), "name": lambda f: info[f][2].lower()}[q.sort]
        pool = sorted((f for f in pool if f in info), key=key)
    more = len(pool) > limit
    top = pool[:limit]
    name_set, text_set = set(names), set(texts)
    # a photo is "sure" when it's close to the best photo for this question (measured: right photos score within
    # ~10% of the best one, look-alikes 20% or more below it)
    photo_sure = max(PHOTO_MIN + 0.005, PHOTO_SURE * max(pbest.values())) if pbest else 1.0
    offline = {d["root"].upper(): (d.get("label") or d["root"].rstrip("\\")) for d in drives
               if d.get("present") is False}
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
            s, _body, how = best[fid]
            why.append(f"{'name' if how == 'name' else 'text'} has a {_closeness(s)} meaning")
        if fid in pbest:
            why.append("the picture shows something like it" if pbest[fid] >= photo_sure else "the picture may show it")
        if q.t0 is not None:
            why.append(f"changed {_ago(r[6], now)}" if r[6] else "date matches")
        if q.place:
            why.append(q.place_label())
        drive = offline.get(r[1][:3].upper())
        if drive:
            why.append(f"on {drive}, not connected now")
        snippet = snippets.get(fid) or (best[fid][1] if fid in best else "")
        # only a weak hint (a picture that "may show it", a loosely related meaning): shown, but as less sure
        strong = (fid in name_set or fid in text_set or (fid in pbest and pbest[fid] >= photo_sure)
                  or (fid in best and best[fid][0] >= 0.38) or listing)
        out.append({"id": fid, "path": r[1], "name": r[2], "dir": r[3], "kind": r[4], "size": r[5], "mtime": r[6],
                    "ago": _ago(r[6], now) if r[6] else "", "why": why, "snippet": snippet, "weak": not strong})
    if not q.sort and not listing and "noweak" not in VARIANTS:     # sure results first, the less sure after
        out.sort(key=lambda x: x["weak"])
    return {"results": out, "understood": q.understood(), "terms": q.terms + q.phrases, "notes": q.notes,
            "more": more, "ms": round((time.perf_counter() - t_start) * 1000), "_time_from_text": time_from_text}
