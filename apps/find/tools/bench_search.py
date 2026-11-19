"""Search speed at whole-PC scale (dev only, not shipped): a synthetic index of --rows file entries in a throwaway
folder, then questions typed one letter at a time through the engine's real search.search().

    cd apps/find
    python tools/bench_search.py --rows 1000000 [--keep DIR]

Prints p50 / p90 / max per keystroke for short (1-2 letters), name (3+ letters) and multi-word questions.
"""
import argparse
import json
import os
import random
import shutil
import statistics
import sys
import tempfile
import time

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP)

WORDS = ("invoice tax receipt budget holiday report meeting notes project plan travel ticket insurance policy "
         "contract salary bank statement school homework recipe garden car service warranty manual photo family "
         "birthday wedding doctor appointment bill rent lease house moving guitar lesson python script backup "
         "network order delivery kitchen paint window library book chapter summary thesis lecture exam grade "
         "img dsc screenshot scan final draft copy new old setup readme license changelog config data log cache "
         "index main test util helper module package resource asset icon logo banner thumbnail").split()
EXTS = (".txt", ".pdf", ".docx", ".xlsx", ".jpg", ".png", ".mp4", ".py", ".js", ".json", ".dll", ".exe", ".log",
        ".md", ".csv", ".zip", ".mp3", ".html", ".xml", ".ini")
KINDS = {".txt": "text", ".pdf": "pdf", ".docx": "document", ".xlsx": "spreadsheet", ".jpg": "image",
         ".png": "image", ".mp4": "video", ".py": "code", ".js": "code", ".json": "code", ".dll": "app",
         ".exe": "app", ".log": "text", ".md": "text", ".csv": "spreadsheet", ".zip": "archive", ".mp3": "audio",
         ".html": "code", ".xml": "code", ".ini": "code"}
TYPED = ("invoice", "tax 2024", "re", "a", "ma", "budget report", "photo", "dsc", "setup.exe", "readme",
         "py", "x", "holiday photos", "zz", "contract", "wedding")


def build(root, rows, seed=3):
    from nobadfind.store import Store
    rng = random.Random(seed)
    s = Store(os.path.join(root, "index.db"), encrypt=False)
    t = time.perf_counter()
    batch = []
    for i in range(rows):
        depth = rng.randint(1, 6)
        d = "C:\\" + "\\".join(rng.choice(WORDS) + (str(rng.randint(1, 99)) if rng.random() < 0.3 else "")
                               for _ in range(depth))
        ext = rng.choice(EXTS)
        name = "_".join(rng.choice(WORDS) for _ in range(rng.randint(1, 3)))
        if rng.random() < 0.4:
            name += f"_{rng.randint(1, 99999)}"
        name += ext
        mt = 1.7e9 + rng.random() * 6e7
        batch.append((d + "\\" + name, name, d, ext, KINDS[ext], rng.randint(100, 10 ** 8), mt, mt, 1))
        if len(batch) == 20000:
            s.upsert_files(batch)
            batch = []
    if batch:
        s.upsert_files(batch)
    return s, time.perf_counter() - t


def bench(store, prepare=None):
    from nobadfind import search
    out = {"short": [], "name": [], "words": []}
    for q in TYPED:
        for i in range(1, len(q) + 1):
            text = q[:i]
            t = time.perf_counter()
            search.search(store, text, limit=60)
            ms = (time.perf_counter() - t) * 1000
            n = len(text.strip())
            out["short" if n <= 2 else ("words" if " " in text.strip() else "name")].append(ms)
    return out


def pct(v, p):
    v = sorted(v)
    return v[min(len(v) - 1, int(round(p / 100 * (len(v) - 1))))]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=1000000)
    ap.add_argument("--keep", default="", help="a folder to build in (and keep, so a later run reuses it)")
    args = ap.parse_args(argv)
    root = args.keep or tempfile.mkdtemp(prefix="nobadfind-bench-")
    os.makedirs(root, exist_ok=True)
    from nobadfind.store import Store
    if os.path.exists(os.path.join(root, "index.db")):
        store, secs = Store(os.path.join(root, "index.db"), encrypt=False), 0.0
    else:
        store, secs = build(root, args.rows)
    n = store.one("SELECT count(*) FROM files")
    t = time.perf_counter()
    store.upgrade_name_index() if hasattr(store, "upgrade_name_index") else None
    up = time.perf_counter() - t
    bench(store)                                  # warm the page cache
    r = bench(store)
    res = {"rows": n, "build_s": round(secs, 1), "name_index_upgrade_s": round(up, 1)}
    for k, v in r.items():
        res[k] = {"keystrokes": len(v), "p50": round(statistics.median(v), 1), "p90": round(pct(v, 90), 1),
                  "max": round(max(v), 1)}
    print(json.dumps(res))
    store.db.close()
    if not args.keep:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
