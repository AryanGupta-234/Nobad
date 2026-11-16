from __future__ import annotations

from pathlib import Path


def test_branding_assets_include_runtime_and_packaged_icons() -> None:
    assert Path("resources/branding/remote-file-manager-icon.png").is_file()
    assert Path("resources/branding/remote-file-manager-256.png").is_file()
    assert Path("resources/branding/remote-file-manager.ico").is_file()


def test_app_main_sets_qt_application_icon() -> None:
    source = Path("app/main.py").read_text(encoding="utf-8")

    assert "icon = application_icon()" in source
    assert 'app.setDesktopFileName("remote-file-manager")' in source
    assert "app.setWindowIcon(icon)" in source
    assert "window.setWindowIcon(icon)" in source


def test_pyinstaller_spec_includes_resources_and_app_icon() -> None:
    source = Path("build.spec").read_text(encoding="utf-8")

    assert "remote-file-manager.ico" in source
    assert 'globals().get("SPECPATH", ".")' in source
    assert "icon=str(APP_ICON)" in source
    assert '(str(RESOURCES_DIR), "resources")' in source
    assert '"credentials"' in source
    assert '"deployment"' in source
    assert '"keyring.backends"' in source
    assert '"argon2-cffi"' in source
    assert "exclude_binaries=True" in source


def test_linux_deb_packaging_metadata_uses_launcher_icon() -> None:
    desktop = Path("packaging/linux/remote-file-manager.desktop").read_text(encoding="utf-8")
    build_script = Path("packaging/linux/build-deb.sh").read_text(encoding="utf-8")

    assert "Icon=remote-file-manager" in desktop
    assert "Exec=remote-file-manager" in desktop
    assert 'BIN_DIR="${PACKAGE_ROOT}/usr/bin"' in build_script
    assert "QT_QPA_PLATFORM" in build_script
    assert "QTWEBENGINE_CHROMIUM_FLAGS" in build_script
    assert "remote-file-manager-256.png" in build_script
    assert "libxcb-cursor0" in build_script
    assert "libxkbcommon-x11-0" in build_script
    assert "libasound2t64 | libasound2" in build_script
    assert "dpkg-deb --build" in build_script
