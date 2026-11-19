"""Autocomplete for the search box and the quick find bar: your own past questions, names in the index, and the
phrases the engine understands ("in downloads", "images", "last week").

    suggest(store, "2 boys in d")  -> items [{text: "2 boys in downloads", kind: "filter", label: "in downloads"}, ...],
                                      complete "2 boys in downloads" (the inline ghost text)

Every item's `text` is the whole question to search (the UI fills the box with it). Names come from the index
only; nothing is looked up on disk except the folder list understand.place_folders keeps.
"""
import datetime as dt
import re

from . import history
from .store import fts_quote
from .understand import FOLDER_LABELS, place_folders

# Phrases query.parse understands, offered as they are typed. (label shown, what it means)
PHRASES = [
    ("in downloads", "folder"), ("on desktop", "folder"), ("in documents", "folder"), ("in pictures", "folder"),
    ("in videos", "folder"), ("in music", "folder"),
    ("images", "kind"), ("photos", "kind"), ("screenshots", "kind"), ("pdf", "kind"), ("videos", "kind"),
    ("songs", "kind"), ("music", "kind"), ("documents", "kind"), ("word documents", "kind"), ("excel sheets", "kind"),
    ("spreadsheets", "kind"), ("slides", "kind"), ("presentations", "kind"), ("code", "kind"), ("notes", "kind"),
    ("emails", "kind"), ("zip files", "kind"), ("folders", "kind"),
    ("today", "time"), ("yesterday", "time"), ("this week", "time"), ("last week", "time"), ("this month", "time"),
    ("last month", "time"), ("this year", "time"), ("last year", "time"), ("recently", "time"),
    ("big files", "size"), ("small files", "size"), ("over 100 mb", "size"), ("under 1 mb", "size"),
    ("newest", "sort"), ("oldest", "sort"), ("largest", "sort"),
    ("containing", "words"), ("having", "words"),
]
_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
           "november", "december"]
MIN_NAME = 2              # letters of a word before names are offered
NAME_POOL = 300           # name matches looked at (the shortest names are offered)
_WORD = re.compile(r"[\wऀ-ॿ.\-+#]+$")


def _phrases(drives=(), folders=(), now=None):
    now = now or dt.date.today()
    out = list(PHRASES)
    # months back from this one, "in march"
    out += [("in " + _MONTHS[(now.month - 1 - i) % 12], "time") for i in range(12)]
    out += [(f"in {now.year - i}", "time") for i in range(1, 4)]
    for d in drives or ():
        r = (d.get("root") or "")[:1].lower()
        if r and r.isalpha() and r != "c":
            out.append((f"on {r} drive", "drive"))
    out += [("in " + f.lower(), "folder") for f in folders]
    seen, uniq = set(), []
    for p, k in out:
        if p not in seen:
            seen.add(p)
            uniq.append((p, k))
    return uniq


def _phrase_items(text, phrases):
    """Phrases that complete the end of what's typed: "pdf in d" -> "pdf in downloads"."""
    low = text.lower()
    if not low.strip() or low.endswith(" "):
        return []
    words = low.split(" ")
    out = []
    for n in (3, 2, 1):                                 # the longest tail that a phrase starts with wins
        if len(words) < n:
            continue
        tail = " ".join(words[-n:])
        if len(tail) < 2:
            continue
        before = text[:len(text) - len(tail)]
        for p, kind in phrases:
            if p.startswith(tail) and p != tail and (" " + p + " ") not in (" " + low + " "):
                full = before + p
                if all(i["text"].lower() != full.lower() for i in out):
                    out.append({"text": full, "kind": "filter", "label": p, "detail": kind})
        if out:
            break
    return out


def _name_items(store, text, limit):
    """Files and folders whose name has a word starting with the last word typed: "invo" -> invoice-march.pdf."""
    m = _WORD.search(text)
    if not m or text.endswith(" "):
        return []
    word = m.group(0).lower().strip(".-")
    if len(word) < MIN_NAME or not any(ch.isalnum() for ch in word):
        return []
    before = text[:m.start()]
    toks = re.findall(r"[\wऀ-ॿ]+", word)
    if not toks:
        return []
    if store.name_index_ready():
        match = " ".join(fts_quote(t) for t in toks[:-1]) + (" " if len(toks) > 1 else "") + fts_quote(toks[-1]) + "*"
        rows = store.q("SELECT f.id, f.name, f.dir, f.kind FROM files f WHERE f.id IN (SELECT rowid FROM names_w "
                       "WHERE names_w MATCH ? LIMIT ?) ORDER BY length(f.name), f.mtime DESC LIMIT ?",
                       (match, NAME_POOL, limit * 3))
    elif len(word) >= 3:
        rows = store.q("SELECT f.id, f.name, f.dir, f.kind FROM files f WHERE f.id IN (SELECT rowid FROM names "
                       "WHERE names MATCH ? LIMIT ?) ORDER BY length(f.name), f.mtime DESC LIMIT ?",
                       ("name:" + fts_quote(word), NAME_POOL, limit * 3))
    else:
        return []
    out, seen = [], set()
    earlier = [w for w in re.findall(r"[\wऀ-ॿ]+", before.lower()) if len(w) >= 2]
    for fid, name, folder, kind in rows:
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        # "tax no" -> "tax notes.txt", not "tax tax notes.txt": the name alone when it has the earlier words too
        text = name if all(w in key for w in earlier) else before + name
        out.append({"text": text, "kind": "folder" if kind == "folder" else "file", "label": name,
                    "detail": folder, "id": fid})
        if len(out) >= limit:
            break
    return out


def _word_completion(text, items):
    """The ghost text: a suggestion that starts with exactly what's typed (case aside), the first in order."""
    low = text.lower()
    for it in items:
        t = it["text"]
        if len(t) > len(text) and t.lower().startswith(low):
            return text + t[len(text):]
    # a name's word that starts with the last word typed ("invo" -> "invoice"), from the first name offered
    m = _WORD.search(text)
    if m and not text.endswith(" "):
        w = m.group(0).lower()
        for it in items:
            if it["kind"] in ("file", "folder"):
                for part in re.findall(r"[\wऀ-ॿ]+", it["label"]):
                    if len(part) > len(w) and part.lower().startswith(w):
                        return text + part[len(w):]
    return ""


def suggest(store, text, history_on=True, limit=8, bases=(), drives=(), now=None):
    """{items, complete}: up to `limit` suggestions in order (history, phrases, names) and the inline completion."""
    text = (text or "")[:200]
    text = re.sub(r"\s+", " ", text.lstrip())
    items = []
    if history_on:
        for q in history.match(store, text, limit=4 if text.strip() else min(limit, 6)):
            items.append({"text": q, "kind": "history", "label": q, "detail": ""})
    if text.strip():
        try:
            folders = place_folders(store, list(bases)) if bases else []
        except Exception:                       # a folder list that can't be read: phrases still work
            folders = []
        folders = [f for f in folders if f.lower() not in FOLDER_LABELS]
        items += _phrase_items(text, _phrases(drives, folders, now))[:3]
        items += _name_items(store, text, 4)
    seen, out = set(), []
    for it in items:
        k = it["text"].lower().strip()
        if k and k != text.lower().strip() and k not in seen:
            seen.add(k)
            out.append(it)
    out = out[:limit]
    return {"items": out, "complete": _word_completion(text, out) if text.strip() else ""}
