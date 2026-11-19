# NOBAD Find packaging

Builds the Windows installer `dist-installer\NobadFind-Setup-<version>.exe`. It installs for the current user only,
with no admin rights, into `%LOCALAPPDATA%\Programs\NOBAD Find`, and adds a Start menu shortcut.

```
cd apps/find
powershell -ExecutionPolicy Bypass -File packaging\build.ps1                 # app + installer
powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -InstallTools   # also installs Inno Setup 6 (winget)
powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -AppOnly        # just dist\NobadFind
```

Needs Python 3.11, the Flutter SDK (the `flutter` command on PATH, or `NOBAD_FLUTTER` set to `flutter.bat` or the
SDK's `bin` folder), Visual Studio's C++ build tools (for `flutter build windows`) and Inno Setup 6 (looked for on
PATH, in Program Files and in `%LOCALAPPDATA%\Programs\Inno Setup 6`).

What `build.ps1` does, in order: creates a fresh `.venv-build` (Python 3.11), installs `requirements-lock.txt` and
`packaging\requirements-build.txt` (PyInstaller), both checked by hash, runs the tests and pyflakes and stops if
either fails, runs `flutter test` and `flutter build windows --release --build-name <version>` in `ui_flutter`,
builds the engine `dist\NobadFind` with PyInstaller (`nobadfind.spec`), copies the UI build
(`ui_flutter\build\windows\x64\runner\Release\*`: `nobad_find.exe`, `flutter_windows.dll`, `data\`) next to
`NobadFind.exe`, checks no WebView files are in the folder, then builds the installer with Inno Setup
(`installer.iss`). It prints the installer's SHA-256 and writes it next to the installer as `.sha256`. Signing is
optional; the three options are at the top of `build.ps1` and sign `NobadFind.exe`, `nobad_find.exe`, the
uninstaller and the installer (unsigned builds trigger SmartScreen).

The installed folder:

| File | What it is |
|---|---|
| `NobadFind.exe` + `_internal\` | The engine (index, indexer, hotkeys, tray, the private pipe). The Start menu shortcut starts it; it starts the window. |
| `nobad_find.exe`, `flutter_windows.dll`, `data\` | The window (Flutter UI, `ui_flutter/`). Started by the engine, outside its job; talks to it only over the pipe. |

| File | What it is |
|---|---|
| `nobadfind.spec` | PyInstaller, onedir, windowed, the engine only. Bundles SQLCipher, pypdf, numpy, onnxruntime, tokenizers and every installed `winrt` projection (Windows OCR). |
| `launch.py` | The exe's entry point (same as `python -m nobadfind`). |
| `installer.iss` | Inno Setup 6. Stops this user's running NOBAD Find (engine and window) before installing and uninstalling; an upgrade clears `_internal\` first so files an older version shipped don't stay. |
| `requirements-build.txt` | PyInstaller and its dependencies, pinned by hash. |
| `make_version_info.py` | Writes the exe's version details (generated `version_info.txt`, not committed). |
| `make_icon.py` | Regenerates `nobadfind.ico` from `ui_flutter/assets/nobad-mark.png` (needs Pillow). |

`requirements-lock.txt` is generated with pip-tools from `requirements-dev.txt` (the command is in its header);
an existing lock keeps its pins, so after changing `requirements.txt` only what changed moves.

Uninstalling runs `NobadFind.exe --uninstall` first: it puts Windows Search back the way it was if NOBAD Find
turned it off (Windows may ask for permission once) and removes NOBAD Find's start-with-Windows entry. Then it
asks whether to delete the search index and settings in `%LOCALAPPDATA%\NOBAD\Find`; your own files are never
touched.

CI (`.github/workflows/find-ci.yml`, job `find-build`) runs the same script, with the Flutter SDK from
`subosito/flutter-action` (pinned by commit, Flutter 3.50.0), and keeps the installer as a workflow artifact.
Releases are built the same way by `find-release.yml` from a `find-v*` tag.
