"""The indexer: scan names, read text, compute meaning vectors, then keep everything fresh. Tuned to this PC.

Phases:  names (parallel walk)  ->  text (worker processes)  ->  meaning (local model)  ->  watching
It steps aside for you: it pauses on battery, during full-screen games or presentations and during calls
(settings), works gently while you use the PC and at full speed when you're away, and every worker process
runs in Windows background mode (low CPU, disk and memory priority).
"""
import concurrent.futures as cf
import json
import os
import stat
import threading
import time

import numpy as np

from . import embed, extract, ocr, photo, winapi
from .governor import FULL, PAUSED, workers_for
from .kinds import READABLE_EXT, kind_of
from .log import log
from .walker import Walker, default_roots

RESCAN_EVERY = 6 * 3600
DEBOUNCE = 2.0
PHOTO_BATCH = 8                  # photos sent to the photo reader at a time
JOB_TIMEOUT = 300                # seconds one file may take before its reader is stopped
REMOVABLE_RESCAN = 1800          # USB drives aren't watched (that would block "safely remove"): re-walk them
PAUSE_CHECK_EVERY = 5.0
# Names worth a meaning vector: things people make and keep (not code, programs or unknown files)
NAME_KINDS = {"pdf", "document", "spreadsheet", "slides", "text", "email", "image", "video", "audio", "archive",
              "ebook", "folder"}
SKIP_NAME_DIRS = ("\\program files", "\\windows\\", "\\appdata\\", "\\$recycle.bin")
IDLE_AFTER = 120                 # seconds without keyboard or mouse input: you're away, work at full speed


def _kill_pool(pool):
    """Stop every reader process of a pool (one is stuck on a file; the pool can't cancel a running job)."""
    for proc in list(getattr(pool, "_processes", {}).values()):
        try:
            proc.terminate()
        except Exception:
            pass


def plan(settings, roots):
    """How hard to work on this PC: walk threads per drive type, text workers from the CPU."""
    cpu = os.cpu_count() or 2
    ssd = all(winapi.is_ssd(os.path.splitdrive(r)[0] + "\\") is not False for r in roots)
    walk = min(32, cpu * 2) if ssd else 2           # parallel reads help SSDs and hurt spinning disks
    text = settings.get("workers") or max(1, min(8, cpu - 2))        # while you use the PC: two threads free
    idle = settings.get("workers") or max(1, min(16, cpu - 1))        # while you're away: one thread free
    if not ssd and not settings.get("workers"):
        text, idle = min(text, 2), min(idle, 2)    # a spinning disk is the bottleneck, more readers only seek
    return {"cpu": cpu, "ssd": ssd, "walk_threads": walk, "text_workers": text, "text_workers_idle": idle}


