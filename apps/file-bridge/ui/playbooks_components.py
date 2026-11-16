from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
import html
import re
from typing import Any

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.playbooks_models import (
    PlaybookCategory,
    PlaybookRecipe,
    PlaybookSafetyTier,
    PlaybookVariable,
)
from ui.icons import get_icon
from ui.theme import DEFAULT_THEME, get_mono_font, get_ui_font

_ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def clean_terminal_output(raw: str) -> str:
    """Remove raw ANSI escape sequences and normalize terminal output."""
    clean = _ANSI_RE.sub("", raw)
    # Convert carriage returns without linefeeds to standard newlines
    clean = clean.replace("\r\n", "\n").replace("\r", "\n")
    return clean


class PlaybooksSidebar(QFrame):
    """Left sidebar for collection tabs, category filters, and snippet creation."""

    collection_changed = Signal(str)
    category_changed = Signal(str)
    create_snippet_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PlaybooksSidebar")
        self.setFixedWidth(240)
        self.setStyleSheet(f"""
            QFrame#PlaybooksSidebar {{
                background-color: {DEFAULT_THEME.surface};
                border-right: 1px solid {DEFAULT_THEME.border};
            }}
        """)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet(f"""
            QScrollArea {{
                background: transparent;
                border: none;
            }}
            QScrollBar:vertical {{
                border: none;
                background: transparent;
                width: 4px;
                margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background: {DEFAULT_THEME.border};
                min-height: 20px;
                border-radius: 2px;
            }}
        """)

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 16, 12, 16)
        layout.setSpacing(12)

        # Header Title
        title_box = QHBoxLayout()
        title_box.setSpacing(8)
        icon_lbl = QLabel()
        icon_lbl.setPixmap(get_icon("playbooks", DEFAULT_THEME.accent, 20).pixmap(20, 20))
        title_box.addWidget(icon_lbl)

        title_lbl = QLabel("Playbooks Studio")
        title_lbl.setFont(get_ui_font(12, QFont.Weight.Bold))
        title_lbl.setStyleSheet(f"color: {DEFAULT_THEME.text};")
        title_box.addWidget(title_lbl)
        title_box.addStretch()
        layout.addLayout(title_box)

        # Collections Section
        coll_header = QLabel("COLLECTIONS")
        coll_header.setFont(get_ui_font(8, QFont.Weight.Bold))
        coll_header.setStyleSheet(f"color: {DEFAULT_THEME.text_dim}; letter-spacing: 0.5px;")
        layout.addWidget(coll_header)

        self._coll_buttons: dict[str, QPushButton] = {}
        collections = [
            ("all", "All Playbooks", "7"),
            ("prebundled", "Pre-bundled", "7"),
            ("custom", "Custom Snippets", "0"),
            ("favorites", "Starred / Favorites", "0"),
        ]

        for coll_id, label, default_count in collections:
            btn = QPushButton()
            btn.setCheckable(True)
            btn.setFixedHeight(34)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            
            btn_layout = QHBoxLayout(btn)
            btn_layout.setContentsMargins(10, 0, 10, 0)
            
            txt_lbl = QLabel(label)
            txt_lbl.setFont(get_ui_font(10))
            txt_lbl.setStyleSheet("color: inherit; background: transparent;")
            btn_layout.addWidget(txt_lbl)
            btn_layout.addStretch()

            badge_lbl = QLabel(default_count)
            badge_lbl.setObjectName(f"count_{coll_id}")
            badge_lbl.setFont(get_mono_font(8))
            badge_lbl.setStyleSheet(f"""
                color: {DEFAULT_THEME.text_dim};
                background: {DEFAULT_THEME.surface_hover};
                border-radius: 4px;
                padding: 1px 6px;
            """)
            btn_layout.addWidget(badge_lbl)

            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    border: 1px solid transparent;
                    border-radius: 6px;
                    color: {DEFAULT_THEME.text_muted};
                    text-align: left;
                }}
                QPushButton:hover {{
                    background: {DEFAULT_THEME.surface_hover};
                    color: {DEFAULT_THEME.text};
                }}
                QPushButton:checked {{
                    background: {DEFAULT_THEME.accent_subtle};
                    border: 1px solid rgba(99, 102, 241, 0.3);
                    color: #a5b4fc;
                }}
            """)
            btn.clicked.connect(lambda _checked=False, cid=coll_id: self._on_collection_click(cid))
            self._coll_buttons[coll_id] = btn
            layout.addWidget(btn)

        self._coll_buttons["all"].setChecked(True)

        # Categories Section
        cat_header = QLabel("CATEGORIES")
        cat_header.setFont(get_ui_font(8, QFont.Weight.Bold))
        cat_header.setStyleSheet(f"color: {DEFAULT_THEME.text_dim}; letter-spacing: 0.5px; margin-top: 10px;")
        layout.addWidget(cat_header)

        self._cat_buttons: dict[str, QPushButton] = {}
        categories = [
            ("all_cats", "All Categories", "•"),
            (PlaybookCategory.SECURITY, "Security & SSL", "🛡"),
            (PlaybookCategory.MAINTENANCE, "Maintenance & Disk", "🧹"),
            (PlaybookCategory.NETWORK, "Network & Ports", "🌐"),
            (PlaybookCategory.DOCKER, "Docker & Containers", "🐳"),
            (PlaybookCategory.DATABASE, "Database & Storage", "🗄"),
        ]

        for cat_id, cat_name, icon_char in categories:
            btn = QPushButton(f"  {icon_char}  {cat_name.replace('&', '&&')}")
            btn.setCheckable(True)
            btn.setFixedHeight(30)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFont(get_ui_font(9))
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    border: none;
                    border-radius: 6px;
                    color: {DEFAULT_THEME.text_muted};
                    text-align: left;
                    padding-left: 8px;
                }}
                QPushButton:hover {{
                    background: {DEFAULT_THEME.surface_hover};
                    color: {DEFAULT_THEME.text};
                }}
                QPushButton:checked {{
                    background: {DEFAULT_THEME.surface_active};
                    color: {DEFAULT_THEME.text};
                    font-weight: bold;
                }}
            """)
            btn.clicked.connect(lambda _checked=False, cid=cat_id: self._on_category_click(cid))
            self._cat_buttons[str(cat_id)] = btn
            layout.addWidget(btn)

        self._cat_buttons["all_cats"].setChecked(True)

        layout.addStretch()

        # Encrypted Vault Pill
        vault_card = QFrame()
        vault_card.setStyleSheet(f"""
            QFrame {{
                background-color: {DEFAULT_THEME.surface_card};
                border: 1px solid {DEFAULT_THEME.border};
                border-radius: 8px;
                padding: 10px;
            }}
        """)
        vc_layout = QVBoxLayout(vault_card)
        vc_layout.setContentsMargins(8, 8, 8, 8)
        vc_layout.setSpacing(4)

        v_top = QHBoxLayout()
        v_icon = QLabel("🔒")
        v_title = QLabel("Vault Encrypted")
        v_title.setFont(get_ui_font(9, QFont.Weight.Bold))
        v_title.setStyleSheet(f"color: {DEFAULT_THEME.success};")
        v_top.addWidget(v_icon)
        v_top.addWidget(v_title)
        v_top.addStretch()
        vc_layout.addLayout(v_top)

        v_desc = QLabel("Custom snippets protected with Argon2id & AES-256-GCM.")
        v_desc.setWordWrap(True)
        v_desc.setFont(get_ui_font(8))
        v_desc.setStyleSheet(f"color: {DEFAULT_THEME.text_dim}; line-height: 1.3;")
        vc_layout.addWidget(v_desc)

        layout.addWidget(vault_card)

        # "+ New Snippet" button
        self.new_btn = QPushButton("+ New Snippet")
        self.new_btn.setFixedHeight(34)
        self.new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.new_btn.setFont(get_ui_font(10, QFont.Weight.Medium))
        self.new_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DEFAULT_THEME.surface_card};
                border: 1px solid {DEFAULT_THEME.border};
                border-radius: 6px;
                color: {DEFAULT_THEME.text};
            }}
            QPushButton:hover {{
                background-color: {DEFAULT_THEME.surface_hover};
                border-color: {DEFAULT_THEME.accent};
                color: #ffffff;
            }}
        """)
        self.new_btn.clicked.connect(self.create_snippet_requested.emit)
        layout.addWidget(self.new_btn)

        self.scroll_area.setWidget(container)
        outer_layout.addWidget(self.scroll_area)

    def _on_collection_click(self, coll_id: str) -> None:
        for cid, btn in self._coll_buttons.items():
            btn.setChecked(cid == coll_id)
        self.collection_changed.emit(coll_id)

    def _on_category_click(self, cat_id: str) -> None:
        for cid, btn in self._cat_buttons.items():
            btn.setChecked(cid == str(cat_id))
        self.category_changed.emit(str(cat_id))

    def update_counts(self, all_count: int, prebundled_count: int, custom_count: int, fav_count: int) -> None:
        if "all" in self._coll_buttons:
            lbl = self._coll_buttons["all"].findChild(QLabel, "count_all")
            if lbl:
                lbl.setText(str(all_count))
        if "prebundled" in self._coll_buttons:
            lbl = self._coll_buttons["prebundled"].findChild(QLabel, "count_prebundled")
            if lbl:
                lbl.setText(str(prebundled_count))
        if "custom" in self._coll_buttons:
            lbl = self._coll_buttons["custom"].findChild(QLabel, "count_custom")
            if lbl:
                lbl.setText(str(custom_count))
        if "favorites" in self._coll_buttons:
            lbl = self._coll_buttons["favorites"].findChild(QLabel, "count_favorites")
            if lbl:
                lbl.setText(str(fav_count))


class PlaybookCardWidget(QFrame):
    """Playbook card item displayed in the central selection column."""

    selected = Signal(str)
    run_requested = Signal(str)
    favorite_toggled = Signal(str)

    def __init__(self, recipe: PlaybookRecipe, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.recipe = recipe
        self._is_selected = False
        self.setObjectName("PlaybookCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(122)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        # Top row: Title + Star + Run button
        top_row = QHBoxLayout()
        top_row.setSpacing(6)

        self.title_lbl = QLabel(recipe.title)
        self.title_lbl.setFont(get_ui_font(10, QFont.Weight.Bold))
        self.title_lbl.setStyleSheet(f"color: {DEFAULT_THEME.text};")
        top_row.addWidget(self.title_lbl, 1)

        # Favorite star button
        self.fav_btn = QToolButton()
        self.fav_btn.setFixedSize(24, 24)
        self.fav_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.fav_btn.setText("★" if recipe.is_favorite else "☆")
        self.fav_btn.setStyleSheet(f"""
            QToolButton {{
                background: transparent;
                border: none;
                color: {'#fbbf24' if recipe.is_favorite else DEFAULT_THEME.text_dim};
                font-size: 14px;
            }}
            QToolButton:hover {{
                color: #f59e0b;
            }}
        """)
        self.fav_btn.clicked.connect(self._on_fav_click)
        top_row.addWidget(self.fav_btn)

        # Inline Quick Run button
        self.run_btn = QPushButton("▶ Run")
        self.run_btn.setFixedSize(56, 24)
        self.run_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.run_btn.setFont(get_ui_font(8, QFont.Weight.Bold))
        self.run_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DEFAULT_THEME.accent_subtle};
                border: 1px solid rgba(99, 102, 241, 0.4);
                border-radius: 4px;
                color: #a5b4fc;
            }}
            QPushButton:hover {{
                background-color: {DEFAULT_THEME.accent};
                border-color: {DEFAULT_THEME.accent};
                color: #ffffff;
            }}
        """)
        self.run_btn.clicked.connect(self._on_run_click)
        top_row.addWidget(self.run_btn)
        layout.addLayout(top_row)

        # Description
        self.desc_lbl = QLabel(recipe.description)
        self.desc_lbl.setWordWrap(True)
        self.desc_lbl.setMaximumHeight(34)
        self.desc_lbl.setFont(get_ui_font(9))
        self.desc_lbl.setStyleSheet(f"color: {DEFAULT_THEME.text_muted};")
        layout.addWidget(self.desc_lbl)

        # Bottom row: Category badge + Safety Badge + Runtime estimate
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(6)

        # Category Badge
        cat_badge = QLabel(str(recipe.category).capitalize())
        cat_badge.setFont(get_ui_font(8))
        cat_badge.setStyleSheet(f"""
            color: {DEFAULT_THEME.text_dim};
            background: {DEFAULT_THEME.surface_hover};
            border-radius: 4px;
            padding: 2px 6px;
        """)
        bottom_row.addWidget(cat_badge)

        # Safety Badge
        safety_color = DEFAULT_THEME.success
        safety_bg = DEFAULT_THEME.success_subtle
        if recipe.safety == PlaybookSafetyTier.SUDO:
            safety_color = DEFAULT_THEME.warning
            safety_bg = DEFAULT_THEME.warning_subtle
        elif recipe.safety == PlaybookSafetyTier.DESTRUCTIVE:
            safety_color = DEFAULT_THEME.danger
            safety_bg = DEFAULT_THEME.danger_subtle

        safety_badge = QLabel(recipe.safety_label)
        safety_badge.setFont(get_ui_font(8, QFont.Weight.Medium))
        safety_badge.setStyleSheet(f"""
            color: {safety_color};
            background: {safety_bg};
            border-radius: 4px;
            padding: 2px 6px;
        """)
        bottom_row.addWidget(safety_badge)

        # Runtime estimate
        time_badge = QLabel(f"⏱ {recipe.runtime_estimate}")
        time_badge.setFont(get_mono_font(8))
        time_badge.setStyleSheet(f"color: {DEFAULT_THEME.text_dim};")
        bottom_row.addWidget(time_badge)
        bottom_row.addStretch()

        layout.addLayout(bottom_row)

        self._update_style()

    def set_selected(self, selected: bool) -> None:
        self._is_selected = selected
        self._update_style()

    def _update_style(self) -> None:
        if self._is_selected:
            self.setStyleSheet(f"""
                QFrame#PlaybookCard {{
                    background-color: #1a1a24;
                    border: 2px solid {DEFAULT_THEME.accent};
                    border-radius: 8px;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QFrame#PlaybookCard {{
                    background-color: {DEFAULT_THEME.surface_card};
                    border: 1px solid #27272a;
                    border-radius: 8px;
                }}
                QFrame#PlaybookCard:hover {{
                    background-color: {DEFAULT_THEME.surface_hover};
                    border-color: #3f3f46;
                }}
            """)

    def mousePressEvent(self, event) -> None:
        self.selected.emit(self.recipe.id)
        super().mousePressEvent(event)

    def _on_run_click(self) -> None:
        self.run_requested.emit(self.recipe.id)

    def _on_fav_click(self) -> None:
        self.recipe.is_favorite = not self.recipe.is_favorite
        self.fav_btn.setText("★" if self.recipe.is_favorite else "☆")
        self.fav_btn.setStyleSheet(f"""
            QToolButton {{
                background: transparent;
                border: none;
                color: {'#fbbf24' if self.recipe.is_favorite else DEFAULT_THEME.text_dim};
                font-size: 14px;
            }}
            QToolButton:hover {{
                color: #f59e0b;
            }}
        """)
        self.favorite_toggled.emit(self.recipe.id)


