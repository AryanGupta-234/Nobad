# NOBAD VPN for Windows: feature list

One line per feature, grouped by area, as implemented in the code. Defaults are given where they matter. How things
work: [ARCHITECTURE.md](ARCHITECTURE.md). What is touched on Windows and the network:
[SYSTEM-INTEGRATION.md](SYSTEM-INTEGRATION.md). End-user guide: [USER-MANUAL.md](USER-MANUAL.md).

Some live-tunnel behaviour still needs verification on more real PCs and networks.

---

## Connection

* Drives the official WireGuard for Windows tunnel service (`wireguard.exe /installtunnelservice`).
* Connect by server button, map click, main button, tray, mini window or command palette.
* Handshake verification (up to 14 s) using `wg.exe latest-handshakes`, with ping as a fallback.
* Detailed failure diagnosis (service state, exit code, WireGuard log lines) with action buttons.
* Health check every 8 s; auto-repair after 2 failed checks, failover to another server after 2 repairs (*Auto-repair & failover*, default on).
* Auto-reconnect with backoff after a drop; other servers tried from the 3rd attempt; stops after 8 attempts and, with the kill switch on, keeps blocking until you choose Restore internet.
* Clean reconnect after sleep/resume and network changes (*Reconnect after sleep or network changes*, default on).
* "Network lost" state while no network is available.
* Captive-portal detection with *Open sign-in page* and automatic reconnect after sign-in (up to 10 min).
* Hostname endpoints resolved before arming protection and pinned as an IP; last known address reused if DNS is blocked.
* IPv4-only / IPv6-only uplinks: the usable address family is tried first.
* Split-tunnel aware health target (pings a host inside the tunnel).
* Streaming-tuned runtime copy: MTU 1380 and keepalive 25 when the config has none (*Streaming-tuned tunnel*, default on).
* Connect on launch to the last server (*Connect on launch*, default off).
* Attaches to a tunnel that is already running when NOBAD starts.
* Quit while keeping the VPN running, or disconnect and quit.
* Panic reset that works in any state and aborts a connect in progress.

## Server choice

* Server list with search, sort (best latency, name, favourites first) and a favourites-only filter.
* Favourites (star).
* Probe all: ICMP ping, TCP 443/80 estimate when ping is blocked.
* Fastest: measures every server (dropping the tunnel briefly) and connects to the quickest.
* Smart pick: live latency blended with learned latency per 4-hour block, failure penalty, per-service block marks (*Smart server choice*, default on).
* Map of server locations with latency colours (green < 80 ms, amber < 180 ms, red slower).
* Streaming guard: watch one service (Netflix, YouTube, Disney+, Prime Video, Spotify, Twitch) and optionally switch server if it is blocked.

## Protection

* Kill switch via Windows Firewall rules `NobadKS4` / `NobadKS6` (default off).
* DNS leak block via `NobadDNS4U/4T/6U/6T`, ports 53 and 853, also to LAN resolvers (default on).
* Fallback DNS injected into the runtime copy when a config has no DNS line (default on, `1.1.1.1, 1.0.0.1`).
* Rules updated in place, never removed during a reconnect.
* Strict kill switch: never releases on its own, never pauses for captive portals (default off).
* Windows Firewall off detection ("Protection not enforced").
* Crash watchdog that relaunches NOBAD (default on), with optional fail-open after 3 failed restarts (default off).
* Boot guard task (SYSTEM) that restores internet after a reboot if NOBAD died with rules left behind and nothing else would remove them.
* Kill switch kept and tunnel reconnected at start-up after a crash (or always in strict mode).

## Configs

* Import from files (several at once), drag and drop, QR image (file or pasted screenshot), pasted text, HTTPS URL, or the configs folder plus Rescan.
* Live validation with line-numbered errors and warnings.
* Editor with private/preshared keys hidden and preserved.
* Refuses `PreUp`/`PostUp`/`PreDown`/`PostDown` in configs from a URL or QR code.
* Optional encryption at rest with Windows DPAPI, machine scope (*Encrypt stored configs*, default off).
* Encrypted runtime copies when WireGuard accepts them, otherwise short-lived plaintext copies in a locked folder.
* Private config folder in ProgramData with a restricted ACL.
* Delete a config (refused while connected to it).
* *Check endpoint*: DNS, ping and TCP reachability report for a server.

