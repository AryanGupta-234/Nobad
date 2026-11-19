"""search, open, reveal, thumbnail, here_folder, path_of, forget, to_main.

Files are always named by result id, never by a path from the UI: the path comes from the index (Api._path)."""
from ..protocol import INVALID_PARAMS, RpcError, int_param, ok, str_param

FILTER_KEYS = ("kind", "modified", "size", "folder", "sort")


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
        text = params.get("text", "")
        filters = params.get("filters") or {}
        if not isinstance(text, str) or not isinstance(filters, dict):
            raise RpcError(INVALID_PARAMS, "'text' must be a string and 'filters' an object")
        if not all(k in FILTER_KEYS and isinstance(v, str) for k, v in filters.items()):
            raise RpcError(INVALID_PARAMS, f"'filters' takes only {', '.join(FILTER_KEYS)}, each a string")
        return _search_result(api.search(text, filters))

    def thumbnail(params, conn=None):
        return {"url": str((api.thumbnail(int_param(params)) or {}).get("url") or "")}

    def to_main(params, conn=None):
        """The quick find bar's Alt+Enter: the main window comes up with the same words typed in."""
        text = str_param(params, "text", "")
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
