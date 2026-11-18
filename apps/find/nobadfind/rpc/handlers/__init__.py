"""Thin RPC handlers: check the shape of the parameters, call the existing Api method, return its result.

Every check the WebView page gets still happens inside the Api methods; there is no second copy of the logic.
"""
from . import search, status, system


def methods(api, events=None):
    """name -> fn(params, conn) for the prototype's methods (ROADMAP Phase 3 step 1)."""
    out = {}
    for mod in (system, search, status):
        out.update(mod.methods(api, events))
    return out
