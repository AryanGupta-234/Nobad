"""The methods the UI can call (pywebview js_api). Every argument from the page is checked here.

The page never hands the app a path to open: it sends a result id, and the path comes from the index.
"""
import ctypes
import os
import subprocess
import sys
import threading
import time
from collections import deque

from . import embed, jobs, ocr, photo, thumbs, wsearch, winapi
from . import hardware as hw
from .const import APP_VER, MODEL_FILES
from .indexer import NAME_KINDS
from .kinds import READABLE_EXT
from .log import log
from .search import SORTS, search

MAX_QUERY = 500
TOTALS_TTL = 10                  # seconds: the phase counts are COUNT queries, too heavy for every 2 s poll
RATE_WINDOW = 15                 # status polls a progress rate is measured over (about 30 s)
MAX_PAUSE_S = 24 * 3600
QUIT_TIMEOUT = 15                # seconds a quit may take before the process ends anyway
PHASES = (("names", "Finding file names"), ("text", "Reading documents"), ("ocr", "Reading words in pictures"),
          ("meaning", "Learning what files mean"), ("photos", "Looking at photos"), ("watching", "Watching for changes"))


class Api:
    def __init__(self, store, settings, indexer, vindex, window_ref):
        self._store = store
        self._settings = settings
        self._indexer = indexer
        self._vindex = vindex
        self._win = window_ref            # callable returning the pywebview window (or None)
        self._watchdog = None             # set by app.py
        self.visible = True               # the main window is shown (the watchdog expects heartbeats)
        self.here = ""                    # the Explorer folder the hotkey was pressed in (see app.bring_up)
        self._model = {"state": "ready" if embed.model_ready() else "missing", "got": 0, "size": 0, "error": ""}
        self._photo_model = {"state": "ready" if photo.model_ready() else "missing", "got": 0, "size": 0, "error": ""}
        self._governor = None             # set by app.py (the status page reads the governor, the activity log,
        self._activity = None             # and what was learned about apps); None in tests
        self._apps = None
        self._slock = threading.Lock()
        self._totals = (0.0, None, {})    # (computed at, settings key, counts)
        self._refresher = None
        self._clock = time.monotonic      # tests replace it
        self._prev = None                 # (time, cpu_seconds, read_bytes) of the last status() call
        self._pcpu = {}                   # pid -> (time, cpu_seconds)
        self._progress = {k: deque(maxlen=RATE_WINDOW) for k, _l in PHASES}
        self._dl = {}                     # model id -> (time, got bytes) for the download speed
        self._on_hide = None              # app.py: what hiding the window means for indexing (lifecycle.after_hide)
        self._timer, self._exit = threading.Timer, os._exit     # tests replace them

    # ---------- search ----------
    def search(self, text, filters=None):
        empty = {"results": [], "understood": [], "terms": [], "notes": [], "ms": 0}
        if not isinstance(text, str):
            return empty
        text = text.strip()[:MAX_QUERY]
        filters = filters if isinstance(filters, dict) else {}
        listing = any(filters.get(k) for k in ("kind", "modified", "size", "folder")) or filters.get("sort") in SORTS - {""}
        if not text and not listing:
            return empty
        try:
            return search(self._store, text, self._indexer.embedder, self._vindex, drives=self._indexer.drive_list,
                          here=self.here, filters=filters, roots=self._indexer.roots(self._indexer.drive_list),
                          photo_text=self._indexer.photo_text, pindex=self._indexer.pindex)
        except Exception as e:
            log(f"search failed: {type(e).__name__}", "warn")
            return {"results": [], "understood": [], "terms": [], "ms": 0, "error": "Search failed. Try other words."}

    def _path(self, file_id):
        if not isinstance(file_id, int) or isinstance(file_id, bool):
            return None
        p = self._store.one("SELECT path FROM files WHERE id=?", (file_id,))
        return p if p and os.path.exists(p) else None

    def open(self, file_id):
        p = self._path(file_id)
        if not p:
            return {"ok": False, "error": "That file isn't there any more."}
        try:
            winapi.open_outside_job(p)    # the default program, outside Find's job: it survives Quit
            return {"ok": True}
        except OSError as e:
            log(f"could not open the file outside NOBAD Find's process group (error {e.winerror or e.errno}); "
                "opened it directly, so it closes if NOBAD Find quits", "warn")
        try:
            os.startfile(p)               # noqa: the default program for this file, as the normal user
            return {"ok": True}
        except OSError as e:
            return {"ok": False, "error": e.strerror or "Windows couldn't open it."}

    def reveal(self, file_id):
        p = self._path(file_id)
        if not p:
            return {"ok": False, "error": "That file isn't there any more."}
        return {"ok": reveal_in_explorer(p)}

    def thumbnail(self, file_id):
        """A small preview of one result (photo, video, PDF) from Windows' thumbnail cache, or ""."""
        if not isinstance(file_id, int) or isinstance(file_id, bool):
            return {"url": ""}
        row = self._store.q("SELECT path, kind, mtime FROM files WHERE id=?", (file_id,))
        if not row or row[0][1] not in thumbs.KINDS:
            return {"url": ""}
        return {"url": thumbs.data_url(row[0][0], row[0][2])}

    def here_folder(self):
        """For the filter bar: the folder "here" means right now ('' if NOBAD Find wasn't opened from one)."""
        return {"path": self.here}

    def path_of(self, file_id):
        p = self._path(file_id)
        return {"path": p or ""}

    def forget(self, file_id):
        """Remove a file or folder from the index and keep it out from now on."""
        if not isinstance(file_id, int):
            return {"ok": False}
        p = self._store.one("SELECT path FROM files WHERE id=?", (file_id,))
        if not p:
            return {"ok": False}
        self._store.forget_path(p)
        self._settings.update({"exclude": self._settings.get("exclude") + [p]})
        return {"ok": True}

    # ---------- status and settings ----------
    def status(self):
        st = dict(self._indexer.status)
        st.update(self._store.stats())
        st["version"] = APP_VER
        st["model"] = dict(self._model)
        st["photo_model"] = dict(self._photo_model)
        st["memory_mb"] = winapi.memory_mb()
        st["models_loaded"] = self._indexer.models_loaded()
        st["admin"] = winapi.is_admin()
        st["roots"] = self._indexer.roots()
        st["ocr"] = ocr.available() or ocr.why_missing()
        st["drives"] = self._indexer.drive_list
        with self._slock:
            self._transparency(st)
        return st

    # ---------- transparency: what NOBAD Find is doing, what it uses, and why ----------
    def _transparency(self, st):
        now = self._clock()
        gov = self._governor
        if gov is not None:
            st["level"], st["reason"] = gov.decision.level, gov.decision.reason
            st["history"] = gov.history
        else:
            st["level"], st["reason"], st["history"] = st.get("level", ""), st.get("reason", ""), []
        history = st["history"]
        st["resources"] = self._resources(now, history[-1].get("gpu") if history else None)
        st["phases"] = self._phases(now, st)
        st["models"] = self._models(now, st, st["resources"]["processes"])
        st["activity"] = self._activity.recent(50) if self._activity is not None else []

    def _resources(self, now, gpu):
        names = {os.getpid(): "Main"}
        labels = {"text reader": "Text reader", "meaning worker": "Meaning worker", "photo worker": "Photo worker"}
        try:
            names.update({pid: labels.get(n, n) for pid, n in self._indexer.worker_names().items()})
        except Exception:
            pass
        pids = jobs.OUTER.pids() if jobs.OUTER is not None else []
        if os.getpid() not in pids:
            pids = [os.getpid()] + pids
        cores = os.cpu_count() or 1
        procs, seen = [], {}
        for pid in pids:
            info = jobs.process_info(pid)
            last = self._pcpu.get(pid)
            cpu = 0.0
            if last and now > last[0]:
                cpu = max(0.0, min(100.0, (info["cpu_seconds"] - last[1]) / (now - last[0]) / cores * 100))
            seen[pid] = (now, info["cpu_seconds"])
            procs.append({"name": names.get(pid, "Window (WebView2)"), "pid": int(pid), "cpu": round(cpu, 1),
                          "memory_mb": int(info["memory_mb"])})
        self._pcpu = seen
        use = jobs.OUTER.usage() if jobs.OUTER is not None else {"cpu_seconds": 0.0, "read_bytes": 0}
        prev, self._prev = self._prev, (now, use["cpu_seconds"], use["read_bytes"])
        cpu, read = 0.0, 0.0
        if prev and now > prev[0]:
            cpu = max(0.0, min(100.0, (use["cpu_seconds"] - prev[1]) / (now - prev[0]) / cores * 100))
            read = max(0.0, (use["read_bytes"] - prev[2]) / (now - prev[0]) / 1048576)
        return {"cpu": round(cpu, 1), "memory_mb": sum(p["memory_mb"] for p in procs), "read_mb_s": round(read, 2),
                "gpu": gpu, "processes": procs}

    def _counts(self, now):
        """(total, still to do) for each phase that counts files (cached TOTALS_TTL seconds)."""
        key = (self._settings.get("content_max_mb"), self._settings.get("src_mail"))
        at, k, counts = self._totals
        if not counts:
            return self._refresh(now, key)                  # the very first call computes inline
        if (k != key or now - at >= TOTALS_TTL) and not (self._refresher and self._refresher.is_alive()):
            self._refresher = threading.Thread(target=self._refresh, args=(now, key), daemon=True, name="counts")
            self._refresher.start()                         # the COUNT queries never hold up a status poll
        return counts

    def _refresh(self, now, key):
        s, st = self._settings, self._store
        counts = self._totals[2]
        text_ext = set(READABLE_EXT)
        if not s.get("src_mail"):
            text_ext -= {".eml", ".mbox"}
        mx = s.get("content_max_mb") * 1024 * 1024
        try:
            counts = {"text": (st.count_readable(text_ext, mx), st.count_needs_text(text_ext, mx)),
                      "ocr": (st.count_readable(ocr.OCR_EXT, mx, ocr.MIN_IMAGE_BYTES),
                              st.count_needs_text(ocr.OCR_EXT, mx, ocr.MIN_IMAGE_BYTES)),
                      "meaning": ((st.one("SELECT count(*) FROM chunks") or 0) + st.count_names(NAME_KINDS),
                                  st.count_chunks_without_vectors() + st.count_names_without_vectors(NAME_KINDS)),
                      "photos": (st.count_photos(photo.PHOTO_EXT, photo.MIN_PHOTO_BYTES, photo.MAX_PHOTO_BYTES),
                                 st.count_photos_to_read(photo.PHOTO_EXT, photo.MIN_PHOTO_BYTES, photo.MAX_PHOTO_BYTES))}
        except Exception as e:
            log(f"status counts failed: {type(e).__name__}", "warn")
            counts = counts or {p: (0, 0) for p in ("text", "ocr", "meaning", "photos")}
        self._totals = (now, key, counts)
        return counts

    def _phases(self, now, st):
        s = self._settings
        counts = self._counts(now)
        cur = {"images": "ocr"}.get(st.get("phase"), st.get("phase"))
        content = bool(s.get("content"))
        on = {"names": True, "text": content, "ocr": content and bool(s.get("ocr")) and bool(ocr.available()),
              "meaning": bool(s.get("semantic")) and embed.model_ready(),
              "photos": bool(s.get("photo_meaning")) and photo.model_ready(), "watching": True}
        counter = {"text": "texts", "ocr": "texts", "meaning": "vectors", "photos": "photos"}
        out = []
        for pid, label in PHASES:
            total = remaining = None
            if pid in counts:
                total, remaining = counts[pid]
            done = max(0, total - remaining) if total is not None else (st.get("files", 0) if pid == "names" else 0)
            hist = self._progress[pid]
            if not on[pid]:
                state = "off"
            elif cur == pid:
                state = "running"
            elif pid == "names":
                state = "waiting" if cur in ("starting", "error", None) else "done"
            elif pid == "watching":
                state = "waiting"
            else:
                state = "done" if not remaining else "waiting"
            if state == "running" and pid in counter:
                hist.append((now, st.get(counter[pid], 0)))
            else:
                hist.clear()                  # a rate only uses samples from while the phase ran
            rate = 0.0
            if state == "running" and len(hist) > 1 and hist[-1][0] > hist[0][0]:
                rate = max(0.0, (hist[-1][1] - hist[0][1]) / (hist[-1][0] - hist[0][0]))
            eta = int(remaining / rate) if rate > 0 and remaining else None
            out.append({"id": pid, "label": label, "state": state, "done": int(done),
                        "total": int(total) if total is not None else None, "rate": round(rate, 2), "eta_s": eta})
        return out

    def _download(self, mid, m, now):
        if m["state"] != "downloading":
            self._dl.pop(mid, None)
            return None
        prev, self._dl[mid] = self._dl.get(mid), (now, m["got"])
        speed = max(0.0, (m["got"] - prev[1]) / (now - prev[0]) / 1048576) if prev and now > prev[0] else 0.0
        return {"got_mb": round(m["got"] / 1048576, 1), "size_mb": round(m["size"] / 1048576, 1),
                "mb_s": round(speed, 2)}

    def _models(self, now, st, procs):
        """Cards describe the model doing the work (its worker process), else the in-process query encoder."""
        ix = self._indexer
        emb, pho = getattr(ix, "embedder", None), getattr(ix, "photo_text", None)
        worker = {p["name"]: p for p in procs}.get
        mw, pw = worker("Meaning worker"), worker("Photo worker")
        try:
            mdev = ix.meaning_device()
        except Exception:
            mdev = None
        mdev = mdev or ("GPU" if getattr(emb, "device", "CPU") == "GPU" else "CPU")
        pdev = "GPU" if getattr(pho, "device", "CPU") == "GPU" else "CPU"
        enc = [(emb, mw), (pho, pw)]
        mem = [w["memory_mb"] if w else None for _e, w in enc]
        meaning_mb = sum(v[1] for v in MODEL_FILES.values()) / 1048576
        photo_mb = sum(v[1] for v in photo.PHOTO_FILES.values()) / 1048576
        ocr_total, ocr_left = self._counts(now).get("ocr", (0, 0))
        return [
            {"id": "meaning", "name": "Meaning search (all-MiniLM-L6-v2)", "license": "Apache-2.0",
             "size_mb": round(meaning_mb), "on_disk": bool(embed.model_ready()),
             "loaded": bool(mw) or bool(getattr(emb, "loaded", False)), "memory_mb": mem[0],
             "device": mdev,
             "items": int(st.get("vectors", 0)) + int(st.get("name_vectors", 0)),
             "download": self._download("meaning", self._model, now)},
            {"id": "photo", "name": "Photo search (SigLIP base)", "license": "Apache-2.0",
             "size_mb": round(photo_mb), "on_disk": bool(photo.model_ready()),
             "loaded": bool(pw) or bool(getattr(pho, "loaded", False)), "memory_mb": mem[1],
             "device": pdev,
             "items": int(st.get("photo_vectors", 0)),
             "download": self._download("photo", self._photo_model, now)},
            {"id": "ocr", "name": "Windows OCR", "license": "Windows", "size_mb": 0, "on_disk": bool(ocr.available()),
             "loaded": False, "memory_mb": None, "device": "Windows", "items": max(0, ocr_total - ocr_left),
             "download": None},
        ]

    # ---------- governor controls ----------
    def pause_for(self, seconds):
        if self._governor is None or not isinstance(seconds, int) or isinstance(seconds, bool) or seconds <= 0:
            return {"ok": False}
        self._governor.pause_for(min(seconds, MAX_PAUSE_S))
        return {"ok": True}

    def resume(self):
        if self._governor is None:
            return {"ok": False}
        self._governor.resume()
        return {"ok": True}

    def learned_apps(self):
        return self._apps.list() if self._apps is not None else []

    def reset_learned(self, exe=None):
        if self._apps is None or not (exe is None or isinstance(exe, str)):
            return {"ok": False}
        self._apps.reset(exe)
        return {"ok": True}

    def hardware(self):
        return hw.scan()

    def get_settings(self):
        return self._settings.all()

    def set_settings(self, changes):
        if not isinstance(changes, dict):
            return {"changed": []}
        changes = {k: v for k, v in changes.items() if k not in ("wsearch_prev",)}
        changed = self._settings.update(changes)
        if "autostart" in changed:
            set_autostart(self._settings.get("autostart"))
        if set(changed) & {"roots", "exclude"}:
            self._indexer.rescan()
        for key, kind in (("index_removable", "removable"), ("index_network", "network")):
            if key in changed:
                if not self._settings.get(key):          # turned off: those drives leave the index
                    self._store.remove_paths([d["root"].rstrip("\\") for d in self._indexer.drive_list
                                              if d.get("type") == kind])
                self._indexer.wake.set()
        if "photo_meaning" in changed:
            if self._settings.get("photo_meaning"):
                threading.Thread(target=self._indexer._load_photo, daemon=True).start()
            else:
                self._indexer.photo_text = None
            self._indexer.wake.set()
        if "ocr" in changed:
            if not self._settings.get("ocr"):
                self._store.set_meta("ocr_pass", "0")    # turned on again later: re-read the scans then
            self._indexer.wake.set()
        if "semantic" in changed and self._settings.get("semantic"):
            threading.Thread(target=self._indexer._load_embedder, daemon=True).start()
            self._indexer.wake.set()
        return {"changed": changed}

    def pick_folder(self):
        w = self._win()
        if not w:
            return {"path": ""}
        import webview
        r = w.create_file_dialog(webview.FOLDER_DIALOG)
        return {"path": r[0] if r else ""}

    def rescan(self):
        self._indexer.rescan()
        return {"ok": True}

    def wipe(self, confirm):
        if confirm != "DELETE":
            return {"ok": False}
        self._store.wipe()
        self._indexer.rescan()
        return {"ok": True}

    # ---------- meaning-search model ----------
    def download_model(self):
        if not self._settings.get("allow_model_download"):
            return {"ok": False, "error": "Allow the download in Settings first."}
        if self._model["state"] == "downloading":
            return {"ok": True}
        self._model.update(state="downloading", got=0, error="")

        def run():
            try:
                embed.download_model(progress=lambda n, got, size: self._model.update(got=got, size=size))
                self._model["state"] = "ready"
                self._settings.update({"semantic": True})
                self._indexer._load_embedder()
                self._indexer.wake.set()
            except Exception as e:
                self._model.update(state="missing", error=str(e)[:200])
                log(f"model download failed: {type(e).__name__}", "warn")
        threading.Thread(target=run, daemon=True, name="model").start()
        return {"ok": True}

    def download_photo_model(self):
        """The photo model (about 211 MB): same pinned, hash-checked download as the text model."""
        if not self._settings.get("allow_photo_model_download"):
            return {"ok": False, "error": "Allow the photo model download in Settings first."}
        if self._photo_model["state"] == "downloading":
            return {"ok": True}
        self._photo_model.update(state="downloading", got=0, error="")
        done = {}

        def progress(name, got, size):
            done[name] = (got, size)
            self._photo_model.update(got=sum(g for g, _s in done.values()),
                                     size=sum(f[1] for f in photo.PHOTO_FILES.values()))

        def run():
            try:
                photo.download_model(progress=progress)
                self._photo_model["state"] = "ready"
                self._settings.update({"photo_meaning": True})
                self._indexer._load_photo()
                self._indexer.wake.set()
            except Exception as e:
                self._photo_model.update(state="missing", error=str(e)[:200])
                log(f"photo model download failed: {type(e).__name__}", "warn")
        threading.Thread(target=run, daemon=True, name="photo-model").start()
        return {"ok": True}

    # ---------- Windows Search ----------
    def wsearch_state(self):
        s = wsearch.state()
        s["saved"] = self._settings.get("wsearch_prev")
        return s

    def wsearch_set(self, off):
        cur = wsearch.state()
        if cur.get("missing"):
            return {"ok": False, "error": "Windows Search isn't installed on this PC."}
        if off:
            if cur["start"] != "disabled":
                self._settings.update({"wsearch_prev": cur["start"]})
            ok = wsearch.request("disabled")
        else:
            ok = wsearch.request(self._settings.get("wsearch_prev") or "delayed-auto")
            if ok:
                self._settings.update({"wsearch_prev": ""})
        return {"ok": ok, "state": wsearch.state(),
                "error": "" if ok else "Windows didn't make the change (the permission prompt may have been closed)."}

    def use_instead_of_windows_search(self, on):
        """One click: Windows Search indexing off (Windows asks permission) and NOBAD Find starts with Windows.
        Off again: Windows Search back exactly as it was. NOBAD Find keeps starting with Windows unless changed."""
        r = self.wsearch_set(bool(on))
        if r.get("ok") and on and not self._settings.get("autostart"):
            self._settings.update({"autostart": True})
            try:
                set_autostart(True)
            except OSError:
                pass
        return r

    # ---------- window ----------
    def heartbeat(self):
        if self._watchdog is not None:
            self._watchdog.beat()
        return {"ok": True}

    def page_visible(self, on):
        if self._watchdog is not None:
            self._watchdog.page_visible(bool(on))
        return {"ok": True}

    def hide(self):
        self.visible = False
        w = self._win()
        if w:
            w.hide()
        if self._on_hide is not None:
            self._on_hide()
        return {"ok": True}

    def quit(self):
        self._quitting = True                  # app.py: closing now really quits instead of hiding
        self._indexer.stop()
        # if closing the windows (WebView2, WinForms) or the exit hangs, end the process anyway; the job then
        # ends every worker and WebView2 with it
        t = self._timer(QUIT_TIMEOUT, self._hard_exit)
        t.daemon = True
        t.start()
        w = self._win()
        if w:
            w.destroy()
        return {"ok": True}

    def _hard_exit(self):
        log("quit took too long; exiting now", "warn")
        self._indexer.stop()
        self._indexer.join(5)                  # a database write in progress is committed first
        self._exit(0)


