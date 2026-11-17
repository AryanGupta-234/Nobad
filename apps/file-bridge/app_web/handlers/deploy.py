from __future__ import annotations

from typing import Any

from app_web import tasks
from app_web.api import fail, handler, ok
from app_web.context import AppContext
from app_web.deploy import PREVIEW_KEY, RUN_KEY, SCAN_KEY
from app_web.files import FileError
from core.exceptions import RemoteFileManagerError


def _call(fn):  # type: ignore[no-untyped-def]
    try:
        return ok(fn())
    except (FileError, RemoteFileManagerError, OSError, UnicodeError) as exc:
        return fail(str(exc))


def _started(started: bool) -> dict[str, Any]:
    if not started:
        raise FileError("A deployment task is already running.")
    return {"started": True}


@handler("deploy.jobs")
def deploy_jobs(_body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return ok({"jobs": ctx.deploy.jobs(), "templates": ctx.deploy.templates(),
               "busy": {k: tasks.is_running(k) for k in (PREVIEW_KEY, RUN_KEY, SCAN_KEY)}})


@handler("deploy.save")
def deploy_save(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: ctx.deploy.save(body.get("job")))


@handler("deploy.delete")
def deploy_delete(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: ctx.deploy.delete(body.get("id")))


@handler("deploy.preview")
def deploy_preview(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: _started(ctx.deploy.start_preview(body.get("job"))))


@handler("deploy.entries")
def deploy_entries(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: ctx.deploy.entries(body.get("token")))


@handler("deploy.run")
def deploy_run(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: _started(ctx.deploy.start_run(body.get("token"), body.get("confirmed"), body.get("break_stale_lock"))))


@handler("deploy.cancel")
def deploy_cancel(_body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    ctx.deploy.cancel()
    return ok()


@handler("deploy.history")
def deploy_history(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: ctx.deploy.history_of(body.get("id")))


@handler("deploy.stages")
def deploy_stages(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: ctx.deploy.stages(body.get("run")))


@handler("deploy.scan")
def deploy_scan(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: _started(ctx.deploy.start_scan(body.get("id"))))


@handler("deploy.rollback")
def deploy_rollback(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: _started(ctx.deploy.start_rollback(body.get("id"), body.get("artifact"), body.get("confirmed"),
                                                            body.get("break_stale_lock"))))
