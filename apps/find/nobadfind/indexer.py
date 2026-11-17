"""The indexer: scan names, read text, compute meaning vectors, then keep everything fresh. Tuned to this PC.

Phases:  names (parallel walk)  ->  text (worker processes)  ->  meaning (local model)  ->  watching
It steps aside for you: it pauses on battery and during full-screen games or presentations (both settings),
and every worker process runs in Windows background mode (low CPU, disk and memory priority).
"""
import concurrent.futures as cf
import os
import stat
import threading
import time

from . import embed, extract, winapi
from .kinds import READABLE_EXT, kind_of
from .log import log
from .walker import Walker, default_roots

RESCAN_EVERY = 6 * 3600
DEBOUNCE = 2.0


def plan(settings, roots):
    """How hard to work on this PC: walk threads per drive type, text workers from the CPU."""
    cpu = os.cpu_count() or 2
    ssd = all(winapi.is_ssd(os.path.splitdrive(r)[0] + "\\") is not False for r in roots)
    walk = min(32, cpu * 2) if ssd else 2           # parallel reads help SSDs and hurt spinning disks
    text = settings.get("workers") or max(1, min(8, cpu - 2))
    return {"cpu": cpu, "ssd": ssd, "walk_threads": walk, "text_workers": text}


class Indexer:
    def __init__(self, store, settings, vindex=None):
        self.store = store
        self.settings = settings
        self.vindex = vindex
        self.embedder = None
        self.stop_ev = threading.Event()
        self.wake = threading.Event()
        self.status = {"phase": "starting", "files": 0, "texts": 0, "vectors": 0, "paused": "", "rate": 0,
                       "errors": 0, "plan": {}, "last_scan": 0}
        self._pending = {}
        self._plock = threading.Lock()
        self._watcher = None
        self._thread = None

    # ---------- control ----------
    def roots(self):
        return self.settings.get("roots") or default_roots(winapi.fixed_drives())

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True, name="indexer")
        self._thread.start()

    def stop(self):
        self.stop_ev.set()
        self.wake.set()
        if self._watcher:
            self._watcher.stop()

    def rescan(self):
        self.store.set_meta("last_scan", 0)
        self.wake.set()

    def _pause_reason(self):
        if self.settings.get("pause_on_battery") and winapi.on_battery():
            return "on battery"
        if self.settings.get("pause_fullscreen") and winapi.busy_fullscreen():
            return "full-screen app"
        return ""

    def _wait_while_paused(self):
        while not self.stop_ev.is_set():
            why = self._pause_reason()
            self.status["paused"] = why
            if not why:
                return True
            self.stop_ev.wait(15)
        return False

    # ---------- main loop ----------
    def _run(self):
        try:
            self.status["plan"] = plan(self.settings, self.roots())
            log(f"indexer plan {self.status['plan']}")
            self._load_embedder()
            while not self.stop_ev.is_set():
                last = float(self.store.meta("last_scan", 0) or 0)
                if time.time() - last > RESCAN_EVERY:
                    self._scan_names()
                    self._start_watcher()
                self._read_texts()
                self._make_vectors()
                self.status["phase"] = "watching"
                self.status.update(self.store.stats())
                self.wake.wait(30)
                self.wake.clear()
                self._apply_changes()
        except Exception as e:                   # the UI shows this; the log keeps the type only
            log(f"indexer stopped: {type(e).__name__}: {e}", "error")
            self.status["phase"] = "error"
            self.status["error"] = f"{type(e).__name__}"

    def _scan_names(self):
        if not self._wait_while_paused():
            return
        self.status["phase"] = "names"
        gen = int(self.store.meta("gen", 0) or 0) + 1
        roots = self.roots()
        t0 = time.time()
        seen = [0]

        def batch(rows):
            self.store.upsert_files(rows)
            seen[0] += len(rows)
            self.status["files"] = seen[0]
            self.status["rate"] = int(seen[0] / max(0.1, time.time() - t0))

        w = Walker(roots, exclude=self.settings.get("exclude"), threads=self.status["plan"]["walk_threads"],
                   gen=gen, on_batch=batch, stop=self.stop_ev)
        w.run()
        if self.stop_ev.is_set():
            return
        removed = sum(self.store.drop_unseen(r, gen) for r in roots)
        self.store.set_meta("gen", gen)
        self.store.set_meta("last_scan", time.time())
        self.status["last_scan"] = time.time()
        self.status["errors"] = w.errors
        log(f"names: {w.count} entries in {time.time() - t0:.1f}s, {removed} gone, {w.errors} unreadable")

    def _read_texts(self):
        if not self.settings.get("content"):
            return
        exts = set(READABLE_EXT)
        if not self.settings.get("src_mail"):
            exts -= {".eml", ".mbox"}
        max_bytes = self.settings.get("content_max_mb") * 1024 * 1024
        workers = self.status["plan"].get("text_workers", 2)
        with cf.ProcessPoolExecutor(max_workers=workers, initializer=extract.init_worker) as pool:
            while not self.stop_ev.is_set():
                if not self._wait_while_paused():
                    return
                jobs = [(fid, p, ext, mt, max_bytes) for fid, p, ext, _size, mt in
                        self.store.needs_text(exts, max_bytes, limit=workers * 32)]
                if not jobs:
                    return
                self.status["phase"] = "text"
                futs = [pool.submit(extract.work, j) for j in jobs]
                for f in cf.as_completed(futs):
                    try:
                        fid, mtime, chunks, err = f.result(timeout=120)
                    except Exception as e:      # a worker died on a file: mark the batch's file unreadable
                        log(f"text worker failed: {type(e).__name__}", "warn")
                        continue
                    self.store.set_text(fid, mtime, chunks, err)
                    self.status["texts"] += 1
                    if self.stop_ev.is_set():
                        return

    def _load_embedder(self):
        if self.settings.get("semantic") and embed.model_ready():
            try:
                self.embedder = embed.Embedder()
                if self.vindex is not None:
                    self.vindex.load(self.store)
                log(f"meaning search on ({self.embedder.device})")
            except Exception as e:
                log(f"meaning search unavailable: {type(e).__name__}", "warn")
                self.embedder = None

    def _make_vectors(self):
        if not self.embedder:
            return
        while not self.stop_ev.is_set():
            if not self._wait_while_paused():
                return
            rows = self.store.chunks_without_vectors(64)
            if not rows:
                return
            self.status["phase"] = "meaning"
            vecs = self.embedder.encode([r[1] for r in rows])
            self.store.add_vectors([(r[0], embed.to_blob(v)) for r, v in zip(rows, vecs)])
            if self.vindex is not None:
                self.vindex.add([r[0] for r in rows], vecs)
            self.status["vectors"] += len(rows)

    # ---------- live changes ----------
    def _start_watcher(self):
        if self._watcher:
            return
        from .watcher import Watcher
        self._watcher = Watcher(self.roots(), self._on_changes, self._on_overflow)
        self._watcher.start()

    def _on_changes(self, root, paths):
        with self._plock:
            now = time.time()
            for p in paths:
                self._pending[p] = now
        self.wake.set()

    def _on_overflow(self, root):
        log(f"too many changes at once under {root}; rescanning it")
        self.store.set_meta("last_scan", 0)
        self.wake.set()

    def _apply_changes(self):
        time.sleep(DEBOUNCE)
        with self._plock:
            paths, self._pending = list(self._pending), {}
        if not paths:
            return
        gen = int(self.store.meta("gen", 0) or 0)
        gone, dirs = [], []
        rows = []
        w = Walker(self.roots(), exclude=self.settings.get("exclude"), gen=gen)
        for p in paths:
            if w.excluded(p):
                continue
            name, parent = os.path.basename(p), os.path.dirname(p)
            try:
                st = os.stat(p, follow_symlinks=False)
            except OSError:
                gone.append(p)
                continue
            if stat.S_ISDIR(st.st_mode):
                dirs.append(p)
                rows.append((p, name, parent, "", "folder", 0, st.st_mtime, st.st_ctime, gen))
            elif stat.S_ISREG(st.st_mode):
                rows.append((p, name, parent, os.path.splitext(name)[1].lower(), kind_of(name), st.st_size,
                             st.st_mtime, st.st_ctime, gen))
        self.store.upsert_files(rows)
        if gone:
            self.store.remove_paths(gone)
        for d in dirs[:50]:                         # a new or moved folder: pick up what's inside it
            Walker([d], exclude=self.settings.get("exclude"), threads=4, gen=gen,
                   on_batch=self.store.upsert_files, stop=self.stop_ev).run()
