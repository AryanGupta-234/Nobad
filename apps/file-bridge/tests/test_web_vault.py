"""Credential vault in the web UI: create/unlock rules, throttling, reveal-only access, edits that keep secrets,
audit of every reveal, auto-lock, and no secret ever in a list reply or the activity log."""
from __future__ import annotations

import json
import string
import time
from pathlib import Path

import pytest

from app_web import bus
from app_web.api import api_post
from app_web.context import AppContext
from app_web.handlers import register_all
from app_web.vault import generate_password

register_all()
MASTER = "correct horse battery staple"
SECRET = "sk_live_9f8e7d6c5b4a"


@pytest.fixture
def ctx(tmp_path: Path) -> AppContext:
    return AppContext.create(tmp_path / "app.sqlite3")


def call(ctx: AppContext, api_name: str, **body):  # type: ignore[no-untyped-def]
    reply = api_post(api_name, body, ctx)
    assert reply["ok"], reply
    return reply.get("data")


def _vault_with_item(ctx: AppContext) -> tuple[str, str]:
    call(ctx, "vault.create", password=MASTER, confirm=MASTER)
    project = call(ctx, "vault.project.create", name="example.com")
    item = call(ctx, "vault.item.save", project_id=project["id"], kind="api_key", title="Stripe live key",
                username="billing@example.com", url_host="api.stripe.com", secret=SECRET, notes="rotate yearly")
    return project["id"], item["id"]


@pytest.mark.parametrize(("password", "confirm", "error"), [
    ("short", "short", "12 characters"),
    (MASTER, MASTER + "x", "don't match"),
])
def test_create_needs_a_long_matching_password(ctx, password: str, confirm: str, error: str) -> None:
    reply = api_post("vault.create", {"password": password, "confirm": confirm}, ctx)
    assert not reply["ok"] and error in reply["error"]
    assert call(ctx, "vault.state")["configured"] is False


def test_lists_and_details_never_carry_the_secret(ctx) -> None:
    project_id, item_id = _vault_with_item(ctx)
    listing = json.dumps(call(ctx, "vault.items", project_id=project_id))
    detail = json.dumps(call(ctx, "vault.item", id=item_id))
    projects = json.dumps(call(ctx, "vault.projects"))
    for blob in (listing, detail, projects):
        assert SECRET not in blob and "rotate yearly" not in blob
    assert call(ctx, "vault.reveal", id=item_id, what="value")["value"] == SECRET
    assert call(ctx, "vault.reveal", id=item_id, what="notes")["value"] == "rotate yearly"


def test_every_reveal_and_copy_is_audited(ctx) -> None:
    _project_id, item_id = _vault_with_item(ctx)
    call(ctx, "vault.reveal", id=item_id, what="value")
    call(ctx, "vault.reveal", id=item_id, what="copied")
    actions = [e["action"] for e in call(ctx, "vault.audit", limit=20)]
    assert "revealed" in actions and "copied" in actions and "created" in actions


def test_editing_the_title_keeps_the_secret_and_notes(ctx) -> None:
    project_id, item_id = _vault_with_item(ctx)
    call(ctx, "vault.item.save", id=item_id, project_id=project_id, kind="api_key", title="Stripe key (live)",
         username="billing@example.com", url_host="api.stripe.com")
    assert call(ctx, "vault.item", id=item_id)["title"] == "Stripe key (live)"
    assert call(ctx, "vault.reveal", id=item_id, what="value")["value"] == SECRET
    assert call(ctx, "vault.reveal", id=item_id, what="notes")["value"] == "rotate yearly"


def test_wrong_passwords_are_throttled(ctx) -> None:
    _vault_with_item(ctx)
    call(ctx, "vault.lock")
    for _ in range(3):
        reply = api_post("vault.unlock", {"password": "wrong"}, ctx)
        assert not reply["ok"] and "incorrect" in reply["error"]
    blocked = api_post("vault.unlock", {"password": MASTER}, ctx)            # even the right one has to wait
    assert not blocked["ok"] and "Try again in" in blocked["error"]
    assert call(ctx, "vault.state")["retry_in"] >= 1
    ctx.vault._next_try = 0                                                 # the wait is over
    assert call(ctx, "vault.unlock", password=MASTER)["unlocked"] is True


def test_locked_vault_gives_nothing(ctx) -> None:
    _project_id, item_id = _vault_with_item(ctx)
    call(ctx, "vault.lock")
    for name, body in (("vault.items", {}), ("vault.reveal", {"id": item_id, "what": "value"}), ("vault.projects", {})):
        reply = api_post(name, body, ctx)
        assert not reply["ok"] and "locked" in reply["error"]


def test_auto_lock_after_inactivity(ctx, monkeypatch: pytest.MonkeyPatch) -> None:
    _vault_with_item(ctx)
    q = bus.subscribe(200)
    try:
        monkeypatch.setattr(ctx.vault, "auto_lock_minutes", lambda: 1)
        ctx.vault._last_used = time.monotonic() - 61
        deadline = time.monotonic() + 20
        while ctx.vault.service.is_unlocked and time.monotonic() < deadline:
            time.sleep(0.2)
        assert ctx.vault.service.is_unlocked is False
        events = []
        while not q.empty():
            events.append(json.loads(q.get_nowait()))
        assert any(e["type"] == "vault" and e["payload"].get("reason") == "idle" for e in events)
    finally:
        bus.unsubscribe(q)


def test_no_secret_or_master_password_reaches_the_activity_log(ctx) -> None:
    _project_id, item_id = _vault_with_item(ctx)
    api_post("vault.unlock", {"password": "a wrong guess 123"}, ctx)
    call(ctx, "vault.reveal", id=item_id, what="value")
    log = json.dumps(bus.recent_log())
    assert SECRET not in log and MASTER not in log and "a wrong guess 123" not in log


def test_generated_passwords_are_long_and_mixed() -> None:
    for _ in range(50):
        value = generate_password(24)
        assert len(value) == 24
        assert any(c in string.ascii_lowercase for c in value) and any(c in string.ascii_uppercase for c in value)
        assert any(c.isdigit() for c in value) and any(not c.isalnum() for c in value)
    assert len(generate_password(4)) == 12                                  # never shorter than 12
    assert len({generate_password(24) for _ in range(100)}) == 100


def test_unknown_kinds_and_oversized_values_are_refused(ctx) -> None:
    project_id, _item_id = _vault_with_item(ctx)
    bad_kind = api_post("vault.item.save", {"project_id": project_id, "kind": "rocket", "title": "x", "secret": "y"}, ctx)
    too_big = api_post("vault.item.save", {"project_id": project_id, "kind": "other", "title": "x", "secret": "y" * 70_000}, ctx)
    assert not bad_kind["ok"] and not too_big["ok"]