class PlaybookInspectorWidget(QFrame):
    """Right pane inspector with dynamic parameter form and code canvas."""

    run_requested = Signal(dict)
    fork_requested = Signal(str)
    delete_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.recipe: PlaybookRecipe | None = None
        self._param_inputs: dict[str, QWidget] = {}
        self._connected: bool = False
        self._connection_target: str = ""

        self.setObjectName("PlaybookInspector")
        self.setStyleSheet(f"""
            QFrame#PlaybookInspector {{
                background-color: {DEFAULT_THEME.canvas};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(14)

        # Header: Title, Category pill, Safety badge, Action buttons
        header_row = QHBoxLayout()
        header_row.setSpacing(10)

        self.title_lbl = QLabel("Select a playbook")
        self.title_lbl.setFont(get_ui_font(13, QFont.Weight.Bold))
        self.title_lbl.setStyleSheet(f"color: {DEFAULT_THEME.text};")
        header_row.addWidget(self.title_lbl)

        self.safety_badge = QLabel("")
        self.safety_badge.setFont(get_ui_font(8, QFont.Weight.Bold))
        self.safety_badge.setStyleSheet(f"""
            color: {DEFAULT_THEME.success};
            background: {DEFAULT_THEME.success_subtle};
            border-radius: 4px;
            padding: 2px 8px;
        """)
        header_row.addWidget(self.safety_badge)
        header_row.addStretch()

        # Action buttons
        self.copy_btn = QPushButton("Copy Script")
        self.copy_btn.setFixedHeight(28)
        self.copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_btn.setFont(get_ui_font(9))
        self.copy_btn.setStyleSheet(f"""
            QPushButton {{
                background: {DEFAULT_THEME.surface_card};
                border: 1px solid {DEFAULT_THEME.border};
                border-radius: 6px;
                color: {DEFAULT_THEME.text_muted};
                padding: 0 10px;
            }}
            QPushButton:hover {{
                background: {DEFAULT_THEME.surface_hover};
                color: {DEFAULT_THEME.text};
            }}
        """)
        self.copy_btn.clicked.connect(self._copy_script)
        header_row.addWidget(self.copy_btn)

        self.fork_btn = QPushButton("Duplicate / Fork")
        self.fork_btn.setFixedHeight(28)
        self.fork_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.fork_btn.setFont(get_ui_font(9))
        self.fork_btn.setStyleSheet(f"""
            QPushButton {{
                background: {DEFAULT_THEME.surface_card};
                border: 1px solid {DEFAULT_THEME.border};
                border-radius: 6px;
                color: {DEFAULT_THEME.text_muted};
                padding: 0 10px;
            }}
            QPushButton:hover {{
                background: {DEFAULT_THEME.surface_hover};
                color: {DEFAULT_THEME.text};
            }}
        """)
        self.fork_btn.clicked.connect(self._on_fork)
        header_row.addWidget(self.fork_btn)

        self.delete_btn = QPushButton("Delete Snippet")
        self.delete_btn.setFixedHeight(28)
        self.delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delete_btn.setFont(get_ui_font(9, QFont.Weight.Medium))
        self.delete_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(239, 68, 68, 0.12);
                border: 1px solid rgba(239, 68, 68, 0.35);
                border-radius: 6px;
                color: #f87171;
                padding: 0 10px;
            }}
            QPushButton:hover {{
                background: #ef4444;
                border-color: #ef4444;
                color: #ffffff;
            }}
        """)
        self.delete_btn.clicked.connect(self._on_delete)
        self.delete_btn.hide()
        header_row.addWidget(self.delete_btn)

        layout.addLayout(header_row)

        # Description
        self.desc_lbl = QLabel("")
        self.desc_lbl.setWordWrap(True)
        self.desc_lbl.setFont(get_ui_font(9))
        self.desc_lbl.setStyleSheet(f"color: {DEFAULT_THEME.text_muted}; line-height: 1.4;")
        layout.addWidget(self.desc_lbl)

        # Dynamic Parameters Form Area
        self.params_container = QFrame()
        self.params_container.setObjectName("ParamsContainer")
        self.params_container.setStyleSheet(f"""
            QFrame#ParamsContainer {{
                background-color: #111116;
                border: 1px solid #27272a;
                border-radius: 8px;
                padding: 12px;
            }}
        """)
        self.params_layout = QVBoxLayout(self.params_container)
        self.params_layout.setContentsMargins(12, 12, 12, 12)
        self.params_layout.setSpacing(10)

        params_title = QLabel("DYNAMIC PARAMETERS & RUNTIME CONFIG")
        params_title.setFont(get_ui_font(8, QFont.Weight.Bold))
        params_title.setStyleSheet(f"color: {DEFAULT_THEME.text_dim}; letter-spacing: 0.5px;")
        self.params_layout.addWidget(params_title)

        self.params_form_host = QWidget()
        self.params_form_layout = QVBoxLayout(self.params_form_host)
        self.params_form_layout.setContentsMargins(0, 0, 0, 0)
        self.params_form_layout.setSpacing(8)
        self.params_layout.addWidget(self.params_form_host)
        layout.addWidget(self.params_container)

        # 4-Stage Execution Pipeline visualization (wrapped in horizontal scroll for responsiveness)
        self.pipeline_scroll = QScrollArea()
        self.pipeline_scroll.setWidgetResizable(True)
        self.pipeline_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.pipeline_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.pipeline_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.pipeline_scroll.setFixedHeight(34)
        self.pipeline_scroll.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
        """)

        self.pipeline_container = QFrame()
        self.pipeline_container.setStyleSheet("background: transparent; border: none;")
        self.pipeline_layout = QHBoxLayout(self.pipeline_container)
        self.pipeline_layout.setContentsMargins(0, 0, 0, 0)
        self.pipeline_layout.setSpacing(8)
        self.pipeline_scroll.setWidget(self.pipeline_container)
        layout.addWidget(self.pipeline_scroll)

        # Monospace Code Canvas
        canvas_header = QHBoxLayout()
        canvas_lbl = QLabel("BASH SCRIPT PREVIEW (INTERPOLATED)")
        canvas_lbl.setFont(get_ui_font(8, QFont.Weight.Bold))
        canvas_lbl.setStyleSheet(f"color: {DEFAULT_THEME.text_dim}; letter-spacing: 0.5px;")
        canvas_header.addWidget(canvas_lbl)
        canvas_header.addStretch()

        self.mode_badge = QLabel("Interactive PTY")
        self.mode_badge.setFont(get_mono_font(8))
        self.mode_badge.setStyleSheet(f"""
            color: #38bdf8;
            background: rgba(56, 189, 248, 0.12);
            border-radius: 4px;
            padding: 2px 6px;
        """)
        canvas_header.addWidget(self.mode_badge)
        layout.addLayout(canvas_header)

        self.code_edit = QPlainTextEdit()
        self.code_edit.setReadOnly(True)
        self.code_edit.setFont(get_mono_font(9))
        self.code_edit.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: #09090d;
                border: 1px solid #27272a;
                border-radius: 8px;
                color: #f4f4f5;
                padding: 12px;
                line-height: 1.5;
            }}
            QPlainTextEdit:focus {{
                border-color: #3f3f46;
            }}
        """)
        layout.addWidget(self.code_edit, 1)

        # Bottom Action Bar
        bottom_bar = QHBoxLayout()
        bottom_bar.setSpacing(12)

        self.conn_note = QLabel("SSH Status: Disconnected")
        self.conn_note.setFont(get_ui_font(9))
        self.conn_note.setStyleSheet(f"color: {DEFAULT_THEME.text_dim};")
        bottom_bar.addWidget(self.conn_note)
        bottom_bar.addStretch()

        self.run_cta = QPushButton("▶  1-Click Run on Server (Ctrl+Enter)")
        self.run_cta.setFixedHeight(40)
        self.run_cta.setCursor(Qt.CursorShape.PointingHandCursor)
        self.run_cta.setFont(get_ui_font(10, QFont.Weight.Bold))
        self.run_cta.setStyleSheet(f"""
            QPushButton {{
                background-color: #059669;
                border: 1px solid #10b981;
                border-radius: 8px;
                color: #ffffff;
                padding: 0 20px;
            }}
            QPushButton:hover {{
                background-color: #10b981;
            }}
            QPushButton:disabled {{
                background-color: {DEFAULT_THEME.surface_card};
                border-color: {DEFAULT_THEME.border};
                color: {DEFAULT_THEME.text_dim};
            }}
        """)
        self.run_cta.clicked.connect(self._on_run_cta)
        bottom_bar.addWidget(self.run_cta)

        layout.addLayout(bottom_bar)

    def set_connection(self, connected: bool, target: str = "") -> None:
        self._connected = connected
        self._connection_target = target
        if connected:
            self.conn_note.setText(f"● Connected: {target}")
            self.conn_note.setStyleSheet(f"color: {DEFAULT_THEME.success};")
            self.run_cta.setEnabled(True)
            self.run_cta.setToolTip("Execute playbook on active remote server")
        else:
            self.conn_note.setText("○ Disconnected — Active SSH session required to run")
            self.conn_note.setStyleSheet(f"color: {DEFAULT_THEME.text_dim};")
            self.run_cta.setEnabled(False)
            self.run_cta.setToolTip("Please connect to a server first via Connections or New Host")

    def load_recipe(self, recipe: PlaybookRecipe) -> None:
        self.recipe = recipe
        self.title_lbl.setText(recipe.title)
        self.desc_lbl.setText(recipe.description)
        self.safety_badge.setText(recipe.safety_label)

        # Show Delete button ONLY for custom/forked snippets
        if not recipe.is_prebundled:
            self.delete_btn.show()
        else:
            self.delete_btn.hide()

        safety_color = DEFAULT_THEME.success
        safety_bg = DEFAULT_THEME.success_subtle
        if recipe.safety == PlaybookSafetyTier.SUDO:
            safety_color = DEFAULT_THEME.warning
            safety_bg = DEFAULT_THEME.warning_subtle
        elif recipe.safety == PlaybookSafetyTier.DESTRUCTIVE:
            safety_color = DEFAULT_THEME.danger
            safety_bg = DEFAULT_THEME.danger_subtle

        self.safety_badge.setStyleSheet(f"""
            color: {safety_color};
            background: {safety_bg};
            border-radius: 4px;
            padding: 2px 8px;
        """)

        # Rebuild parameters form cleanly
        for child in self.params_form_host.findChildren(QWidget):
            child.setParent(None)
            child.deleteLater()

        while self.params_form_layout.count():
            item = self.params_form_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
                item.widget().deleteLater()

        self._param_inputs.clear()

        if not recipe.variables:
            none_lbl = QLabel("No configurable variables — recipe runs with standard safe flags.")
            none_lbl.setFont(get_ui_font(9))
            none_lbl.setStyleSheet(f"color: {DEFAULT_THEME.text_dim}; font-style: italic;")
            self.params_form_layout.addWidget(none_lbl)
        else:
            for var in recipe.variables:
                row = QHBoxLayout()
                row.setSpacing(10)

                lbl = QLabel(var.label)
                lbl.setFont(get_ui_font(9))
                lbl.setStyleSheet(f"color: {DEFAULT_THEME.text}; min-width: 160px;")
                row.addWidget(lbl)

                if var.var_type == "boolean":
                    cb = QCheckBox("Enable")
                    cb.setChecked(var.default_value.lower() in ("true", "1", "yes"))
                    cb.stateChanged.connect(self._reinterpolate_code)
                    self._param_inputs[var.key] = cb
                    row.addWidget(cb)
                elif var.var_type == "choice" and var.options:
                    combo = QComboBox()
                    combo.addItems(var.options)
                    if var.default_value in var.options:
                        combo.setCurrentText(var.default_value)
                    combo.setFont(get_ui_font(9))
                    combo.setStyleSheet(f"""
                        QComboBox {{
                            background-color: #18181f;
                            border: 1px solid #3f3f46;
                            border-radius: 6px;
                            color: #f4f4f5;
                            padding: 6px 10px;
                        }}
                        QComboBox:hover {{
                            border-color: #52525b;
                        }}
                        QComboBox:focus {{
                            border: 1px solid {DEFAULT_THEME.accent};
                        }}
                    """)
                    combo.currentTextChanged.connect(self._reinterpolate_code)
                    self._param_inputs[var.key] = combo
                    row.addWidget(combo, 1)
                else:
                    line = QLineEdit(var.default_value)
                    line.setFont(get_mono_font(9))
                    line.setStyleSheet(f"""
                        QLineEdit {{
                            background-color: #18181f;
                            border: 1px solid #3f3f46;
                            border-radius: 6px;
                            color: #f4f4f5;
                            padding: 6px 10px;
                        }}
                        QLineEdit:hover {{
                            border-color: #52525b;
                        }}
                        QLineEdit:focus {{
                            border: 1px solid {DEFAULT_THEME.accent};
                            background-color: #1e1e28;
                        }}
                    """)
                    line.textChanged.connect(self._reinterpolate_code)
                    self._param_inputs[var.key] = line
                    row.addWidget(line, 1)

                self.params_form_layout.addLayout(row)

        # Pipeline Steps
        for child in self.pipeline_container.findChildren(QWidget):
            child.setParent(None)
            child.deleteLater()

        while self.pipeline_layout.count():
            item = self.pipeline_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
                item.widget().deleteLater()

        for idx, step_name in enumerate(recipe.steps, start=1):
            pill = QLabel(f"{idx}. {step_name}")
            pill.setFont(get_ui_font(8))
            pill.setStyleSheet(f"""
                color: {DEFAULT_THEME.text_muted};
                background: {DEFAULT_THEME.surface_card};
                border: 1px solid {DEFAULT_THEME.border};
                border-radius: 4px;
                padding: 4px 8px;
            """)
            self.pipeline_layout.addWidget(pill)

        self._reinterpolate_code()

    def get_parameter_values(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for key, widget in self._param_inputs.items():
            if isinstance(widget, QCheckBox):
                values[key] = "true" if widget.isChecked() else "false"
            elif isinstance(widget, QComboBox):
                values[key] = widget.currentText()
            elif isinstance(widget, QLineEdit):
                values[key] = widget.text().strip()
        return values

    def _reinterpolate_code(self) -> None:
        if not self.recipe:
            return
        vals = self.get_parameter_values()
        from core.playbooks_manager import interpolate_template
        interpolated = interpolate_template(self.recipe.script_template, vals)
        self.code_edit.setPlainText(interpolated)

    def _copy_script(self) -> None:
        from PySide6.QtGui import QGuiApplication
        clipboard = QGuiApplication.clipboard()
        if clipboard:
            clipboard.setText(self.code_edit.toPlainText())
            self.copy_btn.setText("Copied!")
            QTimer.singleShot(1500, lambda: self.copy_btn.setText("Copy Script"))

    def _on_fork(self) -> None:
        if self.recipe:
            self.fork_requested.emit(self.recipe.id)

    def _on_delete(self) -> None:
        if self.recipe and not self.recipe.is_prebundled:
            self.delete_requested.emit(self.recipe.id)

    def _on_run_cta(self) -> None:
        if self.recipe:
            vals = self.get_parameter_values()
            self.run_requested.emit(vals)


class PlaybookExecutionDock(QFrame):
    """Slide-up bottom dock displaying live streaming terminal output and pipeline status."""

    stop_requested = Signal()
    close_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._elapsed_seconds = 0.0
        self._auto_scroll = True
        self.setObjectName("PlaybookExecutionDock")
        self.setFixedHeight(300)
        self.setStyleSheet(f"""
            QFrame#PlaybookExecutionDock {{
                background-color: {DEFAULT_THEME.canvas};
                border-top: 1px solid {DEFAULT_THEME.border};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 12)
        layout.setSpacing(8)

        # Header: Status, Timer, PID, Target, Pipeline steps, Controls
        header = QHBoxLayout()
        header.setSpacing(10)

        # Status Pill
        self.status_pill = QLabel("● Streaming Output")
        self.status_pill.setFont(get_ui_font(9, QFont.Weight.Bold))
        self.status_pill.setStyleSheet(f"""
            color: #38bdf8;
            background: rgba(56, 189, 248, 0.12);
            border: 1px solid rgba(56, 189, 248, 0.3);
            border-radius: 6px;
            padding: 3px 10px;
        """)
        header.addWidget(self.status_pill)

        # Elapsed Timer
        self.timer_lbl = QLabel("⏱ 0.0s")
        self.timer_lbl.setFont(get_mono_font(9))
        self.timer_lbl.setStyleSheet(f"color: {DEFAULT_THEME.text_dim};")
        header.addWidget(self.timer_lbl)

        # Target badge
        self.target_lbl = QLabel("Target: —")
        self.target_lbl.setFont(get_mono_font(8))
        self.target_lbl.setStyleSheet(f"""
            color: {DEFAULT_THEME.text_muted};
            background: {DEFAULT_THEME.surface_hover};
            border-radius: 4px;
            padding: 2px 6px;
        """)
        header.addWidget(self.target_lbl)

        header.addStretch()

        # Auto-scroll checkbox
        self.autoscroll_cb = QCheckBox("Auto-scroll")
        self.autoscroll_cb.setChecked(True)
        self.autoscroll_cb.setFont(get_ui_font(8))
        self.autoscroll_cb.setStyleSheet(f"color: {DEFAULT_THEME.text_muted};")
        self.autoscroll_cb.stateChanged.connect(self._on_autoscroll_change)
        header.addWidget(self.autoscroll_cb)

        # Copy Logs button
        self.copy_btn = QPushButton("Copy Logs")
        self.copy_btn.setFixedHeight(24)
        self.copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_btn.setFont(get_ui_font(8))
        self.copy_btn.setStyleSheet(f"""
            QPushButton {{
                background: {DEFAULT_THEME.surface_card};
                border: 1px solid {DEFAULT_THEME.border};
                border-radius: 4px;
                color: {DEFAULT_THEME.text_muted};
                padding: 0 8px;
            }}
            QPushButton:hover {{
                background: {DEFAULT_THEME.surface_hover};
                color: {DEFAULT_THEME.text};
            }}
        """)
        self.copy_btn.clicked.connect(self._copy_logs)
        header.addWidget(self.copy_btn)

        # Clear button
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setFixedHeight(24)
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_btn.setFont(get_ui_font(8))
        self.clear_btn.setStyleSheet(f"""
            QPushButton {{
                background: {DEFAULT_THEME.surface_card};
                border: 1px solid {DEFAULT_THEME.border};
                border-radius: 4px;
                color: {DEFAULT_THEME.text_muted};
                padding: 0 8px;
            }}
            QPushButton:hover {{
                background: {DEFAULT_THEME.surface_hover};
                color: {DEFAULT_THEME.text};
            }}
        """)
        self.clear_btn.clicked.connect(self.clear_logs)
        header.addWidget(self.clear_btn)

        # Stop button (SIGINT)
        self.stop_btn = QPushButton("Stop (SIGINT)")
        self.stop_btn.setFixedHeight(24)
        self.stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_btn.setFont(get_ui_font(8, QFont.Weight.Bold))
        self.stop_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: rgba(239, 68, 68, 0.15);
                border: 1px solid #ef4444;
                border-radius: 4px;
                color: #f87171;
                padding: 0 10px;
            }}
            QPushButton:hover {{
                background-color: #ef4444;
                color: #ffffff;
            }}
        """)
        self.stop_btn.clicked.connect(self.stop_requested.emit)
        header.addWidget(self.stop_btn)

        # Close dock button
        self.close_btn = QToolButton()
        self.close_btn.setText("✕")
        self.close_btn.setFixedSize(24, 24)
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.setStyleSheet(f"""
            QToolButton {{
                background: transparent;
                border: none;
                color: {DEFAULT_THEME.text_dim};
                font-size: 11px;
            }}
            QToolButton:hover {{
                color: {DEFAULT_THEME.text};
            }}
        """)
        self.close_btn.clicked.connect(self.close_requested.emit)
        header.addWidget(self.close_btn)

        layout.addLayout(header)

        # Pipeline progress pills row
        self.steps_container = QFrame()
        self.steps_layout = QHBoxLayout(self.steps_container)
        self.steps_layout.setContentsMargins(0, 0, 0, 0)
        self.steps_layout.setSpacing(6)
        layout.addWidget(self.steps_container)

        # Terminal output display
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setFont(get_mono_font(9))
        self.console.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: #08080a;
                border: 1px solid {DEFAULT_THEME.border};
                border-radius: 6px;
                color: #f1f5f9;
                padding: 8px;
                selection-background-color: {DEFAULT_THEME.accent};
            }}
        """)
        layout.addWidget(self.console, 1)

        # QTimer for elapsed time
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._on_timer_tick)

    def start_execution(self, target: str, steps: list[str]) -> None:
        self.clear_logs()
        self._elapsed_seconds = 0.0
        self.timer_lbl.setText("⏱ 0.0s")
        self.target_lbl.setText(f"Target: {target}")
        self.status_pill.setText("● Running Process...")
        self.status_pill.setStyleSheet(f"""
            color: #38bdf8;
            background: rgba(56, 189, 248, 0.12);
            border: 1px solid rgba(56, 189, 248, 0.3);
            border-radius: 6px;
            padding: 3px 10px;
        """)
        self.stop_btn.setEnabled(True)

        # Build steps pills
        while self.steps_layout.count():
            item = self.steps_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for idx, s in enumerate(steps, start=1):
            pill = QLabel(f"Step {idx}: {s}")
            pill.setFont(get_ui_font(8))
            pill.setStyleSheet(f"""
                color: {DEFAULT_THEME.text_dim};
                background: {DEFAULT_THEME.surface_card};
                border: 1px solid {DEFAULT_THEME.border};
                border-radius: 4px;
                padding: 2px 6px;
            """)
            self.steps_layout.addWidget(pill)

        self.steps_layout.addStretch()
        self._timer.start()

    def append_output(self, chunk: str) -> None:
        cleaned = clean_terminal_output(chunk)
        self.console.moveCursor(QTextCursor.MoveOperation.End)
        self.console.insertPlainText(cleaned)
        if self._auto_scroll:
            self.console.moveCursor(QTextCursor.MoveOperation.End)

    def finish_execution(self, exit_code: int, duration_ms: int, message: str) -> None:
        self._timer.stop()
        self.stop_btn.setEnabled(False)
        dur_s = duration_ms / 1000.0
        self.timer_lbl.setText(f"⏱ {dur_s:.1f}s")

        if exit_code == 0:
            self.status_pill.setText(f"✔ Completed (Exit Code 0)")
            self.status_pill.setStyleSheet(f"""
                color: {DEFAULT_THEME.success};
                background: {DEFAULT_THEME.success_subtle};
                border: 1px solid rgba(16, 185, 129, 0.4);
                border-radius: 6px;
                padding: 3px 10px;
            """)
        elif exit_code == 130:
            self.status_pill.setText("⊘ Cancelled (SIGINT)")
            self.status_pill.setStyleSheet(f"""
                color: {DEFAULT_THEME.warning};
                background: {DEFAULT_THEME.warning_subtle};
                border: 1px solid rgba(245, 158, 11, 0.4);
                border-radius: 6px;
                padding: 3px 10px;
            """)
        else:
            self.status_pill.setText(f"✖ Failed (Exit Code {exit_code})")
            self.status_pill.setStyleSheet(f"""
                color: {DEFAULT_THEME.danger};
                background: {DEFAULT_THEME.danger_subtle};
                border: 1px solid rgba(239, 68, 68, 0.4);
                border-radius: 6px;
                padding: 3px 10px;
            """)

    def clear_logs(self) -> None:
        self.console.clear()

    def _copy_logs(self) -> None:
        from PySide6.QtGui import QGuiApplication
        cb = QGuiApplication.clipboard()
        if cb:
            cb.setText(self.console.toPlainText())
            self.copy_btn.setText("Copied!")
            QTimer.singleShot(1500, lambda: self.copy_btn.setText("Copy Logs"))

    def _on_autoscroll_change(self, state: int) -> None:
        self._auto_scroll = (state == Qt.CheckState.Checked.value)

    def _on_timer_tick(self) -> None:
        self._elapsed_seconds += 0.1
        self.timer_lbl.setText(f"⏱ {self._elapsed_seconds:.1f}s")


class NewSnippetDialog(QDialog):
    """Modal dialog for creating a custom playbook snippet saved to encrypted storage."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create Custom Playbook Snippet")
        self.resize(600, 560)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {DEFAULT_THEME.surface};
                color: {DEFAULT_THEME.text};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        # Header
        h_lbl = QLabel("New Custom Playbook")
        h_lbl.setFont(get_ui_font(13, QFont.Weight.Bold))
        layout.addWidget(h_lbl)

        # Title
        t_lbl = QLabel("Title")
        t_lbl.setFont(get_ui_font(9, QFont.Weight.Medium))
        layout.addWidget(t_lbl)
        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("e.g. Restart Production Rails & Puma")
        self.title_input.setFont(get_ui_font(10))
        self.title_input.setStyleSheet(f"""
            QLineEdit {{
                background: #141418;
                border: 1px solid #3f3f46;
                border-radius: 6px;
                color: #f4f4f5;
                padding: 7px 10px;
            }}
            QLineEdit:hover {{
                border-color: #52525b;
            }}
            QLineEdit:focus {{
                border-color: {DEFAULT_THEME.accent};
                background-color: #18181f;
            }}
        """)
        layout.addWidget(self.title_input)

        # Category and Safety Row
        row = QHBoxLayout()
        row.setSpacing(12)

        cat_col = QVBoxLayout()
        c_lbl = QLabel("Category")
        c_lbl.setFont(get_ui_font(9, QFont.Weight.Medium))
        cat_col.addWidget(c_lbl)
        self.cat_combo = QComboBox()
        self.cat_combo.addItems([
            "custom",
            "security",
            "maintenance",
            "network",
            "docker",
            "database",
        ])
        self.cat_combo.setStyleSheet(f"""
            QComboBox {{
                background: #141418;
                border: 1px solid #3f3f46;
                border-radius: 6px;
                color: #f4f4f5;
                padding: 6px 10px;
            }}
            QComboBox:hover {{
                border-color: #52525b;
            }}
            QComboBox:focus {{
                border-color: {DEFAULT_THEME.accent};
            }}
        """)
        cat_col.addWidget(self.cat_combo)
        row.addLayout(cat_col)

        safety_col = QVBoxLayout()
        s_lbl = QLabel("Safety Level")
        s_lbl.setFont(get_ui_font(9, QFont.Weight.Medium))
        safety_col.addWidget(s_lbl)
        self.safety_combo = QComboBox()
        self.safety_combo.addItem("Safe (Read-Only)", PlaybookSafetyTier.SAFE)
        self.safety_combo.addItem("Requires Sudo (Elevation)", PlaybookSafetyTier.SUDO)
        self.safety_combo.addItem("Destructive (Resource Prune)", PlaybookSafetyTier.DESTRUCTIVE)
        self.safety_combo.setStyleSheet(f"""
            QComboBox {{
                background: #141418;
                border: 1px solid #3f3f46;
                border-radius: 6px;
                color: #f4f4f5;
                padding: 6px 10px;
            }}
            QComboBox:hover {{
                border-color: #52525b;
            }}
            QComboBox:focus {{
                border-color: {DEFAULT_THEME.accent};
            }}
        """)
        safety_col.addWidget(self.safety_combo)
        row.addLayout(safety_col)

        layout.addLayout(row)

        # Description
        d_lbl = QLabel("Description")
        d_lbl.setFont(get_ui_font(9, QFont.Weight.Medium))
        layout.addWidget(d_lbl)
        self.desc_input = QLineEdit()
        self.desc_input.setPlaceholderText("Summary of operations and target services...")
        self.desc_input.setFont(get_ui_font(9))
        self.desc_input.setStyleSheet(f"""
            QLineEdit {{
                background: #141418;
                border: 1px solid #3f3f46;
                border-radius: 6px;
                color: #f4f4f5;
                padding: 7px 10px;
            }}
            QLineEdit:hover {{
                border-color: #52525b;
            }}
            QLineEdit:focus {{
                border-color: {DEFAULT_THEME.accent};
                background-color: #18181f;
            }}
        """)
        layout.addWidget(self.desc_input)

        # Bash Script Template
        s_lbl = QLabel("Bash Script Template (use {{VARIABLE}} for placeholders)")
        s_lbl.setFont(get_ui_font(9, QFont.Weight.Medium))
        layout.addWidget(s_lbl)
        self.script_input = QPlainTextEdit()
        self.script_input.setPlaceholderText("#!/usr/bin/env bash\nset -euo pipefail\n\necho 'Running custom task...'")
        self.script_input.setFont(get_mono_font(9))
        self.script_input.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: #0c0d12;
                border: 1px solid #3f3f46;
                border-radius: 6px;
                color: #e2e8f0;
                padding: 10px;
            }}
            QPlainTextEdit:hover {{
                border-color: #52525b;
            }}
            QPlainTextEdit:focus {{
                border-color: {DEFAULT_THEME.accent};
                background-color: #101116;
            }}
        """)
        layout.addWidget(self.script_input, 1)

        # Buttons
        btns = QHBoxLayout()
        btns.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(cancel_btn)

        save_btn = QPushButton("Save to Vault")
        save_btn.setFont(get_ui_font(10, QFont.Weight.Bold))
        save_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DEFAULT_THEME.accent};
                border: 1px solid {DEFAULT_THEME.accent_hover};
                border-radius: 6px;
                color: #ffffff;
                padding: 6px 16px;
            }}
            QPushButton:hover {{
                background-color: {DEFAULT_THEME.accent_hover};
            }}
        """)
        save_btn.clicked.connect(self._validate_and_accept)
        btns.addWidget(save_btn)

        layout.addLayout(btns)

    def _validate_and_accept(self) -> None:
        if not self.title_input.text().strip():
            self.title_input.setFocus()
            return
        if not self.script_input.toPlainText().strip():
            self.script_input.setFocus()
            return
        self.accept()

    def build_recipe(self) -> PlaybookRecipe:
        title = self.title_input.text().strip()
        cat = self.cat_combo.currentText()
        safety = self.safety_combo.currentData() or PlaybookSafetyTier.SAFE
        safety_label = "Safe"
        if safety == PlaybookSafetyTier.SUDO:
            safety_label = "Requires Sudo"
        elif safety == PlaybookSafetyTier.DESTRUCTIVE:
            safety_label = "Destructive"

        desc = self.desc_input.text().strip()
        script = self.script_input.toPlainText()

        # Automatically extract placeholders e.g. {{KEY}}
        placeholders = list(dict.fromkeys(re.findall(r"\{\{([A-Z0-9_]+)\}\}", script)))
        variables = [
            PlaybookVariable(key=k, label=k.replace("_", " ").title(), default_value="")
            for k in placeholders
        ]

        import uuid
        return PlaybookRecipe(
            id=f"custom-{uuid.uuid4().hex[:8]}",
            title=title,
            category=cat,
            safety=safety,
            safety_label=safety_label,
            description=desc,
            script_template=script,
            variables=variables,
            steps=["Initialize environment", "Execute custom instructions", "Verify service exit code"],
            is_prebundled=False,
            is_favorite=False,
            runtime_estimate="~5s",
        )
