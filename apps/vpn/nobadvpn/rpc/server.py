"""The named pipe the Flutter UI connects to: `\\\\.\\pipe\\NOBADVPN-<user SID>` (ctypes only, overlapped I/O).

Adapted from NOBAD Find's engine pipe (apps/find/nobadfind/rpc/server.py). The security model is security.py:
- DACL + Medium label from security.sddl_for (the session's user, SYSTEM, Administrators; no network logons);
- PIPE_REJECT_REMOTE_CLIENTS; FILE_FLAG_FIRST_PIPE_INSTANCE on the first instance (a name someone else created
  first is never shared); the next listening instance exists before a connected one is handed off;
- the caller check (security.check) on the first bytes a client sends, before any request is parsed;
- lines capped at protocol.MAX_MESSAGE (a bigger one is answered with an error, then the client is dropped);
  a client that stops reading is dropped after WRITE_TIMEOUT_MS, so it can't stall the engine.

One reader thread per client; requests run on a small pool, so a slow handler doesn't hold up `state`.
"""
import ctypes
import threading
from concurrent.futures import ThreadPoolExecutor
from ctypes import wintypes

from ..logbus import log
from . import security
from .protocol import (INTERNAL_ERROR, INVALID_REQUEST, MAX_MESSAGE, NOT_ALLOWED, LineBuffer, encode, error,
                       handle_line, run_after)

MAX_CLIENTS = 6
BUF = 64 * 1024
WRITE_TIMEOUT_MS = 5000

PIPE_ACCESS_DUPLEX = 0x3
FILE_FLAG_OVERLAPPED = 0x40000000
FILE_FLAG_FIRST_PIPE_INSTANCE = 0x00080000
PIPE_TYPE_BYTE = PIPE_READMODE_BYTE = PIPE_WAIT = 0
PIPE_REJECT_REMOTE_CLIENTS = 0x8
PIPE_MODE = PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS
ERROR_IO_PENDING, ERROR_PIPE_CONNECTED, ERROR_PIPE_BUSY = 997, 535, 231
WAIT_OBJECT_0, INFINITE = 0, 0xFFFFFFFF
INVALID_HANDLE = ctypes.c_void_p(-1).value


class _OVERLAPPED(ctypes.Structure):
    _fields_ = [("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t), ("Offset", wintypes.DWORD),
                ("OffsetHigh", wintypes.DWORD), ("hEvent", wintypes.HANDLE)]


class _SA(ctypes.Structure):
    _fields_ = [("nLength", wintypes.DWORD), ("lpSecurityDescriptor", ctypes.c_void_p),
                ("bInheritHandle", wintypes.BOOL)]


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
                                ("LocalFree", P, [P]))),
                           (a, (("ConvertStringSecurityDescriptorToSecurityDescriptorW", B,
                                 [wintypes.LPCWSTR, D, ctypes.POINTER(P), ctypes.POINTER(D)]),))):
            for name, res, args in specs:
                f = getattr(dll, name)
                f.restype, f.argtypes = res, args
        _dll.update(k=k, a=a)
    return _dll["k"], _dll["a"]


