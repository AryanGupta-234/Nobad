"""Smart search (0.8.5): what a question was understood as, folders named in it, and the one best guess.

    "2 boys in an image in downloads" -> [folder Downloads] [kind Images] [meaning "2 boys"]

query.parse reads the filters and cuts them out (query.Query.cuts says what each was read from); this module turns
that into the parts the UI shows as removable chips. Each part carries `without`: the question with that part taken
out, so removing a chip is just searching that text (the engine stays the only place questions are understood).

The best guess is one result the engine is sure of (an exact name, the only name that starts with what was typed,
the only match, or a clear winner on more than one signal). When it isn't sure, there's no guess: a wrong guess
under the cursor is worse than none.
"""
import os
import re
import time

from .kinds import KINDS
from .store import fts_quote

KIND_LABELS = {"pdf": "PDFs", "document": "Documents", "spreadsheet": "Spreadsheets", "slides": "Slides",
               "text": "Notes and text", "code": "Code", "email": "Email", "image": "Images", "video": "Videos",
               "audio": "Music and audio", "archive": "Archives", "app": "Apps", "ebook": "Ebooks",
               "folder": "Folders"}
assert set(KIND_LABELS) >= set(KINDS)
FOLDER_LABELS = {"downloads": "Downloads", "desktop": "Desktop", "documents": "Documents", "pictures": "Pictures",
                 "videos": "Videos", "music": "Music"}
SORT_LABELS = {"newest": "Newest first", "oldest": "Oldest first", "largest": "Largest first", "name": "By name"}
PLACE_DEPTH = 2           # "in projects": a folder at most this deep under your folders, an indexed root or a drive
MAX_DIRS = 5              # folders with the same name at the same depth searched together


# ---------- folders named in a question ----------
def _norm_name(s):
    return re.sub(r"[\s_\-.]+", " ", s.lower()).strip()


def place_bases(roots=(), drives=()):
    """The folders "in <name>" is measured from: your profile and its known folders, the indexed roots and the
    drive roots (so D:\\Projects and Documents\\Projects both count, a folder deep inside an app doesn't)."""
    from .winapi import known_folder
    out = [os.path.expanduser("~")]
    out += [p for p in (known_folder(k) for k in FOLDER_LABELS) if p]
    out += list(roots or ())
    out += [d["root"] for d in drives or () if d.get("root")]
    seen, bases = set(), []
    for b in out:
        p = os.path.normpath(b)
        p = p if len(p) <= 3 else p.rstrip("\\/")
        k = os.path.normcase(p)
        if k and k not in seen:
            seen.add(k)
            bases.append(p)
    return bases


def _depth(path, bases):
    p = os.path.normcase(path).rstrip("\\/")
    best = None
    for b in bases:
        b = os.path.normcase(b).rstrip("\\/")
        if p == b:
            return 0
        if p.startswith(b + "\\"):
            d = p[len(b) + 1:].count("\\") + 1
            best = d if best is None else min(best, d)
    return best


def folder_finder(store, bases):
    """words -> (the folder's name, [paths]) or None, for query.parse. Only folders already in the index count
    (never a lookup on disk), and only near the top of your folders (PLACE_DEPTH)."""
    cache = {}

    def find(words):
        key = _norm_name(words)
        if key in cache:
            return cache[key]
        cache[key] = None
        toks = re.findall(r"[\w\u0900-\u097F]+", key)
        if not toks or len(key) < 2:
            return None
        if store.name_index_ready():
            rows = store.q("SELECT f.path, f.name FROM files f WHERE f.id IN (SELECT rowid FROM names_w WHERE names_w "
                           "MATCH ? LIMIT 400) AND f.kind = 'folder'", (" ".join(fts_quote(t) for t in toks),))
        else:
            rows = store.q("SELECT path, name FROM files WHERE kind = 'folder' AND name LIKE ? LIMIT 400",
                           (key.split(" ")[0][:40] + "%",))
        found = []
        for path, name in rows:
            if _norm_name(name) != key:
                continue
            d = _depth(path, bases)
            if d is not None and d <= PLACE_DEPTH:
                found.append((d, len(path), path, name))
        if not found:
            return None
        found.sort()
        top = [f for f in found if f[0] == found[0][0]][:MAX_DIRS]
        cache[key] = (top[0][3], [f[2] for f in top])
        return cache[key]
    return find


