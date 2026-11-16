from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QScrollArea,
    QTabWidget,
    QTableView,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QFrame
)

from core.connections.profile import ConnectionProfile, ProtocolType
from core.result import OperationResult
from deployment.deployment_executor import DeploymentExecutor
from deployment.deployment_history import DeploymentHistoryService
from ui.icons import get_icon
from deployment.deployment_job import (
    DeploymentArtifact,
    DeploymentArtifactKind,
    DeploymentExecutionPolicy,
    DeploymentExecutionResult,
    DeploymentJob,
    DeploymentMode,
    DeploymentPreview,
    DeploymentRun,
    DeploymentRunStatus,
    DeploymentStage,
    DeploymentStageEvent,
    DeploymentStrategy,
    HealthCheckConfig,
    HealthCheckOrigin,
)
from deployment.manual_rollback import ManualRollbackService
from deployment.deployment_planner import DeploymentPlanner
from deployment.deployment_templates import DEPLOYMENT_TEMPLATES, deployment_template
from file_ops.base import human_size
from sync.diff_engine import SyncPlanEntry
from ui.async_worker import AsyncRuntime, AsyncWorker


USER_ROLE = int(Qt.ItemDataRole.UserRole)


class DeploymentPreviewTableModel(QAbstractTableModel):
    HEADERS = ["Action", "Path", "Reason", "Local Size", "Remote Size"]

    def __init__(self) -> None:
        super().__init__()
        self.entries: list[SyncPlanEntry] = []

    def rowCount(self, _parent: QModelIndex = QModelIndex()) -> int:
        return len(self.entries)

    def columnCount(self, _parent: QModelIndex = QModelIndex()) -> int:
        return len(self.HEADERS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self.entries):
            return None
        entry = self.entries[index.row()]
        if role == Qt.ItemDataRole.UserRole:
            return entry
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        values = [
            entry.action.value,
            entry.path,
            entry.reason,
            human_size(entry.source_size),
            human_size(entry.destination_size),
        ]
        return values[index.column()]

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return None

    def set_preview(self, preview: DeploymentPreview | None) -> None:
        self.beginResetModel()
        self.entries = list(preview.sync_preview.entries if preview else [])
        self.endResetModel()


class DeploymentRunTableModel(QAbstractTableModel):
    HEADERS = ["Started", "Status", "Server", "Strategy", "Files", "Duration", "Health"]

    def __init__(self) -> None:
        super().__init__()
        self.runs: list[DeploymentRun] = []

    def rowCount(self, _parent: QModelIndex = QModelIndex()) -> int:
        return len(self.runs)

    def columnCount(self, _parent: QModelIndex = QModelIndex()) -> int:
        return len(self.HEADERS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self.runs):
            return None
        run = self.runs[index.row()]
        if role == Qt.ItemDataRole.UserRole:
            return run
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        duration = run.duration_seconds
        values = [
            self._format_time(run.started_at),
            run.status.value.replace("_", " ").title(),
            run.profile_name or run.host,
            run.strategy.value.replace("_", " ").title(),
            f"{run.uploads + run.overwrites + run.deletes}",
            "-" if duration is None else f"{duration:.1f}s",
            "-" if run.health_ok is None else ("Passed" if run.health_ok else "Failed"),
        ]
        return values[index.column()]

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return None

    def set_runs(self, runs: list[DeploymentRun]) -> None:
        self.beginResetModel()
        self.runs = list(runs)
        self.endResetModel()

    def run_at(self, row: int) -> DeploymentRun | None:
        return self.runs[row] if 0 <= row < len(self.runs) else None

    @staticmethod
    def _format_time(value: datetime) -> str:
        return value.astimezone().strftime("%Y-%m-%d %H:%M")


class DeploymentArtifactTableModel(QAbstractTableModel):
    HEADERS = ["Type", "Path", "Created", "State"]

    def __init__(self) -> None:
        super().__init__()
        self.artifacts: list[DeploymentArtifact] = []

    def rowCount(self, _parent: QModelIndex = QModelIndex()) -> int:
        return len(self.artifacts)

    def columnCount(self, _parent: QModelIndex = QModelIndex()) -> int:
        return len(self.HEADERS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self.artifacts):
            return None
        artifact = self.artifacts[index.row()]
        if role == Qt.ItemDataRole.UserRole:
            return artifact
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        state = "Active" if artifact.active else ("Imported" if artifact.imported else "Available")
        values = [
            artifact.kind.value.title(),
            artifact.path,
            artifact.created_at.astimezone().strftime("%Y-%m-%d %H:%M"),
            state,
        ]
        return values[index.column()]

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return None

    def set_artifacts(self, artifacts: list[DeploymentArtifact]) -> None:
        self.beginResetModel()
        self.artifacts = list(artifacts)
        self.endResetModel()

    def artifact_at(self, row: int) -> DeploymentArtifact | None:
        return self.artifacts[row] if 0 <= row < len(self.artifacts) else None


