"""Fast parallel folder walk as the normal user (the fallback for the optional turbo index, ntfs.py).

Safety: links and junctions are never followed (no loops, no escaping into other folders), other users'
profiles are never entered, and what's in or out follows scope.Rules: the categories the user sees in Settings
(system folders, caches, secrets: names only) plus the ones that are always out (other people's files).
"""
import os
import queue
import threading

from . import scope
from .kinds import kind_of

FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def norm(p):
    return os.path.normcase(os.path.normpath(p))


def profile_dir():
    return scope.profile_dir()


def default_roots(drives):
    """The user's profile, then every fixed drive."""
    roots = [profile_dir()]
    for d in drives:
        if norm(d) not in {norm(r) for r in roots}:
            roots.append(d)
    return roots


def system_skips(rules=None):
    """Folders the walk never enters, by place, for these rules (default: 0.7.0's, no system and no caches)."""
    rules = rules or scope.Rules.legacy()
    out = set(rules.others)
    if not rules.system:
        out |= rules.system_set
    if not rules.caches:
        out.add(rules.appdata)
    return out


class Walker:
    """Walk roots with a pool of threads. on_batch(rows) receives rows ready for Store.upsert_files.
    rules: scope.Rules from the settings; None keeps 0.7.0's skips (no system folders, caches or secrets)."""

    def __init__(self, roots, exclude=(), threads=8, gen=1, on_batch=None, batch=2000, stop=None, rules=None):
        self.roots = [os.path.normpath(r) for r in roots]
        self.root_set = {norm(r) for r in self.roots}
        self.rules = rules or scope.Rules.legacy()
        self.exclude = {norm(e) for e in exclude}
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
        n = norm(path)
        if n in self.exclude and n not in self.root_set:
            return True
        return self.rules.skip_dir(path, name, self.root_set)

    def _base(self, n):
        under = [r for r in self.root_set if n == r or n.startswith(r.rstrip("\\") + "\\")]
        return max(under, key=len) if under else None

    def excluded(self, path):
        """True if path is inside anything the walk would skip (live changes from the watcher, turbo records)."""
        n = norm(path)
        base = self._base(n)
        if base is None:
            return True                                    # outside every root: not in the scope
        for e in self.exclude:
            if (n == e or n.startswith(e.rstrip("\\") + "\\")) and not (
                    base.startswith(e.rstrip("\\") + "\\") or base == e):
                return True
        # like the walk itself, only folders below the root that holds the path count
        return self.rules.out(path, base) or self.rules.skip_file(path)

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
                        if self.rules.skip_file(e.name):
                            continue
                        self._emit((e.path, e.name, d, ext, kind_of(e.name), st.st_size, st.st_mtime, _created(st),
                                    self.gen))
                except OSError:
                    self.errors += 1


def _created(st):
    return getattr(st, "st_birthtime", None) or st.st_ctime
