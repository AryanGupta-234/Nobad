from __future__ import annotations

from typing import Any

from app_web.api import fail, handler, ok
from app_web.context import AppContext
from app_web.files import FileError
from core.exceptions import RemoteFileManagerError


def _call(fn):  # type: ignore[no-untyped-def]
    try:
        return ok(fn())
    except (FileError, RemoteFileManagerError, OSError, UnicodeError) as exc:
        return fail(str(exc))


@handler("health.watch")
def health_watch(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    """Start (or keep) sampling; the page repeats this while the screen is open."""
    return _call(lambda: ctx.health.watch(body.get("on"), body.get("interval")))


@handler("health.kill")
def health_kill(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: {"message": ctx.health.kill(body.get("pid"), body.get("force"))})


@handler("health.scan")
def health_scan(_body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    def start() -> dict[str, Any]:
        if not ctx.health.start_scan():
            raise FileError("Already measuring folders.")
        return {"started": True}
    return _call(start)


@handler("svc.list")
def svc_list(_body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(ctx.services.inventory)


@handler("svc.details")
def svc_details(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: ctx.services.details(body.get("name"), body.get("lines", 80), body.get("errors_only")))


@handler("svc.action")
def svc_action(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: {"message": ctx.services.action(body.get("name"), body.get("action"))})


@handler("svc.reload")
def svc_reload(_body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: {"message": ctx.services.reload()})


@handler("svc.install")
def svc_install(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: {"message": ctx.services.install(body.get("name"), body.get("content"), body.get("start"))})
