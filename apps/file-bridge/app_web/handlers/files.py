from __future__ import annotations

from typing import Any

from app_web import bus
from app_web.api import fail, from_result, handler, ok
from app_web.context import AppContext
from app_web.files import FileError, local_list, local_op, local_roots, remote_list, remote_op
from core.exceptions import RemoteFileManagerError


def _guard(fn):  # type: ignore[no-untyped-def]
    """Turn expected file errors into plain replies (never a 500)."""
    def wrapped(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
        try:
            return fn(body, ctx)
        except (FileError, RemoteFileManagerError, OSError) as exc:
            return fail(str(exc))
    return wrapped


@handler("fs.local.roots")
def fs_local_roots(_body: dict[str, Any], _ctx: AppContext) -> dict[str, Any]:
    return ok(local_roots())


@handler("fs.local.list")
@_guard
def fs_local_list(body: dict[str, Any], _ctx: AppContext) -> dict[str, Any]:
    return ok(local_list(body.get("path"), hidden=body.get("hidden") is True))


@handler("fs.remote.list")
@_guard
def fs_remote_list(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return ok(remote_list(ctx.session.current, body.get("path"), hidden=body.get("hidden") is True))


def _op(side: str, op: str, body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    result = local_op(op, body) if side == "local" else remote_op(ctx.session.current, op, body)
    bus.log(result.message, "ok" if result.ok else "bad", "files")
    return from_result(result)


for _side in ("local", "remote"):
    for _op_name in ("mkdir", "rename", "delete"):
        def _make(side: str = _side, op: str = _op_name):  # type: ignore[no-untyped-def]
            @handler(f"fs.{side}.{op}")
            @_guard
            def run(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
                return _op(side, op, body, ctx)
            return run
        _make()