class Indexer:
    def __init__(self, store, settings, vindex=None, governor=None):
        self.store = store
        self.governor = governor
        self.settings = settings
        self.vindex = vindex
        self.embedder = None
        self.stop_ev = threading.Event()
        self.wake = threading.Event()
        self.status = {"phase": "starting", "files": 0, "texts": 0, "vectors": 0, "paused": "", "rate": 0,
                       "errors": 0, "plan": {}, "last_scan": 0}
        if governor is not None:
            self.status.update(level=governor.decision.level, reason=governor.decision.reason)
        self._pending = {}
        self._plock = threading.Lock()
        self._watcher = None
        self._thread = None
        self._suspects = []              # jobs in flight when a reader crashed (re-read one at a time)
        self._pause = (0.0, "")          # (checked at, reason): the checks cost a registry walk
        self._watched = None             # roots the live watcher covers
        self._walked = {}                # removable root -> when it was last walked
        self.drive_list = []
        self._photo_one_by_one = False   # after a photo stopped the reader: find which one
        self.photo_text = None           # the photo model's text half, for questions (when photo meaning is on)
        self.pindex = embed.VectorIndex(photo.PHOTO_DIM, ("SELECT file_id, v FROM pvecs WHERE length(v) > 0",))             # known_drives(), refreshed by the indexer loop (searches read it)

    # ---------- control ----------
    def roots(self, drives=None):
        """What to index: the folders in Settings, or your profile + fixed drives (+ plugged-in and network
        drives when those settings are on)."""
        if self.settings.get("roots"):
            return list(self.settings.get("roots"))
        drives = winapi.drives() if drives is None else drives
        extra = [d["root"] for d in drives
                 if (d["type"] == "removable" and self.settings.get("index_removable"))
                 or (d["type"] == "network" and self.settings.get("index_network"))]
        return default_roots([d["root"] for d in drives if d["type"] == "fixed"]) + extra

    def known_drives(self):
        """Every drive the index has files from, with its kind and name, and whether it's plugged in now."""
        try:
            known = json.loads(self.store.meta("drives", "{}") or "{}")
        except ValueError:
            known = {}
        now = {d["root"]: d for d in winapi.drives()}
        changed = False
        for root, d in now.items():
            if known.get(root) != {"type": d["type"], "label": d["label"]}:
                known[root] = {"type": d["type"], "label": d["label"]}
                changed = True
        if changed:
            self.store.set_meta("drives", json.dumps(known))
        self.drive_list = [{"root": r, "type": v.get("type"), "label": v.get("label") or "", "present": r in now}
                           for r, v in sorted(known.items())]
        return self.drive_list

    def _away(self):
        if self.governor is not None:
            return self.governor.decision.level == FULL
        return winapi.idle_seconds() >= IDLE_AFTER

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
        if self.governor is not None:
            d = self.governor.decision
            return d.reason if d.level == PAUSED else ""
        t, why = self._pause
        if time.monotonic() - t < PAUSE_CHECK_EVERY:
            return why
        why = self._check_pause()
        self._pause = (time.monotonic(), why)
        return why

    def _check_pause(self):
        if self.settings.get("pause_on_battery") and winapi.on_battery():
            return "on battery"
        if self.settings.get("pause_fullscreen") and winapi.busy_fullscreen():
            return "full-screen app"
        if self.settings.get("pause_on_call") and winapi.in_call():
            return "microphone or camera in use"
        return ""

    def _wait_while_paused(self):
        while not self.stop_ev.is_set():
            if self.governor is not None:
                d = self.governor.decision
                self.status["level"], self.status["reason"] = d.level, d.reason
            why = self._pause_reason()
            self.status["paused"] = why
            if not why:
                return True
            self.stop_ev.wait(0.5 if self.governor is not None else 15)
        return False

    # ---------- main loop ----------
    def _run(self):
        try:
            self.status["plan"] = plan(self.settings, self.roots())
            log(f"indexer plan {self.status['plan']}")
            self._load_embedder()
            self._load_photo()
            self.known_drives()
            if time.time() - float(self.store.meta("last_scan", 0) or 0) <= RESCAN_EVERY:
                self._start_watcher()               # a recent index: just keep it fresh from now on
            while not self.stop_ev.is_set():
                last = float(self.store.meta("last_scan", 0) or 0)
                if time.time() - last > RESCAN_EVERY:
                    self._scan_names()
                    self._start_watcher(restart=True)
                else:
                    self._new_drives()
                self._read_texts()
                self._read_texts(images=True)
                self._make_vectors()
                self._photo_vectors()
                self.status["phase"] = "watching"
                self.status.update(self.store.stats())
                self._tidy_vectors()
                self.release_idle_models()
                self.known_drives()
                self.wake.wait(30)
                self.wake.clear()
                self._apply_changes()
        except Exception as e:                   # the UI shows this; the log keeps the type only
            log(f"indexer stopped: {type(e).__name__}: {e}", "error")
            self.status["phase"] = "error"
            self.status["error"] = f"{type(e).__name__}"

    def _removable_roots(self, roots):
        rem = {d["root"].lower() for d in winapi.drives() if d["type"] == "removable"}
        return [r for r in roots if os.path.splitdrive(r)[0].lower() + "\\" in rem]

    def _new_drives(self):
        """A drive was plugged in (or a setting added one): index just that drive and watch it.
        USB drives are re-walked every half hour instead of watched, so Windows can still eject them."""
        roots = self.roots()
        key = {os.path.normcase(r) for r in roots}
        if self._watched is not None and key != self._watched:
            new = [r for r in roots if os.path.normcase(r) not in self._watched]
            self.known_drives()
            if new:
                log(f"new drive or folder to index: {len(new)}")
                self._scan_names(only=new)
            self._start_watcher(restart=True)
        due = [r for r in self._removable_roots(roots)
               if time.time() - self._walked.get(os.path.normcase(r), 0) > REMOVABLE_RESCAN]
        if due:
            self._scan_names(only=due)

    def _scan_names(self, only=None):
        if not self._wait_while_paused():
            return
        self.status["phase"] = "names"
        gen = int(self.store.meta("gen", 0) or 0) + 1
        roots = only or self.roots()
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
        # a drive that isn't plugged in keeps its files in the index (shown as "not connected"); a USB or
        # network drive that had read errors (pulled out, network dropped) keeps them until a clean walk
        fixed = {d["root"].lower() for d in winapi.drives() if d["type"] == "fixed"}
        removed = sum(self.store.drop_unseen(r, gen) for r in roots if os.path.isdir(r) and (
            not w.errors or os.path.splitdrive(r)[0].lower() + "\\" in fixed))
        for r in self._removable_roots(roots):
            self._walked[os.path.normcase(r)] = time.time()
        self.store.set_meta("gen", gen)
        if not only:
            self.store.set_meta("last_scan", time.time())
        self.status["last_scan"] = time.time()
        self.status["errors"] = w.errors
        log(f"names: {w.count} entries in {time.time() - t0:.1f}s, {removed} gone, {w.errors} unreadable")

    def _read_texts(self, images=False):
        """Read the text inside files in worker processes. images=True: the OCR pass (photos, screenshots),
        which is slow, so it runs after every document has been read."""
        if not self.settings.get("content"):
            return
        use_ocr = bool(self.settings.get("ocr")) and ocr.available()
        if images:
            if not use_ocr:
                return
            exts, min_bytes, phase = set(ocr.OCR_EXT), ocr.MIN_IMAGE_BYTES, "images"
        else:
            exts, min_bytes, phase = set(READABLE_EXT), 0, "text"
            if not self.settings.get("src_mail"):
                exts -= {".eml", ".mbox"}
        if images and self.store.meta("ocr_pass") != "1":
            self.store.reset_scanned_pdfs()          # PDFs read before OCR was on: read the scans again
            self.store.set_meta("ocr_pass", "1")
        max_bytes = self.settings.get("content_max_mb") * 1024 * 1024
        plan_ = self.status["plan"]
        gentle, full = plan_.get("text_workers", 2), plan_.get("text_workers_idle", 2)
        inflight, queued = {}, []                    # future -> (job, started)
        pool = cf.ProcessPoolExecutor(max_workers=max(gentle, full), initializer=extract.init_worker)
        try:
            while not self.stop_ev.is_set():
                if not self._wait_while_paused():
                    return
                away = self._away()
                if self.governor is not None:
                    level = self.governor.decision.level
                    self.status["speed"] = level
                else:
                    self.status["speed"] = "full (you're away)" if away else "gentle (you're using the PC)"
                # after a reader crashed, the files that were being read run one at a time to find the culprit
                careful = bool(self._suspects)
                if self.governor is not None:
                    limit = 1 if careful else max(1, workers_for(level, plan_))
                else:
                    limit = 1 if careful else (full if away else gentle)
                if careful:
                    if not inflight:
                        queued = [self._suspects.pop(0)]
                elif not queued and len(inflight) < limit:
                    skip = {job[0] for job, _t in inflight.values()}
                    queued = [(fid, p, ext, mt, max_bytes, use_ocr) for fid, p, ext, _size, mt in
                              self.store.needs_text(exts, max_bytes, limit=full * 16, min_bytes=min_bytes)
                              if fid not in skip]
                if not queued and not inflight:
                    return
                self.status["phase"] = phase
                while queued and len(inflight) < limit:
                    job = queued.pop(0)
                    inflight[pool.submit(extract.work, job)] = (job, time.monotonic())
                done, _ = cf.wait(list(inflight), timeout=5, return_when=cf.FIRST_COMPLETED)
                for f in done:
                    job, _t = inflight.pop(f)
                    try:
                        fid, mtime, chunks, err = f.result()
                    except cf.BrokenExecutor:
                        # a worker process died: every file in flight fails with it, so don't blame them yet
                        lost = [job] + [j for j, _t in inflight.values()]
                        if careful:
                            log("a file crashed the text reader; it won't be read again until it changes", "warn")
                            self.store.set_text(job[0], job[3], [], "reader crashed")
                        else:
                            self._suspects = lost
                        return                      # the pool is gone; the next round starts a new one
                    except Exception as e:
                        log(f"text worker failed: {type(e).__name__}", "warn")
                        fid, mtime, chunks, err = job[0], job[3], [], "reader failed"
                    self.store.set_text(fid, mtime, chunks, err)
                    self.status["texts"] += 1
                stuck = [(f, j) for f, (j, t) in inflight.items() if time.monotonic() - t > JOB_TIMEOUT]
                if stuck:
                    for _f, j in stuck:
                        self.store.set_text(j[0], j[3], [], "took too long")
                    log(f"{len(stuck)} file(s) took too long to read; restarting the readers", "warn")
                    _kill_pool(pool)                # the other files in flight are simply read again
                    return
        finally:
            pool.shutdown(wait=True, cancel_futures=True)

    def _load_embedder(self):
        if self.settings.get("semantic") and embed.model_ready():
            try:
                if not embed.model_ready():
                    raise RuntimeError("model not downloaded")
                self.embedder = embed.Lazy(embed.Embedder, "meaning")
                if self.store.meta("vec_version") != embed.VEC_VERSION:
                    log("meaning vectors are made a better way now; computing them again")
                    self.store.drop_vectors()
                    self.store.set_meta("vec_version", embed.VEC_VERSION)
                if self.vindex is not None:
                    self.vindex.load(self.store)
                log("meaning search on (the model loads when it's needed)")
            except Exception as e:
                log(f"meaning search unavailable: {type(e).__name__}", "warn")
                self.embedder = None

    def _make_vectors(self):
        """Meaning vectors: first for names (short, fast, and the only clue for photos, music or bills),
        then for the text inside files, each piece with its file's name in front."""
        if not self.embedder:
            return
        self._name_vectors()
        while not self.stop_ev.is_set():
            if not self._wait_while_paused():
                return
            rows = self.store.chunks_without_vectors(128)
            if not rows:
                return
            self.status["phase"] = "meaning"
            titles = self.store.chunk_titles([r[0] for r in rows])
            vecs = self.embedder.encode([embed.chunk_text(titles.get(r[0], ""), r[1]) for r in rows])
            self.store.add_vectors([(r[0], embed.to_blob(v)) for r, v in zip(rows, vecs)])
            if self.vindex is not None:
                self.vindex.add([r[0] for r in rows], vecs)
            self.status["vectors"] += len(rows)
            self._breathe()

    def _name_vectors(self):
        while not self.stop_ev.is_set():
            if not self._wait_while_paused():
                return
            rows = self.store.names_without_vectors(NAME_KINDS, 512)
            if not rows:
                return
            self.status["phase"] = "meaning"
            texts = {fid: ("" if any(s in d.lower() for s in SKIP_NAME_DIRS) else embed.name_text(n, d))
                     for fid, n, d in rows}
            todo = [fid for fid, t in texts.items() if t]
            vecs = self.embedder.encode([texts[f] for f in todo]) if todo else []
            blobs = dict(zip(todo, (embed.to_blob(v) for v in vecs)))
            self.store.add_name_vectors([(fid, blobs.get(fid, b"")) for fid in texts])
            if self.vindex is not None and todo:
                self.vindex.add([embed.name_key(f) for f in todo], vecs)
            self.status["vectors"] += len(todo)
            self._breathe()

    # ---------- photo meaning ----------
    def _load_photo(self):
        if self.settings.get("photo_meaning") and photo.model_ready():
            try:
                self.photo_text = embed.Lazy(photo.TextEncoder, "photo text")
                self.pindex.load(self.store)
                log(f"photo meaning on ({self.pindex.n} photos ready)")
            except Exception as e:
                log(f"photo meaning unavailable: {type(e).__name__}", "warn")
                self.photo_text = None

    def _photo_vectors(self):
        """What's in each photo, made in one separate low-priority process (photos are decoded there)."""
        if not self.photo_text or not self.settings.get("photo_meaning"):
            return
        pool = cf.ProcessPoolExecutor(max_workers=1, initializer=photo.init_worker)
        try:
            while not self.stop_ev.is_set():
                if not self._wait_while_paused():
                    return
                rows = self.store.photos_to_read(photo.PHOTO_EXT, photo.MIN_PHOTO_BYTES, photo.MAX_PHOTO_BYTES,
                                                 limit=PHOTO_BATCH if self._photo_one_by_one else 64)
                if not rows:
                    return
                self.status["phase"] = "photos"
                step = 1 if self._photo_one_by_one else PHOTO_BATCH
                for i in range(0, len(rows), step):
                    if self.stop_ev.is_set() or self._pause_reason():
                        break
                    batch = rows[i:i + step]
                    away = self._away()
                    fut = pool.submit(photo.embed_photos, [(f, p, m, photo.PHOTO_DIR) for f, p, m in batch], away)
                    try:
                        results = fut.result(timeout=JOB_TIMEOUT)
                    except (cf.TimeoutError, cf.BrokenExecutor) as e:
                        # one of these photos hangs or crashes the reader: read them one by one next time
                        if len(batch) == 1:
                            self.store.set_photo_vector(batch[0][0], batch[0][2], b"", "unreadable")
                        else:
                            self._photo_one_by_one = True
                        log(f"photo reader stopped ({type(e).__name__})", "warn")
                        _kill_pool(pool)
                        return
                    for fid, mtime, blob, err in results:
                        self.store.set_photo_vector(fid, mtime, blob, err)
                        if blob:
                            self.pindex.add([fid], np.frombuffer(blob, np.float16)[None])
                            self.status["photos"] = self.status.get("photos", 0) + 1
                    if not away:
                        self.stop_ev.wait(0.2)      # gently while you use the PC
                self._photo_one_by_one = False      # the suspects were read one by one: back to batches
        finally:
            pool.shutdown(wait=True, cancel_futures=True)

    def warm_models(self):
        """The window just opened: load the models now, so the first search is quick (released again when idle)."""
        for m in (self.embedder, self.photo_text):
            if isinstance(m, embed.Lazy):
                try:
                    m.encode(["warm"] if m is self.embedder else "warm")
                except Exception as e:
                    log(f"model warm-up failed: {type(e).__name__}", "warn")

    def models_loaded(self):
        return [m.name for m in (self.embedder, self.photo_text) if isinstance(m, embed.Lazy) and m.loaded]

    def release_idle_models(self):
        """Light when idle: models leave memory a few minutes after the last search or indexing work."""
        for m in (self.embedder, self.photo_text):
            if isinstance(m, embed.Lazy):
                m.release_if_idle()

    def _tidy_vectors(self):
        """Vectors of text that changed or files that went stay in memory until the index is reloaded."""
        if self.vindex is None or not self.embedder:
            return
        live = self.status.get("vectors", 0) + self.status.get("name_vectors", 0)
        if self.vindex.n > 1.3 * live + 1000:
            self.vindex.load(self.store)
        if self.photo_text and self.pindex.n > 1.3 * self.status.get("photo_vectors", 0) + 200:
            self.pindex.load(self.store)            # photos that changed were added again

    def _breathe(self):
        if not self._away():
            self.stop_ev.wait(0.25)                 # leave the CPU (or GPU) to you between batches

    # ---------- live changes ----------
    def _start_watcher(self, restart=False):
        if self._watcher and not restart:
            return
        if self._watcher:
            self._watcher.stop()
            self._watcher = None
        from .watcher import Watcher
        roots = self.roots()
        self._watched = {os.path.normcase(r) for r in roots}
        removable = set(self._removable_roots(roots))
        self._watcher = Watcher([r for r in roots if r not in removable], self._on_changes, self._on_overflow)
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