class Conn:
    """One connected client: its pipe handle, a write lock, its subscriptions, the windows it shows, its pid and
    program (after the caller check)."""

    def __init__(self, k, handle):
        self._k, self.handle = k, handle
        self.events = set()
        self.shown = set()
        self.serves = set()          # windows this UI process can show ("main" / "mini"), from ui_shown/hidden
        self.alive = True
        self.checked = False
        self.image = ""
        self._wlock = threading.Lock()
        self._wov = _OVERLAPPED()
        self._wov.hEvent = k.CreateEventW(None, True, False, None)
        pid = wintypes.DWORD()
        self.pid = pid.value if k.GetNamedPipeClientProcessId(handle, ctypes.byref(pid)) else 0
        self._closed = False

    def send(self, obj):
        data = obj if isinstance(obj, bytes) else encode(obj)
        if len(data) > MAX_MESSAGE + 1:
            data = encode(error(obj.get("id") if isinstance(obj, dict) else None, INTERNAL_ERROR, "Reply too big"))
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
        """linger=True: the client can still read what was already written (an error, quit's reply)."""
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
    """Serves `methods` (name -> fn(params, conn)) on the pipe. start() is False if the pipe can't be made.

    `user_sid`: the account allowed in (the session's user); `check`: fn(handle, pid) -> None or a reason
    (security.check_client by default; tests pass their own)."""

    def __init__(self, methods=None, name=None, user_sid=None, check=None, workers=4):
        self._k, self._a = _dlls()
        self.methods = methods or {}
        self.on_drop = None
        self.on_connect = None
        self.user_sid = user_sid or security.session_user_sid()
        self.name = name or security.pipe_name(self.user_sid)
        self.check = check if check is not None else default_check(self.user_sid)
        self._stop = threading.Event()
        self._stop_evt = self._k.CreateEventW(None, True, False, None)
        self._conns = set()
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="rpc")
        self._sd = ctypes.c_void_p()
        if not self._a.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                security.sddl_for(self.user_sid), 1, ctypes.byref(self._sd), None):     # SDDL_REVISION_1
            raise ctypes.WinError(ctypes.get_last_error())
        self._sa = _SA(ctypes.sizeof(_SA), self._sd, False)
        self._first = True
        self._next = None
        self.thread = None

    def start(self):
        try:
            self._next = self._make_instance()
        except OSError as e:
            log(f"engine pipe not available (error {e.winerror}): another program holds its name", "warn")
            return False
        self.thread = threading.Thread(target=self._accept_loop, daemon=True, name="rpc-accept")
        self.thread.start()
        log("engine pipe ready for NOBAD's window", "info")
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
            c.close(linger=True)
        self._pool.shutdown(wait=False, cancel_futures=True)
        if self._sd:
            self._k.LocalFree(self._sd)
            self._sd = None

    def clients(self):
        with self._lock:
            return [c for c in self._conns if c.alive and c.checked]

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
                log(f"engine pipe: client end hook failed: {type(e).__name__}", "warn")

    # ----- pipe -----
    def _make_instance(self):
        mode = PIPE_ACCESS_DUPLEX | FILE_FLAG_OVERLAPPED | (FILE_FLAG_FIRST_PIPE_INSTANCE if self._first else 0)
        h = self._k.CreateNamedPipeW(self.name, mode, PIPE_MODE, MAX_CLIENTS, BUF, BUF, 0, ctypes.byref(self._sa))
        if not h or h == INVALID_HANDLE:
            raise ctypes.WinError(ctypes.get_last_error())
        self._first = False
        return h

    def _wait(self, event):
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
                    if not self._wait(ov.hEvent):
                        k.CancelIoEx(h, ctypes.byref(ov))
                        k.GetOverlappedResult(h, ctypes.byref(ov), ctypes.byref(n), True)
                        k.CloseHandle(h)
                        return
                    ok = k.GetOverlappedResult(h, ctypes.byref(ov), ctypes.byref(n), False)
                elif not ok and err == ERROR_PIPE_CONNECTED:
                    ok = True
                if not ok:
                    k.DisconnectNamedPipe(h)
                    continue
                self._next = None
                while not self._stop.is_set():                 # the next instance first: the name stays ours
                    try:
                        self._next = self._make_instance()
                        break
                    except OSError as e:
                        if e.winerror != ERROR_PIPE_BUSY:
                            log(f"engine pipe instance failed (error {e.winerror})", "warn")
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

    def _admit(self, conn):
        """The caller check, after the first read (a named pipe client can only be impersonated once it wrote)."""
        try:
            why = self.check(conn.handle, conn.pid)
        except Exception as e:
            why = f"check failed ({type(e).__name__})"
        if why:
            log(f"engine pipe: refused a program (pid {conn.pid}): {why}", "warn")
            return False
        conn.checked = True
        if self.on_connect is not None:
            try:
                self.on_connect(conn)
            except Exception as e:
                log(f"engine pipe: connect hook failed: {type(e).__name__}", "warn")
        return True

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
                    break
                if not self._wait(ov.hEvent):
                    k.CancelIoEx(conn.handle, ctypes.byref(ov))
                    k.GetOverlappedResult(conn.handle, ctypes.byref(ov), ctypes.byref(n), True)
                    break
                if not k.GetOverlappedResult(conn.handle, ctypes.byref(ov), ctypes.byref(n), False):
                    break
                if not conn.checked and not self._admit(conn):
                    linger = conn.send(error(None, NOT_ALLOWED, "This program may not control NOBAD VPN."))
                    break
                try:
                    got = lines.feed(buf.raw[:n.value])
                except ValueError:
                    linger = conn.send(error(None, INVALID_REQUEST, "Message too big"))
                    break
                for line in got:
                    try:
                        self._pool.submit(self._answer, conn, line)
                    except RuntimeError:                       # the pool is shut down: stopping
                        break
        except Exception as e:
            log(f"engine pipe connection ended: {type(e).__name__}", "warn")
        finally:
            k.CloseHandle(ov.hEvent)
            self.drop(conn, linger or self._stop.is_set())

    def _answer(self, conn, line):
        after = []
        reply = handle_line(line, self.methods, conn, after=after)
        if reply is not None and conn.alive and not conn.send(reply):
            self.drop(conn)
        run_after(after)


def default_check(user_sid):
    """security.decide against the real client (the engine's session and user; the pinned programs if installed)."""
    engine = {"user_sid": user_sid, "session": security.own_session()}
    images = security.allowed_images()

    def check(handle, pid):
        facts = security.client_facts(handle, pid)
        why = security.decide(facts, engine, images)
        return why
    return check
