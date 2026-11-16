from __future__ import annotations

from dataclasses import replace

from PySide6.QtWidgets import QDialog, QMessageBox, QVBoxLayout

from core.connections.profile import AuthType, ConnectionProfile, ProfileType, ProtocolType
from ui.new_host_panel import NewHostPanel


class ProfileEditDialog(QDialog):
    def __init__(self, profile: ConnectionProfile, parent=None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self.setWindowTitle(f"Edit connection - {profile.name}")
        self.setMinimumWidth(820)
        self._original = profile
        self._updated_profile: ConnectionProfile | None = None
        self._secret: str | None = None

        self.form = NewHostPanel()
        self.form.status_badge.hide()
        self.form.status_detail.hide()
        self.form.protocol_note.setText(
            "Stored secrets are never displayed. Leave the secret blank to keep the existing keyring entry."
        )
        self.form.save_profile.setChecked(True)
        self.form.save_profile.setEnabled(False)
        self.form.save_profile.setToolTip("This connection is already a saved profile.")
        self.form.connect_button.setText("Save changes")
        self.form.clear_button.setText("Cancel")
        self.form.connect_button.clicked.disconnect()
        self.form.clear_button.clicked.disconnect()
        self.form.connect_button.clicked.connect(self._save)
        self.form.clear_button.clicked.connect(self.reject)
        self.form.auth_type.currentTextChanged.connect(self._sync_remember_secret)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.form)

        self._load_profile()

    def updated_profile(self) -> ConnectionProfile:
        if self._updated_profile is None:
            raise RuntimeError("Profile edit dialog was not accepted.")
        return self._updated_profile

    def secret(self) -> str | None:
        return self._secret

    def remember_secret(self) -> bool:
        return self.form.remember_secret.isChecked()

    def _load_profile(self) -> None:
        profile = self._original
        self.form.protocol.setCurrentText(profile.protocol.value.upper())
        self.form.profile_name.setText(profile.name)
        self.form.host.setText(profile.host)
        self.form.port.setText(str(profile.port))
        self.form.username.setText(profile.username)
        self.form.auth_type.setCurrentText(
            {
                AuthType.PASSWORD: "Password",
                AuthType.SSH_KEY: "SSH Key",
                AuthType.SSH_AGENT: "SSH Agent",
            }.get(profile.auth_type, "Password")
        )
        self.form.key_path.setText(profile.ssh_private_key_path or "")
        self.form.default_local_path.setText(profile.default_local_path or "")
        self.form.default_remote_path.setText(profile.default_remote_path or ".")
        self.form.environment_notes.setPlainText(profile.environment_notes or "")

        options = profile.connection_options
        tls_index = self.form.tls_mode.findData(options.tls_mode)
        if tls_index >= 0:
            self.form.tls_mode.setCurrentIndex(tls_index)
        self.form.verify_tls.setChecked(options.verify_tls)
        self.form.passive_mode.setChecked(options.passive_mode)
        self.form.ftp_encoding.setText(options.encoding)
        self.form.connection_timeout.setText(str(options.timeout))

        has_secret = bool(
            profile.password_secret_ref
            or profile.ssh_private_key_passphrase_secret_ref
        )
        self.form.remember_secret.setChecked(has_secret)
        self.form.secret.setPlaceholderText(
            "Stored in OS keyring - leave blank to keep it"
            if has_secret
            else "password or key passphrase"
        )
        self._sync_remember_secret(self.form.auth_type.currentText())

    def _sync_remember_secret(self, auth_type: str) -> None:
        uses_secret = auth_type in {"Password", "SSH Key"}
        self.form.remember_secret.setEnabled(uses_secret)
        if not uses_secret:
            self.form.remember_secret.setChecked(False)
            return
        matching_secret_exists = (
            auth_type == "Password" and bool(self._original.password_secret_ref)
        ) or (
            auth_type == "SSH Key"
            and bool(self._original.ssh_private_key_passphrase_secret_ref)
        )
        if not matching_secret_exists and not self.form.secret.text():
            self.form.remember_secret.setChecked(False)

    def _save(self) -> None:
        request = self.form.build_request()
        name = request.get("profile_name")
        host = request["host"]
        username = request["username"]
        if not name or not host or not username:
            QMessageBox.warning(
                self,
                "Missing profile details",
                "Profile name, host, and username are required.",
            )
            return
        try:
            port = int(request["port"])
            if not 1 <= port <= 65535:
                raise ValueError
        except (TypeError, ValueError):
            QMessageBox.warning(self, "Invalid port", "Port must be between 1 and 65535.")
            return

        if request["protocol"] not in {"ssh", "sftp", "ftp", "ftps"}:
            QMessageBox.information(
                self,
                "Protocol unavailable",
                f"{request['protocol'].upper()} profiles are planned for a later phase.",
            )
            return
        protocol = ProtocolType(request["protocol"])
        auth_type = {
            "Password": AuthType.PASSWORD,
            "SSH Key": AuthType.SSH_KEY,
            "SSH Agent": AuthType.SSH_AGENT,
        }.get(request["auth_type"], AuthType.PASSWORD)
        if protocol in {ProtocolType.FTP, ProtocolType.FTPS}:
            auth_type = AuthType.PASSWORD
        if auth_type == AuthType.SSH_KEY and not request["key_path"]:
            QMessageBox.warning(self, "Missing SSH key", "Select the local private key file.")
            return

        secret = request["secret"].strip() or None
        matching_secret_exists = (
            auth_type == AuthType.PASSWORD and bool(self._original.password_secret_ref)
        ) or (
            auth_type == AuthType.SSH_KEY
            and bool(self._original.ssh_private_key_passphrase_secret_ref)
        )
        if self.form.remember_secret.isChecked() and not secret and not matching_secret_exists:
            QMessageBox.warning(
                self,
                "Secret required",
                "Enter the password or key passphrase to store in the OS keyring.",
            )
            return

        profile_type = self._original.profile_type
        if protocol == ProtocolType.FTP:
            profile_type = ProfileType.FTP
        elif protocol == ProtocolType.FTPS:
            profile_type = ProfileType.FTPS
        elif profile_type in {ProfileType.FTP, ProfileType.FTPS}:
            profile_type = ProfileType.GENERIC_SSH_SFTP

        options = (
            dict(request.get("connection_options") or {})
            if protocol in {ProtocolType.FTP, ProtocolType.FTPS}
            else dict(self._original.options)
        )
        self._updated_profile = replace(
            self._original,
            name=name,
            profile_type=profile_type,
            protocol=protocol,
            host=host,
            port=port,
            username=username,
            auth_type=auth_type,
            ssh_private_key_path=request["key_path"] if auth_type == AuthType.SSH_KEY else None,
            default_local_path=request.get("default_local_path"),
            default_remote_path=request.get("default_remote_path") or ".",
            environment_notes=request.get("environment_notes"),
            options=options,
        )
        self._secret = secret
        self.accept()
