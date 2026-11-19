"""The indexer: scan names, read text, compute meaning vectors, then keep everything fresh. Tuned to this PC.

Phases:  names (parallel walk)  ->  text (worker processes)  ->  meaning (local model, in a worker process)
         ->  watching
It steps aside for you: it pauses on battery, during full-screen games or presentations and during calls
(settings), works gently while you use the PC and at full speed when you're away, and every worker process
runs at low CPU, disk and memory priority (winapi.worker_priority).
"""
import concurrent.futures as cf
import json
import os
import stat
import threading
import time

import numpy as np

from . import embed, extract, models, ocr, photo, scope, winapi
from .governor import FULL, PAUSED, workers_for
from .kinds import READABLE_EXT, kind_of
from .log import log
from .walker import Walker

RESCAN_EVERY = 6 * 3600
NAMES_ONLY = "names only"         # text_err / photo err of a secret: its content is never read (scope.Rules)
DEBOUNCE = 2.0
PHOTO_BATCH = 8                  # photos sent to the photo reader at a time
MEANING_BACKOFF = (30, 1800)     # seconds before trying a failed meaning worker again: doubling, capped
MEANING_TIMEOUT = 120           # seconds one batch of meaning vectors may take before its worker is replaced
JOB_TIMEOUT = 300                # seconds one file may take before its reader is stopped
REMOVABLE_RESCAN = 1800          # USB drives aren't watched (that would block "safely remove"): re-walk them
PAUSE_CHECK_EVERY = 5.0
READER_TASKS = 200             # files one text reader process reads before a fresh one takes over (its memory
                                 # from pdf/zip parsing goes back to Windows; a new reader starts in ~0.2 s)
RECYCLE_AFTER = 60               # seconds paused before the worker processes end ("Paused: nothing runs")
RECYCLE = "recycle"              # _wait_while_paused / _await: paused that long, end the workers
# Names worth a meaning vector: things people make and keep (not code, programs or unknown files)
NAME_KINDS = {"pdf", "document", "spreadsheet", "slides", "text", "email", "image", "video", "audio", "archive",
              "ebook", "folder"}
SKIP_NAME_DIRS = ("\\program files", "\\windows\\", "\\appdata\\", "\\$recycle.bin")
IDLE_AFTER = 120                 # seconds without keyboard or mouse input: you're away, work at full speed


STATS_EVERY = 30                 # seconds between index counts while watching (_refresh_stats)
NAME_BATCH = 2000                # rows per batch of the names walk (Walker's default)


def drive_root(path):
    d = os.path.splitdrive(path)[0]
    return d.upper() + "\\" if len(d) == 2 else ""


def _kill_pool(pool):
    """Stop every reader process of a pool (one is stuck on a file; the pool can't cancel a running job)."""
    for proc in list(getattr(pool, "_processes", {}).values()):
        try:
            proc.terminate()
        except Exception:
            pass


