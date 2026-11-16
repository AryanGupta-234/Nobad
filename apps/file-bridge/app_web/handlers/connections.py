from __future__ import annotations

from dataclasses import asdict
from typing import Any

from app_web.api import fail, from_result, handler, ok
from app_web.context import AppContext
from app_web.session import ProfileError, build_profile
from core.connections.connection_string import parse_connection_target
from core.connections.profile import AuthType


def _secret(body: dict[str, Any]) -> str | None:
    value = body.get("secret")
    if value is None or value == "":
        return None
    if not isinstance(value, str) or len(value) > 4096:
        raise ProfileError("The password or passphrase is too long.")
    return value


@handler("conn.state")
def conn_state(_body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return ok(ctx.session.state())


@handler("conn.profiles")
def conn_profiles(_body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return ok(ctx.session.profiles())


@handler("conn.parse")
def conn_parse(body: dict[str, Any], _ctx: AppContext) -> dict[str, Any]:
    """Fill the form from a pasted "ssh -p 2222 user@host", "sftp://user@host:22/path" or "user@host"."""
    text = body.get("text")
    target = parse_connection_target(text) if isinstance(text, str) and len(text) < 2048 else None
    if target is None:
        return fail("That doesn't look like a server address.")
    return ok({k: v for k, v in asdict(target).items() if v not in (None, "")})


@handler("conn.connect")
def conn_connect(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    """Connect with a new profile from the form. Optionally save it (and remember the secret in the keyring)."""
    try:
        profile = build_profile(body.get("profile") or {})
        secret = _secret(body)
    except ProfileError as exc:
        return fail(str(exc))
    if profile.auth_type == AuthType.PASSWORD and secret is None:
        return fail("Enter the password.")
    password = secret if profile.auth_type == AuthType.PASSWORD else None
    passphrase = secret if profile.auth_type == AuthType.SSH_KEY else None
    started = ctx.session.start_connect(
        profile, password=password, passphrase=passphrase, save=bool(body.get("save")),
        remember=bool(body.get("remember")), secret=secret,
    )
    return ok({"started": True}) if started else fail("Already connecting. Wait for it to finish.")


@handler("conn.connect_saved")
def conn_connect_saved(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    profile_id = body.get("id")
    profile = ctx.session.find_profile(profile_id) if isinstance(profile_id, str) else None
    if profile is None:
        return fail("That saved connection no longer exists.")
    try:
        password, passphrase, needed = ctx.session.saved_credentials(profile, _secret(body))
    except ProfileError as exc:
        return fail(str(exc))
    if needed:
        return ok({"needs": needed})
    started = ctx.session.start_connect(profile, password=password, passphrase=passphrase)
    return ok({"started": True}) if started else fail("Already connecting. Wait for it to finish.")


@handler("conn.trust")
def conn_trust(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    token = body.get("token")
    if not isinstance(token, str):
        return fail("This host key question has expired. Connect again.")
    return from_result(ctx.session.trust(token, body.get("accept") is True))


@handler("conn.disconnect")
def conn_disconnect(_body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    return ok({"disconnecting": ctx.session.disconnect()})


@handler("conn.delete")
def conn_delete(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    profile_id = body.get("id")
    if not isinstance(profile_id, str) or ctx.session.find_profile(profile_id) is None:
        return fail("That saved connection no longer exists.")
    current = ctx.session.current
    if current is not None and current.profile.id == profile_id:
        return fail("Disconnect before deleting this connection.")
    return from_result(ctx.session.saved.delete_profile(profile_id))


@handler("conn.rename")
def conn_rename(body: dict[str, Any], ctx: AppContext) -> dict[str, Any]:
    profile_id, name = body.get("id"), body.get("name")
    if not isinstance(profile_id, str) or not isinstance(name, str) or len(name) > 120:
        return fail("Enter a name of up to 120 characters.")
    return from_result(ctx.session.saved.rename_profile(profile_id, name))
