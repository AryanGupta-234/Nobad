"""Search quality on a fixed, made-up set of personal files (dev only, not shipped).

    cd apps/find
    python tools/eval_text.py --models-dir <data folder with models/> [--set english|hindi] [--model ID ...]

For each text model: index tools/evalset/<set>.json into a throwaway encrypted-less Store (real files on disk, the
engine's own extract, chunks, name and chunk vectors), then ask every query through the engine's real
search.search() and score the ranked files: recall@5, MRR@10, nDCG@10. "dense" scores the model alone (best
vector per file). Each model runs in its own process, so its RAM is its own: private MB after loading the model
and after indexing, passages/s while indexing, and the search latency (question encoder + ranking).

--variant NAME[,NAME] switches search improvements on for the run (search.VARIANTS) so each is measured alone.
--model none: keywords only (no meaning model).
"""
import argparse
import ctypes
import json
import math
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETS = os.path.join(APP, "tools", "evalset")


class _PMC(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t), ("a", ctypes.c_size_t), ("b", ctypes.c_size_t),
                ("c", ctypes.c_size_t), ("d", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t)]


def private_mb():
    k, ps = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
    k.GetCurrentProcess.restype = wintypes.HANDLE
    ps.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
    m = _PMC()
    m.cb = ctypes.sizeof(m)
    ps.GetProcessMemoryInfo(k.GetCurrentProcess(), ctypes.byref(m), m.cb)
    return m.PagefileUsage / 1048576


def metrics(ranked, relevant):
    rel = set(relevant)
    top5 = ranked[:5]
    recall5 = len(rel & set(top5)) / len(rel)
    rr = next((1 / (i + 1) for i, d in enumerate(ranked[:10]) if d in rel), 0.0)
    dcg = sum(1 / math.log2(i + 2) for i, d in enumerate(ranked[:10]) if d in rel)
    idcg = sum(1 / math.log2(i + 2) for i in range(min(len(rel), 10)))
    return recall5, rr, dcg / idcg


def build(data, root):
    """Write the docs as files; index them with the engine's own code. Returns (store, path -> doc id)."""
    from nobadfind import extract
    from nobadfind.store import Store
    from nobadfind.walker import Walker
    docs = os.path.join(root, "files")
    by_path = {}
    for d in data["docs"]:
        folder = os.path.join(docs, *d["folder"].replace("\\", "/").split("/"))
        os.makedirs(folder, exist_ok=True)
        p = os.path.join(folder, d["name"])
        with open(p, "w", encoding="utf-8") as f:
            f.write(d["body"])
        by_path[os.path.normcase(p)] = d["id"]
    store = Store(os.path.join(root, "i.db"), encrypt=False)
    Walker([docs], gen=1, on_batch=store.upsert_files).run()
    for fid, p, ext, mtime in store.q("SELECT id, path, ext, mtime FROM files WHERE kind != 'folder'"):
        _fid, _mt, chunks, err = extract.work((fid, p, ext, mtime, 25 << 20))
        store.set_text(fid, mtime, chunks, err)
    return store, by_path


def index_vectors(store, emb, vindex):
    """What the indexer's meaning phase does: name vectors, then chunk vectors with the file's name in front."""
    from nobadfind import embed
    from nobadfind.indexer import NAME_KINDS
    n = 0
    t = time.perf_counter()
    rows = store.names_without_vectors(NAME_KINDS, 100000)
    texts = {fid: embed.name_text(nm, d) for fid, nm, d in rows}
    todo = [f for f, s in texts.items() if s]
    if todo:
        vecs = emb.encode([texts[f] for f in todo])
        store.add_name_vectors([(f, embed.to_blob(v)) for f, v in zip(todo, vecs)])
        vindex.add([embed.name_key(f) for f in todo], vecs)
        n += len(todo)
    rows = store.chunks_without_vectors(100000)
    titles = store.chunk_titles([r[0] for r in rows])
    vecs = emb.encode([embed.chunk_text(titles.get(r[0], ""), r[1]) for r in rows])
    store.add_vectors([(r[0], embed.to_blob(v)) for r, v in zip(rows, vecs)])
    vindex.add([r[0] for r in rows], vecs)
    n += len(rows)
    return n, time.perf_counter() - t