def vector_model(store):
    """Catalog id of the model the index's meaning vectors come from; None while there are none. Indexes made
    before 0.8.0 have all-MiniLM-L6-v2 vectors and no id."""
    mid = store.meta("vec_model")
    if mid:
        return mid
    if store.one("SELECT 1 FROM nvecs LIMIT 1") or store.one("SELECT 1 FROM vecs LIMIT 1"):
        return "minilm-l6-v2"
    return None


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
    def __init__(self, store, settings, vindex=None, governor=None, activity=None):
        self.store = store
        self.governor = governor
        self.activity = activity         # every worker Find ends is listed there with its reason
        self._clock = time.monotonic     # tests replace it
        self.paused_s = 0.0              # how long the last _wait_while_paused waited
        self._recycled = False           # a long pause ended the workers: start again from the top
        self._recycle_req = False        # the watchdog asked for fresh workers (Find uses too much memory)
        self.settings = settings
        self.vindex = vindex
        self.embedder = None             # the query encoder for live search (CPU, in this process)
        self._vectors_in_worker = False  # index-time vectors come from the meaning worker (the real model)
        self.vectors_in_process = False  # tests: index-time vectors from make_embedder, in this process
        self.text_model = None           # catalog id of the model the index's vectors (and the encoder) use
        self._passage = {}               # model id -> in-process passage encoder (vectors_in_process only)
        self._notes = []                 # what _note said (tests read it)
        self._mpool, self._mpool_gpu, self._mpool_model = None, None, None
        self._text_pool, self._photo_pool = None, None   # for worker_names (the watchdog's messages)
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
        self._stats_at = None            # when _refresh_stats last counted the index
        self.turbo = None                # turbo.Turbo (engine.py): the optional elevated NTFS reader, or None
        self._walked = {}                # removable root -> when it was last walked
        self.drive_list = []
        self._photo_one_by_one = False   # after a photo stopped the reader: find which one
        self._meaning_fails, self._meaning_retry_at = 0, 0.0     # meaning workers that failed in a row
        self._memory_noted = None        # when the workers' memory limit was last reported
        self.photo_text = None           # the photo model's text half, for questions (when photo meaning is on)
        self.photo_model = None          # catalog id of the photo model in use
        self.pindex = embed.VectorIndex(photo.PHOTO_DIM, ("SELECT file_id, v FROM pvecs WHERE length(v) > 0",))             # known_drives(), refreshed by the indexer loop (searches read it)

    # ---------- control ----------
    def roots(self, drives=None):
        """What to index (scope.roots_for): Whole PC = your profile + fixed drives, My files = your own folders,
        Custom = the folders in Settings; plus plugged-in and network drives when those settings are on."""
        drives = winapi.drives() if drives is None else drives
        return scope.roots_for(self.settings, drives)

    def rules(self):
        """What's in and out inside the roots (scope.Rules): the categories in Settings."""
        return scope.Rules.from_settings(self.settings)

    def _skip_secrets(self, rows, mark):
        """Names only (scope.Rules.names_only): secrets, browser profiles and app databases. Rows (id, path, ...)
        for one of them are marked, never read, whatever the switches say."""
        rules = self.rules()
        keep = []
        for r in rows:
            if rules.names_only(r[1]):
                mark(r)
            else:
                keep.append(r)
        return keep

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
        """Start (or start again after stop() + join()). False while the indexer is still running."""
        if self._thread is not None and self._thread.is_alive():
            return False
        if self.stop_ev.is_set():
            self.stop_ev = threading.Event()
        self.wake.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="indexer")
        self._thread.start()
        return True

    def stop(self, keep_watching=False):
        """keep_watching: the live watcher (threads in this process, no worker) keeps collecting changes, so
        indexing picks them up when it starts again."""
        self.stop_ev.set()
        self.wake.set()
        if self._watcher and not keep_watching:
            self._watcher.stop()
            self._watcher = None

    def join(self, timeout=10):
        """Wait for the indexer (and its worker processes) to end. True when it has."""
        t = self._thread
        if t is not None:
            t.join(timeout)
        return t is None or not t.is_alive()

    def rescan(self):
        self.store.set_meta("last_scan", 0)
        if self.turbo is not None:
            self.turbo.forget_place()               # read everything again, not just the journal since last time
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

    def _wait_while_paused(self, max_wait=None):
        """Wait while paused. True: go on; False: stopping; RECYCLE: still paused after max_wait seconds (the
        caller ends its worker processes, so nothing runs while paused). self.paused_s: how long it waited."""
        t0 = self._clock()
        self.paused_s = 0.0
        while not self.stop_ev.is_set():
            if max_wait is not None and self._recycle_req:
                return RECYCLE
            if self.governor is not None:
                d = self.governor.decision
                self.status["level"], self.status["reason"] = d.level, d.reason
            why = self._pause_reason()
            self.status["paused"] = why
            if not why:
                return True
            self.paused_s = self._clock() - t0
            if max_wait is not None and self.paused_s >= max_wait:
                return RECYCLE
            self.stop_ev.wait(0.5 if self.governor is not None else 15)
            self.paused_s = self._clock() - t0
        return False

    def _await(self, fut, timeout):
        """fut's result, where only time not paused counts towards timeout: a pause caps the workers at 5% CPU,
        and that must not make a file "take too long". RECYCLE when it stays paused for RECYCLE_AFTER with
        fut in flight, None when stopping. Raises cf.TimeoutError, or what the job raised."""
        used = paused = 0.0
        last = self._clock()
        while not fut.done():
            if self.stop_ev.is_set():
                return None
            if self._recycle_req:
                return RECYCLE
            cf.wait([fut], timeout=0.5)
            now = self._clock()
            dt, last = now - last, now
            if fut.done():
                break
            if self._pause_reason():
                paused += dt
                if paused >= RECYCLE_AFTER:
                    return RECYCLE
            else:
                paused = 0.0
                used += dt
                if used > timeout:
                    raise cf.TimeoutError()
        return fut.result()

    def _note(self, text):
        """A worker Find ended, with the reason, for the activity list (and the log)."""
        self._notes = (self._notes + [text])[-20:]
        log(text, "warn")
        if self.activity is not None:
            try:
                self.activity.add("kill", text)
            except Exception:
                pass

    MEMORY_NOTE_EVERY = 1800

    def _memory_limit_hit(self, what):
        """A worker's allocation failed: the worker group reached its memory limit (jobs.worker_memory_limit_mb).
        Logged and listed once in a while, not per file."""
        now = self._clock()
        if self._memory_noted is not None and now - self._memory_noted < self.MEMORY_NOTE_EVERY:
            return
        self._memory_noted = now
        from . import jobs
        peak = jobs.WORKERS.memory_peak_mb() if jobs.WORKERS is not None else 0
        self._note(f"NOBAD Find's {what} reached their memory limit"
                   + (f" ({peak} MB)" if peak else "") + "; the files they were reading are read again one at a time")

    def recycle_workers(self):
        """The watchdog: Find uses too much memory. The worker processes end at their next safe point (the
        work in flight is done again) and fresh ones start."""
        if self.worker_names():
            self._recycle_req = True

    def _recycle(self, pool, what):
        """A long pause or the watchdog: end this pool's worker processes now (its jobs are done again later)."""
        alive = bool(getattr(pool, "_processes", None))
        _kill_pool(pool)
        self._recycled = True
        if alive and self._recycle_req:
            self._note(f"Using a lot of memory, so NOBAD Find ended its {what}; they start again in a moment")
        elif alive:
            self._note(f"Paused for over a minute, so NOBAD Find ended its {what}; work starts again when it "
                       "resumes")
        self._recycle_req = False

    # ---------- main loop ----------
    def _run(self):
        self._recycled = False
        try:
            try:
                if self.store.upgrade_text_index():
                    log("text index rebuilt so Hindi words stay whole")
                if self.store.upgrade_name_index():
                    log("name word index built (fast one- and two-letter searches)")
            except Exception as e:
                log(f"text index upgrade failed: {type(e).__name__}", "warn")
            self.status["plan"] = plan(self.settings, self.roots())
            log(f"indexer plan {self.status['plan']}")
            if self.embedder is None:               # started again after a stop: already loaded
                self._load_embedder()
            if self.photo_text is None:
                self._load_photo()
            if self.turbo is not None:
                self.turbo.ensure()                 # turbo on: one permission prompt per engine run
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
                for step in (self._read_texts, lambda: self._read_texts(images=True), self._make_vectors,
                             self._photo_vectors):
                    if self._recycled:
                        break
                    step()
                if self._recycled:
                    # a long pause ended the workers: wait it out with none running, then start from the top
                    self._recycled = False
                    self._wait_while_paused()
                    continue
                self.status["phase"] = "watching"
                self._refresh_stats()
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

    def _refresh_stats(self):
        """The index counts for the status (six COUNTs over every row: about a second at a million entries), at
        most every STATS_EVERY seconds. Changes arriving all the time (a whole PC with caches) must not make the
        watching loop count the whole index each round."""
        now = self._clock()
        if self._stats_at is not None and now - self._stats_at < STATS_EVERY:
            return
        self._stats_at = now
        self.status.update(self.store.stats())

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
            if len(rows) >= NAME_BATCH:             # a whole PC is a long walk: it steps aside like the rest
                if self._pause_reason():
                    self._wait_while_paused()
                else:
                    self._breathe()

        read, caught = set(), set()
        if self.turbo is not None and not only:
            read, caught = self.turbo.scan(roots, gen, batch, self.stop_ev)
        covered = read | caught
        walk = [r for r in roots if drive_root(r) not in covered]
        w = Walker(walk, exclude=self.settings.get("exclude"), threads=self.status["plan"]["walk_threads"],
                   gen=gen, on_batch=batch, stop=self.stop_ev, rules=self.rules())
        w.run()
        if self.stop_ev.is_set():
            return
        # a drive that isn't plugged in keeps its files in the index (shown as "not connected"); a USB or
        # network drive that had read errors (pulled out, network dropped) keeps them until a clean walk
        fixed = {d["root"].lower() for d in winapi.drives() if d["type"] == "fixed"}
        # a drive turbo caught up from its change journal wasn't read again: its rows keep their generation
        removed = sum(self.store.drop_unseen(r, gen) for r in roots if os.path.isdir(r) and drive_root(r) not in
                      caught and (not w.errors or os.path.splitdrive(r)[0].lower() + "\\" in fixed))
        if not only:
            # a full scan walked everything in scope on the fixed drives: what it didn't see there is gone, or out
            # of the scope now (Whole PC -> My files, system folders turned off)
            removed += sum(self.store.drop_unseen(d, gen) for d in sorted(fixed)
                           if os.path.isdir(d) and drive_root(d) not in caught)
        for r in self._removable_roots(roots):
            self._walked[os.path.normcase(r)] = time.time()
        self.store.set_meta("gen", gen)
        if not only:
            self.store.set_meta("last_scan", time.time())
        self.status["last_scan"] = time.time()
        self.status["errors"] = w.errors
        log(f"names: {seen[0]} entries in {time.time() - t0:.1f}s ({len(read)} drive(s) by turbo, {len(caught)} "
            f"caught up), {removed} gone, {w.errors} unreadable")

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
        alone = set()                                # file ids sent while nothing else was being read
        size = max(gentle, full)

        def new_pool():
            # Not max_tasks_per_child: on Python 3.11 each replacement grows the pool to max_workers (8 readers
            # at Light). A fresh pool every READER_TASKS files per reader keeps readers to what the level allows.
            self._text_pool = cf.ProcessPoolExecutor(max_workers=size, initializer=extract.init_worker)
            return self._text_pool
        pool, sent = new_pool(), 0
        try:
            while not self.stop_ev.is_set():
                go = self._wait_while_paused(max_wait=RECYCLE_AFTER)
                if not go:
                    return
                if go is RECYCLE:
                    self._recycle(pool, "text readers")
                    return                          # the files in flight are read again, not marked
                if self.paused_s:                   # paused time isn't reading time (JOB_TIMEOUT)
                    inflight = {f: (j, t + self.paused_s) for f, (j, t) in inflight.items()}
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
                    todo = self._skip_secrets(
                        self.store.needs_text(exts, max_bytes, limit=full * 16, min_bytes=min_bytes),
                        lambda r: self.store.set_text(r[0], r[4], [], NAMES_ONLY))
                    queued = [(fid, p, ext, mt, max_bytes, use_ocr) for fid, p, ext, _size, mt in todo
                              if fid not in skip]
                if not queued and not inflight:
                    return
                self.status["phase"] = phase
                budget = READER_TASKS * max(1, limit)
                if sent >= budget and not inflight:
                    pool.shutdown(wait=True)        # these readers have done their share: fresh ones
                    pool, sent = new_pool(), 0
                while queued and len(inflight) < limit and sent < budget:
                    sent += 1
                    job = queued.pop(0)
                    if careful:
                        alone.add(job[0])
                    inflight[pool.submit(extract.work, job)] = (job, self._clock())
                done, _ = cf.wait(list(inflight), timeout=5, return_when=cf.FIRST_COMPLETED)
                for f in done:
                    job, _t = inflight.pop(f)
                    try:
                        fid, mtime, chunks, err = f.result()
                    except cf.BrokenExecutor:
                        # a worker process died: every file in flight fails with it, so don't blame them yet
                        lost = [job] + [j for j, _t in inflight.values()]
                        if careful:
                            self._note("A file crashed the text reader; it is skipped until it changes")
                            self.store.set_text(job[0], job[3], [], "reader crashed")
                        else:
                            self._suspects = lost
                        return                      # the pool is gone; the next round starts a new one
                    except Exception as e:
                        log(f"text worker failed: {type(e).__name__}", "warn")
                        fid, mtime, chunks, err = job[0], job[3], [], "reader failed"
                    if err == extract.OUT_OF_MEMORY:
                        self._memory_limit_hit("text readers")
                        if job[0] not in alone:
                            self._suspects.append(job)  # read again on its own, not written off
                            continue
                        err = "too big"                 # out of memory with nothing else running: as before
                    alone.discard(job[0])
                    self.store.set_text(fid, mtime, chunks, err)
                    self.status["texts"] += 1
                stuck = [(f, j) for f, (j, t) in inflight.items() if self._clock() - t > JOB_TIMEOUT]
                if stuck:
                    for _f, j in stuck:
                        self.store.set_text(j[0], j[3], [], "took too long")
                    files = "one file" if len(stuck) == 1 else f"{len(stuck)} files"
                    self._note(f"Stopped a text reader stuck on {files} for {JOB_TIMEOUT // 60} minutes; "
                               f"{'the file is' if len(stuck) == 1 else 'those files are'} skipped")
                    _kill_pool(pool)                # the other files in flight are simply read again
                    return
        finally:
            if self.stop_ev.is_set():
                _kill_pool(pool)                    # stopping: the files in flight are read again next time
            pool.shutdown(wait=True, cancel_futures=True)
            self._text_pool = None

    @staticmethod
    def make_embedder(mid, query=False):
        """A text model (models.CATALOG id) in this process: the question encoder (query=True) for live search."""
        return embed.Embedder(models.model_dir(mid), gpu=False, spec=models.get(mid), query=query)

    def _load_embedder(self):
        """Meaning search with the model the index's vectors come from (indexes before 0.8.0: all-MiniLM). A fresh
        index starts with the model chosen in Settings; a different choice is built later by _rebuild_vectors."""
        if not self.settings.get("semantic"):
            return
        try:
            wanted = models.selected(self.settings, "text")
            active = vector_model(self.store)
            if active and (models.get(active) is None or not models.ready(active)):
                if not models.ready(wanted):
                    log("meaning search unavailable: its model isn't on this PC", "warn")
                    return
                log(f"the meaning model {active} is gone; computing vectors again with {wanted}")
                self.store.drop_vectors()
                active = None
            if active is None:
                if not models.ready(wanted):
                    return
                active = wanted
                self.store.set_meta("vec_model", active)
            if self.store.meta("vec_version") != embed.VEC_VERSION:
                log("meaning vectors are made a better way now; computing them again")
                self.store.drop_vectors()
                self.store.set_meta("vec_version", embed.VEC_VERSION)
            self._use_text_model(active)
            log(f"meaning search on with {active} (the model loads when it's needed)")
        except Exception as e:
            log(f"meaning search unavailable: {type(e).__name__}", "warn")
            self.embedder = None

    def _use_text_model(self, mid):
        """Search with `mid`: its question encoder, and the vectors made with it (never another model's)."""
        spec = models.get(mid)
        self.text_model = mid
        self.embedder = embed.Lazy(lambda: self.make_embedder(mid, True), "meaning", model_id=mid)
        self._vectors_in_worker = not self.vectors_in_process
        if self.vindex is not None:
            self.vindex.reset(spec["dim"], mid)
            self.vindex.load(self.store)

    def _make_vectors(self):
        """Meaning vectors: first for names (short, fast, and the only clue for photos, music or bills),
        then for the text inside files, each piece with its file's name in front."""
        if not self.embedder:
            return
        if self._vectors_in_worker and self._clock() < self._meaning_retry_at:
            return                                  # the worker kept failing: wait (MEANING_BACKOFF)
        try:
            self._name_vectors()
            if not self._recycled:
                self._chunk_vectors()
            if not self._recycled and not self.stop_ev.is_set():
                self._rebuild_vectors()
        finally:
            self._end_meaning_pool()                # the worker process ends when there's nothing to do

    def _rebuild_vectors(self):
        """Another text model was chosen (and is downloaded): its vectors are made beside the current ones (the
        "rebuild" phase), which stay searchable with their own model until the new set is complete; then the two
        swap in one transaction and search moves to the new model."""
        wanted = models.selected(self.settings, "text")
        if not wanted or wanted == self.text_model or not models.ready(wanted):
            if self.store.meta("vec_model_next"):
                self.store.drop_next_vectors()
                self.store.set_meta("vec_model_next", "")
            return
        if self.store.meta("vec_model_next") != wanted:
            self.store.drop_next_vectors()           # another switch was half done: start over for this one
            self.store.set_meta("vec_model_next", wanted)
            log(f"building meaning vectors with {wanted}; {self.text_model} stays in use until they're ready")
        self.status["rebuild"] = {"from": self.text_model, "to": wanted}
        self._name_vectors(next=wanted)
        if not self._recycled:
            self._chunk_vectors(next=wanted)
        if self._recycled or self.stop_ev.is_set():
            return
        left = self.store.count_chunks_without_vectors(next=True) + self.store.count_names_without_vectors(
            NAME_KINDS, next=True)
        if left:
            return
        self.store.swap_vectors()
        self.store.set_meta("vec_model", wanted)
        self.store.set_meta("vec_model_next", "")
        self.status.pop("rebuild", None)
        self._use_text_model(wanted)
        self._note(f"Meaning search now uses {models.get(wanted)['name']}")

    def _meaning_pause(self):
        """Before each meaning batch. False: end this phase (stopping, or a long pause ended the worker)."""
        go = self._wait_while_paused(max_wait=RECYCLE_AFTER if self._mpool is not None else None)
        if go is RECYCLE:
            self._recycle(self._mpool, "meaning worker")
            self._end_meaning_pool()
            return False
        return bool(go)

    def _chunk_vectors(self, next=None):
        """next: the model being switched to (its vectors go to vecs_next and aren't searched yet)."""
        while not self.stop_ev.is_set():
            if not self._meaning_pause():
                return
            rows = self.store.chunks_without_vectors(128, next=bool(next))
            if not rows:
                return
            self.status["phase"] = "rebuild" if next else "meaning"
            titles = self.store.chunk_titles([r[0] for r in rows])
            vecs = self._encode([embed.chunk_text(titles.get(r[0], ""), r[1]) for r in rows], next)
            if vecs is None:
                return
            self.store.add_vectors([(r[0], embed.to_blob(v)) for r, v in zip(rows, vecs)], next=bool(next))
            if self.vindex is not None and not next:
                self.vindex.add([r[0] for r in rows], vecs)
            self.status["rebuilt" if next else "vectors"] = self.status.get("rebuilt" if next else "vectors", 0) + len(rows)
            self._breathe()

    def _name_vectors(self, next=None):
        while not self.stop_ev.is_set():
            if not self._meaning_pause():
                return
            rows = self.store.names_without_vectors(NAME_KINDS, 512, next=bool(next))
            if not rows:
                return
            self.status["phase"] = "rebuild" if next else "meaning"
            texts = {fid: ("" if any(s in d.lower() for s in SKIP_NAME_DIRS) else embed.name_text(n, d))
                     for fid, n, d in rows}
            todo = [fid for fid, t in texts.items() if t]
            vecs = self._encode([texts[f] for f in todo], next) if todo else []
            if vecs is None:
                return
            blobs = dict(zip(todo, (embed.to_blob(v) for v in vecs)))
            self.store.add_name_vectors([(fid, blobs.get(fid, b"")) for fid in texts], next=bool(next))
            if self.vindex is not None and todo and not next:
                self.vindex.add([embed.name_key(f) for f in todo], vecs)
            self.status["rebuilt" if next else "vectors"] = self.status.get("rebuilt" if next else "vectors", 0) + len(todo)
            self._breathe()

    def _encode(self, texts, mid=None):
        """Index-time vectors, float32 (n, MODEL_DIM), made in the meaning worker process (CPU-capped with the
        other workers). GPU only at Full: when the level changes, the next batch gets a matching worker.
        None when stopping or when the worker failed (the batch is done again next round)."""
        mid = mid or self.text_model
        if self.vectors_in_process and mid:
            if mid not in self._passage:
                self._passage[mid] = self.make_embedder(mid, False)
            return self._passage[mid].encode(texts)
        if not self._vectors_in_worker:
            return self.embedder.encode(texts)      # a stand-in model (tests): in this process
        level = self.governor.decision.level if self.governor is not None else FULL
        gpu = level == FULL
        if self._mpool is not None and (self._mpool_gpu != gpu or self._mpool_model != mid):
            self._end_meaning_pool()
        if self._mpool is None:
            plan_ = self.status.get("plan") or {}
            most = max(1, (os.cpu_count() or 2) // 2)
            threads = min(most, max(1, workers_for(level, plan_))) if plan_ else most
            spec = models.get(mid) if mid else None
            self._mpool = cf.ProcessPoolExecutor(max_workers=1, initializer=embed.init_meaning_worker,
                                                 initargs=(models.model_dir(mid) if mid else embed.MODEL_DIR,
                                                           threads, gpu, spec))
            self._mpool_gpu, self._mpool_model = gpu, mid
            log(f"meaning worker started ({'graphics card if there is one' if gpu else 'processor only'}, "
                f"{threads} threads)")
        texts = list(texts)
        try:
            fut = self._mpool.submit(embed.encode_job, texts)
            data = self._await(fut, MEANING_TIMEOUT)    # paused time doesn't count towards the limit
            if data is None:
                return None                     # stopping: _end_meaning_pool ends the worker now
            if data is RECYCLE:
                self._recycle(self._mpool, "meaning worker")    # the batch is done again after the pause
                self._end_meaning_pool()
                return None
        except Exception as e:
            self._meaning_fails += 1
            wait = min(MEANING_BACKOFF[1], MEANING_BACKOFF[0] * 2 ** (self._meaning_fails - 1))
            self._meaning_retry_at = self._clock() + wait
            log(f"meaning worker failed ({type(e).__name__}, {self._meaning_fails} in a row); next try in {wait} s",
                "warn")
            if self._meaning_fails == 1:            # once per run of failures, not every 30 s
                if isinstance(e, cf.TimeoutError):
                    self._note(f"Restarted the meaning worker: a batch took longer than "
                               f"{MEANING_TIMEOUT // 60} minutes")
                else:
                    self._note("Restarted the meaning worker after it stopped unexpectedly")
            _kill_pool(self._mpool)
            self._end_meaning_pool()
            return None
        self._meaning_fails = 0
        return np.frombuffer(data, np.float32).reshape(len(texts), -1)

    def _end_meaning_pool(self):
        pool, self._mpool, self._mpool_gpu, self._mpool_model = self._mpool, None, None, None
        if pool is not None:
            if self.stop_ev.is_set():
                _kill_pool(pool)                    # stopping: don't wait for the batch in flight
            pool.shutdown(wait=True, cancel_futures=True)

    # ---------- photo meaning ----------
    def _load_photo(self):
        """Photo meaning with the photo model chosen in Settings. Photo vectors carry the model id; another model
        starts them again (SigLIP and SigLIP 2 vectors are never compared)."""
        pid = models.selected(self.settings, "photo")
        if not pid or not models.ready(pid):
            return
        try:
            had = self.store.meta("pvec_model") or ("siglip-base" if self.store.one(
                "SELECT 1 FROM pvecs LIMIT 1") else "")
            if had and had != pid:
                self.store.drop_photo_vectors()
                log(f"photo model is now {pid}: the photos are looked at again")
            self.store.set_meta("pvec_model", pid)
            spec = models.get(pid)
            d = models.model_dir(pid)
            self.photo_model = pid
            self.photo_text = embed.Lazy(lambda: photo.TextEncoder(d, style=spec.get("style", "siglip")),
                                         "photo text", model_id=pid)
            self.pindex.reset(spec["dim"], pid)
            self.pindex.load(self.store)
            log(f"photo meaning on with {pid} ({self.pindex.n} photos ready)")
        except Exception as e:
            log(f"photo meaning unavailable: {type(e).__name__}", "warn")
            self.photo_text = None

    def _photo_vectors(self):
        """What's in each photo, made in one separate low-priority process (photos are decoded there)."""
        if not self.photo_text or not self.settings.get("photo_meaning"):
            return
        plan_ = self.status.get("plan") or {}
        level = self.governor.decision.level if self.governor is not None else FULL
        most = max(1, (os.cpu_count() or 2) // 2)
        threads = min(most, max(1, workers_for(level, plan_))) if plan_ else 2      # as the meaning worker
        pool = cf.ProcessPoolExecutor(max_workers=1, initializer=photo.init_worker, initargs=(threads,))
        self._photo_pool = pool
        try:
            while not self.stop_ev.is_set():
                go = self._wait_while_paused(max_wait=RECYCLE_AFTER)
                if not go:
                    return
                if go is RECYCLE:
                    self._recycle(pool, "photo reader")
                    return
                rows = self._skip_secrets(
                    self.store.photos_to_read(photo.PHOTO_EXT, photo.MIN_PHOTO_BYTES, photo.MAX_PHOTO_BYTES,
                                              limit=PHOTO_BATCH if self._photo_one_by_one else 64),
                    lambda r: self.store.set_photo_vector(r[0], r[2], b"", NAMES_ONLY))
                if not rows:
                    return
                self.status["phase"] = "photos"
                step = 1 if self._photo_one_by_one else PHOTO_BATCH
                for i in range(0, len(rows), step):
                    if self.stop_ev.is_set() or self._pause_reason():
                        break
                    batch = rows[i:i + step]
                    away = self._away()
                    pdir = models.model_dir(self.photo_model) if self.photo_model else photo.PHOTO_DIR
                    fut = pool.submit(photo.embed_photos, [(f, p, m, pdir) for f, p, m in batch], away)
                    try:
                        results = self._await(fut, JOB_TIMEOUT)     # paused time doesn't count
                    except (cf.TimeoutError, cf.BrokenExecutor) as e:
                        # one of these photos hangs or crashes the reader: read them one by one next time
                        one = len(batch) == 1
                        if one:
                            self.store.set_photo_vector(batch[0][0], batch[0][2], b"", "unreadable")
                        else:
                            self._photo_one_by_one = True
                        what = (f"was stuck for {JOB_TIMEOUT // 60} minutes" if isinstance(e, cf.TimeoutError)
                                else "crashed")
                        self._note(f"Stopped the photo reader: it {what}; "
                                   + ("the photo is skipped" if one else "those photos are tried one by one"))
                        _kill_pool(pool)
                        return
                    if results is None:
                        return                      # stopping: the finally ends the reader
                    if results is RECYCLE:
                        self._recycle(pool, "photo reader")     # these photos are read again later
                        return
                    retry = False
                    for fid, mtime, blob, err in results:
                        if err == photo.OUT_OF_MEMORY:
                            self._memory_limit_hit("photo reader")
                            if len(batch) > 1:
                                retry = True            # read again one by one next round, not written off
                                continue
                            err = "too big"
                        self.store.set_photo_vector(fid, mtime, blob, err)
                        if blob:
                            self.pindex.add([fid], np.frombuffer(blob, np.float16)[None])
                            self.status["photos"] = self.status.get("photos", 0) + 1
                    if retry:
                        self._photo_one_by_one = True
                        break                           # (skips the reset to batches below)
                    if not away:
                        self.stop_ev.wait(0.2)      # gently while you use the PC
                else:
                    self._photo_one_by_one = False  # the suspects were read one by one: back to batches
        finally:
            if self.stop_ev.is_set():
                _kill_pool(pool)                    # stopping: don't wait for the photos in flight
            pool.shutdown(wait=True, cancel_futures=True)
            self._photo_pool = None

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

    def release_idle_models(self, idle=None):
        """Light when idle: models leave memory a few minutes after the last search or indexing work."""
        for m in (self.embedder, self.photo_text):
            if isinstance(m, embed.Lazy):
                m.release_if_idle(idle)

    def meaning_device(self):
        """'GPU' or 'CPU' for the running meaning worker, None when there is none."""
        if self._mpool is None:
            return None
        return "GPU" if self._mpool_gpu else "CPU"

    def worker_names(self):
        """{pid: 'text reader' | 'meaning worker' | 'photo worker'} for the worker processes running now."""
        out = {}
        for pool, name in ((self._text_pool, "text reader"), (self._mpool, "meaning worker"),
                           (self._photo_pool, "photo worker")):
            for pid in list(getattr(pool, "_processes", None) or {}):
                out[pid] = name
        return out

    def release_models(self):
        """Every model out of memory now (the window closed, or Find is using too much)."""
        self.release_idle_models(0)

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
        if self.turbo is not None and self.turbo.follows(root):
            log(f"too many changes at once under {root}; the turbo change journal has them all")
            return
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
        w = Walker(self.roots(), exclude=self.settings.get("exclude"), gen=gen, rules=self.rules())
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
                   on_batch=self.store.upsert_files, stop=self.stop_ev, rules=self.rules()).run()
