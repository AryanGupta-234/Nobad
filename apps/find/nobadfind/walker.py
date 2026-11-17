"""Fast parallel folder walk (works without admin). The admin "turbo" path in mft.py reads the NTFS index instead.

Safety: links and junctions are never followed (no loops, no escaping into other folders), other users'
profiles are never entered, and secret folders from const.ALWAYS_EXCLUDE_* are skipped.
"""
import os
import queue
import threading

from .const import ALWAYS_EXCLUDE_EXT, ALWAYS_EXCLUDE_NAMES
from .kinds import kind_of

FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def norm(p):
    return os.path.normcase(os.path.normpath(p))


def profile_dir():
    return os.path.normpath(os.environ.get("USERPROFILE") or os.path.expanduser("~"))


def default_roots(drives):
    """The user's profile, then every fixed drive."""
    roots = [profile_dir()]
    for d in drives:
        if norm(d) not in {norm(r) for r in roots}:
            roots.append(d)
    return roots


def system_skips():
    """Folders under drive roots that are never walked: Windows itself, other profiles, app data noise."""
    sysroot = os.environ.get("SystemRoot", r"C:\Windows")
    drive = os.path.splitdrive(sysroot)[0] + "\\"
    prof = profile_dir()
    skips = {norm(sysroot), norm(os.path.join(drive, "ProgramData")), norm(os.path.join(drive, "Recovery")),
             norm(os.path.join(drive, "PerfLogs")), norm(os.path.join(prof, "AppData"))}
    users = os.path.dirname(prof)
    skips.add(norm(users))            # C:\Users is skipped as a whole; the own profile is its own root
    return skips


class Walker:
    """Walk roots with a pool of threads. on_batch(rows) receives rows ready for Store.upsert_files."""

    def __init__(self, roots, exclude=(), threads=8, gen=1, on_batch=None, batch=2000, stop=None):
        self.roots = [os.path.normpath(r) for r in roots]
        self.root_set = {norm(r) for r in self.roots}
        self.exclude = {norm(e) for e in exclude} | system_skips()
        self.threads = max(1, threads)
        self.gen = gen
        self.on_batch = on_batch or (lambda rows: None)
        self.batch = batch
        self.stop = stop or threading.Event()
        self.count = 0
        self.dirs = 0
        self.errors = 0
        self._rows = []
        self._lock = threading.Lock()

    def skip_dir(self, path, name):
        if name.lower() in ALWAYS_EXCLUDE_NAMES or name.startswith("$"):
            return True
        n = norm(path)
        return n in self.exclude and n not in self.root_set

    def excluded(self, path):
        """True if path is inside anything the walk would skip (used for live changes from the watcher)."""
        n = norm(path)
        for e in self.exclude:
            if (n == e or n.startswith(e.rstrip("\\") + "\\")) and not any(
                    n == r or (n.startswith(r.rstrip("\\") + "\\") and r.startswith(e)) for r in self.root_set):
                return True
        # like the walk itself, only folder names below the root that holds the path count
        under = [r for r in self.root_set if n.startswith(r.rstrip("\\") + "\\")]
        base = max(under, key=len) if under else ""
        parts = (n[len(base.rstrip("\\")) + 1:] if base else n).split("\\")
        if not base:
            parts = parts[1:]
        if any(x in ALWAYS_EXCLUDE_NAMES or x.startswith("$") for x in parts[:-1]):
            return True
        return bool(parts) and os.path.splitext(parts[-1])[1] in ALWAYS_EXCLUDE_EXT

    def _emit(self, row):
        with self._lock:
            self._rows.append(row)
            self.count += 1
            if len(self._rows) >= self.batch:
                rows, self._rows = self._rows, []
            else:
                return
        self.on_batch(rows)

    def run(self):
        q = queue.Queue()
        for r in self.roots:
            if os.path.isdir(r):
                q.put(r)
        pending = [q.qsize()]
        plock = threading.Lock()

        def work():
            while not self.stop.is_set():
                try:
                    d = q.get(timeout=0.2)
                except queue.Empty:
                    with plock:
                        if pending[0] == 0:
                            return
                    continue
                try:
                    self._scan(d, q, pending, plock)
                finally:
                    with plock:
                        pending[0] -= 1

        ts = [threading.Thread(target=work, daemon=True, name=f"walk-{i}") for i in range(self.threads)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        with self._lock:
            rows, self._rows = self._rows, []
        if rows:
            self.on_batch(rows)
        return self.count

    def _scan(self, d, q, pending, plock):
        try:
            it = os.scandir(d)
        except OSError:
            self.errors += 1
            return
        self.dirs += 1
        with it:
            for e in it:
                try:
                    st = e.stat(follow_symlinks=False)
                    attrs = getattr(st, "st_file_attributes", 0)
                    if e.is_symlink() or attrs & FILE_ATTRIBUTE_REPARSE_POINT:
                        continue
                    if e.is_dir(follow_symlinks=False):
                        if self.skip_dir(e.path, e.name):
                            continue
                        self._emit((e.path, e.name, d, "", "folder", 0, st.st_mtime, _created(st), self.gen))
                        with plock:
                            pending[0] += 1
                        q.put(e.path)
                    else:
                        ext = os.path.splitext(e.name)[1].lower()
                        if ext in ALWAYS_EXCLUDE_EXT:
                            continue
                        self._emit((e.path, e.name, d, ext, kind_of(e.name), st.st_size, st.st_mtime, _created(st),
                                    self.gen))
                except OSError:
                    self.errors += 1


def _created(st):
    return getattr(st, "st_birthtime", None) or st.st_ctime