## Trusted networks

* Auto-connect on untrusted networks and auto-disconnect on trusted ones (*Use trusted-network rules*, default off).
* Trust the current network with one click, or add names by hand (Wi-Fi name or `Ethernet`).
* Trust checks more than the name: the router's MAC address and, when Windows shows them, the Wi-Fi security type and
  access point (BSSID). A mismatch is treated as untrusted until you confirm it; open Wi-Fi is never trusted.
* Hidden Wi-Fi names (Windows 11 24H2+) are never trusted.
* A manual disconnect is respected until the network changes.

## Streaming and gaming tools

* Speed test (Cloudflare, up to 8 MB / about 5 s) with SD / HD / 4K markers and history.
* Service reachability for Netflix, YouTube, Disney+, Prime Video, Spotify, Twitch plus a Cloudflare baseline.
* Plain-English network check (router, internet, DNS) and *Clear DNS cache*.
* VALORANT region check (community-reported Riot edges for Mumbai/Singapore, cloud-region TCP estimates elsewhere).
* Custom game endpoint test (ping, loss, jitter, verdict).

## Streaming Region Intelligence (Streaming tab → Where to watch)

* Search movies, series, anime, animated and documentary titles (a year or an IMDb id narrows results; de-duplicated
  by TMDB identity; original and alternative titles shown).
* Country-by-country listings by offer type: subscription, free, free with ads, rent, buy. *Not listed* (covered
  country) is kept apart from *unknown* (country not covered).
* Platform view: every platform carrying the title, with its countries.
* Documented restrictions from Wikipedia's banned-film lists, matched by Wikidata identity, with dates, notes,
  citations and a verification label; age ratings shown separately.
* Recommendation of *your* matching VPN servers, scored with reasons and caveats (offer type, your services, latency,
  server-country evidence, past service results, data freshness, restrictions). Server load is shown as not reported.
* One-click connect through the existing engine, then verification of the exit country and platform reachability.
* Freshness labels, stale-data fallback, a six-month cache limit (TMDB terms), required TMDB/JustWatch attribution.
* Your own TMDB key, checked before saving and stored DPAPI-encrypted outside `settings.json`; optional
  "services you have" filter.

## Network Intelligence (Intel tab)

* Network overview: adapters, gateway, DNS health, NXDOMAIN rewriting, DNS interception, multiple uplinks, changes since last seen.
* Investigate a site: DNS comparison across network, configured, independent and encrypted resolvers; TCP, TLS, SNI-filtering, HTTP 451 and IPv6 checks; whether this PC is affected; recommendations.
* Evidence and confidence (low / medium / high, with percentage) on every finding.
* Provider attribution only when names match by evidence.
* DNS lookup of A, AAAA, CNAME, MX, TXT, NS, SOA against every resolver.
* IPv4 / IPv6 view per adapter.
* VPN integrity check: routes, IPv6 leak risk, DNS paths outside the tunnel, tunnel DNS, recent transitions.
* Local history and per-network baselines (default on), with Clear.
* Smart fix agent: safe DNS change with preflight, canaries, verification and automatic rollback; manual *Fix DNS safely* or autonomous (default off).
* Editable list of independent reference resolvers (2 to 8 addresses).

## Fail-safes and repair

* Change journal for every adapter DNS change, written before the change.
* Repair levels: Restore internet (undo), Quick repair, Full network reset, each reporting real command results.
* Repair from the Intel tab, Settings, tray, Start menu shortcuts (work with NOBAD closed) and the command line.
* Uninstaller restores internet before removing anything.

## Interface

* Frameless window with NOBAD's own title bar: native drag and snap, edge resizing, minimise / maximise / close;
  maximising stays above the taskbar. Optional, via *NOBAD title bar*.
* Command palette (Ctrl+K) with fuzzy search over actions, servers, tabs and every setting, plus *Investigate* and
  *Where to watch* for free text, and recently used items first.