class PipelineRibbonWidget(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PipelineRibbon")
        self.setStyleSheet("""
            QFrame#PipelineRibbon {
                background: #121215;
                border: 1px solid #1f222a;
                border-radius: 8px;
            }
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 7, 12, 7)
        layout.setSpacing(8)

        lbl = QLabel("PIPELINE:")
        lbl.setStyleSheet("font-size: 10px; font-weight: 700; color: #71717a; letter-spacing: 0.5px;")
        layout.addWidget(lbl)

        self.step_definitions = [
            ("1. Pre-Flight", [DeploymentStage.VALIDATING, DeploymentStage.LOCKING, DeploymentStage.PREVIEWING]),
            ("2. Local Build", [DeploymentStage.BUILDING]),
            ("3. Snapshot Backup", [DeploymentStage.BACKING_UP, DeploymentStage.PREPARING_RELEASE]),
            ("4. Atomic Upload", [DeploymentStage.TRANSFERRING, DeploymentStage.DELETING, DeploymentStage.CHMOD]),
            ("5. Symlink Switch", [DeploymentStage.SWITCHING_RELEASE, DeploymentStage.POST_DEPLOY, DeploymentStage.CACHE_CLEAR, DeploymentStage.RESTART]),
            ("6. Health Check", [DeploymentStage.HEALTH_CHECK, DeploymentStage.COMPLETED]),
        ]
        self.chips: list[QLabel] = []
        for idx, (label, _stages) in enumerate(self.step_definitions):
            chip = QLabel(f" {label} ")
            chip.setStyleSheet("font-size: 11px; font-weight: 600; color: #71717a; background: #18181b; border: 1px solid #27272a; border-radius: 6px; padding: 3px 8px;")
            self.chips.append(chip)
            layout.addWidget(chip)
            if idx < len(self.step_definitions) - 1:
                arrow = QLabel("➔")
                arrow.setStyleSheet("color: #3f3f46; font-size: 11px;")
                layout.addWidget(arrow)
        layout.addStretch()

    def reset(self) -> None:
        for chip in self.chips:
            chip.setStyleSheet("font-size: 11px; font-weight: 600; color: #71717a; background: #18181b; border: 1px solid #27272a; border-radius: 6px; padding: 3px 8px;")

    def set_stage(self, stage: DeploymentStage) -> None:
        for idx, (_label, stages) in enumerate(self.step_definitions):
            if stage in stages:
                for p_idx in range(idx):
                    self.chips[p_idx].setStyleSheet("font-size: 11px; font-weight: 600; color: #10b981; background: rgba(16, 185, 129, 0.12); border: 1px solid rgba(16, 185, 129, 0.3); border-radius: 6px; padding: 3px 8px;")
                if stage == DeploymentStage.COMPLETED:
                    self.chips[idx].setStyleSheet("font-size: 11px; font-weight: 600; color: #10b981; background: rgba(16, 185, 129, 0.12); border: 1px solid rgba(16, 185, 129, 0.3); border-radius: 6px; padding: 3px 8px;")
                elif stage in {DeploymentStage.FAILED, DeploymentStage.ROLLING_BACK}:
                    self.chips[idx].setStyleSheet("font-size: 11px; font-weight: 600; color: #f43f5e; background: rgba(244, 63, 94, 0.12); border: 1px solid rgba(244, 63, 94, 0.3); border-radius: 6px; padding: 3px 8px;")
                else:
                    self.chips[idx].setStyleSheet("font-size: 11px; font-weight: 600; color: #a5b4fc; background: rgba(99, 102, 241, 0.2); border: 1px solid rgba(99, 102, 241, 0.5); border-radius: 6px; padding: 3px 8px;")
                break


class DeploymentPanel(QWidget):
    log_requested = Signal(str, str)
    save_requested = Signal(object)
    delete_requested = Signal(str)
    refresh_requested = Signal()
    connection_requested = Signal(object, str)
    connection_released = Signal(str)
    execution_started = Signal()
    execution_finished = Signal(object)
    build_output = Signal(str)
    stage_event = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.transfer_manager = None
        self.planner = DeploymentPlanner()
        self.executor = DeploymentExecutor()
        self.manual_rollback_service = ManualRollbackService()
        self.history_service: DeploymentHistoryService | None = None
        self._jobs: list[DeploymentJob] = []
        self._profiles: list[ConnectionProfile] = []
        self._workers: list[AsyncWorker] = []
        self._owned_profile_id: str | None = None
        self._execution_active = False
        self._cancel_available = False
        self._cancel_requested = False
        self._active_run_id: str | None = None
        self._pending_artifact: DeploymentArtifact | None = None

        self.saved_jobs = QComboBox()
        self.saved_jobs.addItem("New deployment", None)
        self.profile = QComboBox()
        self.name = QLineEdit()
        self.name.setPlaceholderText("Production website")
        self.template = QComboBox()
        for template in DEPLOYMENT_TEMPLATES:
            self.template.addItem(template.name, template)
        self.mode = QComboBox()
        self.mode.addItem("Upload only (preserve remote-only files)", DeploymentMode.UPLOAD_ONLY.value)
        self.mode.addItem("Mirror (delete remote-only files)", DeploymentMode.MIRROR.value)
        self.strategy = QComboBox()
        self.strategy.addItem("In-place deployment", DeploymentStrategy.IN_PLACE.value)
        self.strategy.addItem("Atomic release (opt-in)", DeploymentStrategy.ATOMIC_RELEASE.value)

        self.project_folder = QLineEdit(str(Path.home()))
        self.build_folder = QLineEdit(str(Path.home()))
        self.remote_target = QLineEdit()
        self.remote_target.setPlaceholderText("/var/www/example")
        self.ignore_patterns = QTextEdit(".git, node_modules, .env, __pycache__, .DS_Store")
        self.ignore_patterns.setMaximumHeight(58)
        self.backup_directory = QLineEdit()
        self.backup_directory.setPlaceholderText("Optional absolute override outside target")
        self.retention = QSpinBox()
        self.retention.setRange(1, 50)
        self.retention.setValue(5)
        self.release_retention = QSpinBox()
        self.release_retention.setRange(1, 50)
        self.release_retention.setValue(5)

        self.run_build = QCheckBox("Run local build before preview and deployment")
        self.build_command = QLineEdit()
        self.build_command.setPlaceholderText("npm run build")
        self.chmod_enabled = QCheckBox("Apply recursive chmod after uploads")
        self.chmod_mode = QLineEdit("755")
        self.chmod_mode.setMaximumWidth(90)
        self.post_command = QLineEdit()
        self.post_command.setPlaceholderText("npm ci --omit=dev")
        self.cache_command = QLineEdit()
        self.cache_command.setPlaceholderText("Optional cache clear command")
        self.restart_command = QLineEdit()
        self.restart_command.setPlaceholderText("systemctl restart your-app")
        self.health_command = QLineEdit()
        self.health_command.setPlaceholderText("Optional remote command, for example: test -f public/index.html")
        self.health_url = QLineEdit()
        self.health_url.setPlaceholderText("Optional URL, for example: https://example.com/health")
        self.health_origin = QComboBox()
        self.health_origin.addItem("Desktop HTTP request", HealthCheckOrigin.DESKTOP.value)
        self.health_origin.addItem("Remote curl request", HealthCheckOrigin.REMOTE.value)
        self.health_attempts = QSpinBox()
        self.health_attempts.setRange(1, 10)
        self.health_attempts.setValue(3)
        self.health_timeout = QSpinBox()
        self.health_timeout.setRange(1, 300)
        self.health_timeout.setValue(10)
        self.health_interval = QSpinBox()
        self.health_interval.setRange(0, 60)
        self.health_interval.setValue(2)
        self.health_min_status = QSpinBox()
        self.health_min_status.setRange(100, 599)
        self.health_min_status.setValue(200)
        self.health_max_status = QSpinBox()
        self.health_max_status.setRange(100, 599)
        self.health_max_status.setValue(399)
        self.health_expected_text = QLineEdit()
        self.health_expected_text.setPlaceholderText("Optional response substring")
        self.health_verify_tls = QCheckBox("Verify HTTPS certificates")
        self.health_verify_tls.setChecked(True)

        self.browse_project = QPushButton("Browse")
        self.browse_build = QPushButton("Browse")
        self.preview_button = QPushButton("Preview")
        self.preview_button.setIcon(get_icon("search", size=14))
        self.save_button = QPushButton("Save Job")
        self.save_button.setIcon(get_icon("folder", size=14))
        self.delete_button = QPushButton("Delete")
        self.delete_button.setIcon(get_icon("cancel", size=14))
        self.deploy_button = QPushButton("Deploy")
        self.deploy_button.setObjectName("PrimaryButton")
        self.deploy_button.setIcon(get_icon("deploy", color="#ffffff", size=14))
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setIcon(get_icon("cancel", size=14))
        self.cancel_button.setEnabled(False)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setIcon(get_icon("sync", size=14))
        self.history_refresh_button = QPushButton("Refresh History")
        self.history_refresh_button.setIcon(get_icon("sync", size=14))
        self.scan_artifacts_button = QPushButton("Scan Server")
        self.scan_artifacts_button.setIcon(get_icon("search", size=14))
        self.rollback_button = QPushButton("Rollback Selected")
        self.rollback_button.setIcon(get_icon("sync", size=14))
        self.status = QLabel("Choose a saved SSH/SFTP profile and build a fresh deployment preview.")
        self.status.setObjectName("MutedLabel")
        self.status.setWordWrap(True)

        self.model = DeploymentPreviewTableModel()
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.horizontalHeader().setStretchLastSection(True)

        self.build_log = QTextEdit()
        self.build_log.setReadOnly(True)
        self.build_log.setPlaceholderText("Redacted local build output appears here.")
        self.build_log.setStyleSheet("font-family: 'JetBrains Mono', monospace; font-size: 12px; background: #09090b;")

        self.run_model = DeploymentRunTableModel()
        self.run_table = QTableView()
        self.run_table.setModel(self.run_model)
        self.run_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.run_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.run_table.setShowGrid(False)
        self.run_table.verticalHeader().setVisible(False)
        self.run_table.verticalHeader().setDefaultSectionSize(32)
        self.run_table.horizontalHeader().setStretchLastSection(True)

        self.stage_details = QTextEdit()
        self.stage_details.setReadOnly(True)
        self.stage_details.setPlaceholderText("Select a deployment run to inspect ordered stages and redacted output.")
        self.stage_details.setStyleSheet("font-family: 'JetBrains Mono', monospace; font-size: 12px; background: #09090b;")

        self.artifact_model = DeploymentArtifactTableModel()
        self.artifact_table = QTableView()
        self.artifact_table.setModel(self.artifact_model)
        self.artifact_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.artifact_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.artifact_table.setShowGrid(False)
        self.artifact_table.verticalHeader().setVisible(False)
        self.artifact_table.verticalHeader().setDefaultSectionSize(32)
        self.artifact_table.horizontalHeader().setStretchLastSection(True)

        self.pipeline_ribbon = PipelineRibbonWidget()

        # Modern Header Frame
        header = QFrame()
        header.setObjectName("DeploymentHeader")
        header.setStyleSheet("""
            QFrame#DeploymentHeader {
                background: #111114;
                border: 0;
                border-bottom: 1px solid #1e1e24;
            }
            QFrame#DeploymentHeader QLabel {
                background: transparent;
                border: none;
            }
        """)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 10, 14, 10)
        header_layout.setSpacing(10)

        header_text = QVBoxLayout()
        header_text.setSpacing(2)
        h_title = QLabel("Deployment Studio")
        h_title.setStyleSheet("font-size: 16px; font-weight: 700; color: #f4f4f5;")
        h_sub = QLabel("Build, snapshot backup, atomic symlink release, and 1-click rollback")
        h_sub.setStyleSheet("font-size: 12px; color: #71717a;")
        header_text.addWidget(h_title)
        header_text.addWidget(h_sub)
        header_layout.addLayout(header_text)
        header_layout.addStretch()

        job_lbl = QLabel("Job:")
        job_lbl.setStyleSheet("background: transparent; border: none; color: #a1a1aa;")
        header_layout.addWidget(job_lbl)
        self.saved_jobs.setMinimumWidth(180)
        header_layout.addWidget(self.saved_jobs)
        header_layout.addWidget(self.refresh_button)
        header_layout.addWidget(self.save_button)
        header_layout.addWidget(self.delete_button)

        configuration = QTabWidget()
        configuration.addTab(self._paths_tab(), "Target && Files")
        configuration.addTab(self._commands_tab(), "Build && Commands")
        configuration.addTab(self._backup_tab(), "Backup && Safety")
        configuration.addTab(self._health_tab(), "Health Checks")

        top = QWidget()
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(10, 10, 10, 6)
        top_layout.setSpacing(10)
        top_layout.addWidget(self.pipeline_ribbon)
        top_layout.addWidget(configuration)
        top_layout.addLayout(self._actions())
        top_layout.addWidget(self.status)

        self.output_tabs = QTabWidget()
        self.output_tabs.addTab(self.table, "Preview")
        self.output_tabs.addTab(self.build_log, "Build Output")
        self.output_tabs.addTab(self._history_tab(), "History")

        top_scroll = QScrollArea()
        top_scroll.setWidgetResizable(True)
        top_scroll.setFrameShape(QFrame.Shape.NoFrame)
        top_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        top_scroll.setStyleSheet("background: transparent; border: none;")
        top_scroll.setWidget(top)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(top_scroll)
        splitter.addWidget(self.output_tabs)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([310, 520])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(header)
        layout.addWidget(splitter, 1)

        self.saved_jobs.currentIndexChanged.connect(self._load_selected_job)
        self.template.currentIndexChanged.connect(self._apply_selected_template)
        self.browse_project.clicked.connect(lambda: self._browse_folder(self.project_folder))
        self.browse_build.clicked.connect(lambda: self._browse_folder(self.build_folder))
        self.preview_button.clicked.connect(lambda: self._request_action("preview"))
        self.deploy_button.clicked.connect(lambda: self._request_action("deploy"))
        self.save_button.clicked.connect(lambda: self.save_requested.emit(self.current_job()))
        self.delete_button.clicked.connect(self._delete_selected)
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        self.history_refresh_button.clicked.connect(self.refresh_history)
        self.scan_artifacts_button.clicked.connect(self._scan_artifacts)
        self.rollback_button.clicked.connect(self._rollback_selected)
        self.cancel_button.clicked.connect(self.cancel)
        self.build_output.connect(self._append_build_output)
        self.stage_event.connect(self._show_stage)
        self.run_table.selectionModel().currentRowChanged.connect(self._show_selected_run)
        self.artifact_table.selectionModel().currentRowChanged.connect(lambda *_args: self._sync_rollback_enabled())
        self.health_verify_tls.toggled.connect(self._show_tls_warning)
        self._sync_enabled()

    def set_transfer_manager(self, transfer_manager) -> None:  # type: ignore[no-untyped-def]
        self.transfer_manager = transfer_manager
        self._sync_enabled()

    def set_history_service(self, history_service: DeploymentHistoryService) -> None:
        self.history_service = history_service
        self.refresh_history()

    def set_profiles(self, profiles: list[ConnectionProfile]) -> None:
        current_id = self.profile.currentData(USER_ROLE)
        self._profiles = [
            profile for profile in profiles if profile.protocol in {ProtocolType.SSH, ProtocolType.SFTP}
        ]
        self.profile.blockSignals(True)
        self.profile.clear()
        self.profile.addItem("Select saved SSH/SFTP profile", None)
        for profile in self._profiles:
            self.profile.addItem(f"{profile.name} - {profile.username}@{profile.host}", profile.id)
        if current_id:
            index = self.profile.findData(current_id, USER_ROLE)
            if index >= 0:
                self.profile.setCurrentIndex(index)
        self.profile.blockSignals(False)
        self._sync_enabled()

    def set_saved_jobs(self, jobs: list[DeploymentJob]) -> None:
        current_id = self._selected_job_id()
        self._jobs = jobs
        self.saved_jobs.blockSignals(True)
        self.saved_jobs.clear()
        self.saved_jobs.addItem("New deployment", None)
        for job in jobs:
            self.saved_jobs.addItem(job.name, job)
        if current_id:
            for index in range(self.saved_jobs.count()):
                candidate = self.saved_jobs.itemData(index, USER_ROLE)
                if getattr(candidate, "id", None) == current_id:
                    self.saved_jobs.setCurrentIndex(index)
                    break
        self.saved_jobs.blockSignals(False)
        self.refresh_history()

    def current_job(self) -> DeploymentJob:
        selected = self.saved_jobs.currentData(USER_ROLE)
        job_id = getattr(selected, "id", None) or str(uuid4())
        return DeploymentJob(
            id=job_id,
            name=self.name.text().strip() or "Untitled deployment",
            template=self.template.currentText(),
            profile_id=self.profile.currentData(USER_ROLE),
            mode=DeploymentMode(str(self.mode.currentData(USER_ROLE))),
            strategy=DeploymentStrategy(str(self.strategy.currentData(USER_ROLE))),
            local_project_folder=self.project_folder.text().strip(),
            local_build_folder=self.build_folder.text().strip(),
            remote_target_folder=self.remote_target.text().strip(),
            ignore_patterns=self._ignore_patterns(),
            run_local_build=self.run_build.isChecked(),
            local_build_command=self.build_command.text().strip(),
            chmod_enabled=self.chmod_enabled.isChecked(),
            chmod_mode=self.chmod_mode.text().strip() or "755",
            post_deploy_command=self.post_command.text().strip(),
            cache_clear_command=self.cache_command.text().strip(),
            restart_command=self.restart_command.text().strip(),
            backup_directory=self.backup_directory.text().strip(),
            backup_retention=self.retention.value(),
            release_retention=self.release_retention.value(),
            auto_rollback=True,
            health_check=HealthCheckConfig(
                command=self.health_command.text().strip(),
                http_url=self.health_url.text().strip(),
                http_origin=HealthCheckOrigin(str(self.health_origin.currentData(USER_ROLE))),
                attempts=self.health_attempts.value(),
                timeout_seconds=self.health_timeout.value(),
                interval_seconds=self.health_interval.value(),
                minimum_status=self.health_min_status.value(),
                maximum_status=self.health_max_status.value(),
                expected_substring=self.health_expected_text.text(),
                verify_tls=self.health_verify_tls.isChecked(),
            ),
        )

    def start_action(self, job: DeploymentJob, action: str, connection, *, owns_connection: bool) -> None:  # type: ignore[no-untyped-def]
        self._owned_profile_id = connection.profile.id if owns_connection else None
        if action == "scan_artifacts":
            self._start_artifact_scan(job, connection)
            return
        if action == "rollback":
            self._start_manual_rollback(job, connection)
            return
        self._cancel_available = True
        self._cancel_requested = False
        self._active_run_id = None
        if action == "deploy":
            self._active_run_id = self._start_history_run(job, connection, action="deploy")
        self._set_busy(True, "Running local build and creating a fresh preview..." if job.run_local_build else "Creating a fresh deployment preview...")
        self.build_log.clear()
        worker = AsyncWorker(lambda: self._prepare_preview(job, connection.file_operations(), action=action))
        self._workers.append(worker)
        worker.succeeded.connect(
            lambda result: self._preview_ready(result, job, action, connection)
        )
        worker.failed.connect(lambda result: self._action_failed(result, job=job))
        worker.finished.connect(lambda: self._finish_worker(worker))
        worker.start()

    def connection_failed(self, result: OperationResult) -> None:
        self._set_busy(False, result.message)
        self.log_requested.emit(result.message, "error")

    def cancel(self) -> None:
        if not self._cancel_available or self.transfer_manager is None:
            return
        self._cancel_requested = True
        self.status.setText("Cancelling deployment and preparing rollback...")
        AsyncRuntime.instance().submit(self.executor.cancel(self.transfer_manager))

    async def _prepare_preview(self, job: DeploymentJob, remote_ops, *, action: str) -> OperationResult:  # type: ignore[no-untyped-def]
        if job.run_local_build:
            self._record_stage(job, DeploymentStageEvent(job.id, DeploymentStage.BUILDING, "Running local build.", run_id=self._active_run_id))
            build = await self.executor.build_runner.run(
                job.local_build_command,
                working_directory=job.resolved_project_folder(),
                on_output=self.build_output.emit,
            )
            if not build.ok:
                return build
        if action == "deploy":
            self._record_stage(job, DeploymentStageEvent(job.id, DeploymentStage.PREVIEWING, "Building deployment preview.", run_id=self._active_run_id))
        return await self.planner.build_preview(job, remote_ops)

    def _preview_ready(
        self,
        result: OperationResult,
        job: DeploymentJob,
        action: str,
        connection,
    ) -> None:
        preview: DeploymentPreview = result.data
        self.model.set_preview(preview)
        if self._cancel_requested:
            self.status.setText("Deployment preparation cancelled before remote changes.")
            self._finish_active_history(
                job,
                DeploymentRunStatus.CANCELLED,
                "Deployment preparation cancelled before remote changes.",
            )
            self._cancel_available = False
            self._release_owned_connection()
            return
        self.status.setText(self._preview_summary(preview))
        self.log_requested.emit("Fresh deployment preview built.", "info")
        if action == "preview":
            self._cancel_available = False
            self._release_owned_connection()
            return
        if not self._confirm_deployment(job, preview):
            self.status.setText("Deployment cancelled before remote changes.")
            self._finish_active_history(
                job,
                DeploymentRunStatus.CANCELLED,
                "Deployment cancelled before remote changes.",
            )
            self._cancel_available = False
            self._release_owned_connection()
            return
        if self.transfer_manager is None:
            self._action_failed(OperationResult.failure("Transfer manager is unavailable."))
            return

        self._execution_active = True
        self._set_busy(True, "Deployment started. Creating remote backup...")
        self.execution_started.emit()
        self._run_execution(job, preview, connection)

    def _run_execution(
        self,
        job: DeploymentJob,
        preview: DeploymentPreview,
        connection,
        *,
        break_stale_lock: bool = False,
    ) -> None:  # type: ignore[no-untyped-def]
        worker = AsyncWorker(
            lambda: self.executor.execute(
                job,
                preview,
                connection,
                connection.file_operations(),
                self.transfer_manager,
                policy=DeploymentExecutionPolicy(
                    confirmed=True,
                    rollback_on_failure=True,
                    break_stale_lock=break_stale_lock,
                ),
                build_already_completed=job.run_local_build,
                run_id=self._active_run_id,
                history_service=self.history_service,
                on_stage=self.stage_event.emit,
            )
        )
        self._workers.append(worker)
        worker.succeeded.connect(self._execution_succeeded)
        worker.failed.connect(
            lambda result: self._execution_failed(result, job, preview, connection)
        )
        worker.finished.connect(lambda: self._finish_worker(worker))
        worker.start()

    def _execution_succeeded(self, result: OperationResult) -> None:
        data: DeploymentExecutionResult = result.data
        self.status.setText(
            f"Deployment complete | {data.uploads} uploads | {data.overwrites} overwrites | {data.deletes} deletes"
        )
        self.log_requested.emit(result.message, "info")
        for warning in result.warnings:
            self.log_requested.emit(warning, "warning")
        self._execution_active = False
        self._cancel_available = False
        self._cancel_requested = False
        self._active_run_id = None
        self.refresh_history()
        self.execution_finished.emit(result)
        self._release_owned_connection()

    def _execution_failed(
        self,
        result: OperationResult,
        job: DeploymentJob,
        preview: DeploymentPreview,
        connection,
    ) -> None:  # type: ignore[no-untyped-def]
        if isinstance(result.data, dict) and result.data.get("stale_lock"):
            answer = QMessageBox.question(
                self,
                "Remove stale deployment lock?",
                "The remote deployment lock is older than two hours.\n\n"
                "Remove it and rebuild the preview under a new lock?",
            )
            if answer == QMessageBox.StandardButton.Yes:
                self._active_run_id = self._start_history_run(job, connection, action="deploy")
                self._run_execution(job, preview, connection, break_stale_lock=True)
                return
        self._action_failed(result, job=job)

    def _action_failed(self, result: OperationResult, *, job: DeploymentJob | None = None) -> None:
        self.status.setText(result.message)
        level = "warning" if result.status.value == "cancelled" else "error"
        self.log_requested.emit(result.message, level)
        if result.technical_details:
            self.log_requested.emit(result.technical_details, "error")
        for warning in result.warnings:
            self.log_requested.emit(warning, "error")
        if self._execution_active:
            self._execution_active = False
            self.execution_finished.emit(result)
        if self._active_run_id and job is not None:
            status = (
                DeploymentRunStatus.CANCELLED
                if result.status.value == "cancelled"
                else DeploymentRunStatus.FAILED
            )
            self._finish_active_history(job, status, result.message)
        self._cancel_available = False
        self._cancel_requested = False
        self._active_run_id = None
        self.refresh_history()
        self._release_owned_connection()
        QMessageBox.warning(self, "Deployment did not complete", result.message)

    def _confirm_deployment(self, job: DeploymentJob, preview: DeploymentPreview) -> bool:
        commands = [
            command
            for command in [
                f"chmod -R {job.chmod_mode} ." if job.chmod_enabled else "",
                job.post_deploy_command,
                job.cache_clear_command,
                job.restart_command,
            ]
            if command
        ]
        command_summary = "\n".join(f"  - {command}" for command in commands) if commands else "  None"
        health_checks = []
        if job.health_check.command:
            health_checks.append("remote command")
        if job.health_check.http_url:
            health_checks.append(f"HTTP from {job.health_check.http_origin.value}")
        health_summary = ", ".join(health_checks) if health_checks else "disabled"
        message = (
            "Deploy this fresh plan?\n\n"
            f"Target: {preview.remote_root}\n"
            f"Mode: {job.mode.value.replace('_', ' ')}\n"
            f"Strategy: {job.strategy.value.replace('_', ' ')}\n"
            f"Uploads: {preview.uploads}\n"
            f"Overwrites: {preview.overwrites}\n"
            f"Deletes: {preview.deletes}\n"
            f"Transfer size: {human_size(preview.bytes_total)}\n"
            f"Backup: {preview.backup_archive_path if preview.target_exists else 'Target is new; rollback removes it'}\n"
            f"Health checks: {health_summary}\n\n"
            f"Remote commands:\n{command_summary}\n\n"
            "The preview is rebuilt after acquiring the deployment lock. Any transfer, command, "
            "restart, or health-check failure triggers automatic rollback."
        )
        return QMessageBox.question(self, "Confirm deployment", message) == QMessageBox.StandardButton.Yes

    def _load_selected_job(self) -> None:
        job = self.saved_jobs.currentData(USER_ROLE)
        if not isinstance(job, DeploymentJob):
            self.name.clear()
            self.model.set_preview(None)
            self.run_model.set_runs([])
            self.artifact_model.set_artifacts([])
            self.stage_details.clear()
            return
        self.name.setText(job.name)
        self._select_data(self.profile, job.profile_id)
        self._select_data(self.mode, job.mode.value)
        self._select_data(self.strategy, job.strategy.value)
        self.template.blockSignals(True)
        self.template.setCurrentText(job.template)
        self.template.blockSignals(False)
        self.project_folder.setText(job.local_project_folder)
        self.build_folder.setText(job.local_build_folder)
        self.remote_target.setText(job.remote_target_folder)
        self.ignore_patterns.setPlainText(", ".join(job.ignore_patterns))
        self.run_build.setChecked(job.run_local_build)
        self.build_command.setText(job.local_build_command)
        self.chmod_enabled.setChecked(job.chmod_enabled)
        self.chmod_mode.setText(job.chmod_mode)
        self.post_command.setText(job.post_deploy_command)
        self.cache_command.setText(job.cache_clear_command)
        self.restart_command.setText(job.restart_command)
        self.backup_directory.setText(job.backup_directory)
        self.retention.setValue(job.backup_retention)
        self.release_retention.setValue(job.release_retention)
        self.health_command.setText(job.health_check.command)
        self.health_url.setText(job.health_check.http_url)
        self._select_data(self.health_origin, job.health_check.http_origin.value)
        self.health_attempts.setValue(job.health_check.attempts)
        self.health_timeout.setValue(job.health_check.timeout_seconds)
        self.health_interval.setValue(job.health_check.interval_seconds)
        self.health_min_status.setValue(job.health_check.minimum_status)
        self.health_max_status.setValue(job.health_check.maximum_status)
        self.health_expected_text.setText(job.health_check.expected_substring)
        self.health_verify_tls.setChecked(job.health_check.verify_tls)
        self.model.set_preview(None)
        self.refresh_history()

    def _apply_selected_template(self) -> None:
        template = deployment_template(self.template.currentText())
        self.build_command.setText(template.build_command)
        self.post_command.setText(template.post_deploy_command)
        self.restart_command.setText(template.restart_command)
        self.ignore_patterns.setPlainText(", ".join(template.ignore_patterns))
        if template.build_folder:
            project = Path(self.project_folder.text() or Path.home())
            self.build_folder.setText(str(project / template.build_folder))
        self.run_build.setChecked(False)

    def _show_stage(self, event: DeploymentStageEvent) -> None:
        self.status.setText(event.message)
        self.log_requested.emit(event.message, event.level)
        self.pipeline_ribbon.set_stage(event.stage)

    def _append_build_output(self, line: str) -> None:
        self.build_log.append(line)
        if self.history_service and self._active_run_id:
            self.history_service.append_stage_output(self._active_run_id, line)

    def _record_stage(self, job: DeploymentJob, event: DeploymentStageEvent) -> None:
        if self.history_service and event.run_id:
            self.history_service.begin_stage(event)
        self.stage_event.emit(event)

    def _start_history_run(self, job: DeploymentJob, connection, *, action: str) -> str | None:  # type: ignore[no-untyped-def]
        if self.history_service is None:
            return None
        profile = connection.profile
        run = DeploymentRun(
            job_id=job.id,
            profile_id=job.profile_id,
            profile_name=profile.name,
            host=profile.host,
            remote_target=job.remote_target_folder,
            strategy=job.strategy,
            action=action,
        )
        self.history_service.start_run(run)
        return run.id

    def _finish_active_history(
        self,
        job: DeploymentJob,
        status: DeploymentRunStatus,
        message: str,
        *,
        rolled_back: bool = False,
        rollback_error: str | None = None,
        health_ok: bool | None = None,
        artifact_path: str | None = None,
    ) -> None:
        if not self.history_service or not self._active_run_id:
            return
        self.history_service.finish_run(
            self._active_run_id,
            status=status,
            message=message,
            rolled_back=rolled_back,
            rollback_error=rollback_error,
            health_ok=health_ok,
            artifact_path=artifact_path,
            retention=job.history_retention,
        )

    def refresh_history(self) -> None:
        job = self.saved_jobs.currentData(USER_ROLE)
        if not isinstance(job, DeploymentJob) or self.history_service is None:
            self.run_model.set_runs([])
            self.artifact_model.set_artifacts([])
            self.stage_details.clear()
            self._sync_rollback_enabled()
            return
        self.run_model.set_runs(self.history_service.list_runs(job.id, limit=job.history_retention))
        self.artifact_model.set_artifacts(self.history_service.list_artifacts(job.id))
        self._sync_rollback_enabled()

    def _show_selected_run(self, current: QModelIndex, _previous: QModelIndex) -> None:
        run = self.run_model.run_at(current.row())
        if run is None or self.history_service is None:
            self.stage_details.clear()
            return
        lines = [
            f"{run.status.value.replace('_', ' ').title()} | {run.profile_name} | {run.remote_target}",
            f"Strategy: {run.strategy.value.replace('_', ' ')}",
            f"Files: {run.uploads} upload, {run.overwrites} overwrite, {run.deletes} delete",
            f"Message: {run.message or '-'}",
            "",
        ]
        for stage in self.history_service.list_stages(run.id):
            duration = ""
            if stage.finished_at:
                duration = f" ({max(0.0, (stage.finished_at - stage.started_at).total_seconds()):.2f}s)"
            lines.append(f"[{stage.sequence + 1}] {stage.stage.value.replace('_', ' ').title()}{duration}")
            lines.append(stage.message)
            if stage.output_excerpt:
                lines.append(stage.output_excerpt)
            lines.append("")
        self.stage_details.setPlainText("\n".join(lines))

    def _scan_artifacts(self) -> None:
        job = self.saved_jobs.currentData(USER_ROLE)
        if not isinstance(job, DeploymentJob) or not job.profile_id:
            QMessageBox.information(self, "Select a deployment", "Choose a saved deployment job first.")
            return
        self._set_busy(True, "Opening the server to scan deployment artifacts...")
        self.connection_requested.emit(job, "scan_artifacts")

    def _start_artifact_scan(self, job: DeploymentJob, connection) -> None:  # type: ignore[no-untyped-def]
        self._set_busy(True, "Scanning remote backups and releases...")
        worker = AsyncWorker(lambda: self.manual_rollback_service.scan_artifacts(job, connection))
        self._workers.append(worker)
        worker.succeeded.connect(lambda result: self._artifact_scan_ready(result, job))
        worker.failed.connect(lambda result: self._action_failed(result, job=job))
        worker.finished.connect(lambda: self._finish_worker(worker))
        worker.start()

    def _artifact_scan_ready(self, result: OperationResult, job: DeploymentJob) -> None:
        if self.history_service:
            for artifact in result.data or []:
                self.history_service.add_artifact(artifact)
        self.status.setText("Deployment artifacts refreshed from the server.")
        self.refresh_history()
        self._release_owned_connection()

    def _rollback_selected(self) -> None:
        job = self.saved_jobs.currentData(USER_ROLE)
        row = self.artifact_table.currentIndex().row()
        artifact = self.artifact_model.artifact_at(row)
        if not isinstance(job, DeploymentJob) or artifact is None:
            QMessageBox.information(self, "Select an artifact", "Select a backup or release to restore.")
            return
        if artifact.active:
            QMessageBox.information(self, "Already active", "The selected release is already active.")
            return
        expected_kind = (
            DeploymentArtifactKind.RELEASE
            if job.strategy == DeploymentStrategy.ATOMIC_RELEASE
            else DeploymentArtifactKind.BACKUP
        )
        if artifact.kind != expected_kind:
            QMessageBox.warning(
                self,
                "Artifact is incompatible",
                f"{job.strategy.value.replace('_', ' ').title()} rollback requires a "
                f"{expected_kind.value} artifact.",
            )
            return
        answer = QMessageBox.question(
            self,
            "Confirm manual rollback",
            f"Restore this {artifact.kind.value}?\n\n{artifact.path}\n\n"
            "The current deployment will be preserved first. Restart, cache, and health checks "
            "will run after the switch.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._pending_artifact = artifact
        self._set_busy(True, "Opening the server for manual rollback...")
        self.connection_requested.emit(job, "rollback")

    def _start_manual_rollback(self, job: DeploymentJob, connection) -> None:  # type: ignore[no-untyped-def]
        if self._pending_artifact is None:
            self._action_failed(OperationResult.failure("No rollback artifact was selected."), job=job)
            return
        self._active_run_id = self._start_history_run(job, connection, action="manual_rollback")
        self._execution_active = True
        self._cancel_available = False
        self.execution_started.emit()
        self._run_manual_rollback(job, connection)

    def _run_manual_rollback(
        self,
        job: DeploymentJob,
        connection,
        *,
        break_stale_lock: bool = False,
    ) -> None:  # type: ignore[no-untyped-def]
        artifact = self._pending_artifact
        if artifact is None or not self._active_run_id:
            self._action_failed(OperationResult.failure("Rollback state is incomplete."), job=job)
            return
        worker = AsyncWorker(
            lambda: self.manual_rollback_service.rollback(
                job,
                artifact,
                connection,
                run_id=self._active_run_id,
                break_stale_lock=break_stale_lock,
                history_service=self.history_service,
                on_stage=self.stage_event.emit,
            )
        )
        self._workers.append(worker)
        worker.succeeded.connect(lambda result: self._manual_rollback_succeeded(result, job))
        worker.failed.connect(
            lambda result: self._manual_rollback_failed(result, job, connection)
        )
        worker.finished.connect(lambda: self._finish_worker(worker))
        worker.start()

    def _manual_rollback_succeeded(self, result: OperationResult, job: DeploymentJob) -> None:
        data = result.data if isinstance(result.data, DeploymentExecutionResult) else None
        self._finish_active_history(
            job,
            DeploymentRunStatus.ROLLED_BACK,
            result.message,
            rolled_back=True,
            health_ok=data.health_check.ok if data and data.health_check else None,
            artifact_path=data.release_path or data.backup_path if data else None,
        )
        self.status.setText(result.message)
        self.log_requested.emit(result.message, "info")
        self._execution_active = False
        self._active_run_id = None
        self._pending_artifact = None
        self.refresh_history()
        self.execution_finished.emit(result)
        self._release_owned_connection()

    def _manual_rollback_failed(
        self,
        result: OperationResult,
        job: DeploymentJob,
        connection,
    ) -> None:  # type: ignore[no-untyped-def]
        if isinstance(result.data, dict) and result.data.get("stale_lock"):
            answer = QMessageBox.question(
                self,
                "Remove stale deployment lock?",
                "The rollback lock is stale. Remove it and retry the rollback?",
            )
            if answer == QMessageBox.StandardButton.Yes:
                self._finish_active_history(job, DeploymentRunStatus.FAILED, result.message)
                self._active_run_id = self._start_history_run(job, connection, action="manual_rollback")
                self._run_manual_rollback(job, connection, break_stale_lock=True)
                return
        data = result.data if isinstance(result.data, DeploymentExecutionResult) else None
        self._finish_active_history(
            job,
            DeploymentRunStatus.ROLLBACK_FAILED if data and data.rollback_error else DeploymentRunStatus.FAILED,
            result.message,
            rolled_back=bool(data and data.rolled_back),
            rollback_error=data.rollback_error if data else None,
            health_ok=data.health_check.ok if data and data.health_check else None,
        )
        self._pending_artifact = None
        self._action_failed(result, job=None)

    def _sync_rollback_enabled(self) -> None:
        artifact = self.artifact_model.artifact_at(self.artifact_table.currentIndex().row())
        self.rollback_button.setEnabled(artifact is not None and not artifact.active)

    def _show_tls_warning(self, checked: bool) -> None:
        if not checked and self.health_url.text().strip().lower().startswith("https://"):
            self.status.setText("Warning: TLS certificate verification is disabled for the health check.")

    def _finish_worker(self, worker: AsyncWorker) -> None:
        if worker in self._workers:
            self._workers.remove(worker)
        if not self._workers and not self._execution_active:
            self._set_busy(False)

    def _release_owned_connection(self) -> None:
        if self._owned_profile_id:
            self.connection_released.emit(self._owned_profile_id)
            self._owned_profile_id = None

    def _request_action(self, action: str) -> None:
        job = self.current_job()
        if not job.profile_id:
            QMessageBox.information(self, "Select a server", "Choose a saved SSH/SFTP profile for this deployment.")
            return
        if self.transfer_manager is None:
            QMessageBox.warning(self, "Deployment unavailable", "Transfer services are not ready.")
            return
        self._set_busy(True, "Preparing deployment connection...")
        self.connection_requested.emit(job, action)

    def _delete_selected(self) -> None:
        job_id = self._selected_job_id()
        if job_id:
            self.delete_requested.emit(job_id)

    def _selected_job_id(self) -> str | None:
        job = self.saved_jobs.currentData(USER_ROLE)
        return getattr(job, "id", None)

    def _ignore_patterns(self) -> list[str]:
        text = self.ignore_patterns.toPlainText()
        return [
            item
            for item in (part.strip() for line in text.splitlines() for part in line.split(","))
            if item
        ]

    def _preview_summary(self, preview: DeploymentPreview) -> str:
        return (
            f"Upload {preview.uploads} | Overwrite {preview.overwrites} | Delete {preview.deletes} | "
            f"Size {human_size(preview.bytes_total)} | Digest {preview.calculated_digest()[:10]}"
        )

    def _set_busy(self, busy: bool, message: str | None = None) -> None:
        for widget in [
            self.saved_jobs,
            self.profile,
            self.preview_button,
            self.save_button,
            self.delete_button,
            self.deploy_button,
            self.refresh_button,
            self.history_refresh_button,
            self.scan_artifacts_button,
            self.rollback_button,
        ]:
            widget.setEnabled(not busy)
        self.cancel_button.setEnabled(busy and self._cancel_available)
        if message:
            self.status.setText(message)
        if not busy:
            self._sync_enabled()

    def _sync_enabled(self) -> None:
        available = self.transfer_manager is not None
        self.preview_button.setEnabled(available)
        self.deploy_button.setEnabled(available)
        selected = isinstance(self.saved_jobs.currentData(USER_ROLE), DeploymentJob)
        self.history_refresh_button.setEnabled(selected and self.history_service is not None)
        self.scan_artifacts_button.setEnabled(selected)
        self._sync_rollback_enabled()

    def _browse_folder(self, target: QLineEdit) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose deployment folder", target.text())
        if path:
            target.setText(path)

    def _select_data(self, combo: QComboBox, value) -> None:  # type: ignore[no-untyped-def]
        index = combo.findData(value, USER_ROLE)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _saved_bar(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.addWidget(QLabel("Saved job"))
        layout.addWidget(self.saved_jobs, 1)
        layout.addWidget(self.refresh_button)
        layout.addWidget(self.delete_button)
        return layout

    def _paths_tab(self) -> QWidget:
        widget = QWidget()
        layout = QGridLayout(widget)
        layout.addWidget(QLabel("Name"), 0, 0)
        layout.addWidget(self.name, 0, 1)
        layout.addWidget(QLabel("Server"), 0, 2)
        layout.addWidget(self.profile, 0, 3)
        layout.addWidget(QLabel("Preset"), 1, 0)
        layout.addWidget(self.template, 1, 1)
        layout.addWidget(QLabel("Mode"), 1, 2)
        layout.addWidget(self.mode, 1, 3)
        layout.addWidget(QLabel("Release strategy"), 2, 0)
        layout.addWidget(self.strategy, 2, 1, 1, 3)
        layout.addWidget(QLabel("Project folder"), 3, 0)
        layout.addWidget(self.project_folder, 3, 1, 1, 2)
        layout.addWidget(self.browse_project, 3, 3)
        layout.addWidget(QLabel("Build/upload folder"), 4, 0)
        layout.addWidget(self.build_folder, 4, 1, 1, 2)
        layout.addWidget(self.browse_build, 4, 3)
        layout.addWidget(QLabel("Remote target"), 5, 0)
        layout.addWidget(self.remote_target, 5, 1, 1, 3)
        layout.addWidget(QLabel("Ignore rules"), 6, 0)
        layout.addWidget(self.ignore_patterns, 6, 1, 1, 3)
        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(3, 1)
        return widget

    def _commands_tab(self) -> QWidget:
        widget = QWidget()
        layout = QFormLayout(widget)
        layout.addRow(self.run_build)
        layout.addRow("Local build command", self.build_command)
        chmod = QWidget()
        chmod_layout = QHBoxLayout(chmod)
        chmod_layout.setContentsMargins(0, 0, 0, 0)
        chmod_layout.addWidget(self.chmod_enabled)
        chmod_layout.addWidget(self.chmod_mode)
        chmod_layout.addStretch()
        layout.addRow("Permissions", chmod)
        layout.addRow("Post-deploy", self.post_command)
        layout.addRow("Cache clear", self.cache_command)
        layout.addRow("Restart", self.restart_command)
        return widget

    def _backup_tab(self) -> QWidget:
        widget = QWidget()
        layout = QFormLayout(widget)
        automatic = QLabel(
            "Automatic rollback is always enabled. In-place jobs restore archives. Atomic jobs stage "
            "releases and switch the target symlink only after transfers and pre-switch commands pass."
        )
        automatic.setWordWrap(True)
        automatic.setObjectName("MutedLabel")
        layout.addRow(automatic)
        layout.addRow("Backup directory override", self.backup_directory)
        layout.addRow("Successful backups to keep", self.retention)
        layout.addRow("Atomic releases to keep", self.release_retention)
        return widget

    def _health_tab(self) -> QWidget:
        widget = QWidget()
        layout = QFormLayout(widget)
        description = QLabel(
            "Command checks run first. HTTP checks retry after the release is active; exhausted checks "
            "trigger automatic rollback."
        )
        description.setWordWrap(True)
        description.setObjectName("MutedLabel")
        layout.addRow(description)
        layout.addRow("Remote command", self.health_command)
        layout.addRow("HTTP URL", self.health_url)
        layout.addRow("HTTP origin", self.health_origin)
        retry_row = QWidget()
        retry_layout = QHBoxLayout(retry_row)
        retry_layout.setContentsMargins(0, 0, 0, 0)
        retry_layout.addWidget(QLabel("Attempts"))
        retry_layout.addWidget(self.health_attempts)
        retry_layout.addWidget(QLabel("Timeout (s)"))
        retry_layout.addWidget(self.health_timeout)
        retry_layout.addWidget(QLabel("Interval (s)"))
        retry_layout.addWidget(self.health_interval)
        retry_layout.addStretch()
        layout.addRow("Retry policy", retry_row)
        status_row = QWidget()
        status_layout = QHBoxLayout(status_row)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.addWidget(self.health_min_status)
        status_layout.addWidget(QLabel("to"))
        status_layout.addWidget(self.health_max_status)
        status_layout.addStretch()
        layout.addRow("Accepted status", status_row)
        layout.addRow("Expected response text", self.health_expected_text)
        layout.addRow(self.health_verify_tls)
        return widget

    def _history_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        toolbar = QHBoxLayout()
        toolbar.addWidget(self.history_refresh_button)
        toolbar.addWidget(self.scan_artifacts_button)
        toolbar.addStretch()
        toolbar.addWidget(self.rollback_button)
        layout.addLayout(toolbar)

        run_splitter = QSplitter(Qt.Orientation.Vertical)
        run_splitter.addWidget(self.run_table)
        run_splitter.addWidget(self.stage_details)
        run_splitter.setStretchFactor(0, 1)
        run_splitter.setStretchFactor(1, 1)

        history_splitter = QSplitter(Qt.Orientation.Vertical)
        history_splitter.addWidget(run_splitter)
        history_splitter.addWidget(self.artifact_table)
        history_splitter.setStretchFactor(0, 2)
        history_splitter.setStretchFactor(1, 1)
        history_splitter.setSizes([420, 180])
        layout.addWidget(history_splitter, 1)
        return widget

    def _actions(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(10)
        self.preview_button.setStyleSheet("QPushButton { background: #18181b; color: #e4e4e7; border: 1px solid #27272a; border-radius: 6px; height: 32px; padding: 0 14px; } QPushButton:hover { background: #27272a; }")
        self.save_button.setStyleSheet("QPushButton { background: #18181b; color: #e4e4e7; border: 1px solid #27272a; border-radius: 6px; height: 32px; padding: 0 14px; } QPushButton:hover { background: #27272a; }")
        self.cancel_button.setStyleSheet("QPushButton { background: transparent; color: #f43f5e; border: 1px solid rgba(244, 63, 94, 0.4); border-radius: 6px; height: 32px; padding: 0 12px; }")
        self.deploy_button.setStyleSheet("QPushButton { background: #6366f1; color: #ffffff; font-weight: 600; border-radius: 6px; height: 32px; padding: 0 20px; } QPushButton:hover { background: #4f46e5; }")

        layout.addWidget(self.preview_button)
        layout.addWidget(self.save_button)
        layout.addStretch()
        layout.addWidget(self.cancel_button)
        layout.addWidget(self.deploy_button)
        return layout
