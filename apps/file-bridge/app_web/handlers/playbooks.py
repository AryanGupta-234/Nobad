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


@handler("pb.list")
def pb_list(_body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(ctx.playbooks.list)


@handler("pb.save")
def pb_save(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: ctx.playbooks.save(body.get("recipe")))


@handler("pb.delete")
def pb_delete(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: ctx.playbooks.delete(body.get("id")))


@handler("pb.favorite")
def pb_favorite(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: {"favorite": ctx.playbooks.favorite(body.get("id"))})


@handler("pb.render")
def pb_render(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    """The exact script a run would send, for the review step."""
    return _call(lambda: {"script": ctx.playbooks.render(body.get("id"), body.get("values"))})


@handler("pb.run")
def pb_run(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    def start() -> dict[str, Any]:
        if not ctx.playbooks.start(body.get("id"), body.get("values"), body.get("sudo"), body.get("password"), body.get("confirmed")):
            raise FileError("A playbook is already running.")
        return {"started": True}
    return _call(start)


@handler("pb.cancel")
def pb_cancel(_body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    ctx.playbooks.cancel()
    return ok()


@handler("pb.history")
def pb_history(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: ctx.playbooks.history(body.get("id")))
