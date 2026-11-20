"""hello, subscribe, unsubscribe, the window reports (ui_shown, ui_hidden), Windows Search, quit."""
import os
import threading

from ...const import APP_NAME, APP_VER
from ..events import EVENTS
from ..protocol import PROTOCOL, bool_param, choice_param, names_param, ok, str_param

WINDOWS = ("main", "bar")
QUIT_WORD = "QUIT"
_asking = threading.Lock()          # one Windows Search permission prompt at a time
BUSY = "Windows is already asking for permission. Answer that window first."


def _wsearch(r, saved):
    """Windows Search's state in one shape: {missing, start, running, saved}."""
    r = r if isinstance(r, dict) else {}
    missing = bool(r.get("missing"))
    return {"missing": missing, "start": "" if missing else str(r.get("start") or ""),
            "running": False if missing else bool(r.get("running")), "saved": str(saved or "")}


def about():
    return {"app": APP_NAME, "version": APP_VER, "pid": os.getpid()}


def hello(method_names, about=about):
    def fn(params, conn=None):
        return dict({"protocol": PROTOCOL}, **about(), events=sorted(EVENTS), methods=list(method_names))
    return fn


def methods(api, events=None):
    def subscribe(params, conn=None):
        names = names_param(params)
        if events is None or conn is None:
            return {"events": []}
        return {"events": events.subscribe(conn, names)}

    def unsubscribe(params, conn=None):
        names = names_param(params)
        if events is None or conn is None:
            return {"events": []}
        return {"events": events.unsubscribe(conn, names)}

    def ui_shown(params, conn=None):
        window = choice_param(params, "window", WINDOWS, "main")
        if events is not None:
            events.shown(conn, window, api.ui_shown)       # nothing if this client's pipe already closed
        elif window == "main":
            api.ui_shown()
        return {"ok": True}

    def ui_hidden(params, conn=None):
        """The main window was hidden or closed: what that means for indexing is lifecycle.after_hide's call.
        Another UI still showing its main window (two UIs at once) keeps indexing as it is."""
        window = choice_param(params, "window", WINDOWS, "main")
        if events is not None:
            events.hidden(conn, window, api.hide)
        elif window == "main":
            api.hide()
        hook = getattr(api, "_on_all_closed", None)      # the engine checks whether anything is still open
        if hook is not None:
            hook()
        return {"ok": True}

    def wsearch_state(params, conn=None):
        r = api.wsearch_state() or {}
        return _wsearch(r, r.get("saved"))

    def wsearch_change(name, key):
        def call(params, conn=None):
            value = bool_param(params, key)
            if not _asking.acquire(blocking=False):
                return {"ok": False, "error": BUSY, "state": _wsearch(api.wsearch_state(), None)}
            try:
                r = getattr(api, name)(value) or {}
            finally:
                _asking.release()
            out = ok(r)
            out["state"] = _wsearch(r.get("state") if isinstance(r.get("state"), dict) else {"missing": True},
                                    api.get_settings().get("wsearch_prev"))
            return out
        return call

    def quit_(params, conn=None):
        if str_param(params, "confirm") != QUIT_WORD:
            return {"ok": False, "error": f"Send confirm \"{QUIT_WORD}\" to quit NOBAD Find."}
        return ok(api.quit())

    return {"subscribe": subscribe, "unsubscribe": unsubscribe, "ui_shown": ui_shown, "ui_hidden": ui_hidden,
            "wsearch_state": wsearch_state,
            "wsearch_set": wsearch_change("wsearch_set", "off"),
            "use_instead_of_windows_search": wsearch_change("use_instead_of_windows_search", "on"),
            "quit": quit_}
