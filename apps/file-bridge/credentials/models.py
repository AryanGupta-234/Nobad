from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4


class CredentialKind(StrEnum):
    ENV_VAR = "env_var"
    LOGIN = "login"
    SERVER_LOGIN = "server_login"
    HOSTING_PROVIDER = "hosting_provider"
    SSH_SECRET = "ssh_secret"
    DATABASE = "database"
    API_KEY = "api_key"
    GIT_TOKEN = "git_token"
    CI_CD_SECRET = "ci_cd_secret"
    CLOUD_PROVIDER = "cloud_provider"
    DNS_CDN = "dns_cdn"
    EMAIL_SMS = "email_sms"
    PAYMENT_PROVIDER = "payment_provider"
    CERTIFICATE_KEY = "certificate_key"
    LICENSE_KEY = "license_key"
    SECURE_NOTE = "secure_note"
    OTHER = "other"


def now_utc() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class CredentialProject:
    name: str
    id: str = field(default_factory=lambda: str(uuid4()))
    description: str = ""
    tags: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=now_utc)
    updated_at: datetime = field(default_factory=now_utc)


@dataclass(slots=True)
class CredentialItem:
    project_id: str
    title: str
    kind: CredentialKind
    id: str = field(default_factory=lambda: str(uuid4()))
    username: str = ""
    url_host: str = ""
    environment_key: str = ""
    tags: list[str] = field(default_factory=list)
    favorite: bool = False
    has_secret: bool = True
    has_notes: bool = False
    created_at: datetime = field(default_factory=now_utc)
    updated_at: datetime = field(default_factory=now_utc)


@dataclass(slots=True)
class CredentialCustomField:
    item_id: str
    name: str
    id: str = field(default_factory=lambda: str(uuid4()))
    is_secret: bool = True
    created_at: datetime = field(default_factory=now_utc)


@dataclass(slots=True)
class CredentialAuditEvent:
    action: str
    message: str
    project_id: str | None = None
    item_id: str | None = None
    id: int | None = None
    created_at: datetime = field(default_factory=now_utc)


CREDENTIAL_KIND_LABELS: dict[CredentialKind, str] = {
    CredentialKind.ENV_VAR: "Project Credential",
    CredentialKind.LOGIN: "Generic Login",
    CredentialKind.SERVER_LOGIN: "Server Login",
    CredentialKind.HOSTING_PROVIDER: "Hosting Provider",
    CredentialKind.SSH_SECRET: "SSH/SFTP",
    CredentialKind.DATABASE: "Database",
    CredentialKind.API_KEY: "API Key",
    CredentialKind.GIT_TOKEN: "Git Token",
    CredentialKind.CI_CD_SECRET: "CI/CD Secret",
    CredentialKind.CLOUD_PROVIDER: "Cloud Provider",
    CredentialKind.DNS_CDN: "DNS/CDN",
    CredentialKind.EMAIL_SMS: "Email/SMS",
    CredentialKind.PAYMENT_PROVIDER: "Payment Provider",
    CredentialKind.CERTIFICATE_KEY: "Key/Certificate",
    CredentialKind.LICENSE_KEY: "License Key",
    CredentialKind.SECURE_NOTE: "Secure Note",
    CredentialKind.OTHER: "Other",
}


def parse_tags(text: str) -> list[str]:
    seen: set[str] = set()
    tags: list[str] = []
    for part in text.replace("\n", ",").split(","):
        tag = part.strip()
        if tag and tag.lower() not in seen:
            seen.add(tag.lower())
            tags.append(tag)
    return tags


def format_tags(tags: list[str]) -> str:
    return ", ".join(tags)
