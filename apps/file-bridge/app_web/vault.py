"""Credential vault for the web UI, on CredentialVaultService (Argon2id key, AES-GCM per value, audit log).

What this layer adds for a window:
* Secrets reach the page only for an explicit Reveal or Copy, one value at a time; the service writes every reveal
  to the audit log. Lists and details carry metadata only.
* Auto-lock: the key is dropped after ``auto_lock_minutes`` without vault use (the key only lives in memory).
* Unlock throttling: after 3 wrong master passwords, each further try must wait 2, 4, 8 … seconds (max 5 minutes).
* Editing keeps the stored secret, notes and custom fields unless new ones are given, so the page never has to
  hold a value just to save a title change.
* A password generator using ``secrets`` (cryptographically strong).
Nothing here logs a secret or a master password."""
from __future__ import annotations

import secrets
import string
import threading
import time
from typing import Any

from app_web import bus
from credentials.models import CREDENTIAL_KIND_LABELS, CredentialKind
from credentials.vault_service import CredentialVaultService

FREE_ATTEMPTS = 3
MAX_WAIT = 300
MAX_FIELD = 64 * 1024
DEFAULT_AUTO_LOCK = 10


class VaultError(ValueError):
    pass


def _text(value: Any, label: str, *, limit: int = 500, required: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise VaultError(f"{label} must be text.")
    if len(value) > limit:
        raise VaultError(f"{label} is too long.")
    if required and not value.strip():
        raise VaultError(f"{label} is required.")
    return value


def generate_password(length: int = 24, *, symbols: bool = True) -> str:
    length = max(12, min(128, int(length)))
    alphabet = string.ascii_letters + string.digits + ("!#$%&()*+,-.:;<=>?@[]^_{|}~" if symbols else "")
    while True:
        value = "".join(secrets.choice(alphabet) for _ in range(length))
        groups = [any(c.islower() for c in value), any(c.isupper() for c in value), any(c.isdigit() for c in value)]
        if symbols:
            groups.append(any(not c.isalnum() for c in value))
        if all(groups):
            return value


def _iso(value: Any) -> str | None:
    return value.isoformat() if value else None


def item_summary(item: Any) -> dict[str, Any]:
    return {
        "id": item.id, "project_id": item.project_id, "title": item.title, "kind": item.kind.value,
        "kind_label": CREDENTIAL_KIND_LABELS.get(item.kind, item.kind.value), "username": item.username,
        "url_host": item.url_host, "environment_key": item.environment_key, "tags": list(item.tags),
        "favorite": item.favorite, "has_notes": item.has_notes, "updated_at": _iso(item.updated_at),
    }


class VaultFacade:
    def __init__(self, session_factory: Any, settings: Any = None) -> None:
        self.service = CredentialVaultService(session_factory)
        self.settings = settings
        self._last_used = time.monotonic()
        self._failures = 0
        self._next_try = 0.0
        self._lock = threading.Lock()
        self._watch = threading.Thread(target=self._auto_lock_loop, name="vault-auto-lock", daemon=True)
        self._watch.start()

    # ---------------------------------------------------------------- state / locking
    def auto_lock_minutes(self) -> int:
        try:
            return int(self.settings.get("vault.auto_lock_minutes")) if self.settings else DEFAULT_AUTO_LOCK
        except Exception:
            return DEFAULT_AUTO_LOCK

    def state(self) -> dict[str, Any]:
        wait = max(0, int(round(self._next_try - time.monotonic())))
        return {"configured": self.service.is_configured(), "unlocked": self.service.is_unlocked,
                "auto_lock_minutes": self.auto_lock_minutes(), "retry_in": wait}

    def touch(self) -> None:
        self._last_used = time.monotonic()

    def require(self) -> None:
        if not self.service.is_unlocked:
            raise VaultError("The vault is locked. Unlock it with your master password.")
        self.touch()

    def lock(self, reason: str = "locked") -> None:
        was = self.service.is_unlocked
        self.service.lock()
        if was:
            bus.broadcast("vault", {**self.state(), "reason": reason})
            bus.log("Credential vault locked." if reason == "locked" else "Credential vault locked after inactivity.", "info", "vault")

    def _auto_lock_loop(self) -> None:
        while True:
            time.sleep(15)
            minutes = self.auto_lock_minutes()
            if minutes > 0 and self.service.is_unlocked and time.monotonic() - self._last_used > minutes * 60:
                self.lock("idle")

    def create(self, password: Any, confirm: Any) -> None:
        password = _text(password, "Master password", limit=1024)
        if password != confirm:
            raise VaultError("The two passwords don't match.")
        if len(password) < 12:
            raise VaultError("Use at least 12 characters. A few random words work well.")
        result = self.service.create_vault(password)
        if not result.ok:
            raise VaultError(result.message)
        self.touch()
        bus.log("Credential vault created.", "ok", "vault")
        bus.broadcast("vault", self.state())

    def unlock(self, password: Any) -> None:
        with self._lock:
            wait = self._next_try - time.monotonic()
            if wait > 0:
                raise VaultError(f"Too many wrong passwords. Try again in {int(wait) + 1} s.")
            result = self.service.unlock(_text(password, "Master password", limit=1024))
            if not result.ok:
                self._failures += 1
                if self._failures >= FREE_ATTEMPTS:
                    self._next_try = time.monotonic() + min(MAX_WAIT, 2 ** (self._failures - FREE_ATTEMPTS + 1))
                bus.log("Wrong master password for the credential vault.", "warn", "vault")
                raise VaultError(result.message)
            self._failures = 0
            self._next_try = 0.0
        self.touch()
        bus.broadcast("vault", self.state())

    def change_password(self, old: Any, new: Any, confirm: Any) -> None:
        self.require()
        new = _text(new, "New master password", limit=1024)
        if new != confirm:
            raise VaultError("The two new passwords don't match.")
        if len(new) < 12:
            raise VaultError("Use at least 12 characters.")
        result = self.service.change_master_password(_text(old, "Current master password", limit=1024), new)
        if not result.ok:
            raise VaultError(result.message)
        bus.log("Credential vault master password changed.", "ok", "vault")

    # ---------------------------------------------------------------- projects and items
    def projects(self) -> list[dict[str, Any]]:
        self.require()
        counts: dict[str, int] = {}
        for item in self.service.list_items():
            counts[item.project_id] = counts.get(item.project_id, 0) + 1
        return [{"id": p.id, "name": p.name, "description": p.description, "count": counts.get(p.id, 0)}
                for p in self.service.list_projects()]

    def create_project(self, name: Any) -> dict[str, Any]:
        self.require()
        result = self.service.create_project(_text(name, "Project name", limit=120, required=True))
        if not result.ok:
            raise VaultError(result.message)
        return {"id": result.data.id, "name": result.data.name}

    def delete_project(self, project_id: Any) -> None:
        self.require()
        result = self.service.delete_project(str(project_id))
        if not result.ok:
            raise VaultError(result.message)

    def items(self, project_id: Any = None, query: Any = "") -> list[dict[str, Any]]:
        self.require()
        q = _text(query, "Search", limit=200).strip()
        found = self.service.list_items(str(project_id) if project_id else None, query=q)
        return [item_summary(i) for i in sorted(found, key=lambda i: (not i.favorite, i.title.lower()))]

    def item(self, item_id: Any) -> dict[str, Any]:
        self.require()
        found = self._find(item_id)
        return {**item_summary(found), "custom_fields": [f.name for f in self.service.list_custom_fields(found.id)]}

    def _find(self, item_id: Any) -> Any:
        found = next((i for i in self.service.list_items() if i.id == item_id), None) if isinstance(item_id, str) else None
        if found is None:
            raise VaultError("That credential no longer exists.")
        return found

    def save_item(self, body: dict[str, Any]) -> dict[str, Any]:
        self.require()
        kind_value = body.get("kind") or "other"
        try:
            kind = CredentialKind(kind_value)
        except ValueError as exc:
            raise VaultError("Choose a type from the list.") from exc
        fields = body.get("custom_fields")
        if fields is not None and (not isinstance(fields, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in fields.items())):
            raise VaultError("Custom fields must be name and value pairs.")
        meta = {
            "title": _text(body.get("title"), "Title", limit=200, required=True).strip(),
            "username": _text(body.get("username"), "Username", limit=500).strip(),
            "url_host": _text(body.get("url_host"), "URL or host", limit=2000).strip(),
            "environment_key": _text(body.get("environment_key"), "Variable name", limit=200).strip(),
        }
        secret = body.get("secret")
        notes = body.get("notes")
        if secret is not None:
            _text(secret, "Secret", limit=MAX_FIELD)
        if notes is not None:
            _text(notes, "Notes", limit=MAX_FIELD)
        item_id = body.get("id")
        if not item_id:
            project_id = body.get("project_id")
            if not isinstance(project_id, str) or not project_id:
                raise VaultError("Choose a project first.")
            result = self.service.add_item(project_id=project_id, kind=kind, secret_value=secret or "", notes=notes or "",
                                           custom_fields=fields or {}, favorite=bool(body.get("favorite")), **meta)
        else:
            existing = self._find(item_id)
            # keep what wasn't changed (reads are internal; they are not sent to the page)
            if secret is None:
                secret = self._reveal_quietly(existing.id, "value")
            if notes is None:
                notes = self._reveal_quietly(existing.id, "notes") if existing.has_notes else ""
            if fields is None:
                revealed = self.service.reveal_custom_fields(existing.id)
                fields = revealed.data if revealed.ok else {}
            existing.title, existing.kind = meta["title"], kind
            existing.username, existing.url_host, existing.environment_key = meta["username"], meta["url_host"], meta["environment_key"]
            existing.favorite = bool(body.get("favorite", existing.favorite))
            result = self.service.update_item(existing, secret_value=secret, notes=notes, custom_fields=fields)
        if not result.ok:
            raise VaultError(result.message)
        return item_summary(result.data)

    def _reveal_quietly(self, item_id: str, what: str) -> str:
        result = self.service.reveal_notes(item_id) if what == "notes" else self.service.reveal_secret(item_id, action="kept_on_edit")
        if not result.ok:
            raise VaultError(result.message)
        return result.data

    def delete_item(self, item_id: Any) -> None:
        self.require()
        result = self.service.delete_item(self._find(item_id).id)
        if not result.ok:
            raise VaultError(result.message)

    def reveal(self, item_id: Any, what: Any) -> Any:
        """One value for an explicit Reveal or Copy; the service records it in the audit log."""
        self.require()
        found = self._find(item_id)
        if what == "value":
            result = self.service.reveal_secret(found.id, action="revealed")
        elif what == "copied":
            result = self.service.reveal_secret(found.id, action="copied")
        elif what == "notes":
            result = self.service.reveal_notes(found.id)
        elif what == "fields":
            result = self.service.reveal_custom_fields(found.id)
        else:
            raise VaultError("Unknown value.")
        if not result.ok:
            raise VaultError(result.message)
        return result.data

    def audit(self, limit: int = 100) -> list[dict[str, Any]]:
        self.require()
        return [{"action": e.action, "message": e.message, "at": _iso(e.created_at)}
                for e in self.service.audit_events(limit=max(1, min(500, int(limit))))]