def place_folders(store, bases, limit=60):
    """Folder names right under your folders and the indexed roots, for autocomplete ("in pro" -> "in Projects").
    Cached a minute. The local folder is listed (one directory, cheap) and each name only counts when the index
    has that folder; network folders (\\\\server) are never listed."""
    key = (id(store), tuple(bases))
    hit = _place_cache.get(key)
    if hit and time.monotonic() - hit[0] < 60:
        return hit[1]
    names = {}
    for b in bases[:24]:
        if len(b) <= 3 or b.startswith("\\\\"):   # a drive root (system folders as often as yours), or the network
            continue
        try:
            entries = sorted(os.listdir(b))[:300]
        except OSError:
            continue
        for name in entries:
            if name.startswith((".", "$", "_")) or len(name) > 40 or name.lower() in names:
                continue
            path = os.path.join(b, name)
            if store.one("SELECT 1 FROM files WHERE path = ? AND kind = 'folder'", (path,)):
                names[name.lower()] = name
    out = sorted(names.values(), key=str.lower)[:limit]
    _place_cache[key] = (time.monotonic(), out)
    return out


_place_cache = {}


# ---------- the parts a question was understood as ----------
def _rx(phrase, lead=False):
    body = r"\s+".join(re.escape(w) for w in phrase.split())
    pre = r"(?:(?:\b(?:in|of|on|with|as|from)\s+)?(?:\b(?:a|an|the|my|some)\s+))?" if lead else ""
    return re.compile(pre + r"(?<![\w\u0900-\u097F])" + body + r"(?![\w\u0900-\u097F])", re.I)


def _clean(s):
    return re.sub(r"\s+", " ", s).strip()


def _span(text, phrase, lead=False):
    m = _rx(phrase, lead).search(text)
    return (m.start(), m.end()) if m else None


def parts(q, meaning_on=False):
    """[{kind, label, without}] in the order shown: where, what kind, when, size, order, then what it's about.
    kind: folder | drive | kind | time | size | sort | meaning | words."""
    raw = q.raw
    groups = []                     # (kind, label, [(phrase, lead)])
    by = {}
    for part, phrase in q.cuts:
        by.setdefault(part, []).append(phrase)

    def add(kind, label, phrases, lead=False):
        if label:
            groups.append((kind, label, [(p, lead) for p in phrases]))
    if q.folder:
        add("folder", FOLDER_LABELS.get(q.folder, q.folder.capitalize()), by.get("folder", []))
    if q.dirs:
        add("folder", q.dir_label, by.get("dir", []))
    if q.path:
        add("folder", os.path.basename(q.path.rstrip("\\/")) or q.path, by.get("path", []))
    if q.here:
        add("folder", "This folder" if not q.path else "", by.get("here", []))
    if q.place:
        add("drive", q.place_label()[3:].capitalize() if q.place_label().startswith("on ") else q.place_label(),
            by.get("place", []))
    for k in sorted(q.kinds):
        add("kind", KIND_LABELS.get(k, k), by.get("kind:" + k, []), lead=True)
    for a in sorted(q.apps):
        add("kind", f"{a.capitalize()} files", [p for p in by.get("app", []) if p.split()[0] == a])
    for e in sorted(q.exts):
        add("kind", e, [e])
    if q.when:
        add("time", q.when[0].upper() + q.when[1:], by.get("time", []))
    if q.size_label:
        add("size", q.size_label[0].upper() + q.size_label[1:], by.get("size", []))
    if q.sort:
        add("sort", SORT_LABELS.get(q.sort, q.sort), by.get("sort", []))

    def cut(text, phrases):
        for p, lead in phrases:
            sp = _span(text, p, lead) or _span(text, p)
            if sp:
                text = text[:sp[0]] + " " + text[sp[1]:]
        return _clean(text)

    out = []
    every = [pl for g in groups for pl in g[2]]
    for kind, label, phrases in groups:
        if phrases and all(_span(raw, p) for p, _l in phrases):
            without = cut(raw, phrases)
        else:                       # read from Hindi or Hinglish: the rest, in the English it was read as
            without = _clean(" ".join([p for p, _l in every if (p, _l) not in phrases] + q.phrases + q.terms))
        out.append({"kind": kind, "label": label, "without": without})
    about = q.meaning or q.text
    if about:
        spans = sorted(s for s in (_span(raw, p, lead) or _span(raw, p) for p, lead in every) if s)
        if spans and len(spans) == len(every):
            only = _clean(" ".join(raw[a:b] for a, b in spans))
        else:
            only = _clean(" ".join(p for p, _l in every))
        out.append({"kind": "meaning" if meaning_on else "words", "label": about[:80], "without": only})
    return out


