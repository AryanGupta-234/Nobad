from __future__ import annotations

from typing import Any

from app_web import bus
from app_web.api import fail, handler, ok
from app_web.context import AppContext
from app_web.settings_store import FIELDS_BY_ID, SettingError, schema


@handler("settings.schema")
def settings_schema(_body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return ok({**schema(), "values": ctx.settings.values()})


@handler("settings.set")
def settings_set(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    field_id = body.get("id")
    if not isinstance(field_id, str) or field_id not in FIELDS_BY_ID:
        return fail("Unknown setting.")
    try:
        value = ctx.settings.set(field_id, body.get("value"))
    except SettingError as exc:
        return fail(str(exc))
    except Exception as exc:
        return fail(f"Couldn't save the setting: {exc}")
    bus.broadcast("setting_changed", {"id": field_id, "value": value})
    return ok({"id": field_id, "value": value})
