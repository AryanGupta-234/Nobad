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


@handler("tunnel.list")
def tunnel_list(_body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(ctx.tunnels.list)


@handler("tunnel.save")
def tunnel_save(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: ctx.tunnels.save(body.get("tunnel")))


@handler("tunnel.delete")
def tunnel_delete(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: ctx.tunnels.delete(body.get("id")))


@handler("tunnel.start")
def tunnel_start(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: ctx.tunnels.start(body.get("id")))


@handler("tunnel.stop")
def tunnel_stop(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: ctx.tunnels.stop(body.get("id")))


@handler("tunnel.test")
def tunnel_test(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: ctx.tunnels.test(body.get("id")))


@handler("logs.list")
def logs_list(_body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(ctx.logs.list)


@handler("logs.start")
def logs_start(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: ctx.logs.start(body.get("log")))


@handler("logs.tail")
def logs_tail(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: ctx.logs.tail(body.get("id"), body.get("count", 1000)))


@handler("logs.pause")
def logs_pause(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: ctx.logs.pause(body.get("id"), body.get("paused")))


@handler("logs.stop")
def logs_stop(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: ctx.logs.stop(body.get("id"), remove=body.get("remove") is True))
