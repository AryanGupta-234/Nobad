"""Auto-update: HTTPS manifest -> download -> SHA-256 check -> Authenticode status -> silent installer.
Inert until `update_url` is set. Manifest: {"version": "...", "url": "https://.../Setup.exe", "sha256": "<64 hex>", "notes": "..."}"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.request

import sys

from . import reach
from .const import APP_VER, FROZEN, UPDATE_DIR, UPDATE_SIGNER_SUBJECTS, UPDATE_SIGNER_THUMBPRINTS
from .ctx import ctx
from .logbus import broadcast, log
from .syscmd import authenticode, private_workdir

MAX_INSTALLER = 300 * 1024 * 1024   # the installer is ~25 MB; anything near this is not a NOBAD release


def parse_version(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v)))


def is_newer(remote, local=APP_VER):
    r, l = parse_version(remote), parse_version(local)
    return bool(r) and r > l


def validate_manifest(m):
    if not isinstance(m, dict):
        raise ValueError("manifest is not an object")
    v, url, sha = m.get("version"), m.get("url"), str(m.get("sha256", "")).lower()
    if not isinstance(v, str) or not parse_version(v):
        raise ValueError("manifest has no usable version")
    if not isinstance(url, str) or not url.lower().startswith("https://"):
        raise ValueError("manifest url must be https")
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise ValueError("manifest needs a sha256")
    return {"version": v, "url": url, "sha256": sha, "notes": str(m.get("notes", ""))[:2000]}


def fetch_manifest(url):
    req = urllib.request.Request(url, headers={"User-Agent": "NobadVPN/" + APP_VER})
    with reach.urlopen(req, timeout=10) as r:
        raw = r.read(65537)
    if len(raw) > 65536:
        raise ValueError("manifest too large")
    return validate_manifest(json.loads(raw.decode("utf-8-sig")))  # tolerate a BOM (PowerShell 5 Out-File)


class Updater:
    def __init__(self):
        self.state = {"checked": None, "available": False, "version": None, "notes": "", "error": None,
                      "busy": False, "progress": 0, "signature": None}
        self._manifest = None
        self._lock = threading.Lock()

    def snapshot(self):
        return dict(self.state, current=APP_VER, configured=bool(ctx.settings.get("update_url")))

    def _set(self, **kw):
        self.state.update(kw)
        broadcast("update", self.snapshot())

    def check(self):
        url = ctx.settings.get("update_url")
        if not url:
            self._set(error="No update URL is set (Settings → Updates).")
            return self.snapshot()
        try:
            m = fetch_manifest(url)
            self._manifest = m
            self._set(checked=int(time.time()), error=None, available=is_newer(m["version"]), version=m["version"],
                      notes=m["notes"])
            if self.state["available"]:
                log(f"update available: {m['version']}", "ok")
        except Exception as e:
            self._set(checked=int(time.time()), error=f"update check failed: {type(e).__name__}: {e}"[:200])
        return self.snapshot()

    def download_and_install(self):
        if not self._lock.acquire(blocking=False):
            return
        work = None
        try:
            m = self._manifest
            if not m or not is_newer(m["version"]):
                self._set(error="No update to install.")
                return
            self._set(busy=True, progress=0, error=None)
            for old in os.listdir(UPDATE_DIR) if os.path.isdir(UPDATE_DIR) else ():
                if old.startswith("update-"):                # earlier downloads (installed or refused)
                    shutil.rmtree(os.path.join(UPDATE_DIR, old), ignore_errors=True)
            work = private_workdir(UPDATE_DIR, "update-")    # admin-only: nobody can swap the file after the checks
            path = os.path.join(work, "NobadVPN-Setup-" + re.sub(r"[^0-9A-Za-z.\-]", "_", m["version"]) + ".exe")
            h = hashlib.sha256()
            req = urllib.request.Request(m["url"], headers={"User-Agent": "NobadVPN/" + APP_VER})
            with reach.urlopen(req, timeout=30) as r, open(path, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                got = 0
                while True:
                    chunk = r.read(65536)
                    if not chunk:
                        break
                    got += len(chunk)
                    if got > MAX_INSTALLER:              # a hostile or broken server could fill the disk
                        raise ValueError("the update is larger than any NOBAD installer — download stopped")
                    h.update(chunk)
                    f.write(chunk)
                    if total:
                        self._set(progress=int(got * 100 / total))
            if h.hexdigest() != m["sha256"]:
                shutil.rmtree(work, ignore_errors=True)
                self._set(busy=False, error="Downloaded file failed the SHA-256 check — not installed.")
                return
            info = self.signature_info(path)
            self._set(signature=info["status"])
            ok, why = self.signature_acceptable(info, self.signature_info(sys.executable) if FROZEN else None)
            if not ok:
                shutil.rmtree(work, ignore_errors=True)
                log(f"update refused: {why}", "bad")
                self._set(busy=False, error=f"Update not installed: {why}")
                return
            log("installing update — NOBAD will restart", "ok")
            subprocess.Popen([path, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS",
                              "/RESTARTAPPLICATIONS"], creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
            self._set(busy=False, progress=100)
            from .lifecycle import request_quit
            request_quit(False)
        except Exception as e:
            if work:
                shutil.rmtree(work, ignore_errors=True)
            self._set(busy=False, error=f"update failed: {type(e).__name__}: {e}"[:200])
        finally:
            self._lock.release()

    @staticmethod
    def signature_info(path):
        """{'status': Valid|NotSigned|HashMismatch|NotTrusted|..., 'subject': str, 'thumbprint': str}"""
        return authenticode(path, timeout=30)

    @staticmethod
    def signature_status(path):
        return Updater.signature_info(path)["status"]

    @staticmethod
    def signature_acceptable(info, own=None, pinned=None, subjects=None):
        """An installer runs elevated, so a matching SHA-256 is not enough (the manifest host could be the
        attacker). Require a valid Authenticode signature from a pinned publisher/certificate, or from the same
        publisher that signed the running app. Returns (ok, reason)."""
        pinned = tuple(t.upper() for t in (UPDATE_SIGNER_THUMBPRINTS if pinned is None else pinned))
        subjects = tuple(UPDATE_SIGNER_SUBJECTS if subjects is None else subjects)
        if info.get("status") != "Valid":
            return False, f"the installer's code signature is {info.get('status') or 'missing'}"
        if subjects or pinned:
            if (subjects and info.get("subject") in subjects) or (pinned and info.get("thumbprint") in pinned):
                return True, ""
            return False, "the installer is signed by a publisher this app does not trust"
        if own and own.get("status") == "Valid":
            if own.get("subject") != info.get("subject"):
                return False, "the installer is signed by a different publisher"
            return True, ""
        return False, ("this build is not code-signed, so it can't verify who made the update — "
                       "download and install it manually")
