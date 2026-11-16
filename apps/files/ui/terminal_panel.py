from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QSize, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.connections.profile import ConnectionProfile
from core.diagnostics import log_diagnostic
from core.result import OperationResult
from terminal.local_pty_terminal import LocalPtyTerminalSession
from terminal.session_backend import TerminalSessionBackend
from terminal.ssh_terminal import SSHTerminalSession
from terminal.terminal_bridge import normalize_terminal_paste
from ui.async_worker import AsyncRuntime, AsyncWorker
from ui.icons import get_icon


@dataclass(slots=True)
class TerminalTargetChoice:
    kind: str
    profile: ConnectionProfile | None = None


class RemoteTerminalDialog(QDialog):
    def __init__(self, active_connection, saved_profiles: list[ConnectionProfile], parent: QWidget | None = None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self.setWindowTitle("New Remote Terminal")
        self.setFixedWidth(480)
        self.setStyleSheet("QDialog { background: #111114; border: 1px solid #1e1e24; border-radius: 10px; }")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Header with icon
        header_row = QHBoxLayout()
        header_row.setSpacing(12)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(get_icon("servers", color="#6366f1", size=22).pixmap(22, 22))
        icon_lbl.setFixedSize(36, 36)
        icon_lbl.setStyleSheet("background: rgba(99, 102, 241, 0.12); border: 1px solid rgba(99, 102, 241, 0.25); border-radius: 8px;")
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        title = QLabel("New Remote Terminal")
        title.setStyleSheet("font-size: 15px; font-weight: 700; color: #f4f4f5;")
        subtitle = QLabel("Select an active connection or saved profile to launch SSH.")
        subtitle.setStyleSheet("font-size: 12px; color: #71717a;")
        text_layout.addWidget(title)
        text_layout.addWidget(subtitle)

        header_row.addWidget(icon_lbl)
        header_row.addLayout(text_layout)
        header_row.addStretch()
        layout.addLayout(header_row)

        # Target section
        target_layout = QVBoxLayout()
        target_layout.setSpacing(6)
        target_lbl = QLabel("Target Server")
        target_lbl.setStyleSheet("font-size: 11px; font-weight: 600; color: #a1a1aa; text-transform: uppercase; letter-spacing: 0.5px;")
        self.target = QComboBox()
        self.target.setFixedHeight(36)
        if active_connection is not None:
            profile = active_connection.profile
            self.target.addItem(
                f"Active: {profile.name} ({profile.username}@{profile.host}:{profile.port})",
                TerminalTargetChoice("active"),
            )
        for profile in saved_profiles:
            self.target.addItem(
                f"Saved: {profile.name} ({profile.username}@{profile.host}:{profile.port})",
                TerminalTargetChoice("saved", profile),
            )
        target_layout.addWidget(target_lbl)
        target_layout.addWidget(self.target)
        layout.addLayout(target_layout)

        # Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        btn_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(34)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background: #18181b;
                border: 1px solid #27272a;
                border-radius: 6px;
                color: #a1a1aa;
                padding: 0 16px;
                font-size: 12px;
                font-weight: 500;
            }
            QPushButton:hover {
                background: #27272a;
                color: #f4f4f5;
            }
        """)
        cancel_btn.clicked.connect(self.reject)

        self.launch_btn = QPushButton("Launch Terminal")
        self.launch_btn.setFixedHeight(34)
        self.launch_btn.setStyleSheet("""
            QPushButton {
                background: #6366f1;
                border: 1px solid #4f46e5;
                border-radius: 6px;
                color: #ffffff;
                padding: 0 18px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #4f46e5;
            }
            QPushButton:disabled {
                background: #27272a;
                color: #71717a;
                border-color: #27272a;
            }
        """)
        self.launch_btn.setEnabled(self.target.count() > 0)
        self.launch_btn.clicked.connect(self.accept)

        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(self.launch_btn)
        layout.addLayout(btn_layout)

    def selected_choice(self) -> TerminalTargetChoice | None:
        value = self.target.currentData()
        return value if isinstance(value, TerminalTargetChoice) else None


class TerminalWebView(QWebEngineView):
    copyShortcut = Signal()
    pasteShortcut = Signal()
    interruptShortcut = Signal()
    clearShortcut = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        try:
            from PySide6.QtWebEngineCore import QWebEngineSettings
            self.settings().setAttribute(QWebEngineSettings.WebAttribute.FocusOnNavigationEnabled, True)
            self.settings().setAttribute(QWebEngineSettings.WebAttribute.ShowScrollBars, True)
        except Exception:
            pass

    def focusInEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().focusInEvent(event)
        self.page().runJavaScript("window.rfmTerminalFocus && window.rfmTerminalFocus();")

    def mousePressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        super().mousePressEvent(event)
        self.page().runJavaScript("window.rfmTerminalFocus && window.rfmTerminalFocus();")

    def keyPressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        modifiers = event.modifiers()
        key = event.key()
        ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        alt = bool(modifiers & Qt.KeyboardModifier.AltModifier)
        if ctrl and shift and key == Qt.Key.Key_C:
            self.copyShortcut.emit()
            event.accept()
            return
        if ctrl and shift and key == Qt.Key.Key_V:
            self.pasteShortcut.emit()
            event.accept()
            return
        if ctrl and not shift and not alt and key == Qt.Key.Key_C:
            self.interruptShortcut.emit()
            event.accept()
            return
        if ctrl and not shift and not alt and key == Qt.Key.Key_L:
            self.clearShortcut.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class TerminalBridge(QObject):
    rawOutputReceived = Signal(str)
    outputReceived = Signal(str)
    statusChanged = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.session: TerminalSessionBackend | None = None
        self._frontend_ready: bool = False
        self._buffer: list[str] = []
        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(12)
        self._flush_timer.timeout.connect(self._flush_output)
        # Terminal data originates from the asyncio runtime thread. Never let
        # that thread start/stop this GUI-thread QTimer directly.
        self.rawOutputReceived.connect(self._queue_output, Qt.ConnectionType.QueuedConnection)

    def set_session(self, session: TerminalSessionBackend | None) -> None:
        self.session = session

    @Slot()
    def frontendReady(self) -> None:
        self._frontend_ready = True
        self._flush_output()

    @Slot(str)
    def input(self, text: str) -> None:
        if self.session is not None:
            AsyncRuntime.instance().submit(self.session.send(text))

    @Slot()
    def interrupt(self) -> None:
        if self.session is not None:
            AsyncRuntime.instance().submit(self.session.interrupt())

    @Slot(str)
    def copyText(self, text: str) -> None:
        QGuiApplication.clipboard().setText(text)

    @Slot()
    def pasteFromClipboard(self) -> None:
        if self.session is None:
            return
        text = QGuiApplication.clipboard().text()
        if text:
            AsyncRuntime.instance().submit(self.session.send(normalize_terminal_paste(text)))

    @Slot(int, int)
    def resize(self, columns: int, rows: int) -> None:
        if columns < 20 or rows < 5:
            return
        if self.session is not None:
            AsyncRuntime.instance().submit(self.session.resize(columns, rows))

    def append_output(self, text: str) -> None:
        self.rawOutputReceived.emit(text)

    @Slot(str)
    def _queue_output(self, text: str) -> None:
        self._buffer.append(text)
        if self._frontend_ready and not self._flush_timer.isActive():
            self._flush_timer.start()

    def _flush_output(self) -> None:
        if not self._frontend_ready:
            return
        if not self._buffer:
            self._flush_timer.stop()
            return
        text = "".join(self._buffer)
        self._buffer.clear()
        self.outputReceived.emit(text)


class TerminalSessionWidget(QWidget):
    session_finished = Signal(object)
    reconnect_requested = Signal(object)
    backend_exited = Signal()

    def __init__(
        self,
        backend: TerminalSessionBackend,
        *,
        title: str,
        profile_id: str | None,
        owns_connection: bool,
        settings: dict,
    ) -> None:
        super().__init__()
        self.backend = backend
        self._title = title
        self.profile_id = profile_id
        self.owns_connection = owns_connection
        self.settings = settings
        self._closing = False
        self._reconnect_pending = False
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 3
        self._workers: list[AsyncWorker] = []
        self._health_worker: AsyncWorker | None = None
        self._health_timer = QTimer(self)
        self._health_timer.setInterval(30_000)
        self._health_timer.timeout.connect(self._check_transport_health)

        self.status = QLabel("Terminal session starting.")
        self.status.setObjectName("MutedLabel")
        self.status.setMaximumHeight(24)
        self.status.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.view = TerminalWebView()
        self.view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.view.setStyleSheet("background: #09090b; border: none;")
        self.view.page().setBackgroundColor(QColor("#09090b"))
        self.bridge = TerminalBridge()
        self.channel = QWebChannel(self.view.page())
        self.channel.registerObject("terminalBridge", self.bridge)
        self.view.page().setWebChannel(self.channel)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.status)
        layout.addWidget(self.view, 1)

        self.bridge.statusChanged.connect(self.status.setText, Qt.ConnectionType.QueuedConnection)
        # SSH output is read on AsyncRuntime's thread. Route its exit callback
        # through Qt so reconnect timers and the WebEngine view are only ever
        # touched on this widget's GUI thread.
        self.backend_exited.connect(self._backend_exited, Qt.ConnectionType.QueuedConnection)
        self.view.copyShortcut.connect(self.copy)
        self.view.pasteShortcut.connect(self.paste)
        self.view.interruptShortcut.connect(self.interrupt)
        self.view.clearShortcut.connect(self.clear)
        self.view.loadFinished.connect(lambda _ok: self.apply_settings(self.settings))
        self.bridge.set_session(self.backend)
        self._load_terminal_html()
        self.start()

    def focus_terminal(self) -> None:
        self.view.setFocus(Qt.FocusReason.OtherFocusReason)
        proxy = self.view.focusProxy()
        if proxy is not None:
            proxy.setFocus(Qt.FocusReason.OtherFocusReason)
        self.view.page().runJavaScript("window.rfmTerminalFocus && window.rfmTerminalFocus();")

    def showEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().showEvent(event)
        QTimer.singleShot(50, self.focus_terminal)

    def title(self) -> str:
        return self._title

    def start(self) -> None:
        worker = AsyncWorker(lambda: self._restart_backend())
        self._workers.append(worker)
        worker.succeeded.connect(self._backend_started, Qt.ConnectionType.QueuedConnection)
        worker.failed.connect(self._backend_start_failed, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(
            lambda: self._workers.remove(worker) if worker in self._workers else None,
            Qt.ConnectionType.QueuedConnection,
        )
        self.status.setText("Terminal session starting.")
        self.status.setVisible(True)
        worker.start()

    async def _restart_backend(self) -> OperationResult:
        self._closing = True
        await self.backend.close()
        self._closing = False
        return await self.backend.start(self.bridge.append_output, self.backend_exited.emit)

    def close_session(self) -> None:
        self._closing = True
        self._health_timer.stop()
        AsyncRuntime.instance().submit(self.backend.close())
        self.bridge.set_session(None)

    def reconnect_with(self, connection) -> None:  # type: ignore[no-untyped-def]
        """Replace a failed SSH transport while keeping this tab and its cwd."""
        if not isinstance(self.backend, SSHTerminalSession):
            return
        self.backend = SSHTerminalSession(
            connection,
            cwd=self.backend.cwd,
            startup_command=self.backend.startup_command,
        )
        self.bridge.set_session(self.backend)
        self._reconnect_pending = False
        self.start()

    def reconnect_failed(self, result: OperationResult) -> None:
        self._reconnect_pending = False
        self._set_result_status(result)
        self._request_reconnect()

    def reconnect_now(self) -> None:
        """Let the toolbar retry after automatic recovery has given up."""
        if isinstance(self.backend, SSHTerminalSession):
            self._reconnect_attempts = 0
            self._reconnect_pending = False
            self._request_reconnect()
        else:
            self.start()

    def clear(self) -> None:
        self.view.page().runJavaScript("window.rfmTerminalClear && window.rfmTerminalClear();")

    def copy(self) -> None:
        self.view.page().runJavaScript("window.rfmTerminalCopy && window.rfmTerminalCopy();")

    def paste(self) -> None:
        self.view.page().runJavaScript("window.rfmTerminalPaste && window.rfmTerminalPaste();")

    def interrupt(self) -> None:
        self.view.page().runJavaScript("window.rfmTerminalInterrupt && window.rfmTerminalInterrupt();")

    def apply_settings(self, settings: dict) -> None:
        self.settings = settings
        font_size = int(settings.get("font_size", 13))
        scrollback = int(settings.get("scrollback", 5000))
        script = (
            "window.rfmTerminalApplySettings && "
            f"window.rfmTerminalApplySettings({{fontSize: {font_size}, scrollback: {scrollback}}});"
        )
        self.view.page().runJavaScript(script)

    def mark_shared_connection(self) -> None:
        self.owns_connection = False

    def _backend_exited(self) -> None:
        if self._closing:
            return
        if isinstance(self.backend, SSHTerminalSession):
            self._request_reconnect()
            return
        self.session_finished.emit(self)

    def _backend_started(self, result: OperationResult) -> None:
        self._reconnect_attempts = 0
        self._reconnect_pending = False
        if isinstance(self.backend, SSHTerminalSession):
            self._health_timer.start()
        self._set_result_status(result)

    def _backend_start_failed(self, result: OperationResult) -> None:
        self._set_result_status(result)
        if isinstance(self.backend, SSHTerminalSession) and not self._closing:
            self._request_reconnect()

    def _request_reconnect(self) -> None:
        if self._closing or self._reconnect_pending:
            return
        self._health_timer.stop()
        self._reconnect_attempts += 1
        if self._reconnect_attempts > self._max_reconnect_attempts:
            self.status.setText("Terminal connection was lost. Reconnect attempts exhausted; use Reconnect to try again.")
            self.status.setVisible(True)
            return
        self._reconnect_pending = True
        delay_ms = 1000 * (2 ** (self._reconnect_attempts - 1))
        self.status.setText(f"Terminal connection lost. Reconnecting ({self._reconnect_attempts}/{self._max_reconnect_attempts})…")
        self.status.setVisible(True)
        QTimer.singleShot(delay_ms, lambda: self.reconnect_requested.emit(self) if not self._closing else None)

    def _check_transport_health(self) -> None:
        if self._closing or self._reconnect_pending or not isinstance(self.backend, SSHTerminalSession):
            return
        if self._health_worker is not None:
            return
        worker = AsyncWorker(self.backend.health_check)
        self._health_worker = worker
        worker.failed.connect(lambda _result: self._request_reconnect(), Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(self._health_check_finished, Qt.ConnectionType.QueuedConnection)
        worker.start()

    def _health_check_finished(self) -> None:
        worker = self._health_worker
        self._health_worker = None
        if worker is not None:
            worker.deleteLater()

    def _set_result_status(self, result: OperationResult) -> None:
        message = result.message
        if result.suggested_fix:
            message = f"{message} {result.suggested_fix}"
        if result.ok and not result.suggested_fix:
            self.status.clear()
            self.status.setVisible(False)
        else:
            self.status.setText(message)
            self.status.setVisible(True)
        if not result.ok:
            log_diagnostic("terminal", f"{result.message} {result.technical_details or ''}".strip())

    def _load_terminal_html(self) -> None:
        html_path = Path(__file__).resolve().parent.parent / "resources" / "terminal" / "terminal.html"
        log_diagnostic("terminal", f"Loading terminal frontend from {html_path}.")
        self.view.setUrl(QUrl.fromLocalFile(str(html_path)))


class TerminalPanel(QWidget):
    saved_profile_terminal_requested = Signal(object, object)
    terminal_connection_released = Signal(str)
    terminal_reconnect_requested = Signal(object)
    settings_changed = Signal(dict)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("TerminalPanel")
        self.setStyleSheet("QWidget#TerminalPanel { background: #09090b; }")
        self.connection = None
        self.saved_profiles: list[ConnectionProfile] = []
        self.settings: dict = self._default_settings()

        # Modern Studio Header
        header = QFrame()
        header.setObjectName("TerminalHeader")
        header.setStyleSheet("""
            QFrame#TerminalHeader {
                background: #111114;
                border: 0;
                border-bottom: 1px solid #1e1e24;
            }
            QFrame#TerminalHeader QLabel {
                background: transparent;
                border: none;
            }
        """)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 8, 10, 8)
        header_layout.setSpacing(5)

        # Left: Title + compact badge
        title_box = QHBoxLayout()
        title_box.setSpacing(8)
        h_title = QLabel("Terminal Studio")
        h_title.setStyleSheet("font-size: 15px; font-weight: 700; color: #f4f4f5;")
        title_box.addWidget(h_title)

        self.sub_badge = QLabel("WebGL PTY")
        self.sub_badge.setStyleSheet("""
            background: rgba(99, 102, 241, 0.12);
            color: #818cf8;
            border: 1px solid rgba(99, 102, 241, 0.25);
            border-radius: 4px;
            padding: 2px 6px;
            font-size: 10px;
            font-weight: 600;
        """)
        title_box.addWidget(self.sub_badge)
        header_layout.addLayout(title_box)

        self.status = QLabel("Ready")
        self.status.setObjectName("MutedLabel")
        self.status.setStyleSheet("font-size: 11px; color: #71717a; font-family: 'JetBrains Mono', monospace; padding: 0 4px;")
        header_layout.addWidget(self.status)

        header_layout.addStretch()

        # Action Buttons (tight, clean Raycast/Linear aesthetic without scroll area)
        btn_style = (
            "QPushButton { background: #141418; border: 1px solid #1e1e24; "
            "border-radius: 6px; color: #a1a1aa; font-size: 11px; padding: 0 7px; "
            "height: 26px; } QPushButton:hover { background: #1e1e24; color: #f4f4f5; }"
        )
        font_btn_style = (
            "QPushButton { background: #141418; border: 1px solid #1e1e24; "
            "border-radius: 6px; color: #a1a1aa; font-size: 11px; width: 28px; "
            "height: 26px; padding: 0; font-weight: 600; } "
            "QPushButton:hover { background: #1e1e24; color: #f4f4f5; }"
        )

        self.reconnect_button = QPushButton("Reconnect")
        self.reconnect_button.setStyleSheet(btn_style)

        self.clear_button = QPushButton("Clear")
        self.clear_button.setStyleSheet(btn_style)

        self.ctrl_c_button = QPushButton("Ctrl+C")
        self.ctrl_c_button.setStyleSheet(btn_style)

        self.copy_button = QPushButton("Copy")
        self.copy_button.setStyleSheet(btn_style)

        self.paste_button = QPushButton("Paste")
        self.paste_button.setStyleSheet(btn_style)

        self.font_down_button = QPushButton("A-")
        self.font_down_button.setStyleSheet(font_btn_style)
        self.font_down_button.setToolTip("Decrease font size (Ctrl+-)")

        self.font_up_button = QPushButton("A+")
        self.font_up_button.setStyleSheet(font_btn_style)
        self.font_up_button.setToolTip("Increase font size (Ctrl++)")

        self.rename_button = QPushButton("Rename")
        self.rename_button.setStyleSheet(btn_style)

        self.close_button = QPushButton("Close")
        self.close_button.setStyleSheet(
            "QPushButton { background: transparent; border: 1px solid rgba(244, 63, 94, 0.4); "
            "border-radius: 6px; color: #f43f5e; font-size: 11px; padding: 0 7px; height: 26px; } "
            "QPushButton:hover { background: rgba(244, 63, 94, 0.15); }"
        )

        self.new_local_button = QPushButton(" New Local")
        self.new_local_button.setIcon(get_icon("terminal", color="#a1a1aa", size=13))
        self.new_local_button.setFixedHeight(28)
        self.new_local_button.setStyleSheet(
            "QPushButton { background: #141418; border: 1px solid #1e1e24; "
            "border-radius: 6px; color: #f4f4f5; font-size: 11px; padding: 0 9px; } "
            "QPushButton:hover { background: #1e1e24; }"
        )

        self.new_remote_button = QPushButton(" New Remote")
        self.new_remote_button.setObjectName("PrimaryButton")
        self.new_remote_button.setIcon(get_icon("servers", color="#ffffff", size=13))
        self.new_remote_button.setFixedHeight(28)
        self.new_remote_button.setStyleSheet(
            "QPushButton { background: #6366f1; color: #ffffff; font-weight: 600; "
            "padding: 0 11px; border-radius: 6px; font-size: 11px; } "
            "QPushButton:hover { background: #4f46e5; }"
        )

        for button in [
            self.reconnect_button,
            self.clear_button,
            self.ctrl_c_button,
            self.copy_button,
            self.paste_button,
            self.font_down_button,
            self.font_up_button,
            self.rename_button,
            self.close_button,
            self.new_local_button,
            self.new_remote_button,
        ]:
            header_layout.addWidget(button)

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: none;
                border-top: 1px solid #1e1e24;
                background: #09090b;
            }
            QTabBar {
                background: #09090b;
                border: none;
            }
            QTabBar::tab {
                background: #111114;
                color: #a1a1aa;
                border: 1px solid #1e1e24;
                border-bottom: 2px solid transparent;
                border-radius: 6px 6px 0 0;
                padding: 6px 14px;
                font-size: 12px;
                font-weight: 500;
                min-width: 120px;
                margin-right: 2px;
            }
            QTabBar::tab:hover {
                color: #f4f4f5;
                background: #18181b;
            }
            QTabBar::tab:selected {
                color: #818cf8;
                border-bottom: 2px solid #6366f1;
                font-weight: 600;
                background: #18181b;
            }
        """)

        # Empty State
        self.empty_state = QFrame()
        self.empty_state.setObjectName("TerminalEmptyState")
        self.empty_state.setStyleSheet("""
            QFrame#TerminalEmptyState {
                background: #09090b;
                border: none;
            }
            QFrame#TerminalEmptyState QLabel {
                background: transparent;
                border: none;
            }
        """)
        empty_layout = QVBoxLayout(self.empty_state)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.setSpacing(12)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(get_icon("terminal", color="#6366f1", size=48).pixmap(48, 48))
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        t_lbl = QLabel("No Active Terminal Sessions")
        t_lbl.setStyleSheet("font-size: 16px; font-weight: 600; color: #f4f4f5;")
        t_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        desc_lbl = QLabel("Launch a local shell (PTY) or connect to an active remote server over SSH.")
        desc_lbl.setStyleSheet("font-size: 12px; color: #71717a;")
        desc_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        btn_box = QHBoxLayout()
        btn_box.setSpacing(12)
        btn_box.setAlignment(Qt.AlignmentFlag.AlignCenter)

        open_remote_btn = QPushButton("  Connect Remote SSH")
        open_remote_btn.setObjectName("PrimaryButton")
        open_remote_btn.setIcon(get_icon("servers", color="#ffffff", size=14))
        open_remote_btn.setFixedHeight(34)
        open_remote_btn.setStyleSheet("QPushButton { background: #6366f1; color: #ffffff; font-weight: 600; border-radius: 6px; padding: 0 16px; font-size: 12px; } QPushButton:hover { background: #4f46e5; }")
        open_remote_btn.clicked.connect(self._choose_remote_target)

        open_local_btn = QPushButton("  Launch Local Shell")
        open_local_btn.setIcon(get_icon("terminal", color="#a1a1aa", size=14))
        open_local_btn.setFixedHeight(34)
        open_local_btn.setStyleSheet("QPushButton { background: #141418; border: 1px solid #1e1e24; border-radius: 6px; color: #f4f4f5; font-size: 12px; padding: 0 16px; } QPushButton:hover { background: #1e1e24; }")
        open_local_btn.clicked.connect(lambda: self.open_local_at(None))

        btn_box.addWidget(open_remote_btn)
        btn_box.addWidget(open_local_btn)

        empty_layout.addWidget(icon_lbl)
        empty_layout.addWidget(t_lbl)
        empty_layout.addWidget(desc_lbl)
        empty_layout.addSpacing(6)
        empty_layout.addLayout(btn_box)

        self.content_stack = QStackedWidget()
        self.content_stack.addWidget(self.empty_state)
        self.content_stack.addWidget(self.tabs)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(header)
        layout.addWidget(self.content_stack, 1)

        self._shortcuts: list[QShortcut] = []
        self.new_remote_button.clicked.connect(self._choose_remote_target)
        self.new_local_button.clicked.connect(lambda: self.open_local_at(None))
        self.reconnect_button.clicked.connect(lambda: self._current_session().reconnect_now() if self._current_session() else None)
        self.rename_button.clicked.connect(self._rename_current)
        self.clear_button.clicked.connect(lambda: self._current_session().clear() if self._current_session() else None)
        self.ctrl_c_button.clicked.connect(lambda: self._current_session().interrupt() if self._current_session() else None)
        self.copy_button.clicked.connect(lambda: self._current_session().copy() if self._current_session() else None)
        self.paste_button.clicked.connect(lambda: self._current_session().paste() if self._current_session() else None)
        self.font_down_button.clicked.connect(lambda: self._change_font_size(-1))
        self.font_up_button.clicked.connect(lambda: self._change_font_size(1))
        self.close_button.clicked.connect(self._close_current)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self._install_shortcuts()
        self._sync_enabled()
        self._sync_empty_state()

    def showEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().showEvent(event)
        session = self._current_session()
        if session is not None:
            QTimer.singleShot(50, session.focus_terminal)

    def minimumSizeHint(self) -> QSize:
        return QSize(700, 300)

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        w = self.width()
        if hasattr(self, "sub_badge"):
            self.sub_badge.setVisible(w >= 940)
        if hasattr(self, "status"):
            self.status.setVisible(w >= 860)
        if hasattr(self, "font_down_button") and hasattr(self, "font_up_button"):
            self.font_down_button.setVisible(w >= 780)
            self.font_up_button.setVisible(w >= 780)

    def _on_tab_changed(self, index: int) -> None:
        self._sync_enabled()
        session = self._current_session()
        if session is not None:
            QTimer.singleShot(50, session.focus_terminal)

    def new_remote(self) -> None:
        self._choose_remote_target()

    def new_local(self) -> None:
        self.open_local_at(None)

    def reconnect_current(self) -> None:
        session = self._current_session()
        if session is not None:
            session.reconnect_now()

    def close_current(self) -> None:
        self._close_current()

    def copy_current(self) -> None:
        session = self._current_session()
        if session is not None:
            session.copy()

    def paste_current(self) -> None:
        session = self._current_session()
        if session is not None:
            session.paste()

    def change_font_size(self, delta: int) -> None:
        self._change_font_size(delta)

    def set_connection(self, connection) -> None:  # type: ignore[no-untyped-def]
        if not connection.capabilities.can_terminal:
            self.connection = None
            self.status.setText(
                f"Terminal unavailable because {connection.profile.name} does not provide SSH shell access."
            )
            self._sync_enabled()
            return
        self.connection = connection
        self.status.setText(f"Active remote terminal target ready for {connection.profile.name}.")
        self._sync_enabled()

    def set_saved_profiles(self, profiles: list[ConnectionProfile]) -> None:
        self.saved_profiles = profiles
        self._sync_enabled()

    def clear_connection(self, profile_id: str | None = None) -> None:
        if profile_id is None:
            while self.tabs.count():
                self._close_tab(0)
            self.connection = None
        else:
            for index in reversed(range(self.tabs.count())):
                widget = self.tabs.widget(index)
                if isinstance(widget, TerminalSessionWidget) and widget.profile_id == profile_id:
                    self._close_tab(index)
            if self.connection is not None and self.connection.profile.id == profile_id:
                self.connection = None
        if self.connection is None:
            self.status.setText("Use New Local for this computer or New Remote for SSH profiles.")
        self._sync_enabled()

    def adopt_connection(self, profile_id: str) -> None:
        for index in range(self.tabs.count()):
            widget = self.tabs.widget(index)
            if isinstance(widget, TerminalSessionWidget) and widget.profile_id == profile_id:
                widget.mark_shared_connection()

    def open_at(self, cwd: str | None) -> None:
        if self.connection is None:
            self.status.setText("No active remote connection is open.")
            return
        self.open_remote_connection(self.connection, cwd=cwd, owns_connection=False)

    def open_remote_connection(self, connection, *, cwd: str | None, owns_connection: bool) -> None:  # type: ignore[no-untyped-def]
        profile = self._default_profile()
        remote_cwd = self._remote_cwd(connection, cwd)
        backend = SSHTerminalSession(
            connection,
            cwd=remote_cwd,
            startup_command=(profile.get("startup_command") or None),
        )
        title = self._remote_title(connection, remote_cwd)
        session = TerminalSessionWidget(
            backend,
            title=title,
            profile_id=connection.profile.id,
            owns_connection=owns_connection,
            settings=self.settings,
        )
        self._add_session(session)
        self.status.setText(title)

    def open_local_at(self, cwd: str | None) -> None:
        profile = self._default_profile()
        path = self._local_cwd(cwd)
        backend = LocalPtyTerminalSession(
            cwd=path,
            shell_path=(self.settings.get("local_shell_path") or None),
            startup_command=(profile.get("startup_command") or None),
        )
        session = TerminalSessionWidget(
            backend,
            title=f"local:{self._display_local_path(path)}",
            profile_id=None,
            owns_connection=False,
            settings=self.settings,
        )
        self._add_session(session)
        self.status.setText(session.title())

    def apply_settings(self, settings: dict) -> None:
        merged = self._default_settings()
        merged.update(settings)
        self.settings = merged
        for index in range(self.tabs.count()):
            widget = self.tabs.widget(index)
            if isinstance(widget, TerminalSessionWidget):
                widget.apply_settings(self.settings)

    def _add_session(self, session: TerminalSessionWidget) -> None:
        session.session_finished.connect(self._close_finished_session)
        session.reconnect_requested.connect(self.terminal_reconnect_requested)
        index = self.tabs.addTab(session, session.title())
        self.tabs.setCurrentIndex(index)
        self._sync_enabled()
        QTimer.singleShot(60, session.focus_terminal)

    def _current_session(self) -> TerminalSessionWidget | None:
        widget = self.tabs.currentWidget()
        return widget if isinstance(widget, TerminalSessionWidget) else None

    def _choose_remote_target(self) -> None:
        dialog = RemoteTerminalDialog(self.connection, self.saved_profiles, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        choice = dialog.selected_choice()
        if choice is None:
            return
        if choice.kind == "active":
            self.open_at(None)
        elif choice.profile is not None:
            self.saved_profile_terminal_requested.emit(choice.profile, None)

    def _default_profile(self) -> dict:
        profiles = self.settings.get("profiles") or []
        default_name = self.settings.get("default_profile")
        for profile in profiles:
            if profile.get("name") == default_name:
                return profile
        return profiles[0] if profiles else {"name": "Default Shell", "startup_command": ""}

    def _remote_title(self, connection, cwd: str | None) -> str:  # type: ignore[no-untyped-def]
        path = cwd or "~"
        return f"{connection.profile.name}:{path}"

    def _remote_cwd(self, connection, cwd: str | None) -> str | None:  # type: ignore[no-untyped-def]
        explicit = (cwd or "").strip()
        if explicit:
            return explicit
        default_path = (getattr(connection.profile, "default_remote_path", None) or "").strip()
        if default_path and default_path != ".":
            return default_path
        return None

    def _local_cwd(self, cwd: str | None) -> str:
        if cwd:
            target = Path(cwd).expanduser()
            if target.is_file():
                target = target.parent
            if target.is_dir():
                return str(target)
        return str(Path.home())

    def _display_local_path(self, path: str) -> str:
        home = str(Path.home())
        if path == home:
            return "~"
        if path.startswith(home + "/"):
            return "~" + path[len(home) :]
        return path

    def _rename_current(self) -> None:
        index = self.tabs.currentIndex()
        if index < 0:
            return
        current = self.tabs.tabText(index)
        name, ok = QInputDialog.getText(self, "Rename terminal", "Tab name", text=current)
        if ok and name.strip():
            self.tabs.setTabText(index, name.strip())

    def _close_current(self) -> None:
        index = self.tabs.currentIndex()
        if index >= 0:
            self._close_tab(index)

    def _close_finished_session(self, session: TerminalSessionWidget) -> None:
        for index in range(self.tabs.count()):
            if self.tabs.widget(index) is session:
                self.status.setText(f"{session.title()} closed.")
                self._close_tab(index, close_backend=False)
                return

    def _close_tab(self, index: int, *, close_backend: bool = True) -> None:
        widget = self.tabs.widget(index)
        profile_id: str | None = None
        owns_connection = False
        if isinstance(widget, TerminalSessionWidget):
            profile_id = widget.profile_id
            owns_connection = widget.owns_connection
            if close_backend:
                widget.close_session()
        self.tabs.removeTab(index)
        if widget is not None:
            widget.deleteLater()
        if owns_connection and profile_id and not self._has_owned_tab(profile_id):
            self.terminal_connection_released.emit(profile_id)
        self._sync_enabled()

    def _has_owned_tab(self, profile_id: str) -> bool:
        for index in range(self.tabs.count()):
            widget = self.tabs.widget(index)
            if isinstance(widget, TerminalSessionWidget) and widget.profile_id == profile_id and widget.owns_connection:
                return True
        return False

    def _sync_empty_state(self) -> None:
        if self.tabs.count() == 0:
            self.content_stack.setCurrentWidget(self.empty_state)
        else:
            self.content_stack.setCurrentWidget(self.tabs)

    def _sync_enabled(self) -> None:
        has_session = self.tabs.count() > 0
        self.new_remote_button.setEnabled(self.connection is not None or bool(self.saved_profiles))
        self.new_local_button.setEnabled(True)
        for button in [
            self.reconnect_button,
            self.rename_button,
            self.clear_button,
            self.ctrl_c_button,
            self.copy_button,
            self.paste_button,
            self.font_down_button,
            self.font_up_button,
            self.close_button,
        ]:
            button.setEnabled(has_session)
        self._sync_empty_state()

    def _install_shortcuts(self) -> None:
        self._add_shortcut("Ctrl++", lambda: self.change_font_size(1))
        self._add_shortcut("Ctrl+=", lambda: self.change_font_size(1))
        self._add_shortcut("Ctrl+-", lambda: self.change_font_size(-1))

    def _add_shortcut(self, sequence: str, callback) -> None:  # type: ignore[no-untyped-def]
        shortcut = QShortcut(QKeySequence(sequence), self)
        shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        shortcut.activated.connect(lambda: callback() if self.isVisible() else None)
        self._shortcuts.append(shortcut)

    def _run_current(self, callback) -> None:  # type: ignore[no-untyped-def]
        session = self._current_session()
        if session is not None:
            callback(session)

    def _change_font_size(self, delta: int) -> None:
        current = int(self.settings.get("font_size", 13))
        updated = max(8, min(40, current + delta))
        if updated == current:
            return
        self.settings["font_size"] = updated
        self.apply_settings(self.settings)
        self.settings_changed.emit(dict(self.settings))

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self.clear_connection()
        super().closeEvent(event)

    @staticmethod
    def _default_settings() -> dict:
        return {
            "profiles": [{"name": "Default Shell", "startup_command": "", "cwd_mode": "current_remote_path", "theme": "dark"}],
            "default_profile": "Default Shell",
            "font_size": 13,
            "scrollback": 5000,
            "default_new_target": "active_remote",
            "local_shell_path": "",
            "local_cwd_mode": "current_local_path",
        }
