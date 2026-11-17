from __future__ import annotations

from typing import Any

from app_web import tasks
from app_web.api import fail, handler, ok
from app_web.context import AppContext
from app_web.files import FileError
from app_web.sync import PREVIEW_KEY, RUN_KEY
from core.exceptions import RemoteFileManagerError


def _call(fn):  # type: ignore[no-untyped-def]
    try:
        return ok(fn())
    except (FileError, RemoteFileManagerError, OSError, UnicodeError) as exc:
        return fail(str(exc))


@handler("sync.jobs")
def sync_jobs(_body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return ok({"jobs": ctx.sync.jobs(), "busy": {"preview": tasks.is_running(PREVIEW_KEY), "run": tasks.is_running(RUN_KEY)}})


@handler("sync.save")
def sync_save(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: ctx.sync.save(body.get("job")))


@handler("sync.delete")
def sync_delete(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: ctx.sync.delete(body.get("id")))


@handler("sync.preview")
def sync_preview(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    def start() -> dict[str, Any]:
        if not ctx.sync.start_preview(body.get("job")):
            raise FileError("A preview is already being built.")
        return {"started": True}
    return _call(start)


@handler("sync.cancel")
def sync_cancel(_body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    ctx.sync.cancel_preview()
    return ok()


@handler("sync.entries")
def sync_entries(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: ctx.sync.entries(body.get("token")))


@handler("sync.compare")
def sync_compare(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: ctx.sync.compare(body.get("token"), body.get("path")))


@handler("sync.run")
def sync_run(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    def start() -> dict[str, Any]:
        if not ctx.sync.start_run(body.get("token"), body.get("decisions"), body.get("confirmed")):
            raise FileError("A sync is already running.")
        return {"started": True}
    return _call(start)
