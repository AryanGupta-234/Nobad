from __future__ import annotations

import logging
from typing import Any
import uuid

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from core.playbooks_manager import PREBUNDLED_RECIPES, PlaybookStreamingRunner, interpolate_template
from core.playbooks_models import (
    PlaybookCategory,
    PlaybookExecutionRecord,
    PlaybookRecipe,
    PlaybookSafetyTier,
)
from storage.app_data import AppDataService
from ui.async_worker import AsyncProgressWorker
from ui.icons import get_icon
from ui.playbooks_components import (
    NewSnippetDialog,
    PlaybookCardWidget,
    PlaybookExecutionDock,
    PlaybookInspectorWidget,
    PlaybooksSidebar,
)
from ui.theme import DEFAULT_THEME, get_mono_font, get_ui_font

logger = logging.getLogger("remote_file_manager.playbooks_panel")


class PlaybooksPanel(QWidget):
    """
    ⚡ Script Snippets & 1-Click Playbooks Studio.
    Pairs curated sysadmin maintenance recipes with encrypted custom snippets
    and interactive live streaming terminal execution over SSH.
    """

    def __init__(self, app_data: AppDataService | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.app_data = app_data
        self.connection: Any = None
        self._current_profile: Any = None

        self._active_collection: str = "all"
        self._active_category: str = "all_cats"
        self._search_query: str = ""

        self._recipes: list[PlaybookRecipe] = []
        self._selected_recipe: PlaybookRecipe | None = None
        self._card_widgets: dict[str, PlaybookCardWidget] = {}

        self._runner: PlaybookStreamingRunner | None = None
        self._active_worker: AsyncProgressWorker | None = None

        self._init_ui()
        self._load_recipes()

        # Keyboard shortcut for run
        self._run_shortcut = QShortcut(QKeySequence("Ctrl+Return"), self)
        self._run_shortcut.activated.connect(self._on_run_shortcut)

    def _init_ui(self) -> None:
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 1. Left Sidebar
        self.sidebar = PlaybooksSidebar(self)
        self.sidebar.collection_changed.connect(self._on_collection_changed)
        self.sidebar.category_changed.connect(self._on_category_changed)
        self.sidebar.create_snippet_requested.connect(self._open_new_snippet_dialog)
        main_layout.addWidget(self.sidebar)

        # 2. Main Studio Area (Vertical Splitter: Content Area + Slide-up Execution Dock)
        self.main_v_splitter = QSplitter(Qt.Orientation.Vertical)
        self.main_v_splitter.setHandleWidth(1)
        self.main_v_splitter.setStyleSheet(f"""
            QSplitter::handle {{
                background-color: {DEFAULT_THEME.border};
            }}
        """)

        # Top Section: Horizontal Splitter (Middle Cards List + Right Inspector)
        top_container = QWidget()
        top_layout = QHBoxLayout(top_container)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(0)

        self.content_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.content_splitter.setHandleWidth(1)
        self.content_splitter.setStyleSheet(f"""
            QSplitter::handle {{
                background-color: {DEFAULT_THEME.border};
            }}
        """)

        # --- Middle Column: Search + Card List ---
        middle_col = QFrame()
        middle_col.setMinimumWidth(260)
        middle_col.setMaximumWidth(460)
        middle_col.setStyleSheet(f"""
            QFrame {{
                background-color: {DEFAULT_THEME.surface};
                border-right: 1px solid {DEFAULT_THEME.border};
            }}
        """)
        middle_layout = QVBoxLayout(middle_col)
        middle_layout.setContentsMargins(14, 14, 14, 14)
        middle_layout.setSpacing(12)

        # Search Bar
        search_box = QHBoxLayout()
        search_box.setSpacing(8)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filter recipes or keywords (Ctrl+F)...")
        self.search_input.setFont(get_ui_font(9))
        self.search_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {DEFAULT_THEME.surface_card};
                border: 1px solid {DEFAULT_THEME.border};
                border-radius: 6px;
                color: {DEFAULT_THEME.text};
                padding: 6px 10px;
            }}
            QLineEdit:focus {{
                border-color: {DEFAULT_THEME.accent};
            }}
        """)
        self.search_input.textChanged.connect(self._on_search_changed)
        search_box.addWidget(self.search_input)

        middle_layout.addLayout(search_box)

        # Scroll Area for Cards
        self.cards_scroll = QScrollArea()
        self.cards_scroll.setWidgetResizable(True)
        self.cards_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.cards_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.cards_scroll.setStyleSheet(f"""
            QScrollArea {{
                background: transparent;
                border: none;
            }}
        """)

        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(8)
        self.cards_layout.addStretch()
        self.cards_scroll.setWidget(self.cards_container)

        middle_layout.addWidget(self.cards_scroll, 1)

        self.content_splitter.addWidget(middle_col)

        # --- Right Column: Inspector ---
        self.inspector = PlaybookInspectorWidget(self)
        self.inspector.run_requested.connect(self._run_current_recipe)
        self.inspector.fork_requested.connect(self._fork_recipe)
        self.inspector.delete_requested.connect(self._delete_recipe)
        self.content_splitter.addWidget(self.inspector)

        # Set initial horizontal splitter sizes (Cards 360px, Inspector 640px)
        self.content_splitter.setSizes([360, 640])

        top_layout.addWidget(self.content_splitter)
        self.main_v_splitter.addWidget(top_container)

        # 3. Slide-up Execution Dock
        self.dock = PlaybookExecutionDock(self)
        self.dock.stop_requested.connect(self._stop_execution)
        self.dock.close_requested.connect(self._hide_dock)
        self.dock.hide()  # Hidden until execution or log review
        self.main_v_splitter.addWidget(self.dock)

        # Set vertical sizes (Top 700px, Dock 300px)
        self.main_v_splitter.setSizes([700, 300])

        main_layout.addWidget(self.main_v_splitter, 1)

    def set_connection(self, connection: Any, profile: Any = None) -> None:
        """Called when active SSH connection changes."""
        self.connection = connection
        self._current_profile = profile
        is_conn = connection is not None and getattr(connection, "raw_connection", None) is not None
        target_str = ""
        if is_conn:
            target_str = getattr(connection, "host", "")
            if not target_str and profile:
                target_str = getattr(profile, "host", "")
        self.inspector.set_connection(is_conn, target_str)

    def _load_recipes(self) -> None:
        self._recipes.clear()

        # 1. Add custom snippets from database FIRST so custom snippets are top-promoted
        if self.app_data:
            try:
                with self.app_data.session_factory() as session:
                    repo = self.app_data.playbooks(session)
                    custom_recipes = repo.list_custom_snippets()
                    self._recipes.extend(custom_recipes)
            except Exception:
                logger.exception("Error loading custom snippets from database")

        # 2. Add Pre-bundled recipes
        for r in PREBUNDLED_RECIPES:
            self._recipes.append(r)

        self._update_sidebar_counts()
        self._rebuild_card_list()

        # Select first recipe by default
        if self._recipes:
            self._select_recipe(self._recipes[0].id)

    def _update_sidebar_counts(self) -> None:
        all_c = len(self._recipes)
        pre_c = len([r for r in self._recipes if r.is_prebundled])
        cust_c = len([r for r in self._recipes if not r.is_prebundled])
        fav_c = len([r for r in self._recipes if r.is_favorite])
        self.sidebar.update_counts(all_c, pre_c, cust_c, fav_c)

    def _rebuild_card_list(self) -> None:
        # Clear existing card widgets
        while self.cards_layout.count() > 1:
            item = self.cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._card_widgets.clear()

        query = self._search_query.strip().lower()

        filtered: list[PlaybookRecipe] = []
        for r in self._recipes:
            # Collection filter
            if self._active_collection == "prebundled" and not r.is_prebundled:
                continue
            if self._active_collection == "custom" and r.is_prebundled:
                continue
            if self._active_collection == "favorites" and not r.is_favorite:
                continue

            # Category filter
            if self._active_category != "all_cats" and str(r.category) != self._active_category:
                continue

            # Search query filter
            if query:
                text_match = (
                    query in r.title.lower()
                    or query in r.description.lower()
                    or query in str(r.category).lower()
                    or query in r.script_template.lower()
                )
                if not text_match:
                    continue

            filtered.append(r)

        for r in filtered:
            card = PlaybookCardWidget(r)
            card.selected.connect(self._select_recipe)
            card.run_requested.connect(self._quick_run_recipe)
            card.favorite_toggled.connect(self._toggle_favorite)
            self._card_widgets[r.id] = card
            # Insert before the stretch at the end
            self.cards_layout.insertWidget(self.cards_layout.count() - 1, card)

        if not filtered:
            no_lbl = QLabel("No playbooks match current filter.")
            no_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            no_lbl.setFont(get_ui_font(9))
            no_lbl.setStyleSheet(f"color: {DEFAULT_THEME.text_dim}; padding: 24px 0;")
            self.cards_layout.insertWidget(0, no_lbl)

    def _select_recipe(self, recipe_id: str) -> None:
        found: PlaybookRecipe | None = None
        for r in self._recipes:
            if r.id == recipe_id:
                found = r
                break
        if not found:
            return

        self._selected_recipe = found
        for rid, card in self._card_widgets.items():
            card.set_selected(rid == recipe_id)

        self.inspector.load_recipe(found)

        # Scroll selected card into view
        if recipe_id in self._card_widgets:
            self.cards_scroll.ensureWidgetVisible(self._card_widgets[recipe_id], 0, 20)

    def _on_collection_changed(self, coll_id: str) -> None:
        self._active_collection = coll_id
        self._rebuild_card_list()

    def _on_category_changed(self, cat_id: str) -> None:
        self._active_category = cat_id
        self._rebuild_card_list()

    def _on_search_changed(self, query: str) -> None:
        self._search_query = query
        self._rebuild_card_list()

    def _toggle_favorite(self, recipe_id: str) -> None:
        if self.app_data:
            try:
                with self.app_data.session_factory() as session:
                    repo = self.app_data.playbooks(session)
                    repo.toggle_favorite(recipe_id)
                    session.commit()
            except Exception:
                pass
        self._update_sidebar_counts()

    def _quick_run_recipe(self, recipe_id: str) -> None:
        self._select_recipe(recipe_id)
        if self._selected_recipe:
            vals = self.inspector.get_parameter_values()
            self._run_current_recipe(vals)

    def _on_run_shortcut(self) -> None:
        if self._selected_recipe and self.inspector.run_cta.isEnabled():
            vals = self.inspector.get_parameter_values()
            self._run_current_recipe(vals)

    def _run_current_recipe(self, param_values: dict[str, Any]) -> None:
        if not self._selected_recipe:
            return

        if self.connection is None or getattr(self.connection, "raw_connection", None) is None:
            QMessageBox.warning(
                self,
                "Server Not Connected",
                "Cannot execute playbook because there is no active SSH connection.\n\n"
                "Please connect to a remote host first using Connections or New Host.",
            )
            return

        interpolated_script = interpolate_template(self._selected_recipe.script_template, param_values)

        # Show execution dock
        self.dock.show()
        target_name = getattr(self.connection, "host", "remote-host")
        self.dock.start_execution(target_name, self._selected_recipe.steps)

        # Sudo password resolution if available in profile/credentials
        sudo_password = None
        if self._current_profile and getattr(self._current_profile, "password", None):
            sudo_password = self._current_profile.password

        self._runner = PlaybookStreamingRunner(self.connection)

        recipe_ref = self._selected_recipe
        start_dt = datetime.now()

        def make_coro(progress_cb):
            def on_chunk(chunk: str):
                progress_cb({"type": "chunk", "data": chunk})

            assert self._runner is not None
            return self._runner.run_stream(interpolated_script, on_chunk, sudo_password=sudo_password)

        worker = AsyncProgressWorker(make_coro)
        self._active_worker = worker

        def on_progress(event):
            if isinstance(event, dict) and event.get("type") == "chunk":
                self.dock.append_output(event["data"])

        def on_finished(result):
            exit_code = 0
            dur_ms = 0
            out_summary = ""
            if result.ok:
                exit_code = result.data.get("exit_code", 0) if result.data else 0
                dur_ms = result.data.get("duration_ms", 0) if result.data else 0
                out_summary = result.data.get("output", "") if result.data else ""
                self.dock.finish_execution(exit_code, dur_ms, result.message)
            else:
                exit_code = result.data.get("exit_code", 1) if result.data else 1
                dur_ms = result.data.get("duration_ms", 0) if result.data else 0
                out_summary = result.data.get("output", "") if result.data else ""
                self.dock.finish_execution(exit_code, dur_ms, result.message)

            # Persist execution history in SQLite
            if self.app_data:
                try:
                    prof_id = getattr(self._current_profile, "id", None) if self._current_profile else None
                    rec = PlaybookExecutionRecord(
                        id=str(uuid.uuid4()),
                        recipe_id=recipe_ref.id,
                        recipe_title=recipe_ref.title,
                        profile_id=prof_id,
                        started_at=start_dt,
                        duration_ms=dur_ms,
                        exit_code=exit_code,
                        status="success" if exit_code == 0 else ("cancelled" if exit_code == 130 else "failed"),
                        log_output=out_summary,
                    )
                    with self.app_data.session_factory() as session:
                        repo = self.app_data.playbooks(session)
                        repo.record_execution(rec)
                        session.commit()
                except Exception:
                    logger.exception("Error saving execution record")

            self._active_worker = None

        worker.progress.connect(on_progress)
        worker.succeeded.connect(on_finished)
        worker.failed.connect(on_finished)
        worker.start()

    def _stop_execution(self) -> None:
        if self._runner:
            self._runner.cancel()

    def _hide_dock(self) -> None:
        self.dock.hide()

    def _open_new_snippet_dialog(self) -> None:
        dlg = NewSnippetDialog(self)
        if dlg.exec() == NewSnippetDialog.DialogCode.Accepted:
            new_recipe = dlg.build_recipe()
            if self.app_data:
                try:
                    with self.app_data.session_factory() as session:
                        repo = self.app_data.playbooks(session)
                        repo.add_snippet(new_recipe)
                        session.commit()
                except Exception:
                    logger.exception("Error creating custom snippet in DB")

            self._recipes.insert(0, new_recipe)
            self._update_sidebar_counts()
            self._rebuild_card_list()
            self._select_recipe(new_recipe.id)

    def _fork_recipe(self, recipe_id: str) -> None:
        src = next((r for r in self._recipes if r.id == recipe_id), None)
        if not src:
            return

        forked = PlaybookRecipe(
            id=f"custom-fork-{uuid.uuid4().hex[:6]}",
            title=f"{src.title} (Custom)",
            category=PlaybookCategory.CUSTOM,
            safety=src.safety,
            safety_label=src.safety_label,
            description=f"Forked from {src.title}. {src.description}",
            script_template=src.script_template,
            variables=list(src.variables),
            steps=list(src.steps),
            is_prebundled=False,
            is_favorite=False,
            runtime_estimate=src.runtime_estimate,
        )

        if self.app_data:
            try:
                with self.app_data.session_factory() as session:
                    repo = self.app_data.playbooks(session)
                    repo.add_snippet(forked)
                    session.commit()
            except Exception:
                logger.exception("Error saving forked snippet in DB")

        self._recipes.insert(0, forked)
        self._update_sidebar_counts()
        self._rebuild_card_list()
        self._select_recipe(forked.id)

    def _delete_recipe(self, recipe_id: str) -> None:
        target = next((r for r in self._recipes if r.id == recipe_id), None)
        if not target or target.is_prebundled:
            return

        reply = QMessageBox.question(
            self,
            "Delete Playbook Snippet",
            f"Are you sure you want to permanently delete '{target.title}' from your vault?\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        if self.app_data:
            try:
                with self.app_data.session_factory() as session:
                    repo = self.app_data.playbooks(session)
                    repo.delete_snippet(recipe_id)
                    session.commit()
            except Exception:
                logger.exception("Error deleting custom snippet from DB")

        self._recipes = [r for r in self._recipes if r.id != recipe_id]
        self._update_sidebar_counts()
        self._rebuild_card_list()
        if self._recipes:
            self._select_recipe(self._recipes[0].id)
