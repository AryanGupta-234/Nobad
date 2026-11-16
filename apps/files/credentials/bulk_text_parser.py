from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


ENV_RE = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")
SSH_RE = re.compile(
    r"\bssh\b(?:\s+-p\s+(?P<port>\d+))?\s+(?:(?P<user>[^@\s]+)@)?(?P<host>[A-Za-z0-9_.:-]+)"
)
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


@dataclass(slots=True)
class ParsedField:
    label: str
    value: str


@dataclass(slots=True)
class TextBlock:
    title: str
    fields: list[ParsedField] = field(default_factory=list)


def credentials_text_to_json(text: str, *, project_name: str = "Imported Credentials") -> dict[str, Any]:
    """Convert loose credential notes into the Credentials Manager JSON import format."""

    items: list[dict[str, Any]] = []
    current_title = project_name
    current_block = TextBlock(current_title)

    def flush_block() -> None:
        nonlocal current_block
        item = _block_to_item(current_block)
        if item:
            items.append(item)
        current_block = TextBlock(current_title)

    for raw_line in text.splitlines():
        line = _strip_list_marker(raw_line.strip())
        if not line:
            flush_block()
            continue
        env_match = ENV_RE.match(line)
        if env_match:
            key, value = env_match.groups()
            items.append(_env_item(key, _clean_value(value), section=current_title))
            continue
        field = _parse_field(line)
        if field:
            current_block.fields.append(field)
            continue
        if _looks_like_heading(line):
            flush_block()
            current_title = _clean_heading(line)
            current_block = TextBlock(current_title)
            continue
        if line.startswith("http://") or line.startswith("https://") or line.startswith("ssh "):
            current_block.fields.append(ParsedField("url", line))
            continue

    flush_block()
    return {
        "projects": [
            {
                "name": project_name,
                "description": "Imported from loose credential notes.",
                "tags": ["imported"],
                "items": _dedupe_items(items),
            }
        ]
    }


def _parse_field(line: str) -> ParsedField | None:
    normalized = line.replace("\t", " ")
    markdown = MARKDOWN_LINK_RE.search(normalized)
    markdown_url = markdown.group(2).strip() if markdown else ""
    separators = [" - ", ":", "="]
    for separator in separators:
        if separator not in normalized:
            continue
        label, value = normalized.split(separator, 1)
        label = _clean_heading(label)
        value = _clean_value(markdown_url or value)
        if label and value:
            return ParsedField(label, value)
    return None


def _block_to_item(block: TextBlock) -> dict[str, Any] | None:
    if not block.fields:
        return None
    fields = {_normalize_label(field.label): field.value for field in block.fields}
    title = _clean_heading(block.title)
    url = _first_core_field(fields, "url", "link", "console", "host", "server", "endpoint", "uri")
    username = _first_core_field(fields, "username", "user", "email", "login", "account")
    secret = _first_core_field(fields, "password", "passphrase", "pass", "passwd", "secret", "token", "api_key", "key")

    ssh = _parse_ssh(url)
    if ssh:
        username = username or ssh.get("user", "")
        url_host = f"{ssh['host']}:{ssh['port']}"
        custom = {"command": url, "port": str(ssh["port"])}
        return _item(
            title=title or "SSH Server",
            kind="server_login",
            username=username,
            url_host=url_host,
            secret_value=secret,
            notes=f"Command: {url}",
            tags=["server", "ssh"],
            custom_fields=custom,
        )

    if not secret and not username and not url:
        return None
    kind = _kind_from_context(title, fields)
    custom_fields = {
        field.label: field.value
        for field in block.fields
        if not _is_core_label(_normalize_label(field.label))
    }
    return _item(
        title=title or _title_from_url(url) or "Imported Credential",
        kind=kind,
        username=username,
        url_host=url,
        secret_value=secret,
        notes=_notes_from_fields(block.fields),
        tags=_tags_for_kind(kind, title),
        custom_fields=custom_fields,
    )


def _env_item(key: str, value: str, *, section: str) -> dict[str, Any]:
    upper = key.upper()
    kind = "env_var"
    if "MONGO" in upper or "DATABASE" in upper or upper.startswith(("DB_", "POSTGRES_", "MYSQL_")):
        kind = "database"
    elif any(token in upper for token in ["API_KEY", "TOKEN", "SECRET", "ACCESS_KEY", "PRIVATE_KEY"]):
        kind = "api_key"
    elif upper.startswith("AWS_"):
        kind = "cloud_provider"
    elif any(token in upper for token in ["SMTP", "EMAIL", "MAIL_"]):
        kind = "email_sms"
    service_tags = _tags_from_key(key)
    return _item(
        title=key,
        kind=kind,
        secret_value=value,
        environment_key=key,
        notes=f"Imported from section: {section}",
        tags=["env", *service_tags],
    )


