from __future__ import annotations

from typing import Any

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.result import OperationResult
from core.services_manager import (
    SERVICE_INVENTORY_COMMAND,
    ServiceInventorySnapshot,
    ServiceJournalEntry,
    ServiceUnitInfo,
    SystemdServicesCollector,
    control_service,
    daemon_reload,
    fetch_unit_logs,
    fetch_unit_properties,
    install_unit_file,
)
from ui.async_worker import AsyncWorker
from ui.icons import get_icon
from ui.services_components import (
    NewUnitModalDialog,
    ServiceCardWidget,
    ServiceDenseTableView,
    ServiceInspectorWidget,
)


class ServicesHeader(QWidget):
    """Header toolbar for the Systemd Services Manager."""

    view_changed = Signal(str)        # "split" or "table"
    daemon_reload_clicked = Signal()
    new_unit_clicked = Signal()
    refresh_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._view_mode = "split"

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 10)
        layout.setSpacing(12)

        # Left: Icon + Title + Status + Meta
        left_box = QHBoxLayout()
        left_box.setSpacing(10)

        icon_box = QLabel()
        icon_box.setFixedSize(32, 32)
        pix = get_icon("services").pixmap(20, 20)
        icon_box.setPixmap(pix)
        icon_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_box.setStyleSheet(
            "background-color: rgba(99, 102, 241, 0.15); border: 1px solid rgba(99, 102, 241, 0.35); border-radius: 8px;"
        )
        left_box.addWidget(icon_box)

        titles_box = QVBoxLayout()
        titles_box.setSpacing(2)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        self.title_label = QLabel("Systemd Services Manager")
        self.title_label.setStyleSheet("font-size: 15px; font-weight: 700; color: #ffffff;")
        top_row.addWidget(self.title_label)

        self.status_badge = QLabel("● systemd (PID 1) Active")
        self.status_badge.setStyleSheet(
            "background-color: rgba(16, 185, 129, 0.15); border: 1px solid rgba(16, 185, 129, 0.35); border-radius: 10px; "
            "padding: 2px 9px; font-size: 11px; font-weight: 700; color: #34d399;"
        )
        top_row.addWidget(self.status_badge)
        top_row.addStretch(1)
        titles_box.addLayout(top_row)

        self.meta_label = QLabel("No server connected • Disconnected")
        self.meta_label.setStyleSheet("font-size: 11px; font-family: monospace; color: #cbd5e1; font-weight: 500;")
        titles_box.addWidget(self.meta_label)

        left_box.addLayout(titles_box)
        layout.addLayout(left_box)

        layout.addStretch(1)

        # Right Controls: View Switcher, Daemon Reload, + New Unit, Refresh
        controls = QHBoxLayout()
        controls.setSpacing(8)

        # View Mode Switcher
        self.btn_split = QPushButton("Split View")
        self.btn_table = QPushButton("Dense Table")
        for b, mode in ((self.btn_split, "split"), (self.btn_table, "table")):
            b.setCheckable(True)
            b.setStyleSheet(
                """
                QPushButton {
                    background-color: #171720;
                    border: 1px solid #2b2b3a;
                    border-radius: 6px;
                    padding: 4px 10px;
                    font-size: 11px;
                    color: #94a3b8;
                    font-weight: 600;
                }
                QPushButton:checked {
                    background-color: #2b2b3a;
                    color: #ffffff;
                    border-color: #434358;
                }
                """
            )
            b.clicked.connect((lambda m=mode: lambda: self._on_view_mode_changed(m))())
            controls.addWidget(b)
        self.btn_split.setChecked(True)

        # Daemon Reload Button
        self.reload_btn = QPushButton("🔄 Daemon-Reload")
        self.reload_btn.setToolTip("Execute 'systemctl daemon-reload' to reload updated unit files")
        self.reload_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #171720;
                border: 1px solid #2b2b3a;
                border-radius: 6px;
                padding: 4px 12px;
                font-size: 11px;
                color: #e2e8f0;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #232330;
                color: #ffffff;
                border-color: #3b3b4f;
            }
            """
        )
        self.reload_btn.clicked.connect(self.daemon_reload_clicked.emit)
        controls.addWidget(self.reload_btn)

        # New Unit Button
        self.new_btn = QPushButton("+ New Service Unit")
        self.new_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #6366f1;
                border: none;
                border-radius: 6px;
                padding: 5px 14px;
                font-size: 11px;
                color: #ffffff;
                font-weight: 700;
            }
            QPushButton:hover {
                background-color: #4f46e5;
            }
            """
        )
        self.new_btn.clicked.connect(self.new_unit_clicked.emit)
        controls.addWidget(self.new_btn)

        layout.addLayout(controls)

    def set_host_info(self, host_label: str, target: str = "graphical.target") -> None:
        self.meta_label.setText(f"{host_label} • Target: {target}")

    def _on_view_mode_changed(self, mode: str) -> None:
        self._view_mode = mode
        self.btn_split.setChecked(mode == "split")
        self.btn_table.setChecked(mode == "table")
        self.view_changed.emit(mode)


