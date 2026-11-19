"""search, open, reveal, thumbnail, here_folder, path_of, forget, to_main.

Files are always named by result id, never by a path from the UI: the path comes from the index (Api._path)."""
from ...search import FILTER_DAYS, FILTER_KINDS, FILTER_SIZES, SORTS
from ..protocol import INVALID_PARAMS, RpcError, int_param, ok, str_param

MAX_TEXT = 2000                     # characters of typed text (search keeps the first 500)
FILTERS = {"kind": {""} | FILTER_KINDS, "modified": {""} | set(FILTER_DAYS), "size": {""} | set(FILTER_SIZES),
           "sort": set(SORTS), "folder": None}                 # None: any string up to MAX_TEXT


def _text(params, key):
    v = str_param(params, key, "")
    if len(v) > MAX_TEXT:
        raise RpcError(INVALID_PARAMS, f"'{key}' is longer than {MAX_TEXT} characters")
    return v


def _filters(params):
    """The filter bar: an object (left out = none) whose values are the schema's words."""
    f = params.get("filters", {})
    if not isinstance(f, dict):
        raise RpcError(INVALID_PARAMS, "'filters' must be an object")
    for k, v in f.items():
        if k not in FILTERS or not isinstance(v, str) or len(v) > MAX_TEXT:
            raise RpcError(INVALID_PARAMS, f"'filters' takes only {', '.join(FILTERS)}, each a string")
        if FILTERS[k] is not None and v not in FILTERS[k]:
            words = ", ".join(w for w in sorted(FILTERS[k]) if w)
            raise RpcError(INVALID_PARAMS, f"'filters.{k}' must be \"\" (no filter) or one of {words}")
    return f


def _search_result(r):
    """Every search answer in one shape, also the empty and the failed ones (contract: search result)."""
    r = r if isinstance(r, dict) else {}
    return {"results": list(r.get("results") or []), "understood": list(r.get("understood") or []),
            "terms": list(r.get("terms") or []), "notes": list(r.get("notes") or []),
            "more": bool(r.get("more")), "ms": int(r.get("ms") or 0), "error": str(r.get("error") or "")}


def _path(r):
    return {"path": str((r or {}).get("path") or "")}


def methods(api, events=None):
    def search(params, conn=None):
        text = _text(params, "text")
        return _search_result(api.search(text, _filters(params)))

    def thumbnail(params, conn=None):
        return {"url": str((api.thumbnail(int_param(params)) or {}).get("url") or "")}

    def to_main(params, conn=None):
        """The quick find bar's Alt+Enter: the main window comes up with the same words typed in."""
        text = _text(params, "text")
        if events is not None:
            events.show("main", text)
        return {"ok": True}

    return {"search": search,
            "open": lambda params, conn=None: ok(api.open(int_param(params))),
            "reveal": lambda params, conn=None: ok(api.reveal(int_param(params))),
            "thumbnail": thumbnail,
            "here_folder": lambda params, conn=None: _path(api.here_folder()),
            "path_of": lambda params, conn=None: _path(api.path_of(int_param(params))),
            "forget": lambda params, conn=None: ok(api.forget(int_param(params))),
            "to_main": to_main}
