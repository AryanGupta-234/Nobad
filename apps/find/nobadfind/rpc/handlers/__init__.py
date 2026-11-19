"""Thin RPC handlers: check the shape of the parameters, call the existing Api method, shape its result.

Every check the WebView page gets still happens inside the Api methods; there is no second copy of the logic.
The shapes are contract/methods.schema.json (tests/test_rpc_contract.py holds the two together).
"""
from . import models, search, settings, status, system


def methods(api, events=None, about=system.about):
    """name -> fn(params, conn) for every method in the contract. `about` gives hello's app, version and pid."""
    out = {}
    for mod in (system, search, status, settings, models):
        out.update(mod.methods(api, events))
    out["hello"] = system.hello(sorted(set(out) | {"hello"}), about)
    return out
