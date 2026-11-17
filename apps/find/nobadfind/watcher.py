"""Keep the index fresh: Windows folder-change notifications (ReadDirectoryChangesW) on each indexed root.

Runs as the normal user. It only reports which paths changed; the indexer then looks at those paths again.
If notifications overflow (a huge copy), the indexer falls back to a quick rescan of that root.
"""
import ctypes
import os
import struct
import threading
from ctypes import wintypes

from . import winapi
from .log import log

FILE_LIST_DIRECTORY = 0x1
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
NOTIFY = 0x1 | 0x2 | 0x8 | 0x10   # file name, dir name, size, last write
BUF = 64 * 1024

if winapi.WIN:
    k32 = winapi.k32
    k32.ReadDirectoryChangesW.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, wintypes.BOOL,
                                          wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
                                          ctypes.c_void_p]
    k32.ReadDirectoryChangesW.restype = wintypes.BOOL
    k32.CancelIoEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p]


def parse_notify(buf, n):
    """Yield (action, relative_path) from a FILE_NOTIFY_INFORMATION buffer."""
    off = 0
    while off + 12 <= n:
        nxt, action, name_len = struct.unpack_from("<III", buf, off)
        if off + 12 + name_len > n:
            break
        yield action, bytes(buf[off + 12: off + 12 + name_len]).decode("utf-16-le", "replace")
        if not nxt:
            break
        off += nxt


class Watcher:
    def __init__(self, roots, on_changes, on_overflow):
        self.roots = list(roots)
        self.on_changes = on_changes          # fn(root, set_of_paths)
        self.on_overflow = on_overflow        # fn(root)
        self._handles = {}
        self._stop = threading.Event()
        self._threads = []

    def start(self):
        if not winapi.WIN:
            return
        for r in self.roots:
            t = threading.Thread(target=self._watch, args=(r,), daemon=True, name=f"watch:{r}")
            t.start()
            self._threads.append(t)

    def stop(self):
        self._stop.set()
        for h in list(self._handles.values()):
            try:
                k32.CancelIoEx(h, None)
            except Exception:
                pass

    def _watch(self, root):
        h = k32.CreateFileW(root, FILE_LIST_DIRECTORY, 0x7, None, 3, FILE_FLAG_BACKUP_SEMANTICS, None)
        if not h or h == winapi.INVALID_HANDLE:
            log(f"can't watch {root}", "warn")
            return
        self._handles[root] = h
        buf = ctypes.create_string_buffer(BUF)
        got = wintypes.DWORD()
        try:
            while not self._stop.is_set():
                ok = k32.ReadDirectoryChangesW(h, buf, BUF, True, NOTIFY, ctypes.byref(got), None, None)
                if self._stop.is_set():
                    break
                if not ok:
                    log(f"watch stopped for {root} (error {ctypes.get_last_error()})", "warn")
                    break
                if got.value == 0:                     # the buffer overflowed: too many changes at once
                    self.on_overflow(root)
                    continue
                changed = {os.path.join(root, rel) for _a, rel in parse_notify(buf.raw, got.value)}
                if changed:
                    self.on_changes(root, changed)
        finally:
            k32.CloseHandle(h)
            self._handles.pop(root, None)
