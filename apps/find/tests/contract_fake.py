"""A deterministic engine for the contract transcripts: the real handlers and the real Events, over a fake Api
whose answers never depend on the PC, the clock or the index. Transcripts are recorded from it and replayed
against it (tests/test_rpc_contract.py), so the Dart side can parse exactly what the Python side produces."""
from nobadfind.activity import Activity
from nobadfind.const import DEFAULTS
from nobadfind.rpc import handlers
from nobadfind.rpc.events import Events
from nobadfind.settings import coerce

RESULT = {"id": 7, "path": "C:\\Users\\me\\Documents\\tax 2025.pdf", "name": "tax 2025.pdf",
          "dir": "C:\\Users\\me\\Documents", "kind": "pdf", "size": 48213, "mtime": 1763400000.0,
          "ago": "2 days ago", "why": ["name matches"], "snippet": "", "weak": False}


class FakeGov:
    def __init__(self):
        self.level, self.reason = "gentle", "Gentle: you're using the PC"


class FakeApi:
    """Every method the handlers reach, with fixed answers; `calls` records what was asked."""

    def __init__(self):
        self.calls = []
        self.on_quit = None
        self.here = ""
        self.gov = FakeGov()
        self.paused = ""
        self.settings = dict(DEFAULTS)
        self.models = {"meaning": {"state": "missing", "got": 0, "size": 0, "error": ""},
                       "photo": {"state": "missing", "got": 0, "size": 0, "error": ""}}

    def _note(self, *call):
        self.calls.append(call)

    # search
    def search(self, text, filters=None):
        self._note("search", text, filters)
        if not text.strip() and not filters:
            return {"results": [], "understood": [], "terms": [], "notes": [], "ms": 0}
        return {"results": [dict(RESULT)], "understood": ["pdf"], "terms": ["tax"], "notes": [], "more": False,
                "ms": 4}

    def open(self, file_id):
        self._note("open", file_id)
        return {"ok": True} if file_id == 7 else {"ok": False, "error": "That file isn't there any more."}

    def reveal(self, file_id):
        self._note("reveal", file_id)
        return {"ok": True} if file_id == 7 else {"ok": False, "error": "That file isn't there any more."}

    def thumbnail(self, file_id):
        return {"url": "data:image/png;base64,iVBORw0KGgo=" if file_id == 7 else ""}

    def here_folder(self):
        return {"path": self.here}

    def path_of(self, file_id):
        return {"path": RESULT["path"] if file_id == 7 else ""}

    def forget(self, file_id):
        self._note("forget", file_id)
        return {"ok": file_id == 7}

    # status
    def status_brief(self):
        return {"level": self.gov.level, "reason": self.gov.reason, "phase": "text", "files": 1200,
                "paused": self.paused}

    def status(self):
        return dict(STATUS_FULL, level=self.gov.level, reason=self.gov.reason, paused=self.paused)

    def downloads(self):
        return {k: dict(v) for k, v in self.models.items()}

    def pause_for(self, seconds):
        self._note("pause_for", seconds)
        if not isinstance(seconds, int) or seconds <= 0:
            return {"ok": False}
        self.gov.level, self.gov.reason = "paused", "Paused: you paused NOBAD Find for 60 min"
        return {"ok": True}

    def resume(self):
        self._note("resume")
        self.gov.level, self.gov.reason = "gentle", "Gentle: you're using the PC"
        return {"ok": True}

    def learned_apps(self):
        return [{"exe": "game.exe", "seen": 3, "lag_events": 1, "worst_cpu": 92.0, "worst_gpu": None,
                 "start_level": "light", "last_seen": 1763400000.0, "reason": "It slowed down once while Find worked"}]

    def reset_learned(self, exe=None):
        self._note("reset_learned", exe)
        return {"ok": True}

    def hardware(self):
        return {"ram_gb": 15.7, "cores": 8, "threads": 16, "avx2": True, "avx512_vnni": False,
                "gpu": "Intel(R) Iris(R) Xe Graphics", "vram_gb": 0.1, "directml": False, "disk_free_gb": 120.5,
                "ssd": True}

    # settings
    def get_settings(self):
        return dict(self.settings)

    def set_settings(self, changes):
        """Like Settings.update: every value through the real settings.coerce."""
        new = {k: coerce(k, v) for k, v in changes.items() if k in DEFAULTS and k != "wsearch_prev"}
        changed = [k for k, v in new.items() if self.settings[k] != v]
        self.settings.update(new)
        return {"changed": changed}

    def pick_folder(self):
        return {"path": "C:\\Users\\me\\Projects", "busy": False}

    def rescan(self):
        self._note("rescan")
        return {"ok": True}

    def wipe(self, confirm):
        self._note("wipe", confirm)
        return {"ok": confirm == "DELETE"}

    def download_model(self):
        if not self.settings["allow_model_download"]:
            return {"ok": False, "error": "Allow the download in Settings first."}
        self.models["meaning"].update(state="downloading", got=0, size=0)
        return {"ok": True}

    def download_photo_model(self):
        if not self.settings["allow_photo_model_download"]:
            return {"ok": False, "error": "Allow the photo model download in Settings first."}
        self.models["photo"].update(state="downloading", got=0, size=0)
        return {"ok": True}

    # Windows Search
    def wsearch_state(self):
        return {"start": "delayed-auto", "running": True, "saved": self.settings["wsearch_prev"]}

    def wsearch_set(self, off):
        self._note("wsearch_set", off)
        return {"ok": False, "state": {"start": "delayed-auto", "running": True},
                "error": "Windows didn't make the change (the permission prompt may have been closed)."}

    def use_instead_of_windows_search(self, on):
        return self.wsearch_set(bool(on))

    # window
    def ui_shown(self):
        self._note("ui_shown")
        return {"ok": True}

    def hide(self):
        self._note("hide")
        return {"ok": True}

    def quit(self):
        self._note("quit")
        if self.on_quit is not None:
            self.on_quit()                      # engine.py: the quitting event, then the engine stops
        return {"ok": True}


