"""JSON-RPC 2.0 framing and dispatch, free of any Windows call so it can be tested anywhere.

One JSON object per line, at most MAX_MESSAGE bytes either way. Bad JSON, unknown methods and wrong parameters
become JSON-RPC errors; nothing here raises to the caller, and no exception text ever reaches the client (it could
carry a path or a key fragment): the client gets "Internal error", the log gets the exception's type.
Adapted from NOBAD Find's engine pipe (apps/find/nobadfind/rpc/protocol.py).
"""
import json
import threading

from ..logbus import log

PROTOCOL = 1
# A pasted config may be up to 400,000 bytes (the old HTTP cap); JSON escaping and the envelope fit in 1 MiB.
MAX_MESSAGE = 1024 * 1024

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR = -32700, -32600, -32601, -32602, -32603
NOT_ALLOWED = -32001             # the client process failed the engine's caller check (security.check_client)


class RpcError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


def _valid_id(rid):
    return rid is None or (isinstance(rid, (int, str)) and not isinstance(rid, bool))


def error(rid, code, message):
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def notification(method, params):
    return {"jsonrpc": "2.0", "method": method, "params": params}


_local = threading.local()


def after_reply(fn):
    """Run fn once the reply to the request being handled has been written (quit: stop only after the client has
    its answer). Outside a request fn runs now."""
    pending = getattr(_local, "after", None)
    if pending is None:
        fn()
    else:
        pending.append(fn)


def _no_constant(name):
    raise ValueError(f"{name} is not JSON")             # NaN, Infinity: Python's json would accept them


def handle_line(line, methods, conn=None, after=None):
    """One request line (bytes or str) -> the response dict, or None for a notification. Never raises.

    `methods` maps a name to fn(params, conn) -> JSON-able result. `after` collects what handlers asked to run after
    the reply (after_reply); the caller runs it once the reply is sent. Without it, it runs on return."""
    mine = [] if after is None else after
    _local.after = mine
    try:
        return _handle(line, methods, conn)
    finally:
        _local.after = None
        if after is None:
            run_after(mine)


def run_after(fns):
    for fn in fns:
        try:
            fn()
        except Exception as e:
            log(f"rpc after-reply step failed: {type(e).__name__}", "warn")


def _handle(line, methods, conn):
    try:
        msg = json.loads(line, parse_constant=_no_constant)
    except (ValueError, UnicodeDecodeError, RecursionError):
        return error(None, PARSE_ERROR, "Parse error")
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
        rid = msg.get("id") if isinstance(msg, dict) else None
        return error(rid if _valid_id(rid) else None, INVALID_REQUEST, "Invalid Request")
    notification_ = "id" not in msg
    rid = msg.get("id")
    if not _valid_id(rid):
        return error(None, INVALID_REQUEST, "Invalid Request")
    params = msg.get("params")
    if params is None:
        params = {}
    method = msg["method"]
    try:
        if not isinstance(params, dict):
            raise RpcError(INVALID_PARAMS, "params must be an object")
        fn = methods.get(method)
        if fn is None:
            raise RpcError(METHOD_NOT_FOUND, "Method not found")
        result = fn(params, conn)
    except RpcError as e:
        return None if notification_ else error(rid, e.code, e.message)
    except Exception as e:
        log(f"rpc {method[:40]} failed: {type(e).__name__}", "warn")
        return None if notification_ else error(rid, INTERNAL_ERROR, "Internal error")
    return None if notification_ else {"jsonrpc": "2.0", "id": rid, "result": result}


def encode(obj):
    """One line of compact JSON; ensure_ascii keeps odd names (lone surrogates, U+2028) from breaking framing."""
    return (json.dumps(obj, separators=(",", ":"), ensure_ascii=True) + "\n").encode("ascii")


class LineBuffer:
    """Bytes in -> complete lines out; a line longer than `cap` raises ValueError (the connection is dropped)."""

    def __init__(self, cap=MAX_MESSAGE):
        self._buf = bytearray()
        self._cap = cap

    def feed(self, data):
        self._buf += data
        lines = []
        while True:
            i = self._buf.find(b"\n")
            if i < 0:
                break
            line = bytes(self._buf[:i]).rstrip(b"\r")
            del self._buf[:i + 1]
            if len(line) > self._cap:
                raise ValueError("message too big")
            if line.strip():
                lines.append(line)
        if len(self._buf) > self._cap:
            raise ValueError("message too big")
        return lines
