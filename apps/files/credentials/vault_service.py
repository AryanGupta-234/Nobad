from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from core.result import OperationResult
from credentials.crypto import (
    KdfConfig,
    b64decode,
    b64encode,
    decrypt_text,
    derive_key,
    encrypt_text,
    new_salt,
)
from credentials.models import (
    CredentialAuditEvent,
    CredentialCustomField,
    CredentialItem,
    CredentialKind,
    CredentialProject,
)
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from storage.repositories import CredentialAuditRepository, CredentialRepository



VAULT_VERIFIER_TEXT = "remote-file-manager-credential-vault"


class CredentialVaultService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory
        self._key: bytes | None = None
        self._kdf_config = KdfConfig()

    @property
    def is_unlocked(self) -> bool:
        return self._key is not None

    @staticmethod
    def _credential_repo(session: Session):
        from storage.repositories import CredentialRepository
        return CredentialRepository(session)

    @staticmethod
    def _audit_repo(session: Session):
        from storage.repositories import CredentialAuditRepository
        return CredentialAuditRepository(session)

    def lock(self) -> OperationResult:
        self._key = None
        return OperationResult.success("Credential vault locked.")

    def is_configured(self) -> bool:
        with self.session_factory() as session:
            return self._credential_repo(session).get_vault_metadata() is not None

    def create_vault(self, master_password: str) -> OperationResult:
        if len(master_password) < 8:
            return OperationResult.failure("Master password must be at least 8 characters.")
        with self.session_factory() as session:
            repo = self._credential_repo(session)
            if repo.get_vault_metadata() is not None:
                return OperationResult.failure("Credential vault already exists.")
            salt = new_salt()
            key = derive_key(master_password, salt, self._kdf_config)
            repo.set_vault_metadata(
                kdf_name=self._kdf_config.name,
                salt=b64encode(salt),
                kdf_params=self._kdf_config.to_dict(),
                verifier_payload=encrypt_text(key, VAULT_VERIFIER_TEXT, aad="vault-verifier"),
            )
            self._audit_repo(session).add(
                CredentialAuditEvent(action="created_vault", message="Credential vault created.")
            )
            session.commit()
        self._key = key
        return OperationResult.success("Credential vault created and unlocked.")

    def unlock(self, master_password: str) -> OperationResult:
        metadata_result = self._load_metadata()
        if not metadata_result.ok:
            return metadata_result
        metadata = metadata_result.data
        try:
            config = KdfConfig.from_dict(metadata["kdf_params"])
            key = derive_key(master_password, b64decode(metadata["salt"]), config)
        except Exception as exc:
            return OperationResult.failure(
                "Could not derive vault key.",
                technical_details=f"{type(exc).__name__}: {exc}",
            )
        verifier = decrypt_text(key, metadata["verifier_payload"], aad="vault-verifier")
        if not verifier.ok or verifier.data != VAULT_VERIFIER_TEXT:
            return OperationResult.failure("Master password is incorrect.")
        self._key = key
        return OperationResult.success("Credential vault unlocked.")

    def change_master_password(self, old_password: str, new_password: str) -> OperationResult:
        if len(new_password) < 8:
            return OperationResult.failure("New master password must be at least 8 characters.")
        metadata_result = self._load_metadata()
        if not metadata_result.ok:
            return metadata_result
        metadata = metadata_result.data
        config = KdfConfig.from_dict(metadata["kdf_params"])
        old_key = derive_key(old_password, b64decode(metadata["salt"]), config)
        verifier = decrypt_text(old_key, metadata["verifier_payload"], aad="vault-verifier")
        if not verifier.ok or verifier.data != VAULT_VERIFIER_TEXT:
            return OperationResult.failure("Current master password is incorrect.")

        with self.session_factory() as session:
            repo = self._credential_repo(session)
            plaintext_items: list[tuple[CredentialItem, str, str, list[tuple[CredentialCustomField, str]]]] = []
            for item in repo.list_items():
                encrypted = repo.get_item_encrypted(item.id)
                if encrypted is None:
                    continue
                item_meta, encrypted_value, encrypted_notes = encrypted
                value = decrypt_text(old_key, encrypted_value, aad=f"credential:{item.id}:value")
                notes = decrypt_text(old_key, encrypted_notes, aad=f"credential:{item.id}:notes")
                if not value.ok or not notes.ok:
                    return OperationResult.failure("Could not decrypt all credentials before password change.")
                fields: list[tuple[CredentialCustomField, str]] = []
                for field, encrypted_field in repo.list_custom_fields_encrypted(item.id):
                    field_value = decrypt_text(old_key, encrypted_field, aad=f"credential-field:{field.id}")
                    if not field_value.ok:
                        return OperationResult.failure(
                            "Could not decrypt all custom fields before password change."
                        )
                    fields.append((field, field_value.data))
                plaintext_items.append((item_meta, value.data, notes.data, fields))

            new_salt_value = new_salt()
            new_key = derive_key(new_password, new_salt_value, self._kdf_config)
            repo.set_vault_metadata(
                kdf_name=self._kdf_config.name,
                salt=b64encode(new_salt_value),
                kdf_params=self._kdf_config.to_dict(),
                verifier_payload=encrypt_text(new_key, VAULT_VERIFIER_TEXT, aad="vault-verifier"),
            )
            for item, value, notes, fields in plaintext_items:
                repo.add_item(
                    item,
                    encrypted_value=encrypt_text(new_key, value, aad=f"credential:{item.id}:value"),
                    encrypted_notes=encrypt_text(new_key, notes, aad=f"credential:{item.id}:notes") if notes else "",
                )
                repo.replace_custom_fields(
                    item.id,
                    [
                        (
                            field,
                            encrypt_text(new_key, field_value, aad=f"credential-field:{field.id}"),
                        )
                        for field, field_value in fields
                    ],
                )
            self._audit_repo(session).add(
                CredentialAuditEvent(action="changed_master_password", message="Master password changed.")
            )
            session.commit()
        self._key = new_key
        return OperationResult.success("Master password changed.")

    def list_projects(self) -> list[CredentialProject]:
        if not self._key:
            return []
        with self.session_factory() as session:
            return self._credential_repo(session).list_projects()

    def create_project(self, name: str, *, description: str = "", tags: list[str] | None = None) -> OperationResult:
        guard = self._require_unlocked()
        if not guard.ok:
            return guard
        clean_name = name.strip()
        if not clean_name:
            return OperationResult.failure("Project name is required.")
        project = CredentialProject(name=clean_name, description=description.strip(), tags=tags or [])
        with self.session_factory() as session:
            self._credential_repo(session).add_project(project)
            self._audit_repo(session).add(
                CredentialAuditEvent(
                    project_id=project.id,
                    action="created_project",
                    message=f"Credential project created: {project.name}",
                )
            )
            session.commit()
        return OperationResult.success("Credential project created.", data=project)

    def delete_project(self, project_id: str) -> OperationResult:
        guard = self._require_unlocked()
        if not guard.ok:
            return guard
        with self.session_factory() as session:
            repo = self._credential_repo(session)
            project = repo.get_project(project_id)
            if project is None:
                return OperationResult.failure("Credential project was not found.")
            repo.delete_project(project_id)
            self._audit_repo(session).add(
                CredentialAuditEvent(action="deleted_project", message=f"Credential project deleted: {project.name}")
            )
            session.commit()
        return OperationResult.success("Credential project deleted.")

    def add_item(
        self,
        *,
        project_id: str,
        title: str,
        kind: CredentialKind,
        secret_value: str,
        username: str = "",
        url_host: str = "",
        environment_key: str = "",
        notes: str = "",
        tags: list[str] | None = None,
        favorite: bool = False,
        custom_fields: dict[str, str] | None = None,
    ) -> OperationResult:
        guard = self._require_unlocked()
        if not guard.ok:
            return guard
        clean_title = title.strip()
        if not clean_title:
            return OperationResult.failure("Credential title is required.")
        key = self._key
        assert key is not None
        item = CredentialItem(
            project_id=project_id,
            title=clean_title,
            kind=kind,
            username=username.strip(),
            url_host=url_host.strip(),
            environment_key=environment_key.strip(),
            tags=tags or [],
            favorite=favorite,
            has_notes=bool(notes),
        )
        return self._store_item(
            item,
            secret_value=secret_value,
            notes=notes,
            custom_fields=custom_fields or {},
            action="created",
        )

    def update_item(
        self,
        item: CredentialItem,
        *,
        secret_value: str,
        notes: str = "",
        custom_fields: dict[str, str] | None = None,
    ) -> OperationResult:
        guard = self._require_unlocked()
        if not guard.ok:
            return guard
        item.updated_at = datetime.now(UTC)
        item.has_notes = bool(notes)
        return self._store_item(
            item,
            secret_value=secret_value,
            notes=notes,
            custom_fields=custom_fields or {},
            action="updated",
        )

    def list_items(self, project_id: str | None = None, *, query: str = "") -> list[CredentialItem]:
        if not self._key:
            return []
        with self.session_factory() as session:
            repo = self._credential_repo(session)
            return repo.search_items(query, project_id=project_id) if query else repo.list_items(project_id)

    def list_custom_fields(self, item_id: str) -> list[CredentialCustomField]:
        if not self._key:
            return []
        with self.session_factory() as session:
            return self._credential_repo(session).list_custom_fields(item_id)

    def delete_item(self, item_id: str) -> OperationResult:
        guard = self._require_unlocked()
        if not guard.ok:
            return guard
        with self.session_factory() as session:
            repo = self._credential_repo(session)
            item = repo.get_item(item_id)
            if item is None:
                return OperationResult.failure("Credential item was not found.")
            repo.delete_item(item_id)
            self._audit_repo(session).add(
                CredentialAuditEvent(
                    project_id=item.project_id,
                    item_id=item.id,
                    action="deleted",
                    message=f"Credential deleted: {item.title}",
                )
            )
            session.commit()
        return OperationResult.success("Credential item deleted.")

    def reveal_secret(self, item_id: str, *, action: str = "revealed") -> OperationResult:
        return self._reveal_payload(item_id, payload="value", audit_action=action)

    def reveal_notes(self, item_id: str) -> OperationResult:
        return self._reveal_payload(item_id, payload="notes", audit_action="revealed_notes")

    def reveal_custom_fields(self, item_id: str) -> OperationResult:
        guard = self._require_unlocked()
        if not guard.ok:
            return guard
        key = self._key
        assert key is not None
        values: dict[str, str] = {}
        with self.session_factory() as session:
            repo = self._credential_repo(session)
            item = repo.get_item(item_id)
            if item is None:
                return OperationResult.failure("Credential item was not found.")
            for field, encrypted_value in repo.list_custom_fields_encrypted(item_id):
                decrypted = decrypt_text(key, encrypted_value, aad=f"credential-field:{field.id}")
                if not decrypted.ok:
                    return decrypted
                values[field.name] = decrypted.data
            self._audit_repo(session).add(
                CredentialAuditEvent(
                    project_id=item.project_id,
                    item_id=item.id,
                    action="revealed_custom_fields",
                    message=f"Custom fields revealed for credential: {item.title}",
                )
            )
            session.commit()
        return OperationResult.success("Credential custom fields revealed.", data=values)

    def plaintext_item(self, item_id: str) -> OperationResult:
        guard = self._require_unlocked()
        if not guard.ok:
            return guard
        secret = self.reveal_secret(item_id, action="exported")
        if not secret.ok:
            return secret
        notes = self.reveal_notes(item_id)
        if not notes.ok:
            return notes
        fields = self.reveal_custom_fields(item_id)
        if not fields.ok:
            return fields
        with self.session_factory() as session:
            item = self._credential_repo(session).get_item(item_id)
            if item is None:
                return OperationResult.failure("Credential item was not found.")
        return OperationResult.success(
            "Credential plaintext loaded.",
            data={"item": item, "secret_value": secret.data, "notes": notes.data, "custom_fields": fields.data},
        )

    def audit_events(self, *, project_id: str | None = None, limit: int = 200) -> list[CredentialAuditEvent]:
        with self.session_factory() as session:
            return self._audit_repo(session).list(project_id=project_id, limit=limit)

    def _load_metadata(self) -> OperationResult:
        with self.session_factory() as session:
            metadata = self._credential_repo(session).get_vault_metadata()
        if metadata is None:
            return OperationResult.failure("Credential vault has not been created.")
        return OperationResult.success("Credential vault metadata loaded.", data=metadata)

    def _require_unlocked(self) -> OperationResult:
        if self._key is None:
            return OperationResult.failure("Credential vault is locked.")
        return OperationResult.success("Credential vault is unlocked.")

    def _store_item(
        self,
        item: CredentialItem,
        *,
        secret_value: str,
        notes: str,
        custom_fields: dict[str, str],
        action: str,
    ) -> OperationResult:
        key = self._key
        assert key is not None
        encrypted_value = encrypt_text(key, secret_value, aad=f"credential:{item.id}:value")
        encrypted_notes = encrypt_text(key, notes, aad=f"credential:{item.id}:notes") if notes else ""
        encrypted_fields: list[tuple[CredentialCustomField, str]] = []
        for name, value in custom_fields.items():
            field_name = name.strip()
            if not field_name:
                continue
            field = CredentialCustomField(id=str(uuid4()), item_id=item.id, name=field_name)
            encrypted_fields.append((field, encrypt_text(key, value, aad=f"credential-field:{field.id}")))
        with self.session_factory() as session:
            repo = self._credential_repo(session)
            if repo.get_project(item.project_id) is None:
                return OperationResult.failure("Credential project was not found.")
            repo.add_item(item, encrypted_value=encrypted_value, encrypted_notes=encrypted_notes)
            repo.replace_custom_fields(item.id, encrypted_fields)
            self._audit_repo(session).add(
                CredentialAuditEvent(
                    project_id=item.project_id,
                    item_id=item.id,
                    action=action,
                    message=f"Credential {action}: {item.title}",
                )
            )
            session.commit()
        return OperationResult.success(f"Credential {action}.", data=item)

    def _reveal_payload(self, item_id: str, *, payload: str, audit_action: str) -> OperationResult:
        guard = self._require_unlocked()
        if not guard.ok:
            return guard
        key = self._key
        assert key is not None
        with self.session_factory() as session:
            repo = self._credential_repo(session)
            encrypted = repo.get_item_encrypted(item_id)
            if encrypted is None:
                return OperationResult.failure("Credential item was not found.")
            item, encrypted_value, encrypted_notes = encrypted
            if payload == "notes":
                decrypted = decrypt_text(key, encrypted_notes, aad=f"credential:{item.id}:notes")
            else:
                decrypted = decrypt_text(key, encrypted_value, aad=f"credential:{item.id}:value")
            if not decrypted.ok:
                return decrypted
            self._audit_repo(session).add(
                CredentialAuditEvent(
                    project_id=item.project_id,
                    item_id=item.id,
                    action=audit_action,
                    message=f"Credential {audit_action}: {item.title}",
                )
            )
            session.commit()
        return OperationResult.success("Credential value revealed.", data=decrypted.data)