STATUS_FULL = {
    "phase": "text", "files": 1200, "texts": 310, "vectors": 0, "paused": "", "rate": 0, "errors": 0,
    "plan": {"cpu": 16, "ssd": True, "walk_threads": 32, "text_workers": 8, "text_workers_idle": 15},
    "last_scan": 1763400000.0,
    "with_text": 310, "chunks": 900, "name_vectors": 0, "photo_vectors": 0, "encrypted": True, "db_bytes": 5242880,
    "version": "0.7.0",
    "model": {"state": "missing", "got": 0, "size": 0, "error": ""},
    "photo_model": {"state": "missing", "got": 0, "size": 0, "error": ""},
    "memory_mb": 180, "models_loaded": [], "admin": False, "roots": ["C:\\Users\\me"], "ocr": True,
    "drives": [{"root": "C:\\", "type": "fixed", "label": "Windows", "present": True}],
    "level": "gentle", "reason": "Gentle: you're using the PC",
    "history": [{"t": 1763400000.0, "cpu": 12.5, "gpu": 3.0, "find_cpu": 4.0, "find_mb": 180, "level": "gentle"}],
    "resources": {"cpu": 4.0, "memory_mb": 180, "read_mb_s": 1.5, "gpu": 3.0,
                  "processes": [{"name": "Main", "pid": 100, "cpu": 2.0, "memory_mb": 120},
                                {"name": "Text reader", "pid": 101, "cpu": 2.0, "memory_mb": 60}]},
    "phases": [{"id": "names", "label": "Finding file names", "state": "done", "done": 1200, "total": None,
                "rate": 0.0, "eta_s": None},
               {"id": "text", "label": "Reading documents", "state": "running", "done": 310, "total": 800,
                "rate": 5.0, "eta_s": 98},
               {"id": "ocr", "label": "Reading words in pictures", "state": "waiting", "done": 0, "total": 40,
                "rate": 0.0, "eta_s": None},
               {"id": "meaning", "label": "Learning what files mean", "state": "off", "done": 0, "total": 0,
                "rate": 0.0, "eta_s": None},
               {"id": "photos", "label": "Looking at photos", "state": "off", "done": 0, "total": 0,
                "rate": 0.0, "eta_s": None},
               {"id": "watching", "label": "Watching for changes", "state": "waiting", "done": 0, "total": None,
                "rate": 0.0, "eta_s": None}],
    "models": [{"id": "meaning", "name": "Meaning search (all-MiniLM-L6-v2)", "license": "Apache-2.0", "size_mb": 87,
                "on_disk": False, "loaded": False, "memory_mb": None, "device": "CPU", "items": 0, "download": None},
               {"id": "photo", "name": "Photo search (SigLIP base)", "license": "Apache-2.0", "size_mb": 211,
                "on_disk": False, "loaded": False, "memory_mb": None, "device": "CPU", "items": 0, "download": None},
               {"id": "ocr", "name": "Windows OCR", "license": "Windows", "size_mb": 0, "on_disk": True,
                "loaded": False, "memory_mb": None, "device": "Windows", "items": 0, "download": None}],
    "activity": [{"t": 1763400000.0, "kind": "level", "text": "Gentle: you're using the PC"}],
}


class Conn:
    """A client connection that keeps what the engine sent it."""

    def __init__(self, pid=4242):
        self.events, self.shown, self.sent, self.pid, self.alive = set(), set(), [], pid, True

    def send(self, obj):
        self.sent.append(obj)
        return True


class Engine:
    """FakeApi + the real Events and handlers for one connection; `trigger` plays the engine-side lines."""

    def __init__(self):
        self.api = FakeApi()
        self.conn = Conn()
        self.activity = Activity(clock=lambda: 1763400000.0)
        self.events = Events(lambda: [self.conn], lambda c: None, self.api, every=2.0)
        self.activity.listen(self.events.activity)
        self.api.on_quit = self.events.quitting
        self.methods = handlers.methods(self.api, self.events,
                                        lambda: {"app": "NOBAD Find", "version": "0.0.0-contract", "pid": 4242})

    def trigger(self, t):
        do = t["do"]
        if do == "tick":
            self.events.step(t["at"])
        elif do == "level":
            self.api.gov.level, self.api.gov.reason = t["level"], t["reason"]
        elif do == "activity":
            self.activity.add(t["kind"], t["text"])
        elif do == "download":
            self.api.models[t["id"]].update({k: t[k] for k in ("state", "got", "size", "error") if k in t})
        elif do == "hotkey":
            self.events.show(t["what"])
        elif do == "here":
            self.api.here = t["path"]
            self.events.here(t["path"])
        elif do == "notice":
            self.events.notice(t["text"])
        elif do == "quitting":
            self.events.quitting()
        else:
            raise ValueError(f"unknown engine trigger {do!r}")
