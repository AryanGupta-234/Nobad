"""The connection session for the web UI: one active server connection, saved profiles and the host-key prompt.

Built on the shared backend services (ConnectionManager, SavedConnectionService), so profiles saved by earlier
versions of the app are listed here too.

Host keys (repository rule: unknown host = ask, changed key = refuse by default): when the server's key isn't
trusted yet, connecting stops and the page gets a ``hostkey`` event with the fingerprint and a one-time token. Only
``trust(token, accept=True)`` adds the key and reconnects; a token works once and expires after five minutes."""
from __future__ import annotations

import re
import secrets
import time
from dataclasses import dataclass
from typing import Any

from app_web import bus, tasks
from core.connections.manager import ConnectionManager
from core.connections.profile import AuthType, ConnectionProfile, ProfileType, ProtocolType
from core.connections.ssh_async import HostKeyPrompt
from core.result import OperationResult
from security.known_hosts import trust_host_key
from storage.saved_connections import SavedConnectionService

PROMPT_TTL = 300
PROTOCOLS = {"sftp": ProtocolType.SFTP, "ssh": ProtocolType.SSH, "ftp": ProtocolType.FTP, "ftps": ProtocolType.FTPS}
AUTH_TYPES = {"password": AuthType.PASSWORD, "ssh_key": AuthType.SSH_KEY, "ssh_agent": AuthType.SSH_AGENT}
DEFAULT_PORTS = {"sftp": 22, "ssh": 22, "ftp": 21, "ftps": 21}
_HOST = re.compile(r"^[A-Za-z0-9._:\-\[\]%]{1,253}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class ProfileError(ValueError):
    pass


@dataclass
class PendingHostKey:
    profile: ConnectionProfile
    password: str | None
    passphrase: str | None
    prompt: HostKeyPrompt
    save: tuple[bool, bool]          # (save profile, remember secret)
    secret: str | None
    created: float


def _clean_text(value: Any, label: str, *, required: bool = False, limit: int = 256) -> str | None:
    if value is None or value == "":
        if required:
            raise ProfileError(f"{label} is required.")
        return None
    if not isinstance(value, str):
        raise ProfileError(f"{label} must be text.")
    text = value.strip()
    if required and not text:
        raise ProfileError(f"{label} is required.")
    if len(text) > limit or _CONTROL.search(text):
        raise ProfileError(f"{label}: use one line of up to {limit} characters.")
    return text or None


def build_profile(spec: dict[str, Any]) -> ConnectionProfile:
    """A ConnectionProfile from the page's form, validated (no secrets are part of the profile)."""
    protocol = str(spec.get("protocol") or "sftp").lower()
    if protocol not in PROTOCOLS:
        raise ProfileError("Choose SFTP, SSH, FTP or FTPS.")
    host = _clean_text(spec.get("host"), "Host", required=True, limit=253) or ""
    if not _HOST.match(host):
        raise ProfileError("Host: use a name like example.com or an IP address.")
    try:
        port = int(spec.get("port") or DEFAULT_PORTS[protocol])
    except (TypeError, ValueError) as exc:
        raise ProfileError("Port must be a number from 1 to 65535.") from exc
    if not 1 <= port <= 65535:
        raise ProfileError("Port must be a number from 1 to 65535.")
    username = _clean_text(spec.get("username"), "Username", required=True, limit=128) or ""
    auth = str(spec.get("auth_type") or "password")
    if protocol in {"ftp", "ftps"}:
        auth = "password"
    if auth not in AUTH_TYPES:
        raise ProfileError("Choose password, SSH key or SSH agent.")
    key_path = _clean_text(spec.get("key_path"), "Key file", limit=1024) if auth == "ssh_key" else None
    if auth == "ssh_key" and not key_path:
        raise ProfileError("Choose the private key file.")
    name = _clean_text(spec.get("name"), "Name", limit=120) or f"{username}@{host}"
    remote_path = _clean_text(spec.get("remote_path"), "Server folder", limit=1024) or "."
    local_path = _clean_text(spec.get("local_path"), "Local folder", limit=1024)
    profile = ConnectionProfile(
        name=name,
        profile_type=ProfileType.GENERIC_SSH_SFTP if protocol in {"sftp", "ssh"} else ProfileType(protocol),
        protocol=PROTOCOLS[protocol],
        host=host,
        port=port,
        username=username,
        auth_type=AUTH_TYPES[auth],
        ssh_private_key_path=key_path,
        default_remote_path=remote_path,
        default_local_path=local_path,
    )
    return profile


def profile_summary(profile: ConnectionProfile) -> dict[str, Any]:
    """What the page may see about a profile: never a secret, only whether one is saved."""
    return {
        "id": profile.id,
        "name": profile.name,
        "protocol": profile.protocol.value,
        "host": profile.host,
        "port": profile.port,
        "username": profile.username,
        "auth_type": profile.auth_type.value,
        "key_path": profile.ssh_private_key_path,
        "remote_path": profile.default_remote_path or ".",
        "local_path": profile.default_local_path,
        "secret_saved": bool(profile.password_secret_ref or profile.ssh_private_key_passphrase_secret_ref),
        "last_connected": profile.last_connected_date.isoformat() if profile.last_connected_date else None,
        "insecure": profile.protocol == ProtocolType.FTP,
    }


def _prompt_payload(token: str, prompt: HostKeyPrompt) -> dict[str, Any]:
    return {
        "token": token, "host": prompt.host, "address": prompt.address, "port": prompt.port,
        "algorithm": prompt.algorithm, "fingerprint": prompt.fingerprint, "changed": prompt.changed,
        "previous": list(prompt.previous_fingerprints),
    }


class SessionService:
    def __init__(self, app_data: Any) -> None:
        self.app_data = app_data
        self.manager = ConnectionManager()
        self.saved = SavedConnectionService(app_data.session_factory, app_data.credential_store)
        self.current: Any = None            # BaseConnection
        self._pending: dict[str, PendingHostKey] = {}
        self._connecting: str | None = None
        self.on_closed: list[Any] = []      # callbacks(profile_id) when a connection is closed or replaced

    # ---------------------------------------------------------------- state
    def state(self) -> dict[str, Any]:
        state = self._state()
        pending = self.pending_prompt()
        if pending is not None:
            state["hostkey"] = pending        # a page that (re)loads while a host-key question is open still asks it
        return state

    def _state(self) -> dict[str, Any]:
        if self.current is not None:
            p = self.current.profile
            return {"status": "connected", "profile": profile_summary(p), "label": f"{p.username}@{p.host}:{p.port}"}
        if self._connecting:
            return {"status": "connecting", "label": self._connecting}
        return {"status": "disconnected"}

    def _announce(self) -> None:
        bus.broadcast("connection", self.state())

    def profiles(self) -> list[dict[str, Any]]:
        return [profile_summary(p) for p in self.saved.list_profiles()]

    def find_profile(self, profile_id: str) -> ConnectionProfile | None:
        return next((p for p in self.saved.list_profiles() if p.id == profile_id), None)

    # ---------------------------------------------------------------- connect
    def start_connect(
        self,
        profile: ConnectionProfile,
        *,
        password: str | None,
        passphrase: str | None,
        save: bool = False,
        remember: bool = False,
        secret: str | None = None,
        approved_fingerprint: str | None = None,
    ) -> bool:
        self._connecting = f"{profile.username}@{profile.host}:{profile.port}"
        self._announce()

        async def work() -> OperationResult:
            return await self.manager.connect_profile(profile, password=password, passphrase=passphrase)

        def done(result: OperationResult) -> None:
            self._after_connect(result, profile, password, passphrase, (save, remember), secret, approved_fingerprint)

        started = tasks.run_task("conn.connect", work, on_result=done)
        if not started:
            self._connecting = None
            self._announce()
        return started

    def _after_connect(self, result, profile, password, passphrase, save, secret, approved_fingerprint) -> None:  # type: ignore[no-untyped-def]
        self._connecting = None
        prompt = result.data if isinstance(result.data, HostKeyPrompt) else None
        if not result.ok and prompt is not None:
            if approved_fingerprint == prompt.fingerprint:
                bus.log("The trusted SSH host key couldn't be applied. Check that ~/.remote-file-manager/known_hosts "
                        "is writable.", "bad", "ssh")
                bus.broadcast("conn_failed", {"message": "The trusted host key couldn't be applied."})
                self._announce()
                return
            token = secrets.token_urlsafe(18)
            self._expire_prompts()
            self._pending[token] = PendingHostKey(profile, password, passphrase, prompt, save, secret, time.monotonic())
            bus.broadcast("hostkey", _prompt_payload(token, prompt))
            self._announce()
            return
        if not result.ok:
            bus.log(result.message, "bad", "connection")
            if result.suggested_fix:
                bus.log(result.suggested_fix, "info", "connection")
            bus.broadcast("conn_failed", {"message": bus.scrub(result.message), "fix": bus.scrub(result.suggested_fix or "")})
            self._announce()
            return
        previous = self.current
        self.current = result.data
        if previous is not None and previous is not self.current:
            self._closed(previous.profile.id)
            tasks.run_task("conn.close_previous", lambda: self.manager.disconnect(previous.profile.id))
        bus.log(result.message, "ok", "connection")
        for warning in result.warnings:
            bus.log(warning, "warn", "connection")
        save_profile, remember = save
        if save_profile:
            saved = self.saved.save_profile(profile, secret=secret, remember_secret=remember)
            bus.log(saved.message, "ok" if saved.ok else "bad", "connection")
            bus.broadcast("profiles_changed", {})
        self._announce()

    def pending_prompt(self) -> dict[str, Any] | None:
        self._expire_prompts()
        if not self._pending:
            return None
        token, pending = max(self._pending.items(), key=lambda kv: kv[1].created)
        return _prompt_payload(token, pending.prompt)

    def _expire_prompts(self) -> None:
        now = time.monotonic()
        for token in [t for t, p in self._pending.items() if now - p.created > PROMPT_TTL]:
            del self._pending[token]

    def trust(self, token: str, accept: bool) -> OperationResult:
        self._expire_prompts()
        pending = self._pending.pop(token, None)
        if pending is None:
            return OperationResult.failure("This host key question has expired. Connect again.")
        prompt = pending.prompt
        if not accept:
            bus.log(f"Didn't connect to {prompt.host}:{prompt.port}: its host key wasn't trusted.", "warn", "ssh")
            self._announce()
            return OperationResult.success("Not connected.")
        try:
            trust_host_key(prompt.host, prompt.port, prompt.public_key)
        except Exception as exc:
            return OperationResult.failure(f"Couldn't save the trusted host key: {exc}")
        try:
            with self.app_data.session_factory() as session:
                self.app_data.known_hosts(session).trust(prompt.host, prompt.port, prompt.fingerprint)
                session.commit()
        except Exception as exc:
            bus.log(f"Host key trusted, but its cache couldn't be updated: {exc}", "warn", "ssh")
        action = "replaced" if prompt.changed else "trusted"
        bus.log(f"SSH host key {action} for {prompt.host}:{prompt.port} ({prompt.algorithm}, {prompt.fingerprint}).",
                "warn" if prompt.changed else "info", "ssh")
        save_profile, remember = pending.save
        self.start_connect(pending.profile, password=pending.password, passphrase=pending.passphrase,
                           save=save_profile, remember=remember, secret=pending.secret,
                           approved_fingerprint=prompt.fingerprint)
        return OperationResult.success("Trusted. Connecting…")

    def saved_credentials(self, profile: ConnectionProfile, typed_secret: str | None) -> tuple[str | None, str | None, str | None]:
        """(password, passphrase, what's still needed). Typed secrets win over saved ones."""
        password = passphrase = None
        if typed_secret is None:
            loaded = self.saved.load_profile_secret(profile)
            if loaded.ok:
                password, passphrase = loaded.data.password, loaded.data.passphrase
            elif profile.password_secret_ref or profile.ssh_private_key_passphrase_secret_ref:
                raise ProfileError(loaded.message)
        elif profile.auth_type == AuthType.PASSWORD:
            password = typed_secret
        else:
            passphrase = typed_secret or None
        if profile.auth_type == AuthType.PASSWORD and password is None:
            return None, None, "password"
        return password, passphrase, None

    def _closed(self, profile_id: str) -> None:
        for callback in list(self.on_closed):
            try:
                callback(profile_id)
            except Exception as exc:
                bus.log(f"Cleanup after disconnect failed: {exc}", "warn", "connection")

    # ---------------------------------------------------------------- disconnect / profiles
    def disconnect(self) -> bool:
        connection = self.current
        if connection is None:
            return False
        self.current = None
        name = connection.profile.name
        self._closed(connection.profile.id)

        async def work() -> OperationResult:
            return await self.manager.disconnect(connection.profile.id)

        def done(_result: OperationResult) -> None:
            bus.log(f"Disconnected from {name}.", "info", "connection")
            self._announce()

        tasks.run_task("conn.disconnect", work, on_result=done)
        self._announce()
        return True
