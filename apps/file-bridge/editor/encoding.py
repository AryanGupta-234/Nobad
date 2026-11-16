from __future__ import annotations

from pathlib import Path

try:
    import chardet
except ImportError:  # pragma: no cover
    chardet = None  # type: ignore[assignment]


def detect_encoding(path: str | Path) -> str:
    data = Path(path).read_bytes()[:65536]
    if not data:
        return "utf-8"
    if chardet is None:
        return "utf-8"
    result = chardet.detect(data)
    return result.get("encoding") or "utf-8"


def is_probably_binary(path: str | Path) -> bool:
    data = Path(path).read_bytes()[:4096]
    return b"\x00" in data

