"""JSON-RPC 2.0 framing and dispatch, free of any Windows call so it can be tested anywhere.

One JSON object per line, at most MAX_MESSAGE bytes. Bad JSON, unknown methods and wrong parameters become
JSON-RPC errors; nothing here raises to the caller.
"""
import json

from ..log import log

PROTOCOL = 1
MAX_MESSAGE = 1024 * 1024          # bytes in one line, either way

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR = -32700, -32600, -32601, -32602, -32603


class RpcError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


def int_param(params, key="id"):
    v = params.get(key)
    if not isinstance(v, int) or isinstance(v, bool):
        raise RpcError(INVALID_PARAMS, f"'{key}' must be a whole number")
    return v


def bool_param(params, key):
    v = params.get(key)
    if not isinstance(v, bool):
        raise RpcError(INVALID_PARAMS, f"'{key}' must be true or false")
    return v


def str_param(params, key, default=None):
    """A string parameter; `default` None means it must be given."""
    v = params.get(key, default)
    if not isinstance(v, str):
        raise RpcError(INVALID_PARAMS, f"'{key}' must be a string")
    return v


def choice_param(params, key, choices, default):
    v = params.get(key, default)
    if v not in choices:
        raise RpcError(INVALID_PARAMS, f"'{key}' must be one of {', '.join(choices)}")
    return v


def names_param(params, key="events"):
    v = params.get(key)
    if not isinstance(v, list) or not all(isinstance(e, str) for e in v):
        raise RpcError(INVALID_PARAMS, f"'{key}' must be a list of names")
    return v


def ok(r):
    """The {ok, error} answer every action method gives, whatever the Api method left out."""
    r = r if isinstance(r, dict) else {}
    return {"ok": bool(r.get("ok")), "error": str(r.get("error") or "")}


def _valid_id(rid):
    return rid is None or (isinstance(rid, (int, str)) and not isinstance(rid, bool))


def error(rid, code, message):
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def handle_line(line, methods, conn=None):
    """One request line (bytes or str) -> the response dict, or None for a notification. Never raises.

    `methods` maps a name to fn(params, conn) -> JSON-able result."""
    try:
        msg = json.loads(line)
    except (ValueError, UnicodeDecodeError):
        return error(None, PARSE_ERROR, "Parse error")
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
        rid = msg.get("id") if isinstance(msg, dict) else None
        return error(rid if _valid_id(rid) else None, INVALID_REQUEST, "Invalid Request")
    notification = "id" not in msg
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
        return None if notification else error(rid, e.code, e.message)
    except Exception as e:
        log(f"rpc {method[:40]} failed: {type(e).__name__}", "warn")
        return None if notification else error(rid, INTERNAL_ERROR, "Internal error")
    return None if notification else {"jsonrpc": "2.0", "id": rid, "result": result}


def method_of(line):
    """The method name of a request line ('' if it has none); used only for timing logs."""
    try:
        m = json.loads(line).get("method")
        return m if isinstance(m, str) else ""
    except Exception:
        return ""


def encode(obj):
    """One line of compact JSON; ensure_ascii keeps odd file names (lone surrogates, U+2028) from breaking framing."""
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