* Where to watch opens in a large browser window with a poster grid and recent searches.
* Connectivity: automatic routes around blocked hostnames or DNS for NOBAD's own downloads, with a *Test
  connectivity* report.

* Main window with dock tabs: Servers, Streaming, Network, Intel, Details, Settings; last tab remembered.
* Live status, exit IP (copy / refresh), latency, jitter, loss, throughput, uptime, charts.
* Protection check score (up to 7 checks).
* Usage history: daily chart (7 / 30 days / all time), per-server totals, speed-test history, sessions.
* Launch diagnostics card (IP, speed, services, network, VALORANT).
* First-run setup checklist (wizard), reopenable from Settings → Help.
* Notices with action buttons (errors, WireGuard missing or installing, kill switch blocking, firewall off, update available, previous crash).
* Settings in groups with a search box.
* Dark and light mode.
* *Visual effects* (frosted glass, ambient animations), off by default.
* Native splash screen at start-up.
* Window size, position and maximised state remembered and kept on-screen; per-monitor DPI awareness; dark title bar.
* Accessibility: tab roles, roving focus in the dock, live announcements, modal focus trap, skip link, reduced-motion support.
* Tray icon with status dot and full menu (requires pystray and Pillow).
* Mini window (Quick view) from the tray.
* Windows notifications (default on), rate-limited.
* Footer log with expandable history.
* Falls back to the default browser if pywebview is missing.

## Installation, updates, maintenance

* Single installer with bundled, signature-checked WireGuard MSIs (amd64 and arm64).
* No UAC prompt after installation (launcher task); optional start at sign-in.
* Automatic WireGuard reinstall at start-up: bundled MSI, official download, winget; all signature-checked (default on).
* Signed auto-update from an HTTPS manifest (inert until a URL is set).
* Single instance: a second launch brings the running window forward; a hung copy is replaced.
* Diagnostics export (zip, keys removed).
* Local crash reports, optional sending.
* Self-test (`--selftest`).
* Migration from NOMAD Tunnel.

---

## Hidden and power-user features

### Keyboard shortcuts

| Keys | Where | Action |
|---|---|---|
| Ctrl+K (or Cmd+K) | main window | open / close the command palette |
| Space | main window, when focus is on the page (not a field or button) and the palette is closed | connect / disconnect (same as the main button; with nothing selected it runs Fastest) |
| 1, 2, 3, 4 | same condition | switch to the first four dock tabs: 1 Servers, 2 Streaming, 3 Network, 4 Intel |
| Left / Right, Home / End | focus on a dock tab | move between tabs |
| Up / Down, Enter | command palette | select and run a command |
| Esc | command palette, dialogs | close (dialogs trap Tab focus while open) |
| Esc | mini window | hide it |
| Enter | Intel → Sites / DNS input | run Investigate / Look up |
| Ctrl+V | Servers tab (not in a text field) | import a pasted QR image, or open the editor with pasted text that contains `[Interface]` |

There are no shortcuts for Details or Settings; use the palette ("Go to Details", "Go to Settings").

### Command palette commands

Open with Ctrl+K or the **Search** button in the header. Type to filter (substring match).

* Connect / disconnect
* Connect to fastest server
* Run speed test
* Check streaming services
* Probe all servers
* Toggle kill switch
* Open configs folder
* Go to Servers, Go to Streaming, Go to Details, Go to Settings
* Connect → *server name* (one entry per config)

### Other small things in the UI

* The three chips under the status (*Kill switch*, *Auto-repair*, *Stream tune*) toggle those settings directly.
* The "Not running as administrator" warning in the header is clickable (relaunch elevated).
* Clicking the log line in the footer expands the last 150 log entries.
* Settings search also matches hidden keywords and the raw setting key (for example `mtu`, `winsock`, `telemetry`,
  `kill_switch`).
* Opening the Intel tab runs the network overview once automatically.
* The Servers tab accepts dropped files anywhere on the tab.

### Command-line flags