def _item(
    *,
    title: str,
    kind: str,
    secret_value: str = "",
    username: str = "",
    url_host: str = "",
    environment_key: str = "",
    notes: str = "",
    tags: list[str] | None = None,
    custom_fields: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "title": title.strip() or "Imported Credential",
        "kind": kind,
        "username": username.strip(),
        "url_host": url_host.strip(),
        "environment_key": environment_key.strip(),
        "secret_value": secret_value.strip(),
        "notes": notes.strip(),
        "tags": _dedupe_tags(tags or []),
        "custom_fields": dict(custom_fields or {}),
    }


def _parse_ssh(value: str) -> dict[str, str | int] | None:
    if not value:
        return None
    match = SSH_RE.search(value)
    if not match:
        return None
    port = int(match.group("port") or 22)
    return {
        "user": match.group("user") or "",
        "host": match.group("host"),
        "port": port,
    }


def _kind_from_context(title: str, fields: dict[str, str]) -> str:
    context = f"{title} {' '.join(fields.keys())}".lower()
    if "aws" in context or "cloud" in context:
        return "cloud_provider"
    if "hosting" in context or "cpanel" in context or "hpanel" in context or "panel" in context:
        return "hosting_provider"
    if "server" in context or "ssh" in context or "sftp" in context:
        return "server_login"
    if "database" in context or "mongo" in context or "postgres" in context or "mysql" in context:
        return "database"
    if "smtp" in context or "email" in context or "mail" in context:
        return "email_sms"
    if "git" in context or "github" in context or "gitlab" in context:
        return "git_token"
    if "api" in context or "token" in context:
        return "api_key"
    return "login"


def _first(fields: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = fields.get(key)
        if value:
            return value
    return ""


def _first_core_field(fields: dict[str, str], *tokens: str) -> str:
    exact = _first(fields, *tokens)
    if exact:
        return exact
    token_set = set(tokens)
    for label, value in fields.items():
        if not value:
            continue
        parts = label.split("_")
        if token_set.intersection(parts):
            return value
    return ""


def _is_core_label(label: str) -> bool:
    parts = label.split("_")
    core_tokens = {
        "url",
        "link",
        "console",
        "host",
        "server",
        "endpoint",
        "uri",
        "username",
        "user",
        "email",
        "login",
        "account",
        "password",
        "passphrase",
        "pass",
        "passwd",
        "secret",
        "token",
        "api",
        "key",
    }
    return bool(core_tokens.intersection(parts))


def _normalize_label(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")


def _clean_heading(value: str) -> str:
    cleaned = _strip_list_marker(value).strip().strip("-").strip()
    return re.sub(r"\s+", " ", cleaned)


def _strip_list_marker(value: str) -> str:
    return re.sub(r"^(?:[\u2022\u25e6\u25aa\u2219*]+|\d+[.)])\s*", "", value.strip())


def _clean_value(value: str) -> str:
    cleaned = value.strip()
    if (cleaned.startswith('"') and cleaned.endswith('"')) or (cleaned.startswith("'") and cleaned.endswith("'")):
        cleaned = cleaned[1:-1]
    return cleaned.strip()


def _looks_like_heading(line: str) -> bool:
    if len(line) > 96:
        return False
    if ENV_RE.match(line):
        return False
    if any(separator in line for separator in [":", "="]):
        return False
    lowered = line.lower()
    heading_words = [
        "credentials",
        "configuration",
        "api key",
        "database",
        "server",
        "login",
        "smtp",
        "aws",
        "pinecone",
        "token",
        "repo",
    ]
    return any(word in lowered for word in heading_words) or line.istitle()


def _notes_from_fields(fields: list[ParsedField]) -> str:
    return "\n".join(f"{field.label}: {field.value}" for field in fields)


def _title_from_url(url: str) -> str:
    if not url:
        return ""
    ssh = _parse_ssh(url)
    if ssh:
        return f"SSH {ssh['user']}@{ssh['host']}" if ssh["user"] else f"SSH {ssh['host']}"
    return url.split("//")[-1].split("/")[0]


def _tags_for_kind(kind: str, title: str) -> list[str]:
    tags = [kind.replace("_", "-")]
    lowered = title.lower()
    for word in ["aws", "pinecone", "mongo", "github", "gitlab", "smtp", "email", "server", "ssh"]:
        if word in lowered:
            tags.append(word)
    return tags


def _tags_from_key(key: str) -> list[str]:
    lowered = key.lower()
    tags: list[str] = []
    for word in ["aws", "pinecone", "mongo", "google", "gemini", "replicate", "smtp", "email", "db"]:
        if word in lowered:
            tags.append("database" if word == "db" else word)
    return tags


def _dedupe_tags(tags: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        clean = tag.strip()
        if clean and clean.lower() not in seen:
            seen.add(clean.lower())
            result.append(clean)
    return result


def _dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in items:
        key = (item.get("title", ""), item.get("kind", ""), item.get("environment_key", ""))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result