def run_one(args):
    sys.path.insert(0, APP)
    os.environ["NOBAD_FIND_DATA_DIR"] = args.models_dir
    from nobadfind import embed, models, search
    data = json.load(open(os.path.join(SETS, args.set + ".json"), encoding="utf-8"))
    for v in [x for x in (args.variant or "").split(",") if x]:
        search.VARIANTS.add(v)
    root = tempfile.mkdtemp(prefix="nobadfind-eval-")
    out = {"model": args.model, "set": args.set, "variant": args.variant or "base"}
    try:
        base = private_mb()
        store, by_path = build(data, root)
        emb = q_emb = vindex = None
        if args.model != "none":
            spec = models.get(args.model)
            d = models.model_dir(args.model, args.models_dir)
            emb = embed.Embedder(d, threads=args.threads, gpu=False, spec=spec)
            q_emb = embed.Embedder(d, threads=4, gpu=False, spec=spec, query=True)
            out["load_mb"] = round(private_mb() - base)
            vindex = embed.VectorIndex(spec["dim"])
            vindex.model = args.model
            n, secs = index_vectors(store, emb, vindex)
            out["passages_s"] = round(n / secs, 1)
            out["after_index_mb"] = round(private_mb() - base)
        per, dense, lat = [], [], []
        for qi in data["queries"]:
            t = time.perf_counter()
            r = search.search(store, qi["q"], embedder=q_emb, vindex=vindex, limit=20)
            lat.append((time.perf_counter() - t) * 1000)
            ranked = [by_path.get(os.path.normcase(x["path"])) for x in r["results"]]
            per.append((qi.get("type", ""),) + metrics([x for x in ranked if x], qi["relevant"]))
            if vindex is not None:                       # the model alone: best vector per file
                hits = vindex.search(q_emb.encode([qi["q"]])[0], k=200)
                files = []
                for key, _s in hits:
                    fid = -key if embed.is_name(key) else store.one("SELECT file_id FROM chunks WHERE id = ?", (key,))
                    p = store.one("SELECT path FROM files WHERE id = ?", (fid,))
                    did = by_path.get(os.path.normcase(p or ""))
                    if did and did not in files:
                        files.append(did)
                dense.append(metrics(files, qi["relevant"]))

        def agg(rows, i):
            return round(statistics.fmean(r[i] for r in rows), 3)
        out.update(n=len(per), recall5=agg(per, 1), mrr10=agg(per, 2), ndcg10=agg(per, 3),
                   lat_p50=round(statistics.median(lat), 1), lat_p90=round(sorted(lat)[int(0.9 * (len(lat) - 1))], 1))
        for kind in sorted({p[0] for p in per}):
            rows = [p for p in per if p[0] == kind]
            out[f"by_{kind}"] = {"n": len(rows), "recall5": agg(rows, 1), "mrr10": agg(rows, 2), "ndcg10": agg(rows, 3)}
        if dense:
            out.update(dense_recall5=round(statistics.fmean(d[0] for d in dense), 3),
                       dense_mrr10=round(statistics.fmean(d[1] for d in dense), 3),
                       dense_ndcg10=round(statistics.fmean(d[2] for d in dense), 3))
        print(json.dumps(out))
    finally:
        try:
            store.db.close()
        except Exception:
            pass
        shutil.rmtree(root, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--models-dir", required=True, help="a data folder with the models downloaded (a throwaway one)")
    ap.add_argument("--set", default="english")
    ap.add_argument("--model", action="append", help="catalog id; 'none' = keywords only; repeat (default: all)")
    ap.add_argument("--variant", default="", help="comma list of search.VARIANTS to switch on")
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--one", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--python", default=sys.executable)
    args = ap.parse_args(argv)
    if args.one:
        args.model = args.model[0]
        return run_one(args)
    sys.path.insert(0, APP)
    from nobadfind import models
    todo = args.model or (["none"] + models.ids("text"))
    for mid in todo:
        cmd = [args.python, os.path.abspath(__file__), "--one", "--models-dir", args.models_dir, "--set", args.set,
               "--model", mid, "--threads", str(args.threads)] + (["--variant", args.variant] if args.variant else [])
        r = subprocess.run(cmd, cwd=APP, capture_output=True, text=True, encoding="utf-8")
        line = (r.stdout.strip().splitlines() or [""])[-1]
        print(line if line.startswith("{") else json.dumps({"model": mid, "error": (r.stderr or r.stdout)[-600:]}),
              flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