class ServicesPanel(QWidget):
    """
    Main Systemd Services Manager Panel with split cards list,
    deep CGroup inspector, live journal stream, dense table view, and unit installer.
    """

    connect_requested = Signal()
    edit_unit_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ServicesPanel")
        self.setStyleSheet(
            """
            QWidget#ServicesPanel {
                background-color: #0c0c11;
            }
            """
        )

        self._connection: Any | None = None
        self._profile: Any | None = None
        self._snapshot: ServiceInventorySnapshot | None = None
        self._selected_unit: str = ""
        self._active_category: str = "all"
        self._search_query: str = ""
        self._cached_properties: dict[str, dict[str, str]] = {}
        self._workers: list[AsyncWorker] = []

        self._inventory_worker: AsyncWorker | None = None
        self._action_worker: AsyncWorker | None = None
        self._logs_worker: AsyncWorker | None = None
        self._props_worker: AsyncWorker | None = None

        self.stack = QStackedWidget(self)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(0)
        main_layout.addWidget(self.stack)

        self._build_empty_view()
        self._build_services_view()

        self.stack.setCurrentIndex(0)

    def _build_empty_view(self) -> None:
        empty = QWidget()
        empty.setObjectName("EmptyServicesView")
        empty.setStyleSheet("background: transparent;")
        l = QVBoxLayout(empty)
        l.setAlignment(Qt.AlignmentFlag.AlignCenter)
        l.setSpacing(0)

        card = QFrame()
        card.setObjectName("EmptyStateCard")
        card.setFixedWidth(520)
        card.setStyleSheet(
            """
            QFrame#EmptyStateCard {
                background-color: #15151c;
                border: 1px solid #262634;
                border-radius: 16px;
            }
            """
        )
        card_l = QVBoxLayout(card)
        card_l.setContentsMargins(36, 36, 36, 36)
        card_l.setSpacing(14)

        icon_lbl = QLabel()
        icon_lbl.setObjectName("EmptyIcon")
        icon_lbl.setFixedSize(52, 52)
        pix = get_icon("services").pixmap(30, 30)
        icon_lbl.setPixmap(pix)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet(
            """
            QLabel#EmptyIcon {
                background-color: rgba(99, 102, 241, 0.15);
                border: 1px solid rgba(99, 102, 241, 0.35);
                border-radius: 14px;
            }
            """
        )
        card_l.addWidget(icon_lbl, 0, Qt.AlignmentFlag.AlignCenter)

        title = QLabel("Systemd Services Manager")
        title.setStyleSheet(
            "font-size: 17px; font-weight: 700; color: #ffffff; background: transparent; border: none; padding: 0;"
        )
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_l.addWidget(title)

        desc = QLabel(
            "Connect to an SSH host to inspect real-time systemd service states, "
            "control daemons with 1-click start/stop/reload, manage boot persistence, "
            "and stream live journalctl logs without installing anything on the remote host."
        )
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setStyleSheet(
            "font-size: 13px; color: #94a3b8; background: transparent; border: none; padding: 0 16px;"
        )
        card_l.addWidget(desc)

        card_l.addSpacing(6)

        connect_btn = QPushButton("Go to Connections")
        connect_btn.setFixedSize(180, 38)
        connect_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #6366f1;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                font-size: 13px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #4f46e5;
            }
            """
        )
        connect_btn.clicked.connect(self.connect_requested.emit)
        card_l.addWidget(connect_btn, 0, Qt.AlignmentFlag.AlignCenter)

        l.addWidget(card)
        self.stack.addWidget(empty)

    def _build_services_view(self) -> None:
        view = QWidget()
        view.setObjectName("ServicesContentView")
        view.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(view)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # 1. Header Toolbar
        self.header = ServicesHeader(self)
        self.header.view_changed.connect(self._on_view_mode_changed)
        self.header.daemon_reload_clicked.connect(self._on_daemon_reload_clicked)
        self.header.new_unit_clicked.connect(self._on_new_unit_clicked)
        layout.addWidget(self.header)

        # 2. KPI Summary Strip & Filter Search Bar
        kpi_bar = QHBoxLayout()
        kpi_bar.setSpacing(8)

        self.kpi_total = QPushButton("Total: 0")
        self.kpi_running = QPushButton("● Running: 0")
        self.kpi_stopped = QPushButton("Stopped: 0")
        self.kpi_failed = QPushButton("● Failed: 0")
        self.kpi_boot = QPushButton("★ Boot Enabled: 0")

        self.kpi_total.setStyleSheet("background-color: #171720; border: 1px solid #2b2b3a; color: #cbd5e1; border-radius: 6px; padding: 3px 9px; font-size: 11px; font-weight: 600;")
        self.kpi_running.setStyleSheet("background-color: rgba(16, 185, 129, 0.12); border: 1px solid rgba(16, 185, 129, 0.3); color: #34d399; border-radius: 6px; padding: 3px 9px; font-size: 11px; font-weight: 600;")
        self.kpi_stopped.setStyleSheet("background-color: #171720; border: 1px solid #2b2b3a; color: #94a3b8; border-radius: 6px; padding: 3px 9px; font-size: 11px; font-weight: 600;")
        self.kpi_failed.setStyleSheet("background-color: rgba(239, 68, 68, 0.12); border: 1px solid rgba(239, 68, 68, 0.3); color: #f87171; border-radius: 6px; padding: 3px 9px; font-size: 11px; font-weight: 700;")
        self.kpi_boot.setStyleSheet("background-color: rgba(99, 102, 241, 0.12); border: 1px solid rgba(99, 102, 241, 0.3); color: #818cf8; border-radius: 6px; padding: 3px 9px; font-size: 11px; font-weight: 600;")

        self.kpi_total.clicked.connect(lambda: self._set_category_filter("all"))
        self.kpi_running.clicked.connect(lambda: self._set_category_filter("running"))
        self.kpi_stopped.clicked.connect(lambda: self._set_category_filter("stopped"))
        self.kpi_failed.clicked.connect(lambda: self._set_category_filter("failed"))
        self.kpi_boot.clicked.connect(lambda: self._set_category_filter("enabled"))

        kpi_bar.addWidget(self.kpi_total)
        kpi_bar.addWidget(self.kpi_running)
        kpi_bar.addWidget(self.kpi_stopped)
        kpi_bar.addWidget(self.kpi_failed)
        kpi_bar.addWidget(self.kpi_boot)

        kpi_bar.addStretch(1)

        # Search Input
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filter by name, port, description...")
        self.search_input.setFixedWidth(240)
        self.search_input.setStyleSheet(
            """
            QLineEdit {
                background-color: #101014;
                border: 1px solid #2b2b3a;
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 11px;
                color: #ffffff;
            }
            QLineEdit:focus {
                border-color: #6366f1;
            }
            """
        )
        self.search_input.textChanged.connect(self._on_search_changed)
        kpi_bar.addWidget(self.search_input)

        layout.addLayout(kpi_bar)

        # 3. Category Tag Filter Bar
        tags_bar = QHBoxLayout()
        tags_bar.setSpacing(6)
        tag_lbl = QLabel("TAGS:")
        tag_lbl.setStyleSheet("font-size: 10px; font-weight: 700; color: #64748b; letter-spacing: 0.5px;")
        tags_bar.addWidget(tag_lbl)

        self.tag_buttons: dict[str, QPushButton] = {}
        for cat_key, cat_label in (
            ("all", "All"),
            ("web", "Web && Proxies"),
            ("database", "Databases"),
            ("container", "Containers"),
            ("worker", "Workers && Apps"),
            ("security", "Security"),
        ):
            b = QPushButton(cat_label)
            b.setCheckable(True)
            b.setStyleSheet(
                """
                QPushButton {
                    background-color: #171720;
                    border: 1px solid #282836;
                    color: #94a3b8;
                    border-radius: 12px;
                    padding: 2px 9px;
                    font-size: 10px;
                    font-weight: 600;
                }
                QPushButton:checked {
                    background-color: #6366f1;
                    color: #ffffff;
                    border-color: #6366f1;
                }
                """
            )
            b.clicked.connect((lambda k=cat_key: lambda: self._set_category_filter(k))())
            tags_bar.addWidget(b)
            self.tag_buttons[cat_key] = b

        self.tag_buttons["all"].setChecked(True)
        tags_bar.addStretch(1)
        layout.addLayout(tags_bar)

        # 4. Content Switcher: Split View (Master-Detail) vs Dense Table View
        self.view_stack = QStackedWidget(self)

        # Mode A: Split View (60% cards left, 40% inspector right)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setStyleSheet(
            """
            QSplitter::handle {
                background-color: #242430;
                width: 2px;
            }
            """
        )

        # Left Scroll Area with Cards
        cards_scroll = QScrollArea()
        cards_scroll.setWidgetResizable(True)
        cards_scroll.setMinimumWidth(380)
        cards_scroll.setStyleSheet("background: transparent; border: none;")

        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(0, 0, 10, 0)
        self.cards_layout.setSpacing(8)
        self.cards_layout.addStretch(1)

        cards_scroll.setWidget(self.cards_container)
        self.splitter.addWidget(cards_scroll)

        # Right Inspector Panel (wrapped in scroll area for vertical responsiveness)
        inspector_scroll = QScrollArea()
        inspector_scroll.setWidgetResizable(True)
        inspector_scroll.setFrameShape(QFrame.Shape.NoFrame)
        inspector_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inspector_scroll.setStyleSheet("background: transparent; border: none;")

        self.inspector = ServiceInspectorWidget()
        self.inspector.setMinimumWidth(320)
        self.inspector.action_requested.connect(self._on_service_action)
        self.inspector.reload_logs_requested.connect(self._on_reload_logs_requested)
        self.inspector.edit_requested.connect(self._on_edit_unit_requested)
        inspector_scroll.setWidget(self.inspector)
        self.splitter.addWidget(inspector_scroll)

        self.splitter.setSizes([720, 480])
        self.splitter.setStretchFactor(0, 60)
        self.splitter.setStretchFactor(1, 40)
        self.view_stack.addWidget(self.splitter)

        # Mode B: Dense Table View
        self.dense_table = ServiceDenseTableView(self)
        self.dense_table.action_requested.connect(self._on_service_action)
        self.dense_table.unit_selected.connect(self._select_service)
        self.dense_table.edit_requested.connect(self._on_edit_unit_requested)
        self.view_stack.addWidget(self.dense_table)

        layout.addWidget(self.view_stack, 1)

        self.stack.addWidget(view)

    def set_connection(self, connection: Any | None, profile: Any | None = None) -> None:
        """Update active connection reference and trigger inventory refresh."""
        self._connection = connection
        self._profile = profile
        self._snapshot = None
        self._selected_unit = ""

        if connection is None:
            self.stack.setCurrentIndex(0)
            return

        host_title = profile.name if profile and profile.name else (profile.host if profile else "Remote Server")
        user_host = f"{profile.username}@{profile.host}" if profile else "SSH"
        self.header.set_host_info(f"{host_title} ({user_host})")

        self.stack.setCurrentIndex(1)
        self.refresh_inventory()

    def _track_worker(self, worker: AsyncWorker) -> None:
        self._workers.append(worker)
        worker.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)
        worker.start()

    def refresh_inventory(self) -> None:
        """Fetch remote systemd services snapshot agentlessly."""
        if self._connection is None:
            return

        conn = self._connection

        def run_inventory() -> Any:
            return conn.run_command(SERVICE_INVENTORY_COMMAND)

        self._inventory_worker = AsyncWorker(run_inventory)
        self._inventory_worker.succeeded.connect(self._on_inventory_success)
        self._inventory_worker.failed.connect(self._on_inventory_failed)
        self._track_worker(self._inventory_worker)

    def _on_inventory_success(self, res: OperationResult) -> None:
        if not res.ok or not res.data:
            return
        stdout = res.data.get("stdout", "")
        if not stdout:
            return

        snapshot = SystemdServicesCollector.parse_inventory(stdout)
        self._snapshot = snapshot
        self._render_inventory(snapshot)

    def _on_inventory_failed(self, err: Any) -> None:
        pass

    def _render_inventory(self, snap: ServiceInventorySnapshot) -> None:
        # Update KPI badges
        self.kpi_total.setText(f"Total: {snap.total_count}")
        self.kpi_running.setText(f"● Running: {snap.running_count}")
        self.kpi_stopped.setText(f"Stopped: {snap.stopped_count}")
        self.kpi_failed.setText(f"● Failed: {snap.failed_count}")
        self.kpi_boot.setText(f"★ Boot Enabled: {snap.boot_enabled_count}")

        # Filter services
        filtered = self._get_filtered_services()

        # 1. Render Cards
        # Clear existing cards
        while self.cards_layout.count() > 1:
            item = self.cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for s in filtered:
            card = ServiceCardWidget(s, self.cards_container)
            card.clicked.connect(self._select_service)
            card.action_requested.connect(self._on_service_action)
            card.boot_toggled.connect(self._on_boot_toggled)
            card.edit_requested.connect(self._on_edit_unit_requested)
            self.cards_layout.insertWidget(self.cards_layout.count() - 1, card)
            card.show()

        # 2. Render Dense Table
        self.dense_table.set_services(tuple(filtered))

        # Auto-select first priority service if none selected
        if filtered and (not self._selected_unit or not any(s.name == self._selected_unit for s in filtered)):
            self._select_service(filtered[0].name)

    def _get_filtered_services(self) -> list[ServiceUnitInfo]:
        if not self._snapshot:
            return []

        results: list[ServiceUnitInfo] = []
        q = self._search_query.lower()

        for s in self._snapshot.services:
            # Query match
            if q and q not in s.name.lower() and q not in s.description.lower() and q not in s.ports.lower():
                continue

            # Category match
            if self._active_category == "all":
                results.append(s)
            elif self._active_category == "running" and s.is_running:
                results.append(s)
            elif self._active_category == "stopped" and not s.is_running and not s.is_failed:
                results.append(s)
            elif self._active_category == "failed" and s.is_failed:
                results.append(s)
            elif self._active_category == "enabled" and s.is_boot_enabled:
                results.append(s)
            elif s.category == self._active_category:
                results.append(s)

        return results

    def _select_service(self, unit_name: str) -> None:
        self._selected_unit = unit_name

        # Update card active selection borders
        for i in range(self.cards_layout.count() - 1):
            w = self.cards_layout.itemAt(i).widget()
            if isinstance(w, ServiceCardWidget):
                w.update_selection(w._service.name == unit_name)

        if not self._snapshot:
            return

        s = next((item for item in self._snapshot.services if item.name == unit_name), None)
        if not s:
            return

        # Immediate preview with known snapshot info
        self.inspector.set_service(s)

        # Background fetch deep properties & journalctl logs
        if self._connection is not None:
            conn = self._connection

            def fetch_props() -> Any:
                return fetch_unit_properties(conn, unit_name)

            self._props_worker = AsyncWorker(fetch_props)
            self._props_worker.succeeded.connect(
                lambda res, unit=unit_name: self._on_props_received(unit, res)
            )
            self._track_worker(self._props_worker)

            self._fetch_logs(unit_name, errors_only=False)

    def _on_props_received(self, unit_name: str, res: Any) -> None:
        if unit_name != self._selected_unit or not res:
            return
        if isinstance(res, dict):
            props = res
        elif isinstance(res, OperationResult):
            if not res.ok or not res.data:
                return
            stdout = res.data.get("stdout", "")
            props = SystemdServicesCollector.parse_properties(stdout)
        else:
            return

        self._cached_properties[unit_name] = props
        s = next((item for item in self._snapshot.services if item.name == unit_name), None) if self._snapshot else None
        if s:
            self.inspector.set_service(s, props)

    def _on_edit_unit_requested(self, unit_name_or_path: str) -> None:
        if unit_name_or_path.startswith("/"):
            self.edit_unit_requested.emit(unit_name_or_path)
            return

        # Check cached properties for FragmentPath
        cached = self._cached_properties.get(unit_name_or_path, {})
        fragment = cached.get("FragmentPath")
        if fragment and fragment.startswith("/") and not fragment.endswith("/"):
            self.edit_unit_requested.emit(fragment)
        else:
            name = unit_name_or_path if "." in unit_name_or_path else f"{unit_name_or_path}.service"
            self.edit_unit_requested.emit(f"/lib/systemd/system/{name}")

    def _fetch_logs(self, unit_name: str, errors_only: bool = False) -> None:
        if self._connection is None:
            return
        conn = self._connection

        def run_logs() -> Any:
            return fetch_unit_logs(conn, unit_name, lines=50, errors_only=errors_only)

        self._logs_worker = AsyncWorker(run_logs)
        self._logs_worker.succeeded.connect(
            lambda res, unit=unit_name: self._on_logs_received(unit, res)
        )
        self._track_worker(self._logs_worker)

    def _on_logs_received(self, unit_name: str, res: Any) -> None:
        if unit_name != self._selected_unit:
            return
        if isinstance(res, (list, tuple)):
            logs = tuple(res)
        elif isinstance(res, OperationResult):
            if not res.ok or not res.data:
                return
            stdout = res.data.get("stdout", "")
            logs = SystemdServicesCollector.parse_journal(stdout)
        else:
            logs = ()

        self.inspector.console.set_logs(unit_name, logs)

    def _on_reload_logs_requested(self, unit_name: str, errors_only: bool) -> None:
        self._fetch_logs(unit_name, errors_only)

    def _on_service_action(self, unit_name: str, action: str) -> None:
        if self._connection is None:
            return

        conn = self._connection

        def run_action() -> Any:
            return control_service(conn, unit_name, action)

        self._action_worker = AsyncWorker(run_action)
        self._action_worker.succeeded.connect(
            lambda res: self._on_action_completed(res, unit_name, action)
        )
        self._track_worker(self._action_worker)

    def _on_action_completed(self, res: OperationResult, unit_name: str, action: str) -> None:
        if res.ok:
            # Refresh inventory to update UI states
            self.refresh_inventory()
            if unit_name == self._selected_unit:
                self._fetch_logs(unit_name)

    def _on_boot_toggled(self, unit_name: str, enabled: bool) -> None:
        action = "enable" if enabled else "disable"
        self._on_service_action(unit_name, action)

    def _on_daemon_reload_clicked(self) -> None:
        if self._connection is None:
            return
        conn = self._connection

        def run_reload() -> Any:
            return daemon_reload(conn)

        self._action_worker = AsyncWorker(run_reload)
        self._action_worker.succeeded.connect(lambda res: self.refresh_inventory())
        self._track_worker(self._action_worker)

    def _on_new_unit_clicked(self) -> None:
        if self._connection is None:
            return

        dlg = NewUnitModalDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            unit_name = dlg.unit_name
            content = dlg.unit_content
            auto_start = dlg.enable_and_start
            conn = self._connection

            def run_install() -> Any:
                return install_unit_file(conn, unit_name, content, enable_now=auto_start)

            self._action_worker = AsyncWorker(run_install)
            self._action_worker.succeeded.connect(lambda res: self.refresh_inventory())
            self._track_worker(self._action_worker)

    def _on_view_mode_changed(self, mode: str) -> None:
        self.view_stack.setCurrentIndex(0 if mode == "split" else 1)

    def _on_search_changed(self, text: str) -> None:
        self._search_query = text.strip()
        if self._snapshot:
            self._render_inventory(self._snapshot)

    def _set_category_filter(self, cat: str) -> None:
        self._active_category = cat
        for k, btn in self.tag_buttons.items():
            btn.setChecked(k == cat)

        if self._snapshot:
            self._render_inventory(self._snapshot)
