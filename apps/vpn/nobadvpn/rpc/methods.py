"""The pipe's methods: the pipe's own (hello, subscribe, state, the window reports) and a thin bridge to the
WebView UI's handlers (api.HANDLERS, plus Network and Streaming Intelligence).

The bridge adds no logic of its own: params.validate() checks the shape first, then the same handler the WebView
page calls runs with the checked parameters, and its answer is shaped as {"ok": bool, ...}: never a raw
exception, never a bare `{"ok": false}` without a sentence for the UI to show.
"""
import os

from ..logbus import log
from . import params
from .events import EVENTS
from .protocol import PROTOCOL, RpcError

PIPE_ONLY = {"hello", "subscribe", "unsubscribe", "state", "ui_shown", "ui_hidden", "ui_show"}
FALLBACK_ERROR = "NOBAD couldn't do that. The log has the details."


def shape(result):
    """Any handler answer -> a dict with a boolean `ok`, and a non-empty `error` sentence when it isn't ok."""
    if not isinstance(result, dict):
        return {"ok": False, "error": FALLBACK_ERROR}
    out = dict(result)
    out["ok"] = bool(result.get("ok"))
    if not out["ok"]:
        err = result.get("error")
        errs = result.get("errors")
        if not (isinstance(err, str) and err.strip()) and isinstance(errs, list) and errs and isinstance(errs[0], str):
            err = errs[0]                       # free_import: the first file's reason
        out["error"] = err if isinstance(err, str) and err.strip() else FALLBACK_ERROR
    return out


def _who(conn):
    pid = getattr(conn, "pid", 0) or 0
    try:
        from ..lifecycle import process_image
        img = process_image(pid) if pid else None
    except Exception:
        img = None
    return f"{os.path.basename(img) if img else 'a program'} (pid {pid})"


def _audit(name, p, conn):
    """Calls that lower protection or change Windows networking go into the log with the calling program."""
    if name == "settings":
        if p.get("key") in params.PROTECTION_KEYS and p.get("value") is False:
            log(f"{p['key']} turned off from {_who(conn)}", "info")
    elif name in params.SENSITIVE:
        log(f"{name} requested by {_who(conn)}", "info")


def build(handlers, state, events=None, on_visible=None, launch_ui=None, about=None):
    """name -> fn(params, conn) for every method in params.SPEC.

    `handlers`: name -> fn(body) (api.HANDLERS); `state`: fn() -> the state dict; `events`: events.Events;
    `on_visible(bool)`: whether any UI window is on screen now (logbus.set_ui_visible), or None (the WebView owns
    that); `launch_ui(window)` -> bool: start the UI program for a window no client serves; `about()` -> {app,
    version, pid}."""
    out = {}

    def bridged(name, fn):
        def call(p, conn=None):
            checked = params.validate(name, p)
            _audit(name, checked, conn)
            return shape(fn(checked))
        return call

    for name in params.SPEC:
        if name in PIPE_ONLY:
            continue
        fn = handlers.get(name)
        if fn is None:
            raise RuntimeError(f"params.SPEC lists '{name}' but no handler serves it")
        out[name] = bridged(name, fn)

    def hello(p, conn=None):
        params.validate("hello", p)
        a = about() if about else {}
        return dict({"protocol": PROTOCOL}, **a, events=sorted(EVENTS), methods=sorted(params.SPEC))

    def subscribe(p, conn=None):
        names = params.validate("subscribe", p)["events"]
        if events is None or conn is None:
            return {"events": []}
        return {"events": events.subscribe(conn, names)}

    def unsubscribe(p, conn=None):
        names = params.validate("unsubscribe", p)["events"]
        if events is None or conn is None:
            return {"events": []}
        return {"events": events.unsubscribe(conn, names)}

    def state_(p, conn=None):
        params.validate("state", p)
        s = state()
        if not isinstance(s, dict):
            raise RpcError(-32603, "Internal error")
        return s

    def _visible():
        if on_visible is None or events is None:
            return
        on_visible(any(c.shown for c in events._clients()))

    def ui_shown(p, conn=None):
        w = params.validate("ui_shown", p)["window"]
        if conn is not None:
            if not getattr(conn, "alive", True):
                return {"ok": False, "error": "gone"}
            conn.shown.add(w)
            conn.serves.add(w)
        _visible()
        return {"ok": True}

    def ui_hidden(p, conn=None):
        w = params.validate("ui_hidden", p)["window"]
        if conn is not None:
            conn.shown.discard(w)
            conn.serves.add(w)
        _visible()
        return {"ok": True}

    def ui_show(p, conn=None):
        """Show a window: the UI that serves it gets a `show` event; with none, the engine may start the UI.
        `shown` false and `launched` false: the caller (a UI process) should start it itself."""
        w = params.validate("ui_show", p)["window"]
        if events is not None and any(w in c.serves and c.alive for c in events._clients()):
            events.show(w)
            return {"ok": True, "shown": True, "launched": False}
        launched = bool(launch_ui and launch_ui(w))
        return {"ok": True, "shown": False, "launched": launched}

    out.update(hello=hello, subscribe=subscribe, unsubscribe=unsubscribe, state=state_, ui_shown=ui_shown,
               ui_hidden=ui_hidden, ui_show=ui_show)
    missing = set(params.SPEC) - set(out)
    if missing:
        raise RuntimeError(f"no method for {sorted(missing)}")
    return out


def engine_handlers():
    """The WebView UI's handlers, all of them (only the ones in params.SPEC are reachable from the pipe)."""
    from .. import api
    return api.HANDLERS
