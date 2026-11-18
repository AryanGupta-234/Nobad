"""search, open, reveal, thumbnail: files are always named by result id, never by a path from the UI."""
from ..protocol import INVALID_PARAMS, RpcError, int_param


def methods(api, events=None):
    def search(params, conn=None):
        text = params.get("text", "")
        filters = params.get("filters") or {}
        if not isinstance(text, str) or not isinstance(filters, dict):
            raise RpcError(INVALID_PARAMS, "'text' must be a string and 'filters' an object")
        return api.search(text, filters)

    return {"search": search,
            "open": lambda params, conn=None: api.open(int_param(params)),
            "reveal": lambda params, conn=None: api.reveal(int_param(params)),
            "thumbnail": lambda params, conn=None: api.thumbnail(int_param(params))}
