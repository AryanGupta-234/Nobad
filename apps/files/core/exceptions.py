from __future__ import annotations


class RemoteFileManagerError(Exception):
    """Base application exception."""


class CapabilityError(RemoteFileManagerError):
    """Raised when an operation is unavailable for a connection."""


class ConnectionFailedError(RemoteFileManagerError):
    """Raised when a connection cannot be established."""


class UnsafePathError(RemoteFileManagerError):
    """Raised when an operation targets a protected or unsafe path."""


class RemoteEditConflictError(RemoteFileManagerError):
    """Raised when a remote file changed while being edited locally."""

