from __future__ import annotations

import platform
from typing import Any

from app_web import bus
from app_web.api import handler, ok
from app_web.context import APP_NAME, AppContext


@handler("app.info")
def app_info(_body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return ok({
        "name": APP_NAME,
        "version": ctx.version,
        "platform": platform.system(),
        "storage_warning": getattr(ctx.app_data, "storage_warning", None),  # set by #31 (PR #35)
        "window": ctx.window.state() if ctx.window is not None else {"frameless": False, "maximized": False},
    })


@handler("log.recent")
def log_recent(_body: dict[str, Any], _ctx: AppContext) -> dict[str, Any]:
    return ok(bus.recent_log())


@handler("log.clear")
def log_clear(_body: dict[str, Any], _ctx: AppContext) -> dict[str, Any]:
    bus.clear_log()
    bus.broadcast("log_cleared", {})
    return ok()