def reveal_in_explorer(path):
    """Open the folder with the file selected (Shell API, no command line is built)."""
    if not winapi.WIN:
        return False
    ole32 = ctypes.WinDLL("ole32")
    shell32 = ctypes.WinDLL("shell32")
    shell32.ILCreateFromPathW.restype = ctypes.c_void_p
    shell32.ILCreateFromPathW.argtypes = [ctypes.c_wchar_p]
    shell32.SHOpenFolderAndSelectItems.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
    shell32.ILFree.argtypes = [ctypes.c_void_p]
    ole32.CoInitialize(None)
    pidl = shell32.ILCreateFromPathW(path)
    if not pidl:
        return False
    try:
        return shell32.SHOpenFolderAndSelectItems(pidl, 0, None, 0) == 0
    finally:
        shell32.ILFree(pidl)


def set_autostart(on):
    """Start with Windows (hidden, hotkey ready) through the user's own Run key."""
    import winreg
    key = r"Software\Microsoft\Windows\CurrentVersion\Run"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, "NOBAD Find", 0, winreg.REG_SZ,
                              subprocess.list2cmdline(winapi.self_command("--background")))
        else:
            try:
                winreg.DeleteValue(k, "NOBAD Find")
            except FileNotFoundError:
                pass


__all__ = ["Api", "reveal_in_explorer", "set_autostart", "sys"]