# ---------- the best guess ----------
def _stem(name):
    base, ext = os.path.splitext(name)
    return base if ext and len(ext) <= 8 else name


def best_guess(q, results, score, photo_scores=None, listing=False):
    """(result id, reason) when one result is clearly the one, else None. results: the shown order; score: the
    fused rank score of each id; photo_scores: id -> photo similarity."""
    strong = [r for r in results if not r.get("weak")]
    if not strong:
        return None
    typed = _norm_name(q.raw)
    asked = _norm_name(q.text)
    # 1. an exact name ("budget.xlsx", "tax return 2024"); two files with that name (budget.xlsx, budget.log for
    # "budget") is no guess, unless the extension was typed too
    for want in [w for w in dict.fromkeys((typed, asked)) if w]:
        full = [r for r in strong[:20] if _norm_name(r["name"]) == want]
        stem = [r for r in strong[:20] if _norm_name(_stem(r["name"])) == want]
        if len(full) == 1:
            return full[0]["id"], "Exact name"
        if not full and len(stem) == 1:
            return stem[0]["id"], "Exact name"
        if full or stem:
            return None
    if listing:
        if q.sort and strong:
            return strong[0]["id"], SORT_LABELS.get(q.sort, "First")
        return (strong[0]["id"], "The only match") if len(strong) == 1 else None
    # 2. the only name that starts with what was typed ("budg" -> budget.xlsx)
    if len(asked) >= 3:
        starts = [r for r in strong if _norm_name(_stem(r["name"])).startswith(asked)]
        if len(starts) == 1 and "name matches" in starts[0].get("why", []):
            return starts[0]["id"], "The only name that starts like this"
    signals = _signals(strong[0])
    # 3. the only match (the only sure one is enough when it's sure on two counts, or a filter-only question)
    if len(strong) == 1 and (len(results) == 1 or signals >= 2 or (not q.terms and not q.phrases)):
        return strong[0]["id"], "The only match"
    if len(strong) == 1:
        return None
    a, b = strong[0], strong[1]
    sa, sb = score.get(a["id"], 0.0), score.get(b["id"], 0.0)
    # 4. the picture fits clearly best (photo meaning was asked: "2 boys in an image")
    ps = photo_scores or {}
    if "image" in q.kinds and a["id"] in ps:
        pb = ps.get(b["id"], 0.0)
        if ps[a["id"]] >= 1.12 * max(pb, 1e-6):
            return a["id"], "The picture fits best"
    # 5. a clear winner on more than one signal (name and text, or text and meaning)
    if signals >= 2 and sa >= 1.5 * sb:
        return a["id"], "Matches on name and content"
    return None


def _signals(r):
    return sum(1 for w in r.get("why", []) if w in ("name matches", "text inside matches") or "meaning" in w
               or "picture" in w)
