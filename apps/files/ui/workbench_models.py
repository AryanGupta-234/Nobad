from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from PySide6.QtGui import QColor, QPalette

from core.connections.connection_string import parse_connection_target


class ResponsiveBreakpoint(StrEnum):
    NARROW = "narrow"
    MEDIUM = "medium"
    WIDE = "wide"


class FilePaneMode(StrEnum):
    DUAL = "dual"
    LOCAL = "local"
    REMOTE = "remote"


@dataclass(frozen=True, slots=True)
class NavigationItem:
    key: str
    title: str
    icon_name: str
    group: str = "primary"
    enabled: bool = True
    coming_soon: bool = False


@dataclass(frozen=True, slots=True)
class ConnectionCommandState:
    status: str = "Ready"
    detail: str = "No server connected"
    connected: bool = False
    connecting: bool = False


@dataclass(frozen=True, slots=True)
class ConnectionAdvancedOptions:
    default_local_path: str | None = None
    default_remote_path: str | None = None
    environment_notes: str | None = None


@dataclass(frozen=True, slots=True)
class ConnectionFormState:
    request: dict
    advanced: ConnectionAdvancedOptions


@dataclass(frozen=True, slots=True)
class ThemeTokens:
    background: str = "#09090b"
    surface: str = "#111114"
    surface_alt: str = "#16161a"
    surface_hover: str = "#1e1e24"
    border: str = "#1e1e24"
    border_subtle: str = "#151518"
    text: str = "#f4f4f5"
    text_muted: str = "#a1a1aa"
    text_dim: str = "#71717a"
    accent: str = "#6366f1"
    accent_hover: str = "#4f46e5"
    success: str = "#10b981"
    warning: str = "#f59e0b"
    danger: str = "#ef4444"
    input_background: str = "#141418"
    terminal_background: str = "#09090b"


def breakpoint_for_width(width: int) -> ResponsiveBreakpoint:
    if width >= 900:
        return ResponsiveBreakpoint.WIDE
    if width >= 650:
        return ResponsiveBreakpoint.MEDIUM
    return ResponsiveBreakpoint.NARROW


def pane_mode_for_breakpoint(
    breakpoint: ResponsiveBreakpoint,
    preferred: FilePaneMode = FilePaneMode.DUAL,
) -> FilePaneMode:
    if breakpoint in {ResponsiveBreakpoint.WIDE, ResponsiveBreakpoint.MEDIUM}:
        return FilePaneMode.DUAL
    if preferred == FilePaneMode.REMOTE:
        return FilePaneMode.REMOTE
    return FilePaneMode.LOCAL


def default_navigation_items() -> list[NavigationItem]:
    return [
        NavigationItem("New Host", "New Host", "plus"),
        NavigationItem("Connections", "Connections", "servers"),
        NavigationItem("Files", "Dual-Pane Files", "files"),
        NavigationItem("Dashboard", "Server Health", "activity"),
        NavigationItem("Services", "Systemd Services", "services"),
        NavigationItem("Tunnels", "SSH Tunnels & Ports", "tunnels"),
        NavigationItem("Logs", "Live Log Streamer", "logs"),
        NavigationItem("Terminal", "Embedded Terminal", "terminal"),
        NavigationItem("Deployments", "Deployment Studio", "deploy"),
        NavigationItem("Playbooks", "Playbooks & Snippets", "playbooks"),
        NavigationItem("Sync Jobs", "2-Way Sync", "sync"),
        NavigationItem("Credentials", "Credential Vault", "credentials"),
        NavigationItem("Editor", "Code Editor", "editor"),
        NavigationItem("Settings", "Settings", "settings"),
    ]


def build_connection_request(
    *,
    protocol: str,
    host: str,
    port: str,
    username: str,
    auth_type: str,
    secret: str,
    key_path: str | None,
    profile_name: str | None,
    save_profile: bool,
    remember_secret: bool,
    default_local_path: str | None = None,
    default_remote_path: str | None = None,
    environment_notes: str | None = None,
    connection_options: dict | None = None,
) -> dict:
    normalized_protocol = protocol.strip().lower()
    normalized_host = host.strip()
    normalized_port = port.strip()
    normalized_username = username.strip()

    parsed = parse_connection_target(normalized_host)
    if parsed is not None:
        if parsed.protocol and parsed.protocol.lower() in {"ssh", "sftp"}:
            normalized_protocol = parsed.protocol.lower()
        if parsed.host:
            normalized_host = parsed.host
        if parsed.username and not normalized_username:
            normalized_username = parsed.username
        if parsed.port:
            normalized_port = str(parsed.port)

    if not normalized_port:
        normalized_port = default_port_for_protocol(normalized_protocol)

    return {
        "protocol": normalized_protocol,
        "host": normalized_host,
        "port": normalized_port,
        "username": normalized_username,
        "auth_type": auth_type,
        "secret": secret,
        "key_path": key_path.strip() if key_path else None,
        "profile_name": profile_name.strip() if profile_name and profile_name.strip() else None,
        "save_profile": save_profile,
        "remember_secret": remember_secret,
        "default_local_path": default_local_path.strip() if default_local_path and default_local_path.strip() else None,
        "default_remote_path": default_remote_path.strip() if default_remote_path and default_remote_path.strip() else None,
        "environment_notes": environment_notes.strip() if environment_notes and environment_notes.strip() else None,
        "connection_options": dict(connection_options or {}),
    }


