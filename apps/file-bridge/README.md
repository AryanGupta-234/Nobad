# NOBAD File Bridge

NOBAD File Bridge · part of [NOBAD](../../README.md): software with a point of view.

**Status:** in development, not released yet. Issues [#29](https://github.com/AryanGupta-234/Nobad/issues/29) to [#33](https://github.com/AryanGupta-234/Nobad/issues/33) must be fixed before the first release. Author and code owner: [@harshRaj1601](https://github.com/harshRaj1601). AI assistants: see [AGENTS.md](AGENTS.md).

Open, copy, edit and back up the files on your website or server, right from your PC. NOBAD File Bridge
(formerly *NOBAD Files*) is a cross-platform desktop app and part of the NOBAD platform. It's built with Python 3.12
and PySide6.

All commands below are run from `apps/file-bridge/`.

Phase 4A/4B/4C MVP for a cross-platform Python desktop application: a PySide6 file manager with SSH/SFTP and FTP/FTPS browsing, queued transfers, cross-server relay, baseline-aware sync, visual text diffs, remote editing, terminals, structured logs, secure credential references, password-protected credential vaults, and release-aware deployment workflows.

The app does not claim to connect to every hosting platform directly. cPanel, hPanel, AWS EC2, Ubuntu VPS, shared hosting, and cloud storage are profile types. They work only when a supported access method is available, such as SSH, SFTP, FTP/FTPS, a provider API, rsync, or rclone.

## Current Phase

Implemented in this scaffold:

- PySide6 `QtWidgets` responsive workbench with navigation rail, connection page, file manager workspace, editor, terminal, Activity page, settings, sync, and deployments.
- Saved deployment jobs with optional local builds, upload-only or mirror previews, remote tar/zip backups, queued uploads, ordered remote commands, cancellation, and automatic rollback.
- Opt-in atomic deployments under `.rfm-releases`, safe adoption of existing targets, staged symlink switching, active/previous release retention, and in-place compatibility for existing jobs.
- Command and HTTP health checks with retries, desktop or remote-curl origin, status/body verification, TLS warnings, and automatic rollback after failed verification.
- Durable deployment run/stage/artifact history in SQLite, redacted 8 KiB stage excerpts, remote deployment locks, artifact discovery, and confirmed manual rollback.
- SSH/SFTP connection service using AsyncSSH.
- FTP and FTPS connection services using `aioftp`, including explicit or implicit TLS, certificate verification policy, streaming progress, recursive operations, and insecure FTP warnings.
- Capability matrix for profile/protocol-aware UI gating.
- Protocol-neutral remote file operations implemented for SFTP, FTP, and FTPS.
- Faster SFTP directory listing using server-returned directory attributes.
- Interactive tabbed SSH PTY terminal surface using QtWebEngine, QtWebChannel, and local xterm.js assets.
- Queue-scheduled upload/download transfers with concurrency settings, progress, speed, ETA, retry/cancel controls, `.part` safety, and history hooks.
- SQLite persistence for saved connection profiles, secret references, transfer history, recent paths, logs, settings, deployment runs, stage timing, and rollback artifacts.
- Advanced local/remote editor workflow with stable tabs, find/replace, syntax hooks, encoding status, secure temp workspace, stale remote detection, side-by-side comparison, and explicit overwrite/reload/save-as conflict actions.
- Recursive folder upload/download through the transfer queue.
- Current-directory search/filter plus SSH-backed chmod where the connection supports shell commands.
- Local and SSH-backed remote archive preview/create/extract for `.zip` and `.tar.gz`, with strict unsafe-path/link validation and local-relay fallback prompts.
- Local and remote folder-size calculation.
- Baseline-aware two-way sync with three-state comparison, checksum refinement, inferred deletions, explicit per-file conflict decisions, keep-both preservation, fresh-preview execution, and atomic baseline replacement after verification.
- Cross-server copy between SSH/SFTP/FTP/FTPS profiles through a private local relay workspace, with disk preflight, `.part` safety, per-file progress, cancellation, and background destination connections.
- Optional rsync discovery and direct server-side push/pull after remote command and non-interactive SSH authentication probes; Auto mode explains and uses local relay when direct mode is unavailable.
- Idempotent SQLite schema migrations plus sync baseline persistence and protocol-specific connection options.
- SQLite/SQLAlchemy schema definitions and keyring-based credential reference layer.
- Password-protected Credentials Manager for project `.env` values, provider/server logins, hosting panel accounts, API keys, Git tokens, database passwords, CI/CD secrets, DNS/CDN keys, email/SMS/payment credentials, license keys, secure notes, and custom fields.
- Master-password encrypted credential vault using Argon2id key derivation and AES-GCM encrypted SQLite payloads; plaintext values are not written to SQLite or operation logs.
- Credential import/export for `.env`, encrypted `.rfm-vault`, JSON, and CSV flows, with plaintext export warnings.
- Focused unit tests for safety, capabilities, conflicts, and transfer models.

Deferred to later phases:

- cPanel/hPanel provider APIs, rclone, and cloud remotes.
- SFTP pause/resume and speed limits.
- Multi-server deployment orchestration, package installers, public URL mapping, and public plugins.

## Install

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

On systems where `QtWebEngine` is unavailable, the editor panel falls back to a plain Qt text editor so the app can still run.

## New web UI (in development)

A redesigned interface in the NOBAD VPN style, with a blue accent, next to the classic window. Every screen is
there: Files, Connections, Terminal, Editor, Sync, Deployments, Credential vault, Server health, Services, Tunnels,
Live logs, Playbooks and Settings.

```bash
python -m app.web             # app window
python -m app.web --browser   # same UI in your web browser
```

**Windows** uses Edge WebView2, which is part of Windows 10 and 11.

**Linux** uses GTK's WebKit2GTK when its Python bindings are installed, and otherwise Qt WebEngine through the
PySide6 the app already installs (with `qtpy`, installed automatically on Linux). For the lighter GTK window:

```bash
sudo apt install python3-gi gir1.2-webkit2-4.1        # Debian, Ubuntu
sudo dnf install python3-gobject webkit2gtk4.1        # Fedora
```

If neither is available, the app says which packages to install. `--browser` always works. Linux keeps its own
window title bar; NOBAD's title bar is a Windows option.

How it's built and the rules for new screens: [docs/WEB-UI.md](docs/WEB-UI.md).

## Run

```bash
python -m app.main
```

New Host supports `SSH`, `SFTP`, `FTP`, and `FTPS`. Passwords are session-only unless `Save profile` and `Remember secret` are enabled. Saved connection secrets are stored in the OS keyring; SQLite stores only keyring reference metadata. The separate Credentials page stores general developer/devops secrets in a local master-password encrypted vault.

### Bulk import of credential notes

In the Credentials page, *Bulk Import (Text/Docs)* parses loose notes (SSH `URL`/`Password` blocks, web logins,
provider console logins, `.env` lines like `API_KEY=value`), shows a preview, and saves the results straight into
the encrypted vault. Nothing is written to disk in plain text.

## Test

```bash
QT_QPA_PLATFORM=offscreen python -m pytest -q tests
```

Network integration tests remain optional because they require test servers. The deterministic suite covers migrations, sync baselines, conflict resolution, FTP streaming, transfer safety, deployment behavior, terminals, and UI models.

## Package

PyInstaller builds should be created on the target OS: build Linux packages on Linux, and build the Windows `.exe` on Windows.

Install the app and packaging dependency in the same virtualenv:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pip install pyinstaller
```

Build the PyInstaller app folder:

```bash
pyinstaller --clean --noconfirm build.spec
./dist/NobadFileBridge/NobadFileBridge
```

Build a basic Linux `.deb` from that app folder:

```bash
packaging/linux/build-deb.sh 0.4.0 amd64
sudo apt install ./dist/nobad-file-bridge_0.4.0_amd64.deb
nobad-file-bridge
```

If apt prints `Download is performed unsandboxed as root ... couldn't be accessed by user '_apt'`, the package can still install successfully. It means the local `.deb` lives in a directory the `_apt` sandbox user cannot traverse. To avoid that notice, copy the package to `/tmp` first:

```bash
cp ./dist/nobad-file-bridge_0.4.0_amd64.deb /tmp/
sudo apt install /tmp/nobad-file-bridge_0.4.0_amd64.deb
```

The Linux package installs a launcher at `/usr/bin/nobad-file-bridge`. If the app aborts on another PC, run it once with Qt plugin diagnostics:

```bash
QT_DEBUG_PLUGINS=1 nobad-file-bridge 2>&1 | tee /tmp/nobad-file-bridge-startup.log
```

The `.deb` declares common PySide6/QtWebEngine runtime dependencies, including XCB, WebEngine, GL, GTK, NSS, and audio libraries. Rebuild the `.deb` after changing `packaging/linux/build-deb.sh`; the old `.deb` will not contain new dependency metadata.

For Windows, run these commands in PowerShell from the project root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pip install pyinstaller
pyinstaller --clean --noconfirm build.spec
.\dist\NobadFileBridge\NobadFileBridge.exe
```

The spec includes the bundled terminal assets, branding images, credential-vault modules, FTP/FTPS, sync, deployment, terminal, and `resources/branding/remote-file-manager.ico` for the executable icon. Ignore Inno Setup for now; the Windows output is the app folder plus `.exe` under `dist\NobadFileBridge`.