`NobadVPN.exe [flags]` (from source: `python nobad_vpn.py [flags]` or `python -m nobadvpn [flags]`). Unknown flags are
ignored. Flags marked hidden are not shown by `--help`.

| Flag | Hidden | What it does |
|---|---|---|
| `--background` | no | start hidden in the tray (the window still opens if there is no tray, or if a launcher show-flag is present) |
| `--panic` | no | restore internet: remove NOBAD firewall rules, tunnel services and journaled DNS changes, then exit. Needs admin (asks via UAC when not elevated) |
| `--repair-network quick\|full` | no | `--panic` plus the quick or full repair steps; `full` needs a restart |
| `--show-result` | yes | with `--panic` / `--repair-network`: show the result in a message box (used by the Start-menu shortcuts) |
| `--selftest` | no | print what this PC supports (Windows version, DPI, admin, WireGuard, wg.exe, IPv4/IPv6, network name, captive portal, DPAPI, firewall rule create/delete, start-up task, data folder, Python modules). Exit code 1 if any check failed |
| `--version` | no | print the version (`1.0.0`) |
| `--install-tasks` | yes | register the launcher and boot-guard tasks (installed builds only); used by the installer. Exit 2 without admin, 1 if something failed |
| `--autostart on\|off` | yes | with `--install-tasks`: create or remove the start-with-Windows task and save the setting |
| `--guard` | yes | boot-guard run (used by the `NobadVPN Guard` task as SYSTEM). Exit 2 without admin |
| `--watchdog <pid>` | yes | run as the crash watchdog for that process (started by NOBAD itself) |
| `-h`, `--help` | no | argparse help |

If NOBAD is already running, `--panic` and `--repair-network` ask the running copy to do the work, so auto-repair
can't undo the reset.

### Environment variables

* `NOBAD_TMDB_TOKEN`: a TMDB key or token used instead of the saved one (development and CI). The ⚙ dialog shows
  "(from environment)" and hides *Remove key*.


| Variable | Effect |
|---|---|
| `NOBAD_DATA_DIR` | replaces `C:\ProgramData\NobadVPN` for everything (settings, configs, runtime, logs, journal, history, instance file). It also disables the NOMAD Tunnel data migration. Used by the tests and for portable setups. `%LOCALAPPDATA%\NobadVPN\show_window.flag` is not affected. |
| `NOBAD_SIGN_THUMBPRINT`, `NOBAD_SIGN_DLIB` + `NOBAD_SIGN_METADATA`, `NOBAD_SIGN_PFX` + `NOBAD_SIGN_PASS`, `NOBAD_RELEASE_URL` | build-time only (`packaging/build.ps1`): code signing and the URL written into `latest.json`. See [CODE-SIGNING.md](CODE-SIGNING.md). |

