from __future__ import annotations

from typing import Any

from app_web.api import fail, from_result, handler, ok
from app_web.context import AppContext
from app_web.files import FileError
from core.exceptions import RemoteFileManagerError


def _call(fn):  # type: ignore[no-untyped-def]
    try:
        return fn()
    except (FileError, RemoteFileManagerError, OSError) as exc:
        return fail(str(exc))


@handler("xfer.list")
def xfer_list(_body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return ok(ctx.transfers.jobs())


@handler("xfer.plan")
def xfer_plan(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: ok({"conflicts": ctx.transfers.plan(
        ctx.session.current, str(body.get("direction")), body.get("items"), str(body.get("dest") or ""))}))


@handler("xfer.start")
def xfer_start(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    policy = body.get("policy")
    return _call(lambda: ok({"queued": ctx.transfers.start(
        ctx.session.current, str(body.get("direction")), body.get("items"), str(body.get("dest") or ""),
        policy if isinstance(policy, str) else None)}))


@handler("xfer.cancel")
def xfer_cancel(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: from_result(ctx.transfers.cancel(str(body.get("id")))))


@handler("xfer.retry")
def xfer_retry(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: from_result(ctx.transfers.retry(str(body.get("id")))))


@handler("xfer.retry_failed")
def xfer_retry_failed(_body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: from_result(ctx.transfers.retry_failed()))


@handler("xfer.clear")
def xfer_clear(_body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    ctx.transfers.clear_finished()
    return ok()
