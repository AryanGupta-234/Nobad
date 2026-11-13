# NOBAD VPN

WireGuard VPN client for Windows, part of the NOBAD platform. It includes:

* a kill switch and a DNS leak block
* a tray icon and a compact mini window
* smart server choice and usage history
* a first-run wizard
* **Network Intelligence**: explains why a site or the network fails, with evidence
* **Streaming Region Intelligence**: where a title is listed, on which platforms, documented restrictions, and which
  of your servers match (needs your own free TMDB key)

The UI is English only. It ships as **one installer**, `NobadVPN-Setup-<version>.exe`, which includes the official
WireGuard for Windows (installed automatically when missing).

## Build the release (installer)

```powershell
winget install JRSoftware.InnoSetup                               # once (or add -InstallTools below)
powershell -ExecutionPolicy Bypass -File packaging\build.ps1      # tests -> app -> WireGuard -> installer
```

The build produces these files in `dist-installer\`:

* `NobadVPN-Setup-<ver>.exe`, the only file users need
* its `.sha256`
* `latest.json`, the update manifest

To sign the build, see **[docs/CODE-SIGNING.md](docs/CODE-SIGNING.md)**. Unsigned builds work, but they trigger SmartScreen
and cannot auto-update. `-AppOnly` builds just `dist\NobadVPN\` for quick testing.

What the installer does:

1. Installs NOBAD VPN to `Program Files\NOBAD VPN`.
2. Installs the bundled **WireGuard** if it isn't already installed. The installers are the official ones, signed by WireGuard LLC;
   `build.ps1` checks that signature before bundling them. A copy stays in `{app}\redist`, so the app can repair WireGuard
   offline.
3. Registers up to three elevated scheduled tasks:
   * **No-UAC launcher** (`NobadVPN Launcher`): opening NOBAD never shows a UAC prompt.
   * **Boot guard** (`NobadVPN Guard`, runs as SYSTEM at start-up): restores internet if NOBAD died and left the kill
     switch blocking.
   * **Start when I sign in** (`NobadVPN`, optional, on by default): NOBAD is already running in the tray, so it opens
     instantly.
4. Uninstalling first runs `--panic`, so the user is never left offline, then removes the tasks. WireGuard and
   `ProgramData\NobadVPN` (which holds the keys) are kept.

Run from source for development: `python -m pip install --require-hashes -r requirements-lock.txt` (or `pip install -r requirements-dev.txt`), then `python nobad_vpn.py`. It asks for admin rights. Run the tests with `python -m pytest -q tests` and `python -m pyflakes nobadvpn tests`.

## Start-up and performance

* **Splash.** A native splash with the NOBAD logo appears about 0.3 s after start. It's a Win32 layered window, so it doesn't wait for the
  UI engine. The main window is created hidden and shown as soon as its page has loaded, so there's no blank white flash.
* **Nothing slow runs before the window.** Firewall checks, legacy cleanup, task checks and the watchdog all run in the
  background. Firewall state is read with **one** `netsh` call instead of one per rule. Task checks use
  `schtasks /XML` (~0.1 s) instead of PowerShell (~4 s).
* **Single instance.** Opening NOBAD while it's running just brings the existing window to the front, in well under a second.
  A copy that has stopped responding is replaced.
* **Lightweight UI by default.** There's no frosted-glass blur over the animated map, and no ambient animations. The map is a still
  layer that is only redrawn when something changes, with short animation bursts (hover, connecting, the pulse and
  traffic on the active line), and it pauses when the window is hidden. *Settings → Startup & tray →
  Visual effects* turns the rich look back on.
* **Opt-in launch checks.** The speed test and service checks at launch are off by default; run them from their tabs.
  The mini window is only created the first time it's opened.
* **Remaining cost.** About 4 s of a cold start is Windows WebView2 and .NET starting up (measured: a blank pywebview page takes
  about 4 s on the same PC). The splash covers it, and with *Start when I sign in* it's paid once at sign-in rather than when
  you open the app.

## Command line
* `NobadVPN.exe --background` starts hidden in the tray.
* `--panic` removes the firewall rules and tunnels, then exits.
* `--repair-network quick|full` restores internet like `--panic`, then repairs Windows networking (`full` resets
  Winsock/TCP-IP and needs a restart).
* `--selftest` prints what this PC supports.
* `--version` prints the version.
* `--install-tasks [--autostart on|off]` is used by the installer (elevated).

Hidden flags (`--show-result`, `--guard`, `--watchdog`) and other power-user features are listed in
**[docs/FEATURES.md](docs/FEATURES.md)**.

## How protection behaves
* **Kill switch** blocks all outbound traffic that isn't from the tunnel (LAN and server endpoints excepted). It stays armed
  while reconnecting after a drop, sleep or network change.
  * After 8 failed attempts (other servers are tried after the 2nd), the normal kill switch releases with a clear "VPN
    is off" warning.
  * **Strict** mode keeps blocking until you reconnect or press *Restore internet*.
* **DNS leak block** stops DNS (53/853) outside the tunnel. Endpoint hostnames are resolved first and pinned as an IP.
  The last known address is reused while DNS is blocked.
* **After a crash** the rules stay and NOBAD reconnects at its next start.
* **Captive portals** pause the normal kill switch for sign-in. The strict kill switch never pauses on its own.
* **Windows Firewall off**: if any firewall profile is off, NOBAD reports "Protection not enforced" instead of "armed".
* **Trusted Wi-Fi**: a hidden Wi-Fi name (Windows 11 24H2+ without location permission) is never treated as trusted.

## Updates
`latest.json` is an HTTPS manifest with the version, URL and SHA-256. The updater only installs an installer with a
**valid Authenticode signature**, either from the same publisher name as the running app or from a subject or thumbprint
pinned in `nobadvpn/const.py`. A silent update restarts the app afterwards.

## Upgrading from NOMAD Tunnel
On first start, NOBAD:
* copies `ProgramData\NomadTunnel` to `ProgramData\NobadVPN` (the old folder is kept);
* removes the old `Nomad*` firewall rules and the old startup task.

## Layout
```
nobad_vpn.py               launcher (shows the splash before the heavy imports)
nobadvpn/  boot.py splash.py  native splash;  app.py  start-up order;  lifecycle.py  single instance / hand-off
           engine.py firewall.py netwatch.py watchdog.py recovery.py   tunnel, kill switch, DNS block, recovery
           wginstall.py        WireGuard install (bundled MSI -> official download -> winget, all signature-checked)
           autostart.py        launcher + start-with-Windows tasks;  updater.py  signed auto-update
           api.py server.py ui/  loopback API + UI (English only; brand/ holds logo, icon, splash)
