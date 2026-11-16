from __future__ import annotations

from core.connections.ftp_client import FTPConnection


class FTPSConnection(FTPConnection):
    def __init__(self, profile) -> None:  # type: ignore[no-untyped-def]
        super().__init__(profile, secure=True)
