from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_main_shell_uses_new_host_page_without_top_connection_bar() -> None:
    source = _source("ui/main_window.py")

    assert "ConnectionCommandBar" not in source
    assert "body_layout.addWidget(self.connection_bar)" not in source
    assert 'self.new_host_panel = NewHostPanel()' in source
    assert '"New Host": WorkbenchPage' in source
    assert '"Terminal": self.terminal_panel' in source


def test_saved_connections_expose_full_profile_editing() -> None:
    panel_source = _source("ui/connections_panel.py")
    main_source = _source("ui/main_window.py")

    assert 'self.edit_button = QPushButton("Edit")' in panel_source
    assert "self.connections_panel.edit_requested.connect(self._edit_saved_profile)" in main_source
    assert "ProfileEditDialog(profile, self)" in main_source


def test_credentials_manager_is_a_primary_workbench_page() -> None:
    main_source = _source("ui/main_window.py")
    nav_source = _source("ui/workbench_models.py")
    panel_source = _source("ui/credentials_panel.py")

    assert "self.credentials_panel = CredentialsPanel" in main_source
    assert '"Credentials": WorkbenchPage' in main_source
    assert 'NavigationItem("Credentials", "Credentials", "credentials")' in nav_source
    assert "class CredentialsPanel" in panel_source
    assert "Create Credentials Vault" in panel_source
    assert 'self.bulk_import_button = QPushButton("Bulk Import")' in panel_source
    assert "class BulkImportDialog" in panel_source
    assert "preview_loose_text_import" in panel_source
    assert "self.text_input.setAcceptRichText(False)" in panel_source
    assert "class RevealCredentialDialog" in panel_source
    assert 'self.copy_username_button = QPushButton("Copy")' in panel_source
    assert 'self.copy_url_host_button = QPushButton("Copy")' in panel_source
    assert "form.addRow(\"Username / account\", self._copyable_field" in panel_source
    assert "form.addRow(\"URL / host / provider\", self._copyable_field" in panel_source


def test_terminal_set_connection_does_not_auto_open_tab() -> None:
    source = _source("ui/terminal_panel.py")
    method_body = source.split("    def set_connection(self, connection) -> None:", 1)[1].split(
        "    def set_saved_profiles", 1
    )[0]

    assert "open_remote_connection" not in method_body
    assert "Active remote terminal target ready" in method_body


def test_activity_is_a_full_page_and_bottom_dock_is_removed() -> None:
    main_source = _source("ui/main_window.py")
    workbench_source = _source("ui/workbench.py")

    assert "self.activity_page = ActivityPage(self.transfer_panel, self.logs_panel)" in main_source
    assert '"Activity": WorkbenchPage' in main_source
    assert "body_layout.addWidget(self.bottom_dock)" not in main_source
    assert "class ActivityPage" in workbench_source
    assert "class BottomDock" not in workbench_source


def test_workspace_status_bar_has_top_right_disconnect_control() -> None:
    source = _source("ui/main_window.py")

    assert "self.connection_status_bar = ConnectionStatusBar()" in source
    assert "shell_layout.addWidget(self.connection_status_bar)" in source
    assert "self.menuBar().setCornerWidget" not in source


def test_terminal_layout_gives_xterm_the_stretch_space() -> None:
    source = _source("ui/terminal_panel.py")

    assert "layout.addWidget(self.view, 1)" in source
    assert "layout.addWidget(self.tabs, 1)" in source
    assert "self.status.setVisible(False)" in source


def test_terminal_uses_profile_default_remote_path_when_no_cwd_is_passed() -> None:
    source = _source("ui/terminal_panel.py")

    assert "remote_cwd = self._remote_cwd(connection, cwd)" in source
    assert "cwd=remote_cwd" in source
    assert 'getattr(connection.profile, "default_remote_path", None)' in source
    assert 'default_path != "."' in source


def test_sidebar_branding_uses_icon_and_full_two_line_name() -> None:
    source = _source("ui/workbench.py")

    assert "self.logo.setFixedSize(34, 34)" in source
    assert 'self.title = QLabel("Remote File\\nManager")' in source
    assert "self.title.setWordWrap(True)" in source


def test_native_menu_and_diagnostics_are_installed() -> None:
    menu_source = _source("ui/menu_controller.py")
    main_source = _source("app/main.py")

    for menu in ["File", "Connection", "View", "Terminal", "Tools", "Help"]:
        assert f'bar.addMenu("{menu}")' in menu_source
    assert "install_diagnostics()" in main_source


def test_deployments_are_a_primary_workbench_page() -> None:
    main_source = _source("ui/main_window.py")
    nav_source = _source("ui/workbench_models.py")

    assert 'self.deployment_panel = DeploymentPanel()' in main_source
    assert '"Deployments": WorkbenchPage' in main_source
    assert 'NavigationItem("Deployments", "Deployments", "deploy")' in nav_source
    assert 'if section == "Deployments"' not in main_source