packaging/ build.ps1 installer.iss nobad.spec make_brand.py make_manifest.py make_version_info.py
tests/     pytest suite: fake Windows for netsh/sc/wireguard.exe, packaging and UI checks
docs/      CODE-SIGNING.md USER-MANUAL.md FEATURES.md ARCHITECTURE.md SYSTEM-INTEGRATION.md
```

## Documentation
* **[docs/USER-MANUAL.md](docs/USER-MANUAL.md)**: end-user manual.
* **[docs/FEATURES.md](docs/FEATURES.md)**: complete feature list, plus hidden and power-user features.
* **[docs/STREAMING-INTELLIGENCE.md](docs/STREAMING-INTELLIGENCE.md)**: Streaming Region Intelligence: data sources,
  honesty rules, scoring, caching, configuration and limits.
* **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**: how the client works inside.
* **[docs/SYSTEM-INTEGRATION.md](docs/SYSTEM-INTEGRATION.md)**: what NOBAD touches on Windows and on the network.
* **[docs/CODE-SIGNING.md](docs/CODE-SIGNING.md)**: getting and using a code-signing certificate.

## Honest limits
* Windows behaviour is tested against a simulated Windows (fake `netsh`/`sc`/`wireguard.exe`). On one real Windows 11
  PC, a live tunnel, the kill switch (including a simulated tunnel drop), the DNS leak block, the Undo and Quick
  repairs and the WireGuard auto-install all passed. Still to verify on other PCs and networks: sleep/resume, network
  switches, captive portals, ARM64 and clean installs. If you test one of these, please report it in an issue.
* The installer builds with Inno Setup 6 on the development machine (`packaging\build.ps1` produces
  `dist-installer\NobadVPN-Setup-<ver>.exe`), but installing, upgrading and uninstalling on more real PCs still
  needs testing.
* DPAPI machine-scope encryption protects copies, backups and stolen disks. It doesn't protect against other local
  administrators.
* DNS-over-HTTPS (443) isn't blocked by the DNS block alone. The kill switch blocks all non-tunnel traffic.

## How NOBAD is built
NOBAD is an independent studio in its initial launch phase, and NOBAD VPN is its first major release. It is developed
**in collaboration with AI**: AI helps design, write, test and document the code, and a person reviews and owns every
decision and release. The app shows a small "built with AI" mark in its status bar. Contributions are welcome: open
an issue or a pull request on [GitHub](https://github.com/AryanGupta-234/Nobad).

## License
NOBAD VPN is released under the [MIT License](../../LICENSE). The installer also ships third-party components under their
own licenses (WireGuard, Python, pywebview, pystray and others), listed in
[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md). Both files are installed next to `NobadVPN.exe`.
