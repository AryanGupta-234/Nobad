from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from core.connections.profile import AuthType, ConnectionProfile
from core.result import OperationResult
from security.credential_store import CredentialStore, SecretKind, SecureSecretReference
from storage.models import SecureSecretReferenceModel
from storage.repositories import ConnectionProfileRepository, SecretReferenceRepository


@dataclass
class SavedSecretBundle:
    password: str | None = None
    passphrase: str | None = None


class SavedConnectionService:
    def __init__(self, session_factory: sessionmaker[Session], credential_store: CredentialStore) -> None:
        self.session_factory = session_factory
        self.credential_store = credential_store

    def list_profiles(self) -> list[ConnectionProfile]:
        with self.session_factory() as session:
            return ConnectionProfileRepository(session).list()

    def save_profile(
        self,
        profile: ConnectionProfile,
        *,
        secret: str | None = None,
        remember_secret: bool = False,
    ) -> OperationResult:
        with self.session_factory() as session:
            profile_repo = ConnectionProfileRepository(session)
            secret_repo = SecretReferenceRepository(session)

            if remember_secret and secret:
                kind = SecretKind.KEY_PASSPHRASE if profile.auth_type == AuthType.SSH_KEY else SecretKind.PASSWORD
                secret_result = self.credential_store.store_secret(profile.id, kind, secret)
                if not secret_result.ok:
                    return secret_result
                secret_ref: SecureSecretReference = secret_result.data
                secret_repo.add(profile.id, secret_ref)
                if kind == SecretKind.PASSWORD:
                    profile.password_secret_ref = secret_ref.id
                else:
                    profile.ssh_private_key_passphrase_secret_ref = secret_ref.id

            profile_repo.add(profile)
            session.commit()
            return OperationResult.success("Connection profile saved.", data=profile)

    def update_profile(
        self,
        profile: ConnectionProfile,
        *,
        secret: str | None = None,
        remember_secret: bool = False,
    ) -> OperationResult:
        new_reference: SecureSecretReference | None = None
        with self.session_factory() as session:
            profile_repo = ConnectionProfileRepository(session)
            secret_repo = SecretReferenceRepository(session)
            existing = profile_repo.get(profile.id)
            if existing is None:
                return OperationResult.failure("Connection profile was not found.")

            old_references = secret_repo.list_for_profile(profile.id)
            target_kind = (
                SecretKind.KEY_PASSPHRASE
                if profile.auth_type == AuthType.SSH_KEY
                else SecretKind.PASSWORD
            )
            matching_reference_id = (
                existing.ssh_private_key_passphrase_secret_ref
                if target_kind == SecretKind.KEY_PASSPHRASE
                else existing.password_secret_ref
            )

            if remember_secret and secret:
                stored = self.credential_store.store_secret(profile.id, target_kind, secret)
                if not stored.ok:
                    return stored
                new_reference = stored.data
                secret_repo.add(profile.id, new_reference)
                matching_reference_id = new_reference.id
            elif remember_secret and not matching_reference_id:
                return OperationResult.failure(
                    "Enter a password or key passphrase to remember for this authentication method."
                )

            profile.password_secret_ref = (
                matching_reference_id
                if remember_secret and target_kind == SecretKind.PASSWORD
                else None
            )
            profile.ssh_private_key_passphrase_secret_ref = (
                matching_reference_id
                if remember_secret and target_kind == SecretKind.KEY_PASSPHRASE
                else None
            )

            retained_id = matching_reference_id if remember_secret else None
            references_to_remove = [ref for ref in old_references if ref.id != retained_id]
            for reference in references_to_remove:
                secret_repo.delete(reference.id)

            try:
                profile_repo.add(profile)
                session.commit()
            except Exception as exc:
                session.rollback()
                if new_reference is not None:
                    self.credential_store.delete_secret(new_reference)
                return OperationResult.failure(
                    "Could not update connection profile.",
                    technical_details=f"{type(exc).__name__}: {exc}",
                )

        warnings: list[str] = []
        for reference in references_to_remove:
            deleted = self.credential_store.delete_secret(reference)
            if not deleted.ok:
                warnings.append(f"Old keyring secret could not be removed: {deleted.message}")
        return OperationResult.success(
            "Connection profile updated.",
            data=profile,
            warnings=warnings,
        )

    def delete_profile(self, profile_id: str) -> OperationResult:
        with self.session_factory() as session:
            profile_repo = ConnectionProfileRepository(session)
            secret_repo = SecretReferenceRepository(session)
            for ref in secret_repo.list_for_profile(profile_id):
                self.credential_store.delete_secret(ref)
            profile_repo.delete(profile_id)
            session.commit()
        return OperationResult.success("Connection profile deleted.", affected_paths=[profile_id])

    def rename_profile(self, profile_id: str, name: str) -> OperationResult:
        clean_name = name.strip()
        if not clean_name:
            return OperationResult.failure("Connection name cannot be empty.")
        with self.session_factory() as session:
            renamed = ConnectionProfileRepository(session).rename(profile_id, clean_name)
            if not renamed:
                return OperationResult.failure("Connection profile was not found.")
            session.commit()
        return OperationResult.success("Connection profile renamed.", affected_paths=[profile_id])

    def load_profile_secret(self, profile: ConnectionProfile) -> OperationResult:
        with self.session_factory() as session:
            secret_repo = SecretReferenceRepository(session)
            bundle = SavedSecretBundle()
            if profile.password_secret_ref:
                ref = secret_repo.get(profile.password_secret_ref)
                if ref is None:
                    return OperationResult.failure("Saved password reference was not found.")
                result = self.credential_store.get_secret(ref)
                if not result.ok:
                    return result
                bundle.password = result.data
            if profile.ssh_private_key_passphrase_secret_ref:
                ref = secret_repo.get(profile.ssh_private_key_passphrase_secret_ref)
                if ref is None:
                    return OperationResult.failure("Saved key passphrase reference was not found.")
                result = self.credential_store.get_secret(ref)
                if not result.ok:
                    return result
                bundle.passphrase = result.data
            return OperationResult.success("Saved profile secret loaded.", data=bundle)
