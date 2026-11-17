"""``POST /api/<name>`` handlers. Every reply is ``{"ok": bool, "error"?: str, "data"?: ...}``.

Handlers register themselves with ``@handler("name")`` in the ``app_web.handlers`` modules. They receive the
request body (always a dict) and the shared ``AppContext``. Long work goes through ``tasks.run_task`` and reports
back on the event bus, so a handler always answers quickly."""
from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from app_web.bus import scrub
from core.result import OperationResult

Handler = Callable[[dict[str, Any], "Any"], dict[str, Any]]
HANDLERS: dict[str, Handler] = {}
_NAME = re.compile(r"^[a-z][a-z0-9_.]{0,63}$")


def handler(name: str) -> Callable[[Handler], Handler]:
    if not _NAME.match(name):
        raise ValueError(f"Bad API name: {name}")

    def register(fn: Handler) -> Handler:
        if name in HANDLERS:
            raise ValueError(f"API name registered twice: {name}")
        HANDLERS[name] = fn
        return fn

    return register


def ok(data: Any = None, **extra: Any) -> dict[str, Any]:
    reply: dict[str, Any] = {"ok": True}
    if data is not None:
        reply["data"] = data
    reply.update(extra)
    return reply


def fail(message: str, **extra: Any) -> dict[str, Any]:
    return {"ok": False, "error": scrub(message), **extra}


def from_result(result: OperationResult, data: Any = None) -> dict[str, Any]:
    """Map a backend ``OperationResult`` onto an API reply (messages are scrubbed; technical details stay out)."""
    if result.ok:
        reply = ok(data if data is not None else None, message=scrub(result.message))
    else:
        reply = fail(result.message)
        if result.suggested_fix:
            reply["fix"] = scrub(result.suggested_fix)
    if result.warnings:
        reply["warnings"] = [scrub(w) for w in result.warnings]
    return reply


def api_post(name: str, body: dict[str, Any], ctx: Any) -> dict[str, Any]:
    fn = HANDLERS.get(name)
    if fn is None:
        return fail("Unknown action.")
    if not isinstance(body, dict):
        body = {}
    return fn(body, ctx)
