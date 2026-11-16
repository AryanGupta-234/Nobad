from __future__ import annotations

from PySide6.QtCore import QSize, QUrl, Qt
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QHBoxLayout,
    QDialog,
    QInputDialog,
    QLineEdit,
    QMessageBox,
    QStatusBar,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
    QMainWindow,
    QApplication
)

from core.connections.manager import ConnectionManager
from core.connections.profile import AuthType, ConnectionProfile, ProfileType, ProtocolType
from core.connections.ssh_async import HostKeyPrompt
from core.diagnostics import diagnostics_dir
from core.result import OperationResult
from core.app_logger import AppLogRecord
from credentials.import_export import CredentialImportExportService
from credentials.vault_service import CredentialVaultService
from storage.app_data import AppDataService
from storage.saved_connections import SavedConnectionService, SavedSecretBundle
from security.known_hosts import trust_host_key
from transfers.events import TransferLogEvent
from transfers.transfer_manager import TransferManager
from transfers.remote_transfer import RemoteEndpoint, RemoteTransferService
from transfers.transfer_job import TransferJob, TransferStatus
from ui.async_worker import AsyncRuntime, AsyncWorker
from ui.command_palette import CommandPalette
from ui.connections_panel import ConnectionsPanel
from ui.credentials_panel import CredentialsPanel
from ui.dashboard_panel import DashboardPanel
from ui.services_panel import ServicesPanel
from ui.tunnels_panel import TunnelsPanel
from ui.log_streamer_panel import LogStreamerPanel
from ui.playbooks_panel import PlaybooksPanel
from ui.deployment_panel import DeploymentPanel
from deployment.deployment_history import DeploymentHistoryService
from ui.editor_panel import EditorPanel
from ui.local_file_panel import LocalFilePanel
from ui.logs_panel import LogsPanel
from ui.menu_controller import WorkbenchMenuController
from ui.keyboard_shortcuts import install_button_shortcuts
from ui.new_host_panel import NewHostPanel
from ui.profile_edit_dialog import ProfileEditDialog
from ui.remote_file_panel import RemoteFilePanel
from ui.settings_panel import SettingsPanel
from ui.sync_panel import SyncPanel
from sync.baseline_service import SyncBaselineService
from ui.terminal_panel import TerminalPanel
from ui.transfer_queue import TransferQueuePanel
from ui.remote_transfer_dialog import RemoteTransferDialog
from ui.workbench import (
    ActivityPage,
    BottomDockPanel,
    ComingSoonPanel,
    ConnectionStatusBar,
    NavigationRail,
    OperationDetailsDialog,
    ResponsiveFileManager,
    ResponsiveStackedWidget,
    WorkbenchMainView,
    WorkbenchPage,
)
from ui.workbench_models import (
    FilePaneMode,
    breakpoint_for_width,
    create_dark_palette,
    dark_theme_qss,
)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("NOBAD File Bridge")
        self.app_data = AppDataService.create()
        self.saved_connections = SavedConnectionService(self.app_data.session_factory, self.app_data.credential_store)
        self.credential_vault = CredentialVaultService(self.app_data.session_factory)
        self.credential_import_export = CredentialImportExportService(self.credential_vault)
        self.connection_manager = ConnectionManager()
        self.transfer_manager = TransferManager(max_concurrent=self._setting_value("transfer.max_concurrent", 3))
        self.remote_transfer_service = RemoteTransferService(self.transfer_manager)
        self.current_connection = None
        self._terminal_owned_profile_ids: set[str] = set()
        self._connection_credentials: dict[str, tuple[ConnectionProfile, str | None, str | None]] = {}
        self._deployment_owned_profile_ids: set[str] = set()
        self._transfer_owned_profile_ids: set[str] = set()
        self._pending_profile_to_save: tuple[ConnectionProfile, str | None, bool] | None = None
        self._workers: list[AsyncWorker] = []
        self._pages: dict[str, QWidget] = {}
        self._ui_settings = self._setting_value(
            "ui.workbench",
            {
                "sidebar_collapsed": False,
                "activity_active_tab": "Transfers",
                "last_page": "Files",
                "file_manager_pane_mode": "dual",
            },
        )

        self.navigation = NavigationRail()
        self.workspace = ResponsiveStackedWidget()
        self.connection_status_bar = ConnectionStatusBar()
        self.disconnect_button = self.connection_status_bar.disconnect_button
        self.new_host_panel = NewHostPanel()
        self.connections_panel = ConnectionsPanel()
        self.credentials_panel = CredentialsPanel(self.credential_vault, self.credential_import_export)
        self.local_panel = LocalFilePanel()
        self.remote_panel = RemoteFilePanel()
        self.transfer_panel = TransferQueuePanel()
        self.logs_panel = LogsPanel()
        self.editor_panel = EditorPanel()
        self.terminal_panel = TerminalPanel()
        self.settings_panel = SettingsPanel()
        self.sync_panel = SyncPanel()
        self.sync_baseline_service = SyncBaselineService(self.app_data.session_factory)
        self.dashboard_panel = DashboardPanel()
        self.services_panel = ServicesPanel()
        self.tunnels_panel = TunnelsPanel()
        self.log_streamer_panel = LogStreamerPanel()
        self.playbooks_panel = PlaybooksPanel(self.app_data)
        self.deployment_panel = DeploymentPanel()
        self.deployment_history = DeploymentHistoryService(self.app_data)
        self.file_manager = ResponsiveFileManager(self.local_panel, self.remote_panel)
        self.bottom_dock = BottomDockPanel(self.transfer_panel, self.logs_panel)
        self.workbench_main_view = WorkbenchMainView(self.file_manager, self.bottom_dock)
        self.activity_page = self.bottom_dock
        self.coming_soon_panel = ComingSoonPanel()
        self.remote_panel.set_transfer_manager(self.transfer_manager, self.transfer_panel)
        self.sync_panel.set_transfer_manager(self.transfer_manager)
        self.sync_panel.set_baseline_service(self.sync_baseline_service)
        self.deployment_panel.set_transfer_manager(self.transfer_manager)
        self.deployment_panel.set_history_service(self.deployment_history)

        self._build_workspace()
        self._build_shell()
        self._wire()
        self._load_app_settings()
        self._apply_theme()
        self._apply_ui_settings()
        self._install_actions()
        self.menu_controller = WorkbenchMenuController(self)
        self.menuBar().setVisible(False)
        self.menuBar().setFixedHeight(0)
        self._button_shortcuts = install_button_shortcuts(self)
        self._load_saved_profiles()
        self._load_sync_jobs()
        self._load_deployment_jobs()
        if self.app_data.storage_warning:
            self.logs_panel.append_log(self.app_data.storage_warning, "warning")
        self.setStatusBar(QStatusBar())
        self.statusBar().hide()

        # Enforce responsive minimum window floor (supports down to 1024x600 viewports)
        self.setMinimumSize(QSize(1024, 600))
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.Window | Qt.WindowType.WindowMinMaxButtonsHint)
        self.fit_to_screen_workarea()

    def fit_to_screen_workarea(self) -> None:
        """
        Adapts initial window geometry to the primary screen's available workarea,
        accounting for OS panels/taskbars on 1368x768 and smaller displays.
        """
        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            # On 1366/1368x768 displays, avail.height() is typically ~720px.
            target_w = min(1360, max(1024, avail.width() - 32))
            target_h = min(860, max(600, avail.height() - 48))
            self.resize(target_w, target_h)
            x = avail.x() + max(0, (avail.width() - target_w) // 2)
            y = avail.y() + max(0, (avail.height() - target_h) // 2)
            self.move(x, y)
        else:
            self.resize(1280, 720)

    def _build_workspace(self) -> None:
        pages = {
            "New Host": self.new_host_panel,
            "Connections": self.connections_panel,
            "Credentials": self.credentials_panel,
            "Files": self.workbench_main_view,
            "Dashboard": self.dashboard_panel,
            "Services": self.services_panel,
            "Tunnels": self.tunnels_panel,
            "Logs": self.log_streamer_panel,
            "Terminal": self.terminal_panel,
            "Editor": self.editor_panel,
            "Sync Jobs": self.sync_panel,
            "Deployments": self.deployment_panel,
            "Playbooks": self.playbooks_panel,
            "Settings": self.settings_panel,
            "Coming Soon": WorkbenchPage(
                "Coming Soon",
                "Cloud and provider adapters are grouped here so implemented workflows stay focused.",
                self.coming_soon_panel,
            ),
        }
        for key, page in pages.items():
            self._pages[key] = page
            self.workspace.addWidget(page)

    def _build_shell(self) -> None:
        shell = QWidget()
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        # Top Bar spans the full window width
        shell_layout.addWidget(self.connection_status_bar)

        # Main Body: Navigation Rail (60px) + Workspace
        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        body_layout.addWidget(self.navigation)
        body_layout.addWidget(self.workspace, 1)

        shell_layout.addWidget(body, 1)

        # Pre-bind MainWindow to Chromium's native graphics context before show().
        # On Linux (Wayland / X11), Qt's Simple Browser and Qt Forum (issue 141398) confirm that
        # adding a QWebEngineView dynamically into an already-mapped window forces an OpenGL/EGL
        # context switch that unmaps and remaps (flickers) the top-level window.
        # Placing a 1x1 WebEngine view inside the navigation rail (after stretch) before show()
        # binds MainWindow's surface to Chromium's visual right from launch, eliminating the flicker
        # without affecting shell_layout, window geometry, or click coordinates.
        self._webengine_warmup = QWebEngineView(self.navigation)
        self._webengine_warmup.setFixedSize(1, 1)
        self._webengine_warmup.setStyleSheet("background: transparent; border: none;")
        self._webengine_warmup.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._webengine_warmup.load(QUrl("about:blank"))
        self.navigation.layout().addWidget(self._webengine_warmup)

        self.setCentralWidget(shell)

    def _wire(self) -> None:
        self.palette_shortcut = QShortcut(QKeySequence("Ctrl+K"), self)
        self.palette_shortcut.activated.connect(self._show_command_palette)
        self.navigation.section_selected.connect(self._select_section)
        self.connection_status_bar.disconnect_requested.connect(self._disconnect_current)
        self.connection_status_bar.palette_requested.connect(self._show_command_palette)
        self.connection_status_bar.settings_requested.connect(lambda: self._select_section("Settings"))
        self.bottom_dock.clear_finished_requested.connect(self._clear_completed_transfers)
        self.bottom_dock.open_terminal_requested.connect(lambda: self._select_section("Terminal"))
        self.new_host_panel.connect_requested.connect(self._quick_connect)
        self.connections_panel.connect_requested.connect(self._connect_saved_profile)
        self.connections_panel.edit_requested.connect(self._edit_saved_profile)
        self.connections_panel.delete_requested.connect(self._delete_saved_profile)
        self.connections_panel.rename_requested.connect(self._rename_saved_profile)
        self.connections_panel.refresh_button.clicked.connect(self._load_saved_profiles)
        self.connections_panel.new_connection_requested.connect(lambda: self._select_section("New Host"))
        self.credentials_panel.log_requested.connect(self.logs_panel.append_log)
        self.local_panel.upload_requested.connect(self.remote_panel.upload_path)
        self.local_panel.edit_requested.connect(self._open_local_editor)
        self.local_panel.terminal_requested.connect(self._open_local_terminal_at)
        self.local_panel.log_requested.connect(self.logs_panel.append_log)
        self.remote_panel.edit_requested.connect(self._open_editor)
        self.remote_panel.terminal_requested.connect(self._open_terminal_at)
        self.remote_panel.log_requested.connect(self.logs_panel.append_log)
        self.remote_panel.transfer_finished.connect(self._persist_transfer_result)
        self.remote_panel.copy_to_server_requested.connect(self._copy_to_server)
        self.editor_panel.log_requested.connect(self.logs_panel.append_log)
        self.editor_panel.run_in_terminal_requested.connect(self._on_editor_run_in_terminal)
        self.sync_panel.log_requested.connect(self.logs_panel.append_log)
        self.sync_panel.save_requested.connect(self._save_sync_job)
        self.sync_panel.delete_requested.connect(self._delete_sync_job)
        self.sync_panel.refresh_requested.connect(self._load_sync_jobs)
        self.sync_panel.execution_started.connect(lambda: self._show_activity("Transfers", navigate=True))
        self.sync_panel.execution_finished.connect(self._after_sync_execution)
        self.deployment_panel.log_requested.connect(self._on_deployment_log)
        self.deployment_panel.save_requested.connect(self._save_deployment_job)
        self.deployment_panel.delete_requested.connect(self._delete_deployment_job)
        self.deployment_panel.refresh_requested.connect(self._load_deployment_jobs)
        self.deployment_panel.connection_requested.connect(self._prepare_deployment_connection)
        self.deployment_panel.connection_released.connect(self._release_deployment_connection)
        self.deployment_panel.execution_started.connect(lambda: self._show_activity("Transfers", navigate=True))
        self.deployment_panel.execution_finished.connect(self._after_deployment_execution)
        self.transfer_manager.job_updated.connect(self._on_transfer_job_updated)
        self.transfer_manager.log_event.connect(self._on_transfer_log_event)
        self.transfer_manager.batch_finished.connect(lambda _batch_id: self._after_transfer_batch())
        self.transfer_panel.cancel_requested.connect(self._cancel_transfer)
        self.transfer_panel.retry_requested.connect(self._retry_transfer)
        self.transfer_panel.retry_failed_requested.connect(self._retry_failed_transfers)
        self.transfer_panel.clear_completed_requested.connect(self._clear_completed_transfers)
        self.transfer_panel.clear_failed_requested.connect(self._clear_failed_transfers)
        self.terminal_panel.saved_profile_terminal_requested.connect(self._open_terminal_for_saved_profile)
        self.terminal_panel.terminal_connection_released.connect(self._release_terminal_connection)
        self.terminal_panel.terminal_reconnect_requested.connect(self._reconnect_terminal_session)
        self.terminal_panel.settings_changed.connect(self._save_terminal_settings)
        self.settings_panel.settings_changed.connect(self._save_app_settings)
        self.dashboard_panel.connect_requested.connect(lambda: self._select_section("Connections"))
        self.services_panel.connect_requested.connect(lambda: self._select_section("Connections"))
        self.services_panel.edit_unit_requested.connect(self._open_editor)
        self.tunnels_panel.connect_requested.connect(lambda: self._select_section("Connections"))
        self.log_streamer_panel.connect_requested.connect(lambda: self._select_section("Connections"))

    def _install_actions(self) -> None:
        refresh = QAction("Refresh", self)
        refresh.setShortcut(QKeySequence.Refresh)
        refresh.triggered.connect(self.remote_panel.refresh)
        self.addAction(refresh)

        health_action = QAction("Server Health", self)
        health_action.setShortcut(QKeySequence("Ctrl+Alt+H"))
        health_action.triggered.connect(lambda: self._select_section("Dashboard"))
        self.addAction(health_action)

        services_action = QAction("Systemd Services", self)
        services_action.setShortcut(QKeySequence("Ctrl+Alt+S"))
        services_action.triggered.connect(lambda: self._select_section("Services"))
        self.addAction(services_action)

        tunnels_action = QAction("SSH Tunnels & Ports", self)
        tunnels_action.setShortcut(QKeySequence("Ctrl+Alt+T"))
        tunnels_action.triggered.connect(lambda: self._select_section("Tunnels"))
        self.addAction(tunnels_action)

        logs_action = QAction("Live Log Streamer", self)
        logs_action.setShortcut(QKeySequence("Ctrl+Alt+L"))
        logs_action.triggered.connect(lambda: self._select_section("Logs"))
        self.addAction(logs_action)

        playbooks_action = QAction("Playbooks & Snippets", self)
        playbooks_action.setShortcut(QKeySequence("Ctrl+Alt+P"))
        playbooks_action.triggered.connect(lambda: self._select_section("Playbooks"))
        self.addAction(playbooks_action)

    def _select_section(self, section: str) -> None:
        if section in {"Terminal", "Embedded Terminal"}:
            self._set_current_page("Terminal")
            self.navigation.set_current_section("Terminal")
            return
        if section in {"Activity", "Transfers", "Active Transfers"}:
            self.bottom_dock.select_tab("Active Transfers")
            self._set_current_page("Files")
            self.navigation.set_current_section("Files")
            return
        if section == "Logs & Diagnostics":
            self.bottom_dock.select_tab("Logs & Diagnostics")
            self._set_current_page("Files")
            self.navigation.set_current_section("Files")
            return
        if section in {"Logs", "Live Log Streamer"}:
            self._set_current_page("Logs")
            self.navigation.set_current_section("Logs")
            return
        if section == "Sync Jobs":
            self.sync_panel.set_default_paths(self.local_panel.current_path(), self.remote_panel.current_remote_path)
        if section in {"File Manager", "Files"}:
            section = "Files"
            self.navigation.set_current_section("Files")
        if section == "New Host":
            self.new_host_panel.focus_host()
        self._set_current_page(section)

    def _quick_connect(self, request: dict) -> None:
        host = request["host"]
        username = request["username"]
        protocol = request["protocol"]
        if not host or not username:
            QMessageBox.warning(self, "Missing connection details", "Host and username are required.")
            return
        try:
            port = int(request["port"] or "22")
        except ValueError:
            QMessageBox.warning(self, "Invalid port", "Port must be a number.")
            return
        if protocol not in {"sftp", "ssh", "ftp", "ftps"}:
            QMessageBox.information(
                self,
                "Adapter not implemented",
                f"{protocol.upper()} is planned for a later phase.",
            )
            return
        if protocol == "ftp":
            response = QMessageBox.warning(
                self,
                "Insecure FTP connection",
                "FTP does not encrypt credentials or transferred files.\n\nConnect anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if response != QMessageBox.StandardButton.Yes:
                return

        auth_type = self._auth_type(request["auth_type"])
        if protocol in {"ssh", "sftp"}:
            profile = ConnectionProfile.quick_sftp(
                host=host,
                port=port,
                username=username,
                auth_type=auth_type,
                name=request.get("profile_name"),
                default_remote_path=request.get("default_remote_path"),
                ssh_private_key_path=request["key_path"],
            )
            profile.protocol = ProtocolType.SSH if protocol == "ssh" else ProtocolType.SFTP
        else:
            profile = ConnectionProfile(
                name=request.get("profile_name") or f"{username}@{host}",
                profile_type=ProfileType.FTPS if protocol == "ftps" else ProfileType.FTP,
                protocol=ProtocolType.FTPS if protocol == "ftps" else ProtocolType.FTP,
                host=host,
                port=port,
                username=username,
                auth_type=AuthType.PASSWORD,
                default_remote_path=request.get("default_remote_path") or ".",
                options=dict(request.get("connection_options") or {}),
            )
        profile.default_local_path = request.get("default_local_path")
        profile.environment_notes = request.get("environment_notes")
        secret = request["secret"] or None
        password = secret if auth_type == AuthType.PASSWORD else None
        passphrase = secret if auth_type == AuthType.SSH_KEY else None
        self._pending_profile_to_save = (
            profile,
            secret,
            bool(request.get("remember_secret")),
        ) if request.get("save_profile") else None

        self.new_host_panel.set_connecting(host, port)
        self.connection_status_bar.set_connecting(host, port)
        self.statusBar().showMessage(f"Connecting to {host}:{port}...")
        self._start_profile_connection(
            profile,
            password=password,
            passphrase=passphrase,
            on_success=self._connected,
            on_failure=self._connection_failed,
        )

    def _start_profile_connection(
        self,
        profile: ConnectionProfile,
        *,
        password: str | None,
        passphrase: str | None,
        on_success,
        on_failure,
        on_cancel=None,
        approved_fingerprint: str | None = None,
    ) -> None:  # type: ignore[no-untyped-def]
        self._connection_credentials[profile.id] = (profile, password, passphrase)
        worker = AsyncWorker(
            lambda: self.connection_manager.connect_profile(
                profile,
                password=password,
                passphrase=passphrase,
            )
        )
        self._workers.append(worker)
        worker.succeeded.connect(on_success)
        worker.failed.connect(
            lambda result: self._handle_connection_attempt_failure(
                result,
                profile=profile,
                password=password,
                passphrase=passphrase,
                on_success=on_success,
                on_failure=on_failure,
                on_cancel=on_cancel,
                approved_fingerprint=approved_fingerprint,
            )
        )
        worker.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)
        worker.start()

    def _handle_connection_attempt_failure(
        self,
        result: OperationResult,
        *,
        profile: ConnectionProfile,
        password: str | None,
        passphrase: str | None,
        on_success,
        on_failure,
        on_cancel,
        approved_fingerprint: str | None,
    ) -> None:  # type: ignore[no-untyped-def]
        prompt = result.data if isinstance(result.data, HostKeyPrompt) else None
        if prompt is None:
            on_failure(result)
            return
        if approved_fingerprint == prompt.fingerprint:
            on_failure(
                OperationResult.failure(
                    "The approved SSH host key could not be applied.",
                    technical_details=result.technical_details,
                    suggested_fix="Check that ~/.remote-file-manager/known_hosts is writable.",
                )
            )
            return
        if not self._confirm_host_key(prompt):
            cancelled = OperationResult.failure(
                f"Connection to {profile.host}:{profile.port} was cancelled because the host key was not trusted."
            )
            if on_cancel is not None:
                on_cancel(cancelled)
            else:
                self._connection_cancelled(cancelled)
            return
        try:
            trusted_path = trust_host_key(
                prompt.host,
                prompt.port,
                prompt.public_key,
            )
        except Exception as exc:
            on_failure(
                OperationResult.failure(
                    "Could not save the trusted SSH host key.",
                    technical_details=f"{type(exc).__name__}: {exc}",
                    suggested_fix="Check permissions for ~/.remote-file-manager/known_hosts.",
                )
            )
            return

        try:
            with self.app_data.session_factory() as session:
                self.app_data.known_hosts(session).trust(
                    prompt.host,
                    prompt.port,
                    prompt.fingerprint,
                )
                session.commit()
        except Exception as exc:
            self.logs_panel.append_log(
                f"Host key was trusted, but its SQLite cache could not be updated: {exc}",
                "warning",
            )

        action = "replaced" if prompt.changed else "trusted"
        message = (
            f"SSH host key {action} for {prompt.host}:{prompt.port} "
            f"({prompt.algorithm}, {prompt.fingerprint})."
        )
        self.logs_panel.append_log(message, "warning" if prompt.changed else "info")
        self._persist_log(
            "ssh_host_key",
            "warning" if prompt.changed else "info",
            message,
            profile_id=profile.id,
        )
        self.statusBar().showMessage(f"Trusted host key in {trusted_path}. Connecting...")
        self._start_profile_connection(
            profile,
            password=password,
            passphrase=passphrase,
            on_success=on_success,
            on_failure=on_failure,
            on_cancel=on_cancel,
            approved_fingerprint=prompt.fingerprint,
        )

    def _confirm_host_key(self, prompt: HostKeyPrompt) -> bool:
        dialog = QMessageBox(self)
        if prompt.changed:
            dialog.setWindowTitle("SSH host key changed")
            dialog.setIcon(QMessageBox.Icon.Critical)
            dialog.setText(
                f"The SSH identity of {prompt.host}:{prompt.port} has changed."
            )
            previous = "\n".join(prompt.previous_fingerprints) or "Unavailable"
            dialog.setInformativeText(
                "This can indicate a rebuilt server, changed hosting configuration, or a man-in-the-middle attack.\n\n"
                "Verify the new fingerprint with your hosting provider before continuing.\n\n"
                f"Key type: {prompt.algorithm}\n"
                f"New fingerprint: {prompt.fingerprint}\n"
                f"Previously trusted: {previous}"
            )
            dialog.setStandardButtons(
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
            )
            dialog.setDefaultButton(QMessageBox.StandardButton.Cancel)
            dialog.button(QMessageBox.StandardButton.Yes).setText("Replace Trusted Key")
        else:
            dialog.setWindowTitle("Trust SSH host key?")
            dialog.setIcon(QMessageBox.Icon.Question)
            dialog.setText(
                f"The authenticity of {prompt.host}:{prompt.port} has not been established."
            )
            address = (
                f"\nServer address: {prompt.address}"
                if prompt.address and prompt.address != prompt.host
                else ""
            )
            dialog.setInformativeText(
                "Compare this SHA-256 fingerprint with the value from your hosting provider or server administrator.\n\n"
                f"Key type: {prompt.algorithm}\n"
                f"Fingerprint: {prompt.fingerprint}"
                f"{address}"
            )
            dialog.setStandardButtons(
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            dialog.setDefaultButton(QMessageBox.StandardButton.No)
            dialog.button(QMessageBox.StandardButton.Yes).setText("Trust and Connect")
        return dialog.exec() == QMessageBox.StandardButton.Yes

    def _connection_cancelled(self, result: OperationResult) -> None:
        self.logs_panel.append_log(result.message, "warning")
        self.new_host_panel.set_disconnected("Connection cancelled")
        if self.current_connection is None:
            self.connection_status_bar.set_disconnected("Connection cancelled")
        self.statusBar().showMessage("Connection cancelled")

    def _connected(self, result: OperationResult) -> None:
        self.current_connection = result.data
        profile = self.current_connection.profile
        self._terminal_owned_profile_ids.discard(self.current_connection.profile.id)
        self.terminal_panel.adopt_connection(self.current_connection.profile.id)
        if profile.default_local_path and not self.local_panel.set_path(profile.default_local_path):
            warning = (
                f"Default local path {profile.default_local_path} does not exist or is not a directory. "
                f"Keeping {self.local_panel.current_path()}."
            )
            self.logs_panel.append_log(warning, "warning")
            self._persist_log(
                "connection_path",
                "warning",
                warning,
                profile_id=profile.id,
            )
        remote_ops = self.current_connection.file_operations()
        self.remote_panel.set_connection(self.current_connection)
        self.remote_panel.set_remote_ops(
            remote_ops,
            initial_path=profile.default_remote_path or ".",
        )
        self.editor_panel.set_remote_ops(remote_ops)
        self.editor_panel.set_connection(self.current_connection)
        self.sync_panel.set_remote_ops(
            remote_ops,
            self.current_connection.profile.id,
        )
        self.sync_panel.set_connection(
            self.current_connection,
            self.remote_transfer_service.rsync,
        )
        self.terminal_panel.set_connection(self.current_connection)
        self.dashboard_panel.set_connection(self.current_connection, profile)
        self.services_panel.set_connection(self.current_connection, profile)
        self.tunnels_panel.set_connection(self.current_connection, profile)
        self.log_streamer_panel.set_connection(self.current_connection, profile)
        self.playbooks_panel.set_connection(self.current_connection, profile)
        self.logs_panel.append_log(result.message, "info")
        self._persist_log("connection", "info", result.message, profile_id=self.current_connection.profile.id)
        for warning in result.warnings:
            self.logs_panel.append_log(warning, "warning")
            self._persist_log("connection", "warning", warning, profile_id=self.current_connection.profile.id)
        if self._pending_profile_to_save:
            profile, secret, remember_secret = self._pending_profile_to_save
            save_result = self.saved_connections.save_profile(profile, secret=secret, remember_secret=remember_secret)
            self.logs_panel.append_log(save_result.message, "info" if save_result.ok else "error")
            self._persist_log(
                "connection_profile",
                "info" if save_result.ok else "error",
                save_result.message,
                technical_details=save_result.technical_details,
                profile_id=profile.id,
            )
            self._pending_profile_to_save = None
            self._load_saved_profiles()
        self.new_host_panel.set_connected(profile.name, f"{profile.username}@{profile.host}:{profile.port}")
        self.connection_status_bar.set_connected(
            profile.name,
            f"{profile.username}@{profile.host}:{profile.port}",
        )
        self.statusBar().showMessage(result.message)
        self.file_manager.set_remote_active()
        self._set_current_page("Files")

    def _connection_failed(self, result: OperationResult) -> None:
        self.logs_panel.append_log(result.message, "error")
        self._persist_log("connection", "error", result.message, result.technical_details)
        if result.suggested_fix:
            self.logs_panel.append_log(result.suggested_fix, "info")
        detail = f"\n\n{result.technical_details}" if result.technical_details else ""
        fix = f"\n\nSuggested fix:\n{result.suggested_fix}" if result.suggested_fix else ""
        OperationDetailsDialog(
            title="Connection failed",
            message=result.message + fix,
            details=result.technical_details or detail.strip() or None,
            parent=self,
        ).exec()
        self.new_host_panel.set_disconnected("Connection failed")
        if self.current_connection is None:
            self.connection_status_bar.set_disconnected("Connection failed")
        self.statusBar().showMessage("Connection failed")

    def _connect_saved_profile(self, profile: ConnectionProfile) -> None:
        if profile.protocol == ProtocolType.FTP and not self._confirm_insecure_ftp():
            return
        existing = self.connection_manager.get(profile.id)
        if existing is not None:
            self._terminal_owned_profile_ids.discard(profile.id)
            self.terminal_panel.adopt_connection(profile.id)
            self._connected(OperationResult.success(f"Connected to {profile.host}.", data=existing))
            return

        credentials = self._saved_profile_credentials(profile)
        if credentials is None:
            return
        password, passphrase = credentials

        self.connection_status_bar.set_connecting(profile.host, profile.port)
        self.statusBar().showMessage(f"Connecting to {profile.host}:{profile.port}...")
        self._start_profile_connection(
            profile,
            password=password,
            passphrase=passphrase,
            on_success=self._connected,
            on_failure=self._connection_failed,
        )

    def _confirm_insecure_ftp(self) -> bool:
        response = QMessageBox.warning(
            self,
            "Insecure FTP connection",
            "FTP does not encrypt credentials or transferred files.\n\nConnect anyway?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return response == QMessageBox.StandardButton.Yes

    def _copy_to_server(self, item) -> None:  # type: ignore[no-untyped-def]
        if self.current_connection is None:
            return
        profiles = [
            profile
            for profile in self.saved_connections.list_profiles()
            if profile.id != self.current_connection.profile.id
            and profile.protocol in {ProtocolType.SSH, ProtocolType.SFTP, ProtocolType.FTP, ProtocolType.FTPS}
        ]
        if not profiles:
            QMessageBox.information(self, "Copy to server", "Save another SSH/SFTP/FTP/FTPS profile first.")
            return
        dialog = RemoteTransferDialog(profiles, default_path=".", parent=self)
        if dialog.exec() != RemoteTransferDialog.DialogCode.Accepted:
            return
        destination_profile, destination_path, mode = dialog.values()
        if destination_profile is None:
            return
        if destination_profile.protocol == ProtocolType.FTP and not self._confirm_insecure_ftp():
            return
        existing = self.connection_manager.get(destination_profile.id)
        if existing is not None:
            self._preview_remote_transfer(item, existing, destination_path, mode, owns_connection=False)
            return
        credentials = self._saved_profile_credentials(destination_profile)
        if credentials is None:
            return
        password, passphrase = credentials
        self._start_profile_connection(
            destination_profile,
            password=password,
            passphrase=passphrase,
            on_success=lambda result: self._remote_transfer_connected(
                result,
                item,
                destination_path,
                mode,
            ),
            on_failure=self._connection_failed,
        )

    def _remote_transfer_connected(self, result: OperationResult, item, destination_path: str, mode) -> None:  # type: ignore[no-untyped-def]
        connection = result.data
        self._transfer_owned_profile_ids.add(connection.profile.id)
        self._preview_remote_transfer(item, connection, destination_path, mode, owns_connection=True)

    def _preview_remote_transfer(
        self,
        item,
        destination_connection,
        destination_path: str,
        mode,
        *,
        owns_connection: bool,
    ) -> None:  # type: ignore[no-untyped-def]
        source = RemoteEndpoint(
            self.current_connection.profile.id,
            self.current_connection.profile.name,
            self.current_connection,
            self.current_connection.file_operations(),
        )
        destination = RemoteEndpoint(
            destination_connection.profile.id,
            destination_connection.profile.name,
            destination_connection,
            destination_connection.file_operations(),
        )
        worker = AsyncWorker(
            lambda: self.remote_transfer_service.preview(
                source,
                destination,
                item,
                destination_path,
                mode=mode,
            )
        )
        self._workers.append(worker)
        worker.succeeded.connect(
            lambda result: self._confirm_remote_transfer(result, owns_connection)
        )
        worker.failed.connect(
            lambda result: self._remote_transfer_failed(result, destination.profile_id, owns_connection)
        )
        worker.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)
        worker.start()

    def _confirm_remote_transfer(self, result: OperationResult, owns_connection: bool) -> None:
        plan = result.data
        response = QMessageBox.question(
            self,
            "Copy to server",
            (
                f"Source: {plan.source.name}\n"
                f"Destination: {plan.destination.name}:{plan.destination_root}\n"
                f"Files: {len(plan.files)}\n"
                f"Estimated size: {plan.total_bytes} bytes\n"
                f"Existing destinations: {len(plan.conflicts)}\n"
                f"Mode: {plan.mode.value}\n\n"
                "Start this cross-server transfer?"
            ),
        )
        if response != QMessageBox.StandardButton.Yes:
            self._release_transfer_connection(plan.destination.profile_id, owns_connection)
            return
        self._show_activity("Transfers", navigate=True)
        worker = AsyncWorker(lambda: self.remote_transfer_service.execute(plan))
        self._workers.append(worker)
        worker.succeeded.connect(
            lambda transfer_result: self._remote_transfer_finished(
                transfer_result,
                plan.destination.profile_id,
                owns_connection,
            )
        )
        worker.failed.connect(
            lambda transfer_result: self._remote_transfer_failed(
                transfer_result,
                plan.destination.profile_id,
                owns_connection,
            )
        )
        worker.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)
        worker.start()

    def _remote_transfer_finished(
        self,
        result: OperationResult,
        destination_profile_id: str,
        owns_connection: bool,
    ) -> None:
        self.logs_panel.append_log(result.message, "info")
        for message in result.logs:
            self.logs_panel.append_log(message, "info")
        self._release_transfer_connection(destination_profile_id, owns_connection)

    def _remote_transfer_failed(
        self,
        result: OperationResult,
        destination_profile_id: str,
        owns_connection: bool,
    ) -> None:
        self.logs_panel.append_log(result.message, "error")
        self._show_activity("Logs", navigate=True)
        self._release_transfer_connection(destination_profile_id, owns_connection)
        QMessageBox.warning(self, "Cross-server transfer failed", result.message)

    def _release_transfer_connection(self, profile_id: str, owns_connection: bool) -> None:
        if not owns_connection or profile_id not in self._transfer_owned_profile_ids:
            return
        self._transfer_owned_profile_ids.discard(profile_id)
        worker = AsyncWorker(lambda: self.connection_manager.disconnect(profile_id))
        self._workers.append(worker)
        worker.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)
        worker.start()

    def _saved_profile_credentials(self, profile: ConnectionProfile) -> tuple[str | None, str | None] | None:
        secret_result = self.saved_connections.load_profile_secret(profile)
        password: str | None = None
        passphrase: str | None = None
        if secret_result.ok:
            bundle: SavedSecretBundle = secret_result.data
            password = bundle.password
            passphrase = bundle.passphrase
        elif profile.password_secret_ref or profile.ssh_private_key_passphrase_secret_ref:
            QMessageBox.warning(self, "Saved secret unavailable", secret_result.message)
            return None

        if profile.auth_type == AuthType.PASSWORD and password is None:
            password, ok = QInputDialog.getText(
                self,
                "Password required",
                f"Password for {profile.username}@{profile.host}",
                QLineEdit.EchoMode.Password,
            )
            if not ok:
                return None
        elif profile.auth_type == AuthType.SSH_KEY and passphrase is None and profile.ssh_private_key_path:
            passphrase, ok = QInputDialog.getText(
                self,
                "Key passphrase",
                f"Passphrase for {profile.ssh_private_key_path}",
                QLineEdit.EchoMode.Password,
            )
            if not ok:
                passphrase = None
        return password, passphrase

    def _disconnect_current(self) -> None:
        if self.current_connection is None:
            self.new_host_panel.set_disconnected()
            self.connection_status_bar.set_disconnected()
            return
        profile_id = self.current_connection.profile.id
        profile_name = self.current_connection.profile.name
        self.connection_status_bar.set_disconnecting(profile_name)
        self.statusBar().showMessage(f"Disconnecting from {profile_name}...")
        worker = AsyncWorker(lambda: self.connection_manager.disconnect(profile_id))
        self._workers.append(worker)
        worker.succeeded.connect(lambda result: self._disconnected(result, profile_name, profile_id))
        worker.failed.connect(self._connection_failed)
        worker.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)
        worker.start()

    def _disconnected(self, result: OperationResult, profile_name: str, profile_id: str) -> None:
        self.current_connection = None
        self.remote_panel.clear_connection()
        self.terminal_panel.clear_connection(profile_id)
        self.editor_panel.clear_connection()
        self.sync_panel.clear_connection()
        self.dashboard_panel.set_connection(None)
        self.services_panel.set_connection(None)
        self.tunnels_panel.set_connection(None)
        self.log_streamer_panel.set_connection(None)
        self.playbooks_panel.set_connection(None)
        self.new_host_panel.set_disconnected(f"Disconnected from {profile_name}")
        self.connection_status_bar.set_disconnected(f"Disconnected from {profile_name}")
        self.logs_panel.append_log(result.message, "info" if result.ok else "warning")
        self._persist_log("connection", "info" if result.ok else "warning", result.message)
        self.statusBar().showMessage(result.message)

    def _delete_saved_profile(self, profile_id: str) -> None:
        result = self.saved_connections.delete_profile(profile_id)
        self.logs_panel.append_log(result.message, "info" if result.ok else "error")
        self._persist_log("connection_profile", "info" if result.ok else "error", result.message)
        self._load_saved_profiles()

    def _edit_saved_profile(self, profile: ConnectionProfile) -> None:
        dialog = ProfileEditDialog(profile, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        updated = dialog.updated_profile()
        result = self.saved_connections.update_profile(
            updated,
            secret=dialog.secret(),
            remember_secret=dialog.remember_secret(),
        )
        level = "info" if result.ok else "error"
        self.logs_panel.append_log(result.message, level)
        self._persist_log(
            "connection_profile",
            level,
            result.message,
            technical_details=result.technical_details,
            profile_id=profile.id,
        )
        for warning in result.warnings:
            self.logs_panel.append_log(warning, "warning")
        if not result.ok:
            QMessageBox.warning(
                self,
                "Could not update profile",
                result.message,
            )
            return
        self._load_saved_profiles()
        if self.connection_manager.get(profile.id) is not None:
            self.statusBar().showMessage(
                "Saved profile updated. Connection changes apply after reconnecting."
            )

    def _connect_selected_profile(self) -> None:
        profile = self.connections_panel.selected_profile()
        if profile is None:
            self._select_section("Connections")
            QMessageBox.information(self, "No saved profile selected", "Select a saved connection first.")
            return
        self._connect_saved_profile(profile)

    def _rename_saved_profile(self, profile_id: str, name: str) -> None:
        result = self.saved_connections.rename_profile(profile_id, name)
        self.logs_panel.append_log(result.message, "info" if result.ok else "error")
        self._persist_log("connection_profile", "info" if result.ok else "error", result.message)
        self._load_saved_profiles()

    def _load_saved_profiles(self) -> None:
        try:
            profiles = self.saved_connections.list_profiles()
            self.connections_panel.set_profiles(profiles)
            self.terminal_panel.set_saved_profiles(profiles)
            self.deployment_panel.set_profiles(profiles)
        except Exception as exc:
            self.logs_panel.append_log(f"Could not load saved profiles: {exc}", "error")

    def _load_sync_jobs(self) -> None:
        try:
            with self.app_data.session_factory() as session:
                self.sync_panel.set_saved_jobs(self.app_data.sync_jobs(session).list())
        except Exception as exc:
            self.logs_panel.append_log(f"Could not load sync jobs: {exc}", "error")

    def _load_deployment_jobs(self) -> None:
        try:
            with self.app_data.session_factory() as session:
                self.deployment_panel.set_saved_jobs(self.app_data.deployment_jobs(session).list())
        except Exception as exc:
            self.logs_panel.append_log(f"Could not load deployment jobs: {exc}", "error")

    def _save_sync_job(self, job) -> None:  # type: ignore[no-untyped-def]
        try:
            with self.app_data.session_factory() as session:
                self.app_data.sync_jobs(session).add(job)
                session.commit()
            self.logs_panel.append_log(f"Saved sync job {job.name}.", "info")
            self._load_sync_jobs()
        except Exception as exc:
            self.logs_panel.append_log(f"Could not save sync job: {exc}", "error")

    def _delete_sync_job(self, job_id: str) -> None:
        try:
            with self.app_data.session_factory() as session:
                self.app_data.sync_jobs(session).delete(job_id)
                session.commit()
            self.logs_panel.append_log("Deleted sync job.", "info")
            self._load_sync_jobs()
        except Exception as exc:
            self.logs_panel.append_log(f"Could not delete sync job: {exc}", "error")

    def _save_deployment_job(self, job) -> None:  # type: ignore[no-untyped-def]
        try:
            with self.app_data.session_factory() as session:
                self.app_data.deployment_jobs(session).add(job)
                session.commit()
            self.logs_panel.append_log(f"Saved deployment job {job.name}.", "info")
            self._persist_log("deployment_job", "info", f"Saved deployment job {job.name}.", profile_id=job.profile_id)
            self._load_deployment_jobs()
        except Exception as exc:
            self.logs_panel.append_log(f"Could not save deployment job: {exc}", "error")

    def _delete_deployment_job(self, job_id: str) -> None:
        try:
            with self.app_data.session_factory() as session:
                self.app_data.deployment_jobs(session).delete(job_id)
                session.commit()
            self.logs_panel.append_log("Deleted deployment job.", "info")
            self._persist_log("deployment_job", "info", "Deleted deployment job.")
            self._load_deployment_jobs()
        except Exception as exc:
            self.logs_panel.append_log(f"Could not delete deployment job: {exc}", "error")

    def _prepare_deployment_connection(self, job, action: str) -> None:  # type: ignore[no-untyped-def]
        profile = next(
            (candidate for candidate in self.saved_connections.list_profiles() if candidate.id == job.profile_id),
            None,
        )
        if profile is None:
            self.deployment_panel.connection_failed(OperationResult.failure("Saved deployment profile was not found."))
            return
        if profile.protocol not in {ProtocolType.SSH, ProtocolType.SFTP}:
            self.deployment_panel.connection_failed(
                OperationResult.failure("Deployments require a saved SSH/SFTP profile with shell access.")
            )
            return

        existing = self.connection_manager.get(profile.id)
        if existing is not None:
            if not existing.capabilities.can_exec_command:
                self.deployment_panel.connection_failed(
                    OperationResult.failure("This connection does not provide remote shell command capability.")
                )
                return
            owns_connection = (
                profile.id in self._deployment_owned_profile_ids
                and profile.id not in self._terminal_owned_profile_ids
                and not (self.current_connection is not None and self.current_connection.profile.id == profile.id)
            )
            self.deployment_panel.start_action(job, action, existing, owns_connection=owns_connection)
            return

        credentials = self._saved_profile_credentials(profile)
        if credentials is None:
            self.deployment_panel.connection_failed(OperationResult.failure("Deployment credentials were not provided."))
            return
        password, passphrase = credentials
        self.statusBar().showMessage(f"Opening deployment connection for {profile.name}...")
        self._start_profile_connection(
            profile,
            password=password,
            passphrase=passphrase,
            on_success=lambda result: self._deployment_profile_connected(result, job, action),
            on_failure=self._deployment_connection_failed,
            on_cancel=self._deployment_connection_cancelled,
        )

    def _deployment_profile_connected(self, result: OperationResult, job, action: str) -> None:  # type: ignore[no-untyped-def]
        connection = result.data
        if not connection.capabilities.can_exec_command:
            self._deployment_connection_failed(
                OperationResult.failure("This server does not provide the shell commands required for deployment.")
            )
            AsyncRuntime.instance().submit(self.connection_manager.disconnect(connection.profile.id))
            return
        self._deployment_owned_profile_ids.add(connection.profile.id)
        self.logs_panel.append_log(f"Deployment connection opened for {connection.profile.name}.", "info")
        self._persist_log(
            "deployment",
            "info",
            f"Deployment connection opened for {connection.profile.name}.",
            profile_id=connection.profile.id,
        )
        self.deployment_panel.start_action(job, action, connection, owns_connection=True)
        self.statusBar().showMessage(result.message)

    def _deployment_connection_failed(self, result: OperationResult) -> None:
        self.logs_panel.append_log(result.message, "error")
        self._persist_log("deployment", "error", result.message, result.technical_details)
        self._show_activity("Logs", navigate=True)
        self.deployment_panel.connection_failed(result)

    def _deployment_connection_cancelled(self, result: OperationResult) -> None:
        self.logs_panel.append_log(result.message, "warning")
        self.deployment_panel.connection_failed(result)
        self.statusBar().showMessage("Deployment connection cancelled")

    def _release_deployment_connection(self, profile_id: str) -> None:
        if profile_id not in self._deployment_owned_profile_ids:
            return
        if self.current_connection is not None and self.current_connection.profile.id == profile_id:
            self._deployment_owned_profile_ids.discard(profile_id)
            return
        if profile_id in self._terminal_owned_profile_ids:
            self._deployment_owned_profile_ids.discard(profile_id)
            return
        self._deployment_owned_profile_ids.discard(profile_id)
        worker = AsyncWorker(lambda: self.connection_manager.disconnect(profile_id))
        self._workers.append(worker)
        worker.succeeded.connect(
            lambda result: self.logs_panel.append_log(result.message, "info" if result.ok else "warning")
        )
        worker.failed.connect(lambda result: self.logs_panel.append_log(result.message, "warning"))
        worker.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)
        worker.start()

    def _on_deployment_log(self, message: str, level: str) -> None:
        self.logs_panel.append_log(message, level)
        self._persist_log("deployment", level, message)
        if level in {"warning", "error"}:
            self._show_activity("Logs", navigate=True)

    def _after_deployment_execution(self, result: OperationResult) -> None:
        self._show_activity("Transfers" if result.ok else "Logs", navigate=True)
        if self.current_connection is not None:
            self.remote_panel.refresh()

    def _persist_log(
        self,
        operation: str,
        level: str,
        message: str,
        technical_details: str | None = None,
        profile_id: str | None = None,
    ) -> None:
        try:
            with self.app_data.session_factory() as session:
                self.app_data.logs(session).add(
                    AppLogRecord(
                        operation=operation,
                        level=level,
                        message=message,
                        technical_details=technical_details,
                        profile_id=profile_id,
                    )
                )
                session.commit()
        except Exception:
            pass

    def _persist_transfer_result(self, result: OperationResult) -> None:
        job = result.data
        if job is None:
            return
        try:
            with self.app_data.session_factory() as session:
                self.app_data.transfers(session).add(job)
                self.app_data.logs(session).add(
                    AppLogRecord(
                        operation="transfer",
                        level="info" if result.ok else "error",
                        message=result.message,
                        technical_details=result.technical_details,
                        profile_id=self.current_connection.profile.id if self.current_connection else None,
                    )
                )
                session.commit()
        except Exception:
            pass

    def _on_transfer_job_updated(self, job: TransferJob) -> None:
        self.transfer_panel.update_job(job)
        active_count = len([j for j in self.transfer_manager.jobs.values() if j.status == TransferStatus.RUNNING])
        self.bottom_dock.set_transfer_count(active_count)
        self.bottom_dock.set_bandwidth(f"▲ {self.transfer_panel.bandwidth_label.text()}")
        if job.status in {TransferStatus.QUEUED, TransferStatus.FAILED}:
            self._show_activity("Transfers", navigate=True)
        if job.status in {TransferStatus.COMPLETED, TransferStatus.FAILED, TransferStatus.CANCELLED}:
            self._persist_transfer_job(job)

    def _on_transfer_log_event(self, event: TransferLogEvent) -> None:
        self.logs_panel.append_log(event.message, event.level)
        self._persist_log("transfer", event.level, event.message, event.technical_details)
        if event.level in {"error", "warning"}:
            self._show_activity("Logs", navigate=True)

    def _after_transfer_batch(self) -> None:
        self.remote_panel.refresh()
        self._show_activity("Transfers")

    def _after_sync_execution(self, _result: OperationResult) -> None:
        self.remote_panel.refresh()
        self._show_activity("Transfers", navigate=True)

    def _persist_transfer_job(self, job: TransferJob) -> None:
        try:
            with self.app_data.session_factory() as session:
                self.app_data.transfers(session).add(job)
                session.commit()
        except Exception:
            pass

    def _cancel_transfer(self, job_id: str) -> None:
        AsyncRuntime.instance().submit(self.transfer_manager.cancel_job(job_id))

    def _retry_transfer(self, job_id: str) -> None:
        AsyncRuntime.instance().submit(self.transfer_manager.retry_job(job_id))

    def _retry_failed_transfers(self) -> None:
        AsyncRuntime.instance().submit(self.transfer_manager.retry_failed())

    def _clear_completed_transfers(self) -> None:
        self.transfer_manager.clear_completed()
        self.transfer_panel.set_jobs(list(self.transfer_manager.queue.jobs))

    def _clear_failed_transfers(self) -> None:
        self.transfer_manager.clear_failed()
        self.transfer_panel.set_jobs(list(self.transfer_manager.queue.jobs))

    def _open_editor(self, remote_path: str) -> None:
        self._set_current_page("Editor")
        self.editor_panel.open_remote_file(remote_path)

    def _open_local_editor(self, local_path: str) -> None:
        self._set_current_page("Editor")
        self.editor_panel.open_local_file(local_path)

    def _open_terminal_at(self, remote_path: str) -> None:
        self._select_section("Terminal")
        self.terminal_panel.open_at(remote_path)

    def _open_local_terminal_at(self, local_path: str) -> None:
        self._select_section("Terminal")
        self.terminal_panel.open_local_at(local_path)

    def _open_terminal_for_saved_profile(self, profile: ConnectionProfile, cwd: str | None) -> None:
        if profile.protocol not in {ProtocolType.SFTP, ProtocolType.SSH}:
            QMessageBox.information(
                self,
                "Terminal unavailable",
                f"{profile.protocol.value.upper()} terminals are planned for a later phase. Use SSH/SFTP profiles.",
            )
            return

        existing = self.connection_manager.get(profile.id)
        if existing is not None:
            if (
                profile.id in self._deployment_owned_profile_ids
                and not (self.current_connection is not None and self.current_connection.profile.id == profile.id)
            ):
                self._terminal_owned_profile_ids.add(profile.id)
            owns_connection = (
                profile.id in self._terminal_owned_profile_ids
                and not (self.current_connection is not None and self.current_connection.profile.id == profile.id)
            )
            self._set_current_page("Terminal")
            self.terminal_panel.open_remote_connection(existing, cwd=cwd, owns_connection=owns_connection)
            return

        credentials = self._saved_profile_credentials(profile)
        if credentials is None:
            return
        password, passphrase = credentials
        self._set_current_page("Terminal")
        self.statusBar().showMessage(f"Opening terminal for {profile.name}...")
        self._start_profile_connection(
            profile,
            password=password,
            passphrase=passphrase,
            on_success=lambda result: self._terminal_profile_connected(result, profile, cwd),
            on_failure=self._terminal_connection_failed,
            on_cancel=self._terminal_connection_cancelled,
        )

    def _terminal_profile_connected(self, result: OperationResult, profile: ConnectionProfile, cwd: str | None) -> None:
        connection = result.data
        self._terminal_owned_profile_ids.add(profile.id)
        self.terminal_panel.open_remote_connection(connection, cwd=cwd, owns_connection=True)
        self.logs_panel.append_log(f"Terminal connection opened for {profile.name}.", "info")
        self._persist_log("terminal", "info", f"Terminal connection opened for {profile.name}.", profile_id=profile.id)
        for warning in result.warnings:
            self.logs_panel.append_log(warning, "warning")
            self._persist_log("terminal", "warning", warning, profile_id=profile.id)
        self.statusBar().showMessage(result.message)

    def _terminal_connection_failed(self, result: OperationResult) -> None:
        self.logs_panel.append_log(result.message, "error")
        self._persist_log("terminal", "error", result.message, result.technical_details)
        if result.suggested_fix:
            self.logs_panel.append_log(result.suggested_fix, "info")
        fix = f"\n\nSuggested fix:\n{result.suggested_fix}" if result.suggested_fix else ""
        OperationDetailsDialog(
            title="Terminal connection failed",
            message=result.message + fix,
            details=result.technical_details or None,
            parent=self,
        ).exec()
        self.statusBar().showMessage("Terminal connection failed")

    def _terminal_connection_cancelled(self, result: OperationResult) -> None:
        self.logs_panel.append_log(result.message, "warning")
        self.statusBar().showMessage("Terminal connection cancelled")

    def _reconnect_terminal_session(self, terminal_session) -> None:  # type: ignore[no-untyped-def]
        """Rebuild the SSH transport for a terminal tab after a network drop."""
        profile_id = getattr(terminal_session, "profile_id", None)
        cached = self._connection_credentials.get(profile_id) if profile_id else None
        if cached is None:
            terminal_session.reconnect_failed(
                OperationResult.failure(
                    "Automatic terminal reconnect needs this session's credentials.",
                    suggested_fix="Open a saved profile or reconnect manually and keep this window open.",
                )
            )
            return
        profile, password, passphrase = cached
        self.statusBar().showMessage(f"Reconnecting terminal for {profile.name}...")

        async def reconnect() -> OperationResult:
            await self.connection_manager.disconnect(profile.id)
            return await self.connection_manager.connect_profile(
                profile,
                password=password,
                passphrase=passphrase,
            )

        worker = AsyncWorker(reconnect)
        self._workers.append(worker)
        worker.succeeded.connect(lambda result: self._terminal_session_reconnected(result, terminal_session))
        worker.failed.connect(terminal_session.reconnect_failed)
        worker.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)
        worker.start()

    def _terminal_session_reconnected(self, result: OperationResult, terminal_session) -> None:  # type: ignore[no-untyped-def]
        connection = result.data
        terminal_session.reconnect_with(connection)
        profile = connection.profile
        if self.current_connection is not None and self.current_connection.profile.id == profile.id:
            self.current_connection = connection
            remote_ops = connection.file_operations()
            self.remote_panel.set_connection(connection)
            self.remote_panel.set_remote_ops(remote_ops, initial_path=self.remote_panel.current_remote_path)
            self.editor_panel.set_remote_ops(remote_ops)
            self.editor_panel.set_connection(self.current_connection)
            self.sync_panel.set_remote_ops(remote_ops, profile.id)
            self.sync_panel.set_connection(connection, self.remote_transfer_service.rsync)
            self.terminal_panel.set_connection(connection)
            self.playbooks_panel.set_connection(connection, profile)
        message = f"Terminal reconnected for {profile.name}."
        self.logs_panel.append_log(message, "info")
        self._persist_log("terminal", "info", message, profile_id=profile.id)
        self.statusBar().showMessage(message)

    def _release_terminal_connection(self, profile_id: str) -> None:
        if profile_id not in self._terminal_owned_profile_ids:
            return
        if self.current_connection is not None and self.current_connection.profile.id == profile_id:
            self._terminal_owned_profile_ids.discard(profile_id)
            return
        self._terminal_owned_profile_ids.discard(profile_id)
        worker = AsyncWorker(lambda: self.connection_manager.disconnect(profile_id))
        self._workers.append(worker)
        worker.succeeded.connect(lambda result: self.logs_panel.append_log(result.message, "info" if result.ok else "warning"))
        worker.failed.connect(lambda result: self.logs_panel.append_log(result.message, "warning"))
        worker.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)
        worker.start()

    def _on_editor_run_in_terminal(self, path: str) -> None:
        self._select_section("Terminal")
        if self.current_connection is not None:
            self.terminal_panel.open_remote_connection(self.current_connection, cwd=None, owns_connection=False)
        else:
            self.terminal_panel.open_local_at(None)

    def _load_app_settings(self) -> None:
        settings = {
            "transfer.max_concurrent": self._setting_value("transfer.max_concurrent", 3),
            "tools": self._setting_value(
                "tools",
                {"rsync_path": "rsync", "rclone_path": "rclone"},
            ),
            "terminal": self._setting_value(
                "terminal",
                {
                    "profiles": [{"name": "Default Shell", "startup_command": "", "cwd_mode": "current_remote_path", "theme": "dark"}],
                    "default_profile": "Default Shell",
                    "font_size": 13,
                    "scrollback": 5000,
                    "default_new_target": "active_remote",
                    "local_shell_path": "",
                    "local_cwd_mode": "current_local_path",
                },
            ),
            "file_browser": self._setting_value("file_browser", {"local_view": "details", "remote_view": "details"}),
        }
        self.transfer_manager.set_max_concurrent(int(settings["transfer.max_concurrent"]))
        self.remote_transfer_service.rsync.configured_executable = (
            settings["tools"].get("rsync_path") or None
        )
        self.settings_panel.apply_settings(settings)
        self.terminal_panel.apply_settings(settings["terminal"])
        self.local_panel.set_view_mode(settings["file_browser"].get("local_view", "details"))
        self.remote_panel.set_view_mode(settings["file_browser"].get("remote_view", "details"))

    def _save_app_settings(self, settings: dict) -> None:
        try:
            with self.app_data.session_factory() as session:
                repo = self.app_data.settings(session)
                repo.set("transfer.max_concurrent", {"value": int(settings["transfer.max_concurrent"])})
                repo.set("terminal", {"value": settings["terminal"]})
                repo.set("tools", {"value": settings.get("tools", {})})
                repo.set("file_browser", {"value": settings.get("file_browser", {})})
                session.commit()
        except Exception:
            return
        self.transfer_manager.set_max_concurrent(int(settings["transfer.max_concurrent"]))
        self.remote_transfer_service.rsync.configured_executable = (
            settings.get("tools", {}).get("rsync_path") or None
        )
        self.terminal_panel.apply_settings(settings["terminal"])
        browser = settings.get("file_browser", {})
        self.local_panel.set_view_mode(browser.get("local_view", "details"))
        self.remote_panel.set_view_mode(browser.get("remote_view", "details"))

    def _save_terminal_settings(self, terminal_settings: dict) -> None:
        self._save_app_settings(
            {
                "transfer.max_concurrent": self.transfer_manager.max_concurrent,
                "terminal": terminal_settings,
                "tools": {
                    "rsync_path": self.remote_transfer_service.rsync.configured_executable or "rsync",
                    "rclone_path": self.settings_panel.rclone_path.text().strip() or "rclone",
                },
                "file_browser": {
                    "local_view": self.settings_panel.local_file_view.currentData() or "details",
                    "remote_view": self.settings_panel.remote_file_view.currentData() or "details",
                },
            }
        )

    def _toggle_sidebar(self) -> None:
        current = bool(self._ui_settings.get("sidebar_collapsed", False))
        self._ui_settings["sidebar_collapsed"] = not current
        self._apply_responsive_layout()
        self._save_ui_settings()

    def _toggle_activity(self) -> None:
        self._select_section("Activity")

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About NOBAD File Bridge",
            "NOBAD File Bridge\n\nSSH/SFTP and FTP/FTPS workbench with files, cross-server transfers, editor, terminal, sync, deployments, and logs.",
        )

    def _show_diagnostics_folder(self) -> None:
        folder = diagnostics_dir()
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _apply_ui_settings(self) -> None:
        self.bottom_dock.open_tab(
            str(
                self._ui_settings.get(
                    "activity_active_tab",
                    self._ui_settings.get("bottom_dock_active_tab", "Active Transfers"),
                )
            )
        )
        mode = self._ui_settings.get("file_manager_pane_mode", "dual")
        try:
            self.file_manager.set_pane_mode(FilePaneMode(mode))
        except ValueError:
            self.file_manager.set_pane_mode(FilePaneMode.DUAL)
        self._set_current_page("Files", persist=False)
        self._apply_responsive_layout()

    def _save_ui_settings(self) -> None:
        page = self._current_page_key()
        self._ui_settings = {
            "sidebar_collapsed": True,
            "activity_active_tab": self.bottom_dock.active_tab(),
            "last_page": page,
            "file_manager_pane_mode": self.file_manager.pane_mode().value,
        }
        try:
            with self.app_data.session_factory() as session:
                self.app_data.settings(session).set("ui.workbench", {"value": self._ui_settings})
                session.commit()
        except Exception:
            pass

    def _setting_value(self, key: str, default):  # type: ignore[no-untyped-def]
        try:
            with self.app_data.session_factory() as session:
                value = self.app_data.settings(session).get(key, {"value": default})
                if isinstance(value, dict) and "value" in value:
                    return value["value"]
        except Exception:
            pass
        return default

    def _show_command_palette(self) -> None:
        palette = CommandPalette(self)
        palette.command_selected.connect(self._run_palette_command)
        palette.exec()

    def _run_palette_command(self, command: str) -> None:
        if command == "Open settings":
            self._select_section("Settings")
        elif command == "Open dashboard":
            self._select_section("Dashboard")
        elif command == "Open services":
            self._select_section("Services")
        elif command == "Open tunnels":
            self._select_section("Tunnels")
        elif command == "Open log streamer":
            self._select_section("Logs")
        elif command == "Open playbooks":
            self._select_section("Playbooks")
        elif command == "Open logs":
            self._show_activity("Logs", navigate=True)
        elif command == "Open credentials":
            self._select_section("Credentials")
        elif command in {"Connect", "New Host"}:
            self._select_section("New Host")
        elif command == "Disconnect":
            self._disconnect_current()
        elif command == "Open terminal":
            self._select_section("Terminal")
            target = self.terminal_panel.settings.get("default_new_target", "active_remote")
            if target == "local" or self.current_connection is None:
                self.terminal_panel.open_local_at(self.local_panel.current_path())
            else:
                self.terminal_panel.open_at(None)
        elif command == "Open terminal here":
            if self.current_connection is not None:
                self._open_terminal_at(self.remote_panel.current_remote_path)
            else:
                self._open_local_terminal_at(self.local_panel.current_path())
        elif command in {"Upload", "Download"}:
            self._select_section("Files")
        else:
            self.logs_panel.append_log(f"{command} is scaffolded for a later phase.", "info")

    def _show_activity(self, tab: str, *, navigate: bool = False) -> None:
        self.bottom_dock.open_tab(tab)
        if navigate:
            self._set_current_page("Files")
        else:
            self._ui_settings["activity_active_tab"] = self.bottom_dock.active_tab()

    def _auth_type(self, value: str) -> AuthType:
        if value == "SSH Key":
            return AuthType.SSH_KEY
        if value == "SSH Agent":
            return AuthType.SSH_AGENT
        return AuthType.PASSWORD

    def _set_current_page(self, key: str, *, persist: bool = True) -> None:
        if key in {"Activity", "Transfers", "Active Transfers"}:
            self.bottom_dock.select_tab("Active Transfers")
            key = "Files"
        elif key == "Logs & Diagnostics":
            self.bottom_dock.select_tab("Logs & Diagnostics")
            key = "Files"

        page = self._pages.get(key)
        if page is None:
            key = "Files"
            page = self._pages.get("Files")
        if page is not None:
            self.workspace.setCurrentWidget(page)
        self.navigation.set_current_section(key)
        if persist:
            self._save_ui_settings()

    def _current_page_key(self) -> str:
        current = self.workspace.currentWidget()
        for key, page in self._pages.items():
            if page is current:
                return key
        return "Files"

    def _apply_theme(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.setPalette(create_dark_palette())
        self.setStyleSheet(dark_theme_qss())

    def _apply_responsive_layout(self) -> None:
        breakpoint = breakpoint_for_width(self.width())
        self.navigation.set_collapsed(True)
        self.file_manager.set_breakpoint(breakpoint)

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        self._apply_responsive_layout()
