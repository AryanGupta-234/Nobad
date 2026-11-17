from __future__ import annotations

from typing import Any

from app_web.api import fail, handler, ok
from app_web.context import AppContext
from app_web.files import FileError


def _call(fn):  # type: ignore[no-untyped-def]
    try:
        return fn()
    except FileError as exc:
        return fail(str(exc))


@handler("term.list")
def term_list(_body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return ok(ctx.terminals.list())


@handler("term.history")
def term_history(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    """What the terminal showed so far, for a window that was reloaded."""
    return _call(lambda: ok({"data": ctx.terminals.get(body.get("id")).history()}))


@handler("term.open")
def term_open(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    kind = body.get("kind")
    if kind not in {"remote", "local"}:
        kind = "remote" if ctx.settings.get("terminal.default_new_target") == "active_remote" and ctx.session.current else "local"
    cwd = body.get("cwd") if isinstance(body.get("cwd"), str) and len(body.get("cwd")) < 4096 else None
    shell = ctx.settings.get("terminal.local_shell_path") or None
    return _call(lambda: ok(ctx.terminals.open(
        kind, connection=ctx.session.current, cwd=cwd, shell=shell, cols=body.get("cols", 100), rows=body.get("rows", 30))))


@handler("term.input")
def term_input(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: (ctx.terminals.write(body.get("id"), body.get("data")), ok())[1])


@handler("term.resize")
def term_resize(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: (ctx.terminals.resize(body.get("id"), body.get("cols"), body.get("rows")), ok())[1])


@handler("term.close")
def term_close(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    ctx.terminals.close(body.get("id"))
    return ok()
