from __future__ import annotations

from typing import Any

from app_web.api import fail, handler, ok
from app_web.context import AppContext


@handler("window.action")
def window_action(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    """Title-bar buttons: minimize | maximize | close | drag | resize(edge) | state."""
    act = body.get("do")
    edge = body.get("edge")
    if ctx.window is None:                                   # --browser mode or tests: no native window
        return ok({"frameless": False, "maximized": False})
    if not isinstance(act, str) or (edge is not None and not isinstance(edge, str)):
        return fail("Unknown window action.")
    try:
        return ok(ctx.window.action(act, edge))
    except ValueError as exc:
        return fail(str(exc))


@handler("window.pick")
def window_pick(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    """Native open-file / open-folder dialog. Without a window (browser mode) the page asks for a typed path."""
    kind = body.get("kind")
    if kind not in {"file", "files", "folder"}:
        return fail("Unknown dialog.")
    if ctx.window is None:
        return ok({"paths": [], "available": False})
    start = body.get("start") if isinstance(body.get("start"), str) else None
    return ok({"paths": ctx.window.pick(kind, start), "available": True})
