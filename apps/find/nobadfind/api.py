"""The methods the UI can call (pywebview js_api). Every argument from the page is checked here.

The page never hands the app a path to open: it sends a result id, and the path comes from the index.
"""
import ctypes
import os
import subprocess
import sys
import threading

from . import embed, ocr, wsearch, winapi
from .log import log
from .search import search

MAX_QUERY = 500


class Api:
    def __init__(self, store, settings, indexer, vindex, window_ref):
        self._store = store
        self._settings = settings
        self._indexer = indexer
        self._vindex = vindex
        self._win = window_ref            # callable returning the pywebview window (or None)
        self.here = ""                    # the Explorer folder the hotkey was pressed in (see app.bring_up)
        self._model = {"state": "ready" if embed.model_ready() else "missing", "got": 0, "size": 0, "error": ""}

    # ---------- search ----------
    def search(self, text, filters=None):
        empty = {"results": [], "understood": [], "terms": [], "notes": [], "ms": 0}
        if not isinstance(text, str):
            return empty
        text = text.strip()[:MAX_QUERY]
        filters = filters if isinstance(filters, dict) else {}
        if not text and not any(filters.get(k) for k in ("kind", "modified", "size", "folder")):
            return empty
        try:
            return search(self._store, text, self._indexer.embedder, self._vindex, drives=self._indexer.drive_list,
                          here=self.here, filters=filters, roots=self._indexer.roots(self._indexer.drive_list))
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
            os.startfile(p)               # noqa: the default program for this file, as the normal user
            return {"ok": True}
        except OSError as e:
            return {"ok": False, "error": e.strerror or "Windows couldn't open it."}

    def reveal(self, file_id):
        p = self._path(file_id)
        if not p:
            return {"ok": False, "error": "That file isn't there any more."}
        return {"ok": reveal_in_explorer(p)}

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
        st["model"] = dict(self._model)
        st["admin"] = winapi.is_admin()
        st["roots"] = self._indexer.roots()
        st["ocr"] = ocr.available() or ocr.why_missing()
        st["drives"] = self._indexer.drive_list
        return st

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

    # ---------- window ----------
    def hide(self):
        w = self._win()
        if w:
            w.hide()
        return {"ok": True}

    def quit(self):
        self._quitting = True                  # app.py: closing now really quits instead of hiding
        self._indexer.stop()
        w = self._win()
        if w:
            w.destroy()
        return {"ok": True}


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
