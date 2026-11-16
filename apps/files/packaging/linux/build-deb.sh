#!/usr/bin/env bash
set -euo pipefail

APP_ID="remote-file-manager"
APP_NAME="Remote File Manager"
VERSION="${1:-0.4.0}"
ARCH="${2:-amd64}"
DIST_DIR="dist"
PYINSTALLER_APP="${DIST_DIR}/RemoteFileManager"
PACKAGE_ROOT="${DIST_DIR}/deb/${APP_ID}_${VERSION}_${ARCH}"
INSTALL_ROOT="${PACKAGE_ROOT}/opt/remote-file-manager"
BIN_DIR="${PACKAGE_ROOT}/usr/bin"
DESKTOP_DIR="${PACKAGE_ROOT}/usr/share/applications"
ICON_DIR="${PACKAGE_ROOT}/usr/share/icons/hicolor/256x256/apps"
DEBIAN_DIR="${PACKAGE_ROOT}/DEBIAN"
OUTPUT_DEB="${DIST_DIR}/${APP_ID}_${VERSION}_${ARCH}.deb"

if [[ ! -x "${PYINSTALLER_APP}/RemoteFileManager" ]]; then
    echo "Missing executable at: ${PYINSTALLER_APP}/RemoteFileManager"
    echo ""
    echo "Please build the application binary first by running:"
    echo "  uv run --with pyinstaller pyinstaller --clean --noconfirm build.spec"
    echo ""
    exit 1
fi

rm -rf "${PACKAGE_ROOT}"
mkdir -p "${INSTALL_ROOT}" "${BIN_DIR}" "${DESKTOP_DIR}" "${ICON_DIR}" "${DEBIAN_DIR}"

cp -a "${PYINSTALLER_APP}" "${INSTALL_ROOT}/"
cat > "${BIN_DIR}/remote-file-manager" <<'LAUNCHER'
#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/remote-file-manager/RemoteFileManager"

# XCB is the most predictable backend for PySide6/PyInstaller desktop bundles
# across Ubuntu/Debian versions. Users can override it before launching if needed.
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb}"
export QT_QPA_PLATFORMTHEME="${QT_QPA_PLATFORMTHEME:-generic}"
export QT_STYLE_OVERRIDE="${QT_STYLE_OVERRIDE:-Fusion}"

# The terminal surface uses local QtWebEngine assets. Disabling GPU avoids
# startup crashes on machines with older or VM graphics drivers.
export QTWEBENGINE_CHROMIUM_FLAGS="${QTWEBENGINE_CHROMIUM_FLAGS:---disable-gpu}"

exec "${APP_DIR}/RemoteFileManager" "$@"
LAUNCHER
chmod 0755 "${BIN_DIR}/remote-file-manager"
install -m 0644 "packaging/linux/remote-file-manager.desktop" "${DESKTOP_DIR}/remote-file-manager.desktop"
install -m 0644 "resources/branding/remote-file-manager-256.png" "${ICON_DIR}/remote-file-manager.png"
INSTALLED_SIZE_KIB="$(du -sk "${PACKAGE_ROOT}" | cut -f1)"

cat > "${DEBIAN_DIR}/control" <<CONTROL
Package: ${APP_ID}
Version: ${VERSION}
Section: utils
Priority: optional
Architecture: ${ARCH}
Installed-Size: ${INSTALLED_SIZE_KIB}
Depends: libc6, libstdc++6, libgcc-s1, libglib2.0-0, libdbus-1-3, libfontconfig1, libfreetype6, libgl1, libegl1, libx11-6, libx11-xcb1, libxext6, libxrender1, libsm6, libice6, libxcb1, libxcb-cursor0, libxcb-icccm4, libxcb-image0, libxcb-keysyms1, libxcb-randr0, libxcb-render0, libxcb-render-util0, libxcb-shape0, libxcb-shm0, libxcb-sync1, libxcb-util1, libxcb-xfixes0, libxcb-xinerama0, libxcb-xkb1, libxkbcommon0, libxkbcommon-x11-0, libnss3, libnspr4, libatk1.0-0, libatk-bridge2.0-0, libcups2, libdrm2, libgbm1, libxcomposite1, libxdamage1, libxfixes3, libxrandr2, libgtk-3-0, libasound2t64 | libasound2
Maintainer: Remote File Manager Team <support@example.invalid>
Description: ${APP_NAME}
 Native desktop workbench for SSH/SFTP and FTP/FTPS file management,
 transfers, terminals, sync, editing, and deployment workflows.
CONTROL

dpkg-deb --build "${PACKAGE_ROOT}" "${OUTPUT_DEB}"
chmod 0644 "${OUTPUT_DEB}"
echo "Successfully built Debian package: ${OUTPUT_DEB}"
