from __future__ import annotations

DEFAULT_IGNORE_PATTERNS = [
    "node_modules",
    ".git",
    "vendor",
    "__pycache__",
    ".venv",
]


def should_ignore(path: str, patterns: list[str] | None = None) -> bool:
    active = patterns or DEFAULT_IGNORE_PATTERNS
    normalized = path.replace("\\", "/")
    return any(part in active for part in normalized.split("/"))