Build script switches: `-AppOnly` (only `dist\NobadVPN\`), `-InstallTools` (install Inno Setup with winget).

### Settings that are not (fully) in the Settings screen

All live in `C:\ProgramData\NobadVPN\settings.json`. Values read from the file are validated like values from the
UI; invalid values fall back to the default. Keys NOBAD doesn't know are ignored and disappear the next time
the file is written.

| Key | Default | Notes |
|---|---|---|
| `dpapi_runtime_ok` | `true` | switched off automatically when WireGuard refuses an encrypted runtime copy. It cannot be changed from the UI or API; set it back to `true` by hand to retry encrypted runtime copies |
| `wizard_done` | `false` | set when the checklist is finished or skipped; `false` makes it open again at start |
| `last_region` | `null` | last connected server; used by Connect on launch, tray "Connect (last server)", auto-reconnect, trusted-network auto-connect |
| `favorites` | `[]` | starred servers (max 200) |
| `trusted_networks` | `[]` | trusted network names (max 100, each up to 64 characters) |
| `trusted_fingerprints` | `{}` | per trusted name: Wi-Fi security and confirmed access points, and router MACs; set only by *Trust current network* / *Confirm this network* |
| `window` | `null` | main window `x`, `y`, `w`, `h`, `maximized` (minimum 1060 x 700) |
| `last_tab` | `"t1"` | last dock tab (`t1` Streaming, `t2` Servers, `t3` Settings, `t4` Details, `t5` Network, `t6` Intel) |
| `theme` | `"dark"` | `dark` or `light` |
| `settings_version` | `2` | schema version; v1 files are migrated (existing users with a `last_region` skip the wizard) |
| `watchdog_failopen` | `false` | in Settings, but note it is also read by the boot guard after a reboot |
| `ni_reference_dns` | five resolvers | at least 2 and at most 8 IP addresses |
| `update_url`, `crash_report_url` | `""` | must start with `https://` |

Build-time trust anchors for updates are in `nobadvpn/const.py`: `UPDATE_SIGNER_SUBJECTS` and
`UPDATE_SIGNER_THUMBPRINTS` (both empty, meaning "same publisher as the running exe").

### Diagnostics export

*Settings → Privacy & security → Export diagnostics* writes `NobadDiagnostics-<date>-<time>.zip` to
`ProgramData\NobadVPN\exports`, copies it to your Desktop (or Downloads), and selects it in Explorer. Contents:

* `summary.json`: version, Python, Windows version, admin, DPI, IPv4/IPv6 capability, WireGuard presence, settings
  (without trusted networks, update and crash URLs, window geometry), connection state, firewall rules present, the
  last 30 network events, server list;
* `configs_redacted/*.conf.txt`: configs with private and preshared keys replaced;
* `logs/nobad.log*`;
* `system/`: `ipconfig /all`, `route print -4` / `-6`, `netsh wlan show interfaces`, NOBAD's firewall rules,
  `wg show`, the WireGuard log, WireGuard tunnel service states;
* `README.txt`.

Every file is scrubbed: key values, MAC addresses (masked), Wi-Fi names (SSID/profile lines and known network names).
Server endpoints, public keys and your network's IP addressing are included on purpose.

### Crash reports

* Unhandled errors in the main thread are saved as `ProgramData\NobadVPN\crash\crash-<time>.json`; errors in
  background threads are saved as `error-<time>.json` (newest 20 kept) and never shown as a crash.
* A report contains the app version, OS, Python version, the traceback and the last 40 log lines, with the home
  folder and user name masked and keys scrubbed.
* After a crash the next start shows "NOBAD closed unexpectedly last time" with *Review report*: send (only if a crash
  report server is set) or dismiss.
* Automatic sending at start-up only when *Send crash reports* is on **and** *Crash report server* is set. Nothing
  is configured by default.

### Migration from NOMAD Tunnel (previous product name)

* On the first start, if `ProgramData\NobadVPN\settings.json` does not exist, `ProgramData\NomadTunnel` is copied over
  (except `runtime`, `logs`, `updates`, `instance.json`, `*.tmp`, `clean_exit.flag`). The old folder is kept; DPAPI
  encrypted configs stay valid.
* Old `Nomad*` firewall rules and the `NomadTunnel` start-up task are removed at start-up; the uninstaller also
  deletes that task; every reset removes `Nomad*` rules.
* A running `NomadTunnel.exe` is closed when the packaged `NobadVPN.exe` starts (not when run from source).
* Even older locations are read once: `tunnel_settings.json` and a `configs\` folder next to the app. Copied configs
  trigger a warning to delete the originals (they may be in a cloud-synced folder).
* `sessions.json` (old session log) is imported into `usage.json`.

### Other things a normal user would not find

* `GET /api/ping` on the loopback server answers `{"app": "nobad-vpn", "ver": ...}` without a token.
* NOBAD keeps working without pywebview (opens the UI in your browser) and without pystray/Pillow (no tray or mini
  window).
* The engine re-checks the Windows Firewall profile state at most once a minute while applying rules.
* The traffic monitor keeps sampling every 30 s even with the window closed, so usage history stays accurate.
* The streaming guard first checks a Cloudflare baseline so it doesn't blame a service when the tunnel itself is down.
* `--selftest` creates and deletes a test firewall rule `NobadSelfTest` to prove rule creation works.
* The `NobadVPN` start-with-Windows task is repaired automatically when it points at an old install location.