def default_port_for_protocol(protocol: str) -> str:
    value = protocol.strip().lower()
    if value == "ftp":
        return "21"
    if value == "ftps":
        return "21"
    return "22"


def create_dark_palette() -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#111114"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#f4f4f5"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#09090b"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#141418"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#18181b"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#f4f4f5"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#f4f4f5"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#141418"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#f4f4f5"))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Light, QColor("#1e1e24"))
    palette.setColor(QPalette.ColorRole.Midlight, QColor("#1e1e24"))
    palette.setColor(QPalette.ColorRole.Dark, QColor("#09090b"))
    palette.setColor(QPalette.ColorRole.Mid, QColor("#141418"))
    palette.setColor(QPalette.ColorRole.Shadow, QColor("#000000"))
    palette.setColor(QPalette.ColorRole.Link, QColor("#6366f1"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#6366f1"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    return palette


def dark_theme_qss(tokens: ThemeTokens | None = None) -> str:
    t = tokens or ThemeTokens()
    return f"""
    QMainWindow {{
        background: {t.background};
    }}
    QWidget {{
        color: {t.text};
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
        font-size: 13px;
    }}
    QLabel {{
        background: transparent;
        border: none;
        color: {t.text};
    }}
    QCheckBox, QRadioButton {{
        background: transparent;
        border: none;
        color: {t.text};
    }}
    QFrame#NavigationRail {{
        background: {t.surface};
        border: 0;
        border-right: 1px solid {t.border};
    }}
    QMenuBar {{
        background: #09090b;
        color: #a1a1aa;
        border: none;
        height: 0px;
    }}
    QMenuBar::item {{
        background: transparent;
        color: transparent;
    }}
    QMenu {{
        background: #121215;
        border: 1px solid {t.border};
        border-radius: 6px;
        padding: 4px;
        color: #e4e4e7;
    }}
    QMenu::item {{
        padding: 6px 20px 6px 10px;
        border-radius: 4px;
    }}
    QMenu::item:selected {{
        background: #27272a;
        color: #ffffff;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 6px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: #27272a;
        min-height: 20px;
        border-radius: 3px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: #3f3f46;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 6px;
        margin: 0;
    }}
    QScrollBar::handle:horizontal {{
        background: #27272a;
        min-width: 20px;
        border-radius: 3px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background: #3f3f46;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0px;
    }}
    QFrame#ConnectionCommandBar, QFrame#ConnectionDrawer, QFrame#ActivityPage, QFrame#PanelHeader {{
        background: {t.surface};
        border: 1px solid {t.border};
    }}
    QFrame#ConnectionStatusBar {{
        background: {t.surface};
        border: none;
        border-bottom: 1px solid {t.border};
    }}
    QFrame#StatusBadge {{
        background: transparent;
        border: none;
    }}
    QLabel#MutedLabel {{
        color: {t.text_muted};
    }}
    QLabel#DimLabel {{
        color: {t.text_dim};
    }}
    QLabel#PageTitle {{
        font-size: 18px;
        font-weight: 700;
        color: {t.text};
    }}
    QLabel#SidebarTitle {{
        font-size: 14px;
        font-weight: 600;
        color: {t.text};
    }}
    QLabel#SectionTitle {{
        color: {t.text_muted};
        font-size: 11px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }}
    QLineEdit, QSpinBox, QTextEdit, QPlainTextEdit {{
        background: {t.input_background};
        color: {t.text};
        border: 1px solid {t.border};
        border-radius: 6px;
        padding: 6px 10px;
        selection-background-color: {t.accent};
    }}
    QLineEdit:focus, QSpinBox:focus, QTextEdit:focus, QPlainTextEdit:focus {{
        border: 1px solid {t.accent};
    }}
    QComboBox {{
        background: {t.input_background};
        color: {t.text};
        border: 1px solid {t.border};
        border-radius: 6px;
        padding: 5px 24px 5px 10px;
        min-height: 22px;
        selection-background-color: {t.accent};
    }}
    QComboBox:hover {{
        border-color: #3f3f46;
    }}
    QComboBox:focus {{
        border: 1px solid {t.accent};
    }}
    QComboBox::drop-down {{
        subcontrol-origin: padding;
        subcontrol-position: top right;
        width: 22px;
        border-left: none;
    }}
    QComboBox::down-arrow {{
        image: none;
        width: 0;
        height: 0;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-top: 5px solid {t.text_muted};
        margin-right: 6px;
    }}
    QComboBox QAbstractItemView {{
        background-color: #141418;
        color: #f4f4f5;
        border: 1px solid {t.border};
        border-radius: 6px;
        padding: 4px;
        selection-background-color: rgba(99, 102, 241, 0.25);
        selection-color: #ffffff;
        outline: none;
    }}
    QComboBox QAbstractItemView::item {{
        min-height: 28px;
        padding: 4px 10px;
        border-radius: 4px;
        color: #d4d4d8;
    }}
    QComboBox QAbstractItemView::item:selected {{
        background-color: rgba(99, 102, 241, 0.25);
        color: #ffffff;
    }}
    QComboBox QAbstractItemView::item:hover {{
        background-color: #1e1e24;
        color: #ffffff;
    }}
    QPushButton, QToolButton {{
        background: {t.surface_alt};
        color: {t.text};
        border: 1px solid {t.border};
        border-radius: 6px;
        padding: 6px 12px;
        font-weight: 500;
    }}
    QPushButton:hover, QToolButton:hover {{
        background: {t.surface_hover};
        border-color: #3f3f46;
    }}
    QPushButton:pressed, QToolButton:pressed {{
        background: {t.surface_alt};
    }}
    QPushButton#PrimaryButton, QToolButton#PrimaryButton {{
        background: {t.accent};
        border-color: {t.accent};
        color: white;
        font-weight: 600;
    }}
    QPushButton#PrimaryButton:hover, QToolButton#PrimaryButton:hover {{
        background: {t.accent_hover};
        border-color: {t.accent_hover};
    }}
    QPushButton#SuccessButton {{
        background: {t.success};
        border-color: {t.success};
        color: white;
        font-weight: 600;
    }}
    QPushButton#DangerButton {{
        background: {t.danger};
        border-color: {t.danger};
        color: white;
        font-weight: 600;
        padding: 5px 12px;
    }}
    QPushButton#DangerButton:disabled {{
        background: {t.surface_alt};
        border-color: {t.border};
        color: {t.text_dim};
    }}
    QToolButton#NavButton {{
        border: 0;
        border-radius: 8px;
        padding: 8px 12px;
        color: {t.text_muted};
        text-align: left;
    }}
    QToolButton#NavButton:hover {{
        background: {t.surface_hover};
        color: {t.text};
    }}
    QToolButton#NavButton:checked {{
        background: {t.surface_alt};
        color: {t.accent};
        font-weight: 600;
    }}
    QScrollArea, QScrollArea > QWidget > QWidget {{
        background: transparent;
        border: none;
    }}
    QTableView, QTreeView {{
        background: {t.surface};
        alternate-background-color: {t.surface_alt};
        border: 1px solid {t.border};
        border-radius: 8px;
        gridline-color: {t.border_subtle};
        selection-background-color: rgba(99, 102, 241, 0.2);
        selection-color: {t.text};
    }}
    QHeaderView {{
        background: {t.surface};
        border: none;
    }}
    QHeaderView::section {{
        background: {t.surface};
        color: {t.text_muted};
        border: 0;
        border-right: 1px solid {t.border_subtle};
        border-bottom: 1px solid {t.border};
        padding: 6px 10px;
        font-size: 11px;
        font-weight: 600;
        text-transform: uppercase;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 6px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {t.border};
        min-height: 20px;
        border-radius: 3px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: #3f3f46;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
        width: 0;
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 6px;
        margin: 0;
    }}
    QScrollBar::handle:horizontal {{
        background: {t.border};
        min-width: 20px;
        border-radius: 3px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background: #3f3f46;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        height: 0;
        width: 0;
    }}
    QTabWidget::pane {{
        border: 1px solid {t.border};
        border-radius: 8px;
        background: {t.surface};
    }}
    QTabBar::tab {{
        background: {t.surface};
        color: {t.text_muted};
        border: 0;
        border-bottom: 2px solid transparent;
        padding: 8px 14px;
        margin-right: 4px;
        font-weight: 500;
    }}
    QTabBar::tab:selected {{
        color: {t.text};
        border-bottom: 2px solid {t.accent};
    }}
    QTabBar::tab:hover:!selected {{
        color: {t.text};
    }}
    QSplitter::handle {{
        background: {t.border};
    }}
    QSplitter::handle:horizontal {{
        width: 1px;
    }}
    QSplitter::handle:vertical {{
        height: 1px;
    }}
    QStatusBar {{
        background: {t.surface};
        color: {t.text_muted};
        border-top: 1px solid {t.border};
    }}
    QMenu {{
        background: {t.surface_alt};
        border: 1px solid {t.border};
        border-radius: 8px;
        padding: 4px;
    }}
    QMenu::item {{
        padding: 6px 12px;
        border-radius: 4px;
        color: {t.text};
    }}
    QMenu::item:selected {{
        background: {t.surface_hover};
    }}
    QToolTip {{
        background: {t.surface_alt};
        color: {t.text};
        border: 1px solid {t.border};
        border-radius: 4px;
        padding: 4px 8px;
    }}
    QProgressBar {{
        background: {t.surface_alt};
        border: 1px solid {t.border};
        border-radius: 4px;
        text-align: center;
        font-size: 11px;
        color: {t.text_muted};
    }}
    QProgressBar::chunk {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {t.accent}, stop:1 {t.success});
        border-radius: 3px;
    }}
    QTreeView, QTreeWidget {{
        background: {t.surface};
        alternate-background-color: {t.surface_alt};
        border: 1px solid {t.border};
        border-radius: 8px;
        show-decoration-selected: 1;
        outline: none;
    }}
    QTreeView::item, QTreeWidget::item {{
        height: 28px;
        padding: 2px 4px;
        color: {t.text};
        border: none;
    }}
    QTreeView::item:hover, QTreeWidget::item:hover {{
        background: {t.surface_hover};
    }}
    QTreeView::item:selected, QTreeWidget::item:selected {{
        background: rgba(99, 102, 241, 0.2);
        color: #ffffff;
    }}
    QDialog, QMessageBox, QFileDialog, QInputDialog {{
        background-color: #111114;
        color: {t.text};
    }}
    QDialog QLabel, QMessageBox QLabel, QInputDialog QLabel {{
        color: {t.text};
        background: transparent;
        border: none;
    }}
    QMessageBox QLabel#qt_msgbox_label {{
        font-size: 13px;
        color: #f4f4f5;
        min-width: 400px;
        padding: 4px 0px;
    }}
    QInputDialog QLineEdit {{
        background-color: #141418;
        border: 1px solid #27272a;
        border-radius: 6px;
        color: #f4f4f5;
        padding: 8px 12px;
        font-size: 13px;
        min-width: 380px;
    }}
    QInputDialog QLineEdit:focus {{
        border: 1px solid {t.accent};
    }}
    QFileDialog QLabel {{
        color: {t.text};
        background: transparent;
        border: none;
    }}
    QFileDialog QTreeView, QFileDialog QListView {{
        background-color: #0c0d10;
        color: {t.text};
        border: 1px solid {t.border};
        border-radius: 6px;
    }}
    QFileDialog QHeaderView::section {{
        background-color: #141418;
        color: {t.text_muted};
        border: none;
        border-bottom: 1px solid {t.border};
    }}
    QFileDialog QToolButton {{
        background-color: #141418;
        border: 1px solid {t.border};
        border-radius: 4px;
        color: {t.text_muted};
        padding: 4px 8px;
    }}
    QFileDialog QToolButton:hover {{
        background-color: #1e1e24;
        color: #ffffff;
    }}
    QFileDialog QLineEdit, QFileDialog QComboBox {{
        background-color: #141418;
        border: 1px solid {t.border};
        border-radius: 6px;
        color: {t.text};
        padding: 4px 8px;
    }}
    QMessageBox QPushButton, QInputDialog QPushButton, QDialogButtonBox QPushButton, QDialog QPushButton {{
        qproperty-icon: url();
        background-color: #18181b;
        border: 1px solid #27272a;
        border-radius: 6px;
        color: #e4e4e7;
        padding: 6px 18px;
        min-width: 80px;
        font-size: 12px;
        font-weight: 500;
    }}
    QMessageBox QPushButton:hover, QInputDialog QPushButton:hover, QDialogButtonBox QPushButton:hover, QDialog QPushButton:hover {{
        background-color: #27272a;
        color: #ffffff;
        border-color: #3f3f46;
    }}
    QMessageBox QPushButton:default, QInputDialog QPushButton:default, QDialogButtonBox QPushButton:default, QDialog QPushButton:default {{
        background-color: {t.accent};
        border-color: {t.accent};
        color: #ffffff;
        font-weight: 600;
    }}
    QMessageBox QPushButton:default:hover, QInputDialog QPushButton:default:hover, QDialogButtonBox QPushButton:default:hover, QDialog QPushButton:default:hover {{
        background-color: {t.accent_hover};
    }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical,
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
        background: none;
    }}
    """
