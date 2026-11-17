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
