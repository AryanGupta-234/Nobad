from __future__ import annotations

from ui.workbench_models import (
    FilePaneMode,
    ResponsiveBreakpoint,
    ThemeTokens,
    breakpoint_for_width,
    build_connection_request,
    dark_theme_qss,
    default_navigation_items,
    pane_mode_for_breakpoint,
)


def test_responsive_breakpoints_match_desktop_laptop_targets() -> None:
    assert breakpoint_for_width(1440) == ResponsiveBreakpoint.WIDE
    assert breakpoint_for_width(1366) == ResponsiveBreakpoint.MEDIUM
    assert breakpoint_for_width(1024) == ResponsiveBreakpoint.MEDIUM
    assert breakpoint_for_width(850) == ResponsiveBreakpoint.NARROW


def test_navigation_groups_future_modules_out_of_primary_flow() -> None:
    items = default_navigation_items()
    primary = [item.key for item in items if item.group == "primary"]
    coming_soon = [item.key for item in items if item.group == "coming_soon"]

    assert primary == [
        "New Host",
        "Connections",
        "Files",
        "Dashboard",
        "Terminal",
        "Deployments",
        "Sync Jobs",
        "Credentials",
        "Editor",
        "Settings",
    ]
    assert coming_soon == []
    assert all(item.coming_soon for item in items if item.group == "coming_soon")


def test_narrow_file_manager_uses_single_pane_without_changing_preference() -> None:
    assert pane_mode_for_breakpoint(ResponsiveBreakpoint.WIDE, FilePaneMode.REMOTE) == FilePaneMode.DUAL
    assert pane_mode_for_breakpoint(ResponsiveBreakpoint.MEDIUM, FilePaneMode.LOCAL) == FilePaneMode.LOCAL
    assert pane_mode_for_breakpoint(ResponsiveBreakpoint.NARROW, FilePaneMode.REMOTE) == FilePaneMode.REMOTE
    assert pane_mode_for_breakpoint(ResponsiveBreakpoint.NARROW, FilePaneMode.DUAL) == FilePaneMode.LOCAL


def test_connection_request_parses_ssh_command_and_preserves_key_path_only() -> None:
    request = build_connection_request(
        protocol="SFTP",
        host="ssh -p 65002 ubuntu@3.17.144.64",
        port="",
        username="",
        auth_type="SSH Key",
        secret="key passphrase",
        key_path="/home/user/server.pem",
        profile_name="EC2 Production",
        save_profile=True,
        remember_secret=True,
        default_local_path=" /home/user/project ",
        default_remote_path=" /var/www/html ",
        environment_notes=" Uses PEM auth ",
    )

    assert request["protocol"] == "ssh"
    assert request["host"] == "3.17.144.64"
    assert request["port"] == "65002"
    assert request["username"] == "ubuntu"
    assert request["auth_type"] == "SSH Key"
    assert request["key_path"] == "/home/user/server.pem"
    assert request["profile_name"] == "EC2 Production"
    assert request["save_profile"] is True
    assert request["remember_secret"] is True
    assert request["default_local_path"] == "/home/user/project"
    assert request["default_remote_path"] == "/var/www/html"
    assert request["environment_notes"] == "Uses PEM auth"


def test_dark_theme_contains_status_and_input_tokens() -> None:
    tokens = ThemeTokens(accent="#ff3366", input_background="#101114")
    qss = dark_theme_qss(tokens)

    assert "#ff3366" in qss
    assert "#101114" in qss
    assert "QTableView" in qss
    assert "QLineEdit:focus" in qss
