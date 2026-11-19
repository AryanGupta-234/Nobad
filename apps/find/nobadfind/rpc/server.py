"""The named pipe the UI connects to: `\\\\.\\pipe\\NOBADFind-<user SID>` (ctypes only, overlapped I/O).

Security:
- DACL from SDDL `D:P(D;;GA;;;NU)(A;;GA;;;<user SID>)`: only this user, network logons denied, nothing inherited.
- `PIPE_REJECT_REMOTE_CLIENTS`: no connections from other machines.
- `FILE_FLAG_FIRST_PIPE_INSTANCE` on the first instance: if any process already holds the name, the engine
  refuses to serve instead of sharing it. The next listening instance is created before a connected one is handed
  off, so the name is never free while the engine runs. (The Flutter client also checks the pipe's owner is the
  current user and allows identification-level impersonation only.)
- Lines are capped at protocol.MAX_MESSAGE; a client that sends more is dropped. A client that stops reading is
  dropped after WRITE_TIMEOUT_MS, so it can't stall the engine.

One reader thread per client; requests run on a small thread pool so a slow thumbnail doesn't hold up a search.
Methods in `slow` (they wait for the user: a folder dialog, a permission prompt) get a thread of their own, so
they can never use up the pool; each of them lets only one call wait at a time (the handlers say "busy").
"""
import ctypes
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from ctypes import wintypes

from ..log import log
from .protocol import (INTERNAL_ERROR, INVALID_REQUEST, MAX_MESSAGE, LineBuffer, encode, error, handle_line, method_of,
                       run_after)

MAX_CLIENTS = 8
BUF = 64 * 1024
WRITE_TIMEOUT_MS = 5000

PIPE_ACCESS_DUPLEX = 0x3
FILE_FLAG_OVERLAPPED = 0x40000000
FILE_FLAG_FIRST_PIPE_INSTANCE = 0x00080000
PIPE_TYPE_BYTE = PIPE_READMODE_BYTE = PIPE_WAIT = 0
PIPE_REJECT_REMOTE_CLIENTS = 0x8
ERROR_IO_PENDING, ERROR_PIPE_CONNECTED, ERROR_PIPE_BUSY = 997, 535, 231
WAIT_OBJECT_0, INFINITE = 0, 0xFFFFFFFF
INVALID_HANDLE = ctypes.c_void_p(-1).value


class _OVERLAPPED(ctypes.Structure):
    _fields_ = [("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t), ("Offset", wintypes.DWORD),
                ("OffsetHigh", wintypes.DWORD), ("hEvent", wintypes.HANDLE)]


class _SA(ctypes.Structure):
    _fields_ = [("nLength", wintypes.DWORD), ("lpSecurityDescriptor", ctypes.c_void_p),
                ("bInheritHandle", wintypes.BOOL)]


class _SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]


_dll = {}


def _dlls():
    if not _dll:
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        a = ctypes.WinDLL("advapi32", use_last_error=True)
        H, D, B, P = wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, ctypes.c_void_p
        POV = ctypes.POINTER(_OVERLAPPED)
        for dll, specs in ((k, (("CreateNamedPipeW", H, [wintypes.LPCWSTR, D, D, D, D, D, D, ctypes.POINTER(_SA)]),
                                ("ConnectNamedPipe", B, [H, POV]),
                                ("DisconnectNamedPipe", B, [H]),
                                ("CreateEventW", H, [P, B, B, wintypes.LPCWSTR]),
                                ("SetEvent", B, [H]),
                                ("ResetEvent", B, [H]),
                                ("CloseHandle", B, [H]),
                                ("ReadFile", B, [H, P, D, P, POV]),
                                ("WriteFile", B, [H, P, D, P, POV]),
                                ("GetOverlappedResult", B, [H, POV, ctypes.POINTER(D), B]),
                                ("CancelIoEx", B, [H, POV]),
                                ("WaitForMultipleObjects", D, [D, ctypes.POINTER(H), B, D]),
                                ("WaitForSingleObject", D, [H, D]),
                                ("GetNamedPipeClientProcessId", B, [H, ctypes.POINTER(D)]),
                                ("GetCurrentProcess", H, []),
                                ("LocalFree", P, [P]))),
                           (a, (("OpenProcessToken", B, [H, D, ctypes.POINTER(H)]),
                                ("GetTokenInformation", B, [H, ctypes.c_int, P, D, ctypes.POINTER(D)]),
                                ("ConvertSidToStringSidW", B, [P, ctypes.POINTER(wintypes.LPWSTR)]),
                                ("ConvertStringSecurityDescriptorToSecurityDescriptorW", B,
                                 [wintypes.LPCWSTR, D, ctypes.POINTER(P), ctypes.POINTER(D)])))):
            for name, res, args in specs:
                f = getattr(dll, name)
                f.restype, f.argtypes = res, args
        _dll.update(k=k, a=a)
    return _dll["k"], _dll["a"]


