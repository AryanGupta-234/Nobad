from __future__ import annotations

from typing import Any

from app_web.api import fail, handler, ok
from app_web.context import AppContext
from app_web.vault import VaultError, generate_password
from credentials.models import CREDENTIAL_KIND_LABELS


def _call(fn):  # type: ignore[no-untyped-def]
    try:
        return ok(fn())
    except VaultError as exc:
        return fail(str(exc))


@handler("vault.state")
def vault_state(_body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return ok({**ctx.vault.state(), "kinds": [{"value": k.value, "label": v} for k, v in CREDENTIAL_KIND_LABELS.items()]})


@handler("vault.create")
def vault_create(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: (ctx.vault.create(body.get("password"), body.get("confirm")), ctx.vault.state())[1])


@handler("vault.unlock")
def vault_unlock(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: (ctx.vault.unlock(body.get("password")), ctx.vault.state())[1])


@handler("vault.lock")
def vault_lock(_body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    ctx.vault.lock()
    return ok(ctx.vault.state())


@handler("vault.change_password")
def vault_change_password(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: ctx.vault.change_password(body.get("old"), body.get("new"), body.get("confirm")))


@handler("vault.projects")
def vault_projects(_body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(ctx.vault.projects)


@handler("vault.project.create")
def vault_project_create(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: ctx.vault.create_project(body.get("name")))


@handler("vault.project.delete")
def vault_project_delete(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: ctx.vault.delete_project(body.get("id")))


@handler("vault.items")
def vault_items(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: ctx.vault.items(body.get("project_id"), body.get("query") or ""))


@handler("vault.item")
def vault_item(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: ctx.vault.item(body.get("id")))


@handler("vault.item.save")
def vault_item_save(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: ctx.vault.save_item(body))


@handler("vault.item.delete")
def vault_item_delete(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: ctx.vault.delete_item(body.get("id")))


@handler("vault.reveal")
def vault_reveal(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    """A single value, for an explicit Reveal or Copy (recorded in the vault's audit log)."""
    return _call(lambda: {"value": ctx.vault.reveal(body.get("id"), body.get("what"))})


@handler("vault.audit")
def vault_audit(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return _call(lambda: ctx.vault.audit(body.get("limit", 100)))


@handler("vault.generate")
def vault_generate(body: dict[str, Any], _ctx: AppContext) -> dict[str, Any]:
    try:
        return ok({"value": generate_password(int(body.get("length", 24)), symbols=body.get("symbols") is not False)})
    except (TypeError, ValueError):
        return fail("Choose a length from 12 to 128.")
