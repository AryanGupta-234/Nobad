# NOBAD Find packaging

Builds the Windows installer `dist-installer\NobadFind-Setup-<version>.exe`. It installs for the current user only,
with no admin rights, into `%LOCALAPPDATA%\Programs\NOBAD Find`, and adds a Start menu shortcut.

```
cd apps/find
powershell -ExecutionPolicy Bypass -File packaging\build.ps1                 # app + installer
powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -InstallTools   # also installs Inno Setup 6 (winget)
powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -AppOnly        # just dist\NobadFind
```

What `build.ps1` does, in order: creates a fresh `.venv-build` (Python 3.11), installs `requirements-lock.txt` and
`packaging\requirements-build.txt` (PyInstaller), both checked by hash, runs the tests and pyflakes and stops if
either fails, builds `dist\NobadFind` with PyInstaller (`nobadfind.spec`), then the installer with Inno Setup
(`installer.iss`). It prints the installer's SHA-256 and writes it next to the installer as `.sha256`. Signing is
optional; the three options are at the top of `build.ps1` (unsigned builds trigger SmartScreen).

| File | What it is |
|---|---|
| `nobadfind.spec` | PyInstaller, onedir, windowed. Bundles `nobadfind/ui`, pywebview (Edge WebView2 only), SQLCipher, pypdf, numpy, onnxruntime, tokenizers and every installed `winrt` projection (Windows OCR). |
| `launch.py` | The exe's entry point (same as `python -m nobadfind`). |
| `installer.iss` | Inno Setup 6. Stops this user's running NOBAD Find before installing and uninstalling. |
| `requirements-build.txt` | PyInstaller and its dependencies, pinned by hash. |
| `make_version_info.py` | Writes the exe's version details (generated `version_info.txt`, not committed). |
| `make_icon.py` | Regenerates `nobadfind.ico` from `nobadfind/ui/brand/nobad-mark.png` (needs Pillow). |

Uninstalling runs `NobadFind.exe --uninstall` first: it puts Windows Search back the way it was if NOBAD Find
turned it off (Windows may ask for permission once) and removes NOBAD Find's start-with-Windows entry. Then it
asks whether to delete the search index and settings in `%LOCALAPPDATA%\NOBAD\Find`; your own files are never
touched.

CI (`.github/workflows/find-ci.yml`, job `find-build`) runs the same script and keeps the installer as a workflow
artifact. Nothing is published: NOBAD Find isn't released yet.
