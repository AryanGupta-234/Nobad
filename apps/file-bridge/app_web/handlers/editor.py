from __future__ import annotations

from typing import Any

from app_web.api import fail, handler, ok
from app_web.context import AppContext
from app_web.files import FileError


def _call(fn):  # type: ignore[no-untyped-def]
    try:
        return ok(fn())
    except (FileError, OSError, UnicodeError) as exc:
        return fail(str(exc))


@handler("edit.list")
def edit_list(_body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return ok(ctx.editor.list())


@handler("edit.open")
def edit_open(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: ctx.editor.open(str(body.get("side")), body.get("path"), ctx.session.current))


@handler("edit.text")
def edit_text(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    """The text of an open tab, for a window that was reloaded."""
    return _call(lambda: {**ctx.editor.get(body.get("id")).summary(),
                          "text": ctx.editor._current_text(ctx.editor.get(body.get("id")))})


@handler("edit.save")
def edit_save(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: ctx.editor.save(body.get("id"), body.get("text"), force=body.get("force") is True,
                                         connection=ctx.session.current))


@handler("edit.latest")
def edit_latest(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: ctx.editor.latest(body.get("id"), ctx.session.current))


@handler("edit.reload")
def edit_reload(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: ctx.editor.reloaded(body.get("id"), ctx.session.current))


@handler("edit.close")
def edit_close(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    ctx.editor.close(body.get("id"))
    return ok()
