from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass

from core.result import OperationResult
from credentials.bulk_text_parser import credentials_text_to_json
from credentials.crypto import (
    KdfConfig,
    b64decode,
    b64encode,
    decrypt_json,
    derive_key,
    encrypt_json,
    new_salt,
)
from credentials.env_parser import EnvEntry, format_env, parse_env
from credentials.models import CredentialItem, CredentialKind, CredentialProject
from credentials.vault_service import CredentialVaultService


@dataclass(frozen=True, slots=True)
class ImportPreview:
    creates: int
    updates: int
    conflicts: int
    entries: int


class CredentialImportExportService:
    def __init__(self, vault: CredentialVaultService) -> None:
        self.vault = vault
        self._kdf_config = KdfConfig()

    def preview_env_import(self, project_id: str, text: str) -> ImportPreview:
        entries = parse_env(text)
        existing = self._env_items_by_key(project_id)
        creates = 0
        updates = 0
        for entry in entries:
            if entry.key in existing:
                updates += 1
            else:
                creates += 1
        return ImportPreview(creates=creates, updates=updates, conflicts=updates, entries=len(entries))

    def preview_loose_text_import(self, project_id: str, text: str) -> OperationResult:
        if not self.vault.is_unlocked:
            return OperationResult.failure("Credential vault is locked.")
        items = self._payload_items_from_loose_text(text)
        existing = self._items_by_conflict_key(project_id)
        conflicts = sum(1 for payload in items if self._payload_conflict_key(payload) in existing)
        preview = ImportPreview(
            creates=len(items) - conflicts,
            updates=conflicts,
            conflicts=conflicts,
            entries=len(items),
        )
        return OperationResult.success(
            "Bulk credential import preview created.",
            data={"preview": preview, "items": items},
        )

    def import_loose_text(self, project_id: str, text: str, *, conflict_policy: str = "rename") -> OperationResult:
        if not self.vault.is_unlocked:
            return OperationResult.failure("Credential vault is locked.")
        if conflict_policy not in {"rename", "overwrite", "skip"}:
            return OperationResult.failure("Unsupported bulk import conflict policy.")
        items = self._payload_items_from_loose_text(text)
        existing = self._items_by_conflict_key(project_id)
        existing_titles = {item.title for item in self.vault.list_items(project_id)}
        created = 0
        updated = 0
        skipped = 0
        renamed = 0
        for payload in items:
            key = self._payload_conflict_key(payload)
            current = existing.get(key)
            if current is not None:
                if conflict_policy == "skip":
                    skipped += 1
                    continue
                if conflict_policy == "overwrite":
                    result = self._update_payload_item(current, payload)
                    if not result.ok:
                        return result
                    updated += 1
                    existing[key] = result.data
                    continue
                payload = dict(payload)
                env_key = str(payload.get("environment_key") or "").strip()
                if env_key:
                    alternate_key = self._alternate_payload_key(env_key, payload, existing)
                    if str(payload.get("title") or "").strip() == env_key:
                        payload["title"] = alternate_key
                    else:
                        payload["title"] = self._alternate_item_title(
                            str(payload.get("title") or "Imported Credential"),
                            existing_titles,
                        )
                    payload["environment_key"] = alternate_key
                else:
                    payload["title"] = self._alternate_item_title(str(payload.get("title") or "Imported Credential"), existing_titles)
                key = self._payload_conflict_key(payload)
                renamed += 1
            result = self._add_payload_item(project_id, payload)
            if not result.ok:
                return result
            existing[key] = result.data
            existing_titles.add(result.data.title)
            created += 1
        return OperationResult.success(
            f"Bulk imported {created + updated} credentials.",
            data={
                "created": created,
                "updated": updated,
                "skipped": skipped,
                "renamed": renamed,
                "entries": len(items),
            },
        )

    def import_env(self, project_id: str, text: str, *, conflict_policy: str = "overwrite") -> OperationResult:
        if not self.vault.is_unlocked:
            return OperationResult.failure("Credential vault is locked.")
        entries = parse_env(text)
        existing = self._env_items_by_key(project_id)
        created = 0
        updated = 0
        skipped = 0
        for entry in entries:
            current = existing.get(entry.key)
            if current is not None:
                if conflict_policy == "skip":
                    skipped += 1
                    continue
                if conflict_policy == "rename":
                    entry = EnvEntry(key=self._alternate_env_key(entry.key, existing), value=entry.value)
                    current = None
                else:
                    result = self.vault.update_item(
                        current,
                        secret_value=entry.value,
                        custom_fields={},
                    )
                    if not result.ok:
                        return result
                    updated += 1
                    continue
            result = self.vault.add_item(
                project_id=project_id,
                title=entry.key,
                kind=CredentialKind.ENV_VAR,
                secret_value=entry.value,
                environment_key=entry.key,
                tags=["env"],
            )
            if not result.ok:
                return result
            existing[entry.key] = result.data
            created += 1
        return OperationResult.success(
            f"Imported {len(entries)} .env entries.",
            data={"created": created, "updated": updated, "skipped": skipped},
        )

    def export_env(self, project_id: str) -> OperationResult:
        if not self.vault.is_unlocked:
            return OperationResult.failure("Credential vault is locked.")
        entries: list[EnvEntry] = []
        for item in self.vault.list_items(project_id):
            if item.kind != CredentialKind.ENV_VAR:
                continue
            value = self.vault.reveal_secret(item.id, action="exported_env")
            if not value.ok:
                return value
            entries.append(EnvEntry(key=item.environment_key or item.title, value=value.data))
        return OperationResult.success(".env export created.", data=format_env(entries))

    def export_encrypted(self, project_ids: list[str], export_password: str) -> OperationResult:
        if not self.vault.is_unlocked:
            return OperationResult.failure("Credential vault is locked.")
        if len(export_password) < 8:
            return OperationResult.failure("Export password must be at least 8 characters.")
        payload_projects = []
        projects = [project for project in self.vault.list_projects() if project.id in set(project_ids)]
        for project in projects:
            payload_items = []
            for item in self.vault.list_items(project.id):
                plaintext = self.vault.plaintext_item(item.id)
                if not plaintext.ok:
                    return plaintext
                payload_items.append(self._item_to_payload(plaintext.data))
            payload_projects.append(
                {
                    "id": project.id,
                    "name": project.name,
                    "description": project.description,
                    "tags": project.tags,
                    "items": payload_items,
                }
            )
        salt = new_salt()
        key = derive_key(export_password, salt, self._kdf_config)
        encrypted = encrypt_json(
            key,
            {"version": 1, "projects": payload_projects},
            aad="rfm-vault-export",
        )
        bundle = {
            "format": "rfm-vault",
            "version": 1,
            "kdf": self._kdf_config.to_dict(),
            "salt": b64encode(salt),
            "payload": encrypted,
        }
        return OperationResult.success("Encrypted vault export created.", data=json.dumps(bundle, indent=2))

    def import_encrypted(self, data: str, export_password: str, *, conflict_policy: str = "rename") -> OperationResult:
        if not self.vault.is_unlocked:
            return OperationResult.failure("Credential vault is locked.")
        try:
            bundle = json.loads(data)
            if bundle.get("format") != "rfm-vault":
                return OperationResult.failure("Unsupported credential vault export format.")
            config = KdfConfig.from_dict(bundle.get("kdf"))
            key = derive_key(export_password, b64decode(str(bundle["salt"])), config)
            payload_result = decrypt_json(key, str(bundle["payload"]), aad="rfm-vault-export")
        except (KeyError, json.JSONDecodeError, ValueError) as exc:
            return OperationResult.failure(
                "Could not read encrypted vault export.",
                technical_details=f"{type(exc).__name__}: {exc}",
            )
        if not payload_result.ok:
            return payload_result
        created_projects = 0
        created_items = 0
        existing_names = {project.name for project in self.vault.list_projects()}
        for project_payload in payload_result.data.get("projects", []):
            name = str(project_payload.get("name") or "Imported Project").strip()
            if name in existing_names:
                if conflict_policy == "skip":
                    continue
                if conflict_policy == "rename":
                    name = self._alternate_project_name(name, existing_names)
            project_result = self.vault.create_project(
                name,
                description=str(project_payload.get("description") or ""),
                tags=list(project_payload.get("tags") or []),
            )
            if not project_result.ok:
                return project_result
            created_projects += 1
            existing_names.add(project_result.data.name)
            for item_payload in project_payload.get("items", []):
                result = self._add_payload_item(project_result.data.id, item_payload)
                if not result.ok:
                    return result
                created_items += 1
        return OperationResult.success(
            "Encrypted vault import completed.",
            data={"projects": created_projects, "items": created_items},
        )

    def export_json(self, project_ids: list[str]) -> OperationResult:
        if not self.vault.is_unlocked:
            return OperationResult.failure("Credential vault is locked.")
        projects = []
        for project in self.vault.list_projects():
            if project.id not in set(project_ids):
                continue
            items = []
            for item in self.vault.list_items(project.id):
                plaintext = self.vault.plaintext_item(item.id)
                if not plaintext.ok:
                    return plaintext
                items.append(self._item_to_payload(plaintext.data))
            projects.append({"name": project.name, "description": project.description, "tags": project.tags, "items": items})
        return OperationResult.success("Credential JSON export created.", data=json.dumps({"projects": projects}, indent=2))

    def import_json(self, data: str, *, conflict_policy: str = "rename") -> OperationResult:
        try:
            payload = json.loads(data)
        except json.JSONDecodeError as exc:
            return OperationResult.failure("Could not parse credential JSON.", technical_details=str(exc))
        created = 0
        existing_names = {project.name for project in self.vault.list_projects()}
        for project_payload in payload.get("projects", []):
            name = str(project_payload.get("name") or "Imported Project")
            if name in existing_names:
                if conflict_policy == "skip":
                    continue
                name = self._alternate_project_name(name, existing_names)
            project_result = self.vault.create_project(
                name,
                description=str(project_payload.get("description") or ""),
                tags=list(project_payload.get("tags") or []),
            )
            if not project_result.ok:
                return project_result
            existing_names.add(project_result.data.name)
            for item_payload in project_payload.get("items", []):
                result = self._add_payload_item(project_result.data.id, item_payload)
                if not result.ok:
                    return result
                created += 1
        return OperationResult.success("Credential JSON import completed.", data={"items": created})

    def export_csv(self, project_id: str) -> OperationResult:
        if not self.vault.is_unlocked:
            return OperationResult.failure("Credential vault is locked.")
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=["title", "kind", "username", "url_host", "environment_key", "tags", "secret_value", "notes"],
        )
        writer.writeheader()
        for item in self.vault.list_items(project_id):
            plaintext = self.vault.plaintext_item(item.id)
            if not plaintext.ok:
                return plaintext
            data = plaintext.data
            writer.writerow(
                {
                    "title": item.title,
                    "kind": item.kind.value,
                    "username": item.username,
                    "url_host": item.url_host,
                    "environment_key": item.environment_key,
                    "tags": ",".join(item.tags),
                    "secret_value": data["secret_value"],
                    "notes": data["notes"],
                }
            )
        return OperationResult.success("Credential CSV export created.", data=output.getvalue())

    def _env_items_by_key(self, project_id: str) -> dict[str, CredentialItem]:
        existing: dict[str, CredentialItem] = {}
        for item in self.vault.list_items(project_id):
            if item.kind == CredentialKind.ENV_VAR:
                existing[item.environment_key or item.title] = item
        return existing

    def _items_by_conflict_key(self, project_id: str) -> dict[tuple[str, str], CredentialItem]:
        existing: dict[tuple[str, str], CredentialItem] = {}
        for item in self.vault.list_items(project_id):
            existing[self._item_conflict_key(item)] = item
        return existing

    def _alternate_env_key(self, key: str, existing: dict[str, CredentialItem]) -> str:
        counter = 2
        candidate = f"{key}_{counter}"
        while candidate in existing:
            counter += 1
            candidate = f"{key}_{counter}"
        return candidate

    def _alternate_project_name(self, name: str, existing_names: set[str]) -> str:
        counter = 2
        candidate = f"{name} ({counter})"
        while candidate in existing_names:
            counter += 1
            candidate = f"{name} ({counter})"
        return candidate

    def _alternate_item_title(self, title: str, existing_titles: set[str]) -> str:
        clean_title = title.strip() or "Imported Credential"
        counter = 2
        candidate = f"{clean_title} ({counter})"
        while candidate in existing_titles:
            counter += 1
            candidate = f"{clean_title} ({counter})"
        existing_titles.add(candidate)
        return candidate

    def _alternate_payload_key(self, key: str, payload: dict, existing: dict[tuple[str, str], CredentialItem]) -> str:
        kind = self._kind_from_payload(payload).value
        counter = 2
        candidate = f"{key}_{counter}"
        while (kind, candidate.lower()) in existing:
            counter += 1
            candidate = f"{key}_{counter}"
        return candidate

    def _payload_items_from_loose_text(self, text: str) -> list[dict]:
        payload = credentials_text_to_json(text)
        projects = payload.get("projects") or []
        if not projects:
            return []
        items = projects[0].get("items") or []
        return [dict(item) for item in items if isinstance(item, dict)]

    def _payload_conflict_key(self, payload: dict) -> tuple[str, str]:
        kind = self._kind_from_payload(payload).value
        primary = str(payload.get("environment_key") or payload.get("title") or "").strip().lower()
        if not primary:
            primary = str(payload.get("url_host") or payload.get("username") or "imported").strip().lower()
        return kind, primary

    def _item_conflict_key(self, item: CredentialItem) -> tuple[str, str]:
        primary = (item.environment_key or item.title or item.url_host or item.username or "imported").strip().lower()
        return item.kind.value, primary

    def _kind_from_payload(self, payload: dict) -> CredentialKind:
        try:
            return CredentialKind(str(payload.get("kind") or CredentialKind.OTHER.value))
        except ValueError:
            return CredentialKind.OTHER

    def _item_to_payload(self, data: dict) -> dict:
        item: CredentialItem = data["item"]
        return {
            "title": item.title,
            "kind": item.kind.value,
            "username": item.username,
            "url_host": item.url_host,
            "environment_key": item.environment_key,
            "tags": item.tags,
            "favorite": item.favorite,
            "secret_value": data["secret_value"],
            "notes": data["notes"],
            "custom_fields": dict(data["custom_fields"]),
        }

    def _add_payload_item(self, project_id: str, payload: dict) -> OperationResult:
        kind = self._kind_from_payload(payload)
        return self.vault.add_item(
            project_id=project_id,
            title=str(payload.get("title") or "Imported Credential"),
            kind=kind,
            secret_value=str(payload.get("secret_value") or ""),
            username=str(payload.get("username") or ""),
            url_host=str(payload.get("url_host") or ""),
            environment_key=str(payload.get("environment_key") or ""),
            notes=str(payload.get("notes") or ""),
            tags=list(payload.get("tags") or []),
            favorite=bool(payload.get("favorite", False)),
            custom_fields=dict(payload.get("custom_fields") or {}),
        )

    def _update_payload_item(self, item: CredentialItem, payload: dict) -> OperationResult:
        item.title = str(payload.get("title") or item.title).strip()
        item.kind = self._kind_from_payload(payload)
        item.username = str(payload.get("username") or "").strip()
        item.url_host = str(payload.get("url_host") or "").strip()
        item.environment_key = str(payload.get("environment_key") or "").strip()
        item.tags = list(payload.get("tags") or [])
        item.favorite = bool(payload.get("favorite", False))
        return self.vault.update_item(
            item,
            secret_value=str(payload.get("secret_value") or ""),
            notes=str(payload.get("notes") or ""),
            custom_fields=dict(payload.get("custom_fields") or {}),
        )
