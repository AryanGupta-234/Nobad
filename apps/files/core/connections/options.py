from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class ConnectionOptions:
    tls_mode: str = "explicit"
    verify_tls: bool = True
    passive_mode: bool = True
    encoding: str = "utf-8"
    timeout: float = 30.0

    @classmethod
    def from_mapping(cls, value: dict | None) -> "ConnectionOptions":
        data = value or {}
        try:
            timeout = max(1.0, float(data.get("timeout", 30.0)))
        except (TypeError, ValueError):
            timeout = 30.0
        return cls(
            tls_mode=str(data.get("tls_mode", "explicit")),
            verify_tls=bool(data.get("verify_tls", True)),
            passive_mode=bool(data.get("passive_mode", True)),
            encoding=str(data.get("encoding", "utf-8")),
            timeout=timeout,
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
