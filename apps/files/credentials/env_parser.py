from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EnvEntry:
    key: str
    value: str


def parse_env(text: str) -> list[EnvEntry]:
    entries: list[EnvEntry] = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        raw = lines[index]
        index += 1
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if value.startswith(("'", '"')):
            quote = value[0]
            body = value[1:]
            while not _ends_with_unescaped_quote(body, quote) and index < len(lines):
                body += "\n" + lines[index]
                index += 1
            if _ends_with_unescaped_quote(body, quote):
                body = body[:-1]
            value = _unescape_double_quoted(body) if quote == '"' else body
        else:
            value = _strip_inline_comment(value).strip()
        entries.append(EnvEntry(key=key, value=value))
    return entries


def format_env(entries: list[EnvEntry]) -> str:
    lines = []
    for entry in entries:
        lines.append(f"{entry.key}={quote_env_value(entry.value)}")
    return "\n".join(lines) + ("\n" if lines else "")


def quote_env_value(value: str) -> str:
    if value == "":
        return '""'
    if any(ch in value for ch in "\n #\"'"):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        return f'"{escaped}"'
    return value


def _strip_inline_comment(value: str) -> str:
    escaped = False
    for index, char in enumerate(value):
        if char == "\\" and not escaped:
            escaped = True
            continue
        if char == "#" and not escaped and index > 0 and value[index - 1].isspace():
            return value[:index]
        escaped = False
    return value


def _ends_with_unescaped_quote(value: str, quote: str) -> bool:
    if not value.endswith(quote):
        return False
    slash_count = 0
    for char in reversed(value[:-1]):
        if char == "\\":
            slash_count += 1
        else:
            break
    return slash_count % 2 == 0


def _unescape_double_quoted(value: str) -> str:
    result = []
    escaped = False
    mapping = {"n": "\n", "r": "\r", "t": "\t", "\\": "\\", '"': '"'}
    for char in value:
        if escaped:
            result.append(mapping.get(char, char))
            escaped = False
        elif char == "\\":
            escaped = True
        else:
            result.append(char)
    if escaped:
        result.append("\\")
    return "".join(result)
