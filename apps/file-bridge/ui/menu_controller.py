from __future__ import annotations

from PySide6.QtGui import QAction, QKeySequence


class WorkbenchMenuController:
    def __init__(self, window) -> None:  # type: ignore[no-untyped-def]
        self.window = window
        self.actions: list[QAction] = []
        self._build()

    def _build(self) -> None:
        bar = self.window.menuBar()

        file_menu = bar.addMenu("File")
        self._add(file_menu, "New Host", lambda: self.window._select_section("New Host"), "Ctrl+Shift+H")
        self._add(file_menu, "Settings", lambda: self.window._select_section("Settings"), "Ctrl+,")
        file_menu.addSeparator()
        self._add(file_menu, "Quit", self.window.close, "Ctrl+Shift+Q")

        connection_menu = bar.addMenu("Connection")
        self._add(connection_menu, "Connect Selected", self.window._connect_selected_profile, "Ctrl+Return")
        self._add(connection_menu, "Disconnect Current", self.window._disconnect_current, "Ctrl+Shift+D")
        self._add(connection_menu, "Refresh Profiles", self.window._load_saved_profiles)

        view_menu = bar.addMenu("View")
        self._add(view_menu, "Toggle Sidebar", self.window._toggle_sidebar, "Ctrl+Alt+B")
        self._add(view_menu, "Activity", self.window._toggle_activity, "Ctrl+Alt+J")
        view_menu.addSeparator()
        self._add(view_menu, "Files", lambda: self.window._select_section("Files"), "Ctrl+Alt+1")
        self._add(view_menu, "Terminal", lambda: self.window._select_section("Terminal"), "Ctrl+Alt+2")
        self._add(view_menu, "Activity Logs", lambda: self.window._show_activity("Logs", navigate=True), "Ctrl+Alt+3")
        self._add(view_menu, "Credentials", lambda: self.window._select_section("Credentials"), "Ctrl+Alt+4")

        terminal_menu = bar.addMenu("Terminal")
        self._add(terminal_menu, "New Remote", lambda: self._terminal_action(self.window.terminal_panel.new_remote), "Ctrl+Shift+N")
        self._add(terminal_menu, "New Local", lambda: self._terminal_action(self.window.terminal_panel.new_local), "Ctrl+Alt+N")
        terminal_menu.addSeparator()
        self._add(terminal_menu, "Copy", lambda: self._terminal_action(self.window.terminal_panel.copy_current))
        self._add(terminal_menu, "Paste", lambda: self._terminal_action(self.window.terminal_panel.paste_current))
        self._add(terminal_menu, "Reconnect", lambda: self._terminal_action(self.window.terminal_panel.reconnect_current))
        self._add(terminal_menu, "Close Tab", lambda: self._terminal_action(self.window.terminal_panel.close_current), "Ctrl+Shift+W")
        terminal_menu.addSeparator()
        self._add(terminal_menu, "Font Bigger", lambda: self._terminal_action(lambda: self.window.terminal_panel.change_font_size(1)), "Ctrl++")
        self._add(terminal_menu, "Font Smaller", lambda: self._terminal_action(lambda: self.window.terminal_panel.change_font_size(-1)), "Ctrl+-")

        tools_menu = bar.addMenu("Tools")
        self._add(tools_menu, "Credentials", lambda: self.window._select_section("Credentials"))
        self._add(tools_menu, "Sync Jobs", lambda: self.window._select_section("Sync Jobs"))
        self._add(tools_menu, "Deployments", lambda: self.window._select_section("Deployments"))
        self._add(tools_menu, "Playbooks & Snippets", lambda: self.window._select_section("Playbooks"), "Ctrl+Alt+P")
        self._add(tools_menu, "Live Log Streamer", lambda: self.window._select_section("Logs"), "Ctrl+Alt+L")
        self._add(tools_menu, "Command Palette", self.window._show_command_palette, "Ctrl+Shift+P")

        help_menu = bar.addMenu("Help")
        self._add(help_menu, "About", self.window._show_about)
        self._add(help_menu, "Diagnostics Folder", self.window._show_diagnostics_folder)

    def _add(self, menu, text: str, callback, shortcut: str | None = None) -> QAction:  # type: ignore[no-untyped-def]
        action = QAction(text, self.window)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(callback)
        menu.addAction(action)
        self.actions.append(action)
        return action

    def _terminal_action(self, callback) -> None:  # type: ignore[no-untyped-def]
        self.window._select_section("Terminal")
        callback()