def user_sid():
    """The current user's SID as a string (S-1-5-21-...)."""
    k, a = _dlls()
    tok = wintypes.HANDLE()
    if not a.OpenProcessToken(k.GetCurrentProcess(), 0x8, ctypes.byref(tok)):     # TOKEN_QUERY
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        need = wintypes.DWORD()
        a.GetTokenInformation(tok, 1, None, 0, ctypes.byref(need))                   # TokenUser
        buf = ctypes.create_string_buffer(need.value)
        if not a.GetTokenInformation(tok, 1, buf, need, ctypes.byref(need)):
            raise ctypes.WinError(ctypes.get_last_error())
        sid = _SID_AND_ATTRIBUTES.from_buffer(buf).Sid
        s = wintypes.LPWSTR()
        if not a.ConvertSidToStringSidW(sid, ctypes.byref(s)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return s.value
        finally:
            k.LocalFree(s)
    finally:
        k.CloseHandle(tok)


def pipe_name(sid=None):
    return "\\\\.\\pipe\\NOBADFind-" + (sid or user_sid())


def sddl_for(sid):
    """Protected DACL: network logons denied, full access for this user only."""
    if not (sid.startswith("S-1-") and all(c.isdigit() or c in "S-" for c in sid)):
        raise ValueError("not a SID")
    return f"D:P(D;;GA;;;NU)(A;;GA;;;{sid})"


class Conn:
    """One connected client: its pipe handle, a write lock, what it subscribed to, which of its windows are up
    (ui_shown / ui_hidden) and its process id."""

    def __init__(self, k, handle):
        self._k, self.handle = k, handle
        self.events = set()
        self.shown = set()
        self.alive = True
        self._wlock = threading.Lock()
        self._wov = _OVERLAPPED()
        self._wov.hEvent = k.CreateEventW(None, True, False, None)
        pid = wintypes.DWORD()
        self.pid = pid.value if k.GetNamedPipeClientProcessId(handle, ctypes.byref(pid)) else 0
        self._closed = False

    def send(self, obj):
        data = encode(obj)
        if len(data) > MAX_MESSAGE + 1:
            data = encode(error(obj.get("id"), INTERNAL_ERROR, "Reply too big"))
        k = self._k
        with self._wlock:
            if not self.alive:
                return False
            buf = ctypes.create_string_buffer(data, len(data))
            k.ResetEvent(self._wov.hEvent)
            if not k.WriteFile(self.handle, buf, len(data), None, ctypes.byref(self._wov)) \
                    and ctypes.get_last_error() != ERROR_IO_PENDING:
                self.alive = False
                return False
            if k.WaitForSingleObject(self._wov.hEvent, WRITE_TIMEOUT_MS) != WAIT_OBJECT_0:
                k.CancelIoEx(self.handle, ctypes.byref(self._wov))           # not reading: give up on it
                self.alive = False
            n = wintypes.DWORD()
            if not k.GetOverlappedResult(self.handle, ctypes.byref(self._wov), ctypes.byref(n), True) \
                    or n.value != len(data):
                self.alive = False
            return self.alive

    def close(self, linger=False):
        """linger=True: let the client still read what was already written (e.g. the "Message too big" error).
        DisconnectNamedPipe throws away anything the client hasn't read yet; closing the handle alone doesn't
        (the client reads it, then gets end-of-file) and never blocks, unlike FlushFileBuffers."""
        k = self._k
        with self._wlock:
            self.alive = False
            if self._closed:
                return
            self._closed = True
        k.CancelIoEx(self.handle, None)
        if not linger:
            k.DisconnectNamedPipe(self.handle)
        k.CloseHandle(self.handle)
        k.CloseHandle(self._wov.hEvent)


class Server:
    """Serves `methods` (name -> fn(params, conn)) on the user's pipe. start() is False if the pipe can't be made."""

    def __init__(self, methods=None, name=None, workers=4):
        self._k, self._a = _dlls()
        self.methods = methods or {}
        self.on_drop = None                  # fn(conn) after a client is gone (pipe liveness: Rpc._dropped)
        self.slow = set()                    # method names answered on a thread of their own
        self.sid = user_sid()
        self.name = name or pipe_name(self.sid)
        self._stop = threading.Event()
        self._stop_evt = self._k.CreateEventW(None, True, False, None)
        self._conns = set()
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="rpc")
        self._sd = ctypes.c_void_p()
        if not self._a.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl_for(self.sid), 1, ctypes.byref(self._sd), None):          # SDDL_REVISION_1
            raise ctypes.WinError(ctypes.get_last_error())
        self._sa = _SA(ctypes.sizeof(_SA), self._sd, False)
        self._first = True
        self._next = None
        self.thread = None

    def start(self):
        try:
            self._next = self._make_instance()
        except OSError as e:
            log(f"rpc pipe not available (error {e.winerror}): another NOBAD Find engine may be running", "warn")
            return False
        self.thread = threading.Thread(target=self._accept_loop, daemon=True, name="rpc-accept")
        self.thread.start()
        log("rpc pipe ready")
        return True

    def stop(self):
        self._stop.set()
        self._k.SetEvent(self._stop_evt)
        if self.thread:
            self.thread.join(3)
        with self._lock:
            conns = list(self._conns)
            self._conns.clear()
        for c in conns:
            c.close(linger=True)             # a client still reads what was written (quit's reply, quitting)
        self._pool.shutdown(wait=False, cancel_futures=True)
        self._k.LocalFree(self._sd)
        self._sd = None

    def clients(self):
        with self._lock:
            return [c for c in self._conns if c.alive]

    def drop(self, conn, linger=False):
        with self._lock:
            if conn not in self._conns:
                return
            self._conns.discard(conn)
        conn.close(linger)
        if self.on_drop is not None:
            try:
                self.on_drop(conn)
            except Exception as e:
                log(f"rpc client end hook failed: {type(e).__name__}", "warn")

    def allow_foreground(self):
        """A hotkey press gives the engine the right to bring a window to the front: pass it on to the UIs."""
        user32 = ctypes.WinDLL("user32")
        for c in self.clients():
            if c.pid:
                user32.AllowSetForegroundWindow(wintypes.DWORD(c.pid))

    # ----- pipe -----
    def _make_instance(self):
        mode = PIPE_ACCESS_DUPLEX | FILE_FLAG_OVERLAPPED | (FILE_FLAG_FIRST_PIPE_INSTANCE if self._first else 0)
        h = self._k.CreateNamedPipeW(self.name, mode, PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT |
                                     PIPE_REJECT_REMOTE_CLIENTS, MAX_CLIENTS, BUF, BUF, 0, ctypes.byref(self._sa))
        if not h or h == INVALID_HANDLE:
            raise ctypes.WinError(ctypes.get_last_error())
        self._first = False
        return h

    def _wait(self, event):
        """Wait for an overlapped operation or stop(). True = the operation finished."""
        arr = (wintypes.HANDLE * 2)(event, self._stop_evt)
        return self._k.WaitForMultipleObjects(2, arr, False, INFINITE) == WAIT_OBJECT_0

    def _accept_loop(self):
        k = self._k
        ov = _OVERLAPPED()
        ov.hEvent = k.CreateEventW(None, True, False, None)
        n = wintypes.DWORD()
        try:
            while not self._stop.is_set():
                h = self._next
                k.ResetEvent(ov.hEvent)
                ok = k.ConnectNamedPipe(h, ctypes.byref(ov))
                err = ctypes.get_last_error()
                if not ok and err == ERROR_IO_PENDING:
                    if not self._wait(ov.hEvent):              # stopping
                        k.CancelIoEx(h, ctypes.byref(ov))
                        k.GetOverlappedResult(h, ctypes.byref(ov), ctypes.byref(n), True)
                        k.CloseHandle(h)
                        return
                    ok = k.GetOverlappedResult(h, ctypes.byref(ov), ctypes.byref(n), False)
                elif not ok and err == ERROR_PIPE_CONNECTED:
                    ok = True
                if not ok:                                     # gone before we got it: reuse the instance
                    k.DisconnectNamedPipe(h)
                    continue
                self._next = None
                while not self._stop.is_set():                 # the next instance first: the name stays ours
                    try:
                        self._next = self._make_instance()
                        break
                    except OSError as e:
                        if e.winerror != ERROR_PIPE_BUSY:      # busy = MAX_CLIENTS in use: wait for one to end
                            log(f"rpc pipe instance failed (error {e.winerror})", "warn")
                        if self._stop.wait(0.5):
                            break
                conn = Conn(k, h)
                with self._lock:
                    self._conns.add(conn)
                threading.Thread(target=self._serve, args=(conn,), daemon=True, name="rpc-conn").start()
                if self._next is None:
                    return
        finally:
            k.CloseHandle(ov.hEvent)
            if self._next is not None and self._stop.is_set():
                k.CloseHandle(self._next)
                self._next = None

    def _serve(self, conn):
        k = self._k
        ov = _OVERLAPPED()
        ov.hEvent = k.CreateEventW(None, True, False, None)
        buf = ctypes.create_string_buffer(BUF)
        lines = LineBuffer()
        n = wintypes.DWORD()
        linger = False
        try:
            while not self._stop.is_set() and conn.alive:
                k.ResetEvent(ov.hEvent)
                if not k.ReadFile(conn.handle, buf, BUF, None, ctypes.byref(ov)) \
                        and ctypes.get_last_error() != ERROR_IO_PENDING:
                    break                                      # the client closed its end
                if not self._wait(ov.hEvent):
                    k.CancelIoEx(conn.handle, ctypes.byref(ov))
                    k.GetOverlappedResult(conn.handle, ctypes.byref(ov), ctypes.byref(n), True)
                    break
                if not k.GetOverlappedResult(conn.handle, ctypes.byref(ov), ctypes.byref(n), False):
                    break
                try:
                    got = lines.feed(buf.raw[:n.value])
                except ValueError:
                    linger = conn.send(error(None, INVALID_REQUEST, "Message too big"))   # it must get to read it
                    break
                for line in got:
                    if method_of(line) in self.slow:
                        threading.Thread(target=self._answer, args=(conn, line), daemon=True,
                                         name="rpc-slow").start()
                        continue
                    try:
                        self._pool.submit(self._answer, conn, line)
                    except RuntimeError:                       # the pool is shut down: stopping
                        break
        except Exception as e:
            log(f"rpc connection ended: {type(e).__name__}", "warn")
        finally:
            k.CloseHandle(ov.hEvent)
            self.drop(conn, linger or self._stop.is_set())    # stopping: what was written stays readable

    def _answer(self, conn, line):
        t0 = time.perf_counter()
        after = []
        reply = handle_line(line, self.methods, conn, after=after)
        if reply is not None and conn.alive and not conn.send(reply):
            self.drop(conn)
        run_after(after)                                       # e.g. quit: only now may the engine stop
        if method_of(line) == "search":                       # how long it took, never the words searched for
            r = reply.get("result") if isinstance(reply, dict) else None
            log(f"rpc search {(time.perf_counter() - t0) * 1000:.1f} ms "
                f"(ranking {r.get('ms') if isinstance(r, dict) else '?'} ms)")
