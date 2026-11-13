# NOBAD VPN for Windows: system integration

What NOBAD VPN installs, writes, changes and contacts on a Windows PC, taken from the source code
(`nobadvpn/`, `packaging/installer.iss`, `packaging/build.ps1`). Internal design is in
[ARCHITECTURE.md](ARCHITECTURE.md).

> Some behaviour with a live tunnel, the kill switch and the installer still needs verification on more real PCs.

---

## 1. Installation

`NobadVPN-Setup-<version>.exe` is an Inno Setup installer (`packaging/installer.iss`).

| Item | Value |
|---|---|
| Requires | administrator rights (`PrivilegesRequired=admin`), Windows 10 version 1809 (10.0.17763) or later, x64-compatible (runs on ARM64 through x64 emulation) |
| Program folder | `C:\Program Files\NOBAD VPN` (`{autopf}\NOBAD VPN`) containing `NobadVPN.exe` and the PyInstaller files |
| Bundled WireGuard | `C:\Program Files\NOBAD VPN\redist\wireguard-amd64.msi` and `wireguard-arm64.msi` (kept so the app can reinstall WireGuard offline) |
| Start menu (`NOBAD VPN` group) | `NOBAD VPN`; `Restore internet (NOBAD)` = `NobadVPN.exe --panic --show-result`; `Repair network (NOBAD)` = `NobadVPN.exe --repair-network quick --show-result` |
| Desktop shortcut | optional task "Create a desktop shortcut", unchecked by default |
| Optional task | "Start NOBAD VPN when I sign in", off by default (`unchecked`); left unticked, Setup keeps the current Settings choice |

Install steps, in order:

1. Copy the app files and the two WireGuard MSIs.
2. If `wireguard.exe` is not in `Program Files\WireGuard` (64- or 32-bit), run
   `msiexec /i "{app}\redist\wireguard-<arch>.msi" /qn /norestart DO_NOT_LAUNCH=1` (the arm64 MSI on ARM64). If it is
   still missing afterwards, a message says NOBAD will offer to install it when it starts.
3. Run `NobadVPN.exe --install-tasks --autostart on` (or `off`) while Setup is still elevated (see section 3).
4. Offer "Launch NOBAD VPN". In a silent install (used by the in-app updater) it starts `NobadVPN.exe --background`.

Running from source (`python nobad_vpn.py`) installs nothing; it asks for admin rights through UAC and never gets the
launcher or boot-guard tasks (those are only for an exe under `Program Files`).

---

## 2. Files and folders

### 2.1 `C:\ProgramData\NobadVPN` (data folder)

Created on first start. Its ACL is reset to **SYSTEM and Administrators (full control)** with inheritance removed
(`icacls`). The `configs` subfolder additionally grants the current user Modify. The `runtime` subfolder is reset to
SYSTEM and Administrators only. Setting the environment variable `NOBAD_DATA_DIR` moves the whole folder (see
[FEATURES.md](FEATURES.md#environment-variables)).

| Path | Contents |
|---|---|
| `settings.json` | all settings (versioned, validated on load) |
| `configs\<name>.conf` / `<name>.conf.dpapi` | your WireGuard configs, **including private keys**. `.dpapi` = encrypted with Windows DPAPI (machine scope) when *Encrypt stored configs* is on |
| `runtime\` | temporary tuned copies handed to WireGuard (MTU/keepalive, fallback DNS, pinned endpoint IP). Deleted (overwritten, then removed) when the tunnel is torn down; leftovers are deleted at the next start |
| `logs\nobad.log` (+ `.1` ... `.5`) | rotating log, 1 MB per file. Key values are replaced by `(hidden)` |
| `usage.json` | daily totals, per-server totals, last 500 sessions, last 200 speed tests (400 days kept) |
| `sessions.json` | legacy session file, read once and migrated into `usage.json` |
| `smart.json` | learned latency per server and time of day, per-service block marks, connect failures |
| `endpoints.json` | last resolved IP addresses of hostname endpoints (reused while the DNS block prevents a lookup) |
| `geo_cache.json` | location (lat/lon, city, country, IP) of each server endpoint, from ipinfo.io |
| `reach.json` | which route works per hostname on this network (direct, official alternative name, or encrypted DNS); kept for a day and cleared when the network changes |
| `instance.json` | running copy's loopback port, PID, start time and API token |
| `clean_exit.flag` | written on a normal exit; its absence at the next start means a crash |
| `netchanges.json` | change journal: original adapter DNS saved before the fix agent changed it |
| `netintel\history.jsonl` | last 400 Network Intelligence results (when *Keep local diagnostic history* is on) |
| `netintel\baselines.json` | per-network baseline (gateways, DNS servers, suffix, IPv6, DNS latency); networks are identified by a hash |
| `netintel\sinkholes.json` | addresses seen answering for filtered names, per network |
| `netintel\fix_profiles.json` | DNS fixes the agent made, per network |
| `crash\crash-<time>.json` | crash reports (always saved locally); renamed to `.sent` or `.dismissed` |
| `crash\error-<time>.json` | non-fatal background-thread errors (newest 20 kept) |
| `exports\NobadDiagnostics-<date>-<time>.zip` | diagnostics bundles (also copied to Desktop or Downloads) |
| `updates\` | downloaded update installers; a downloaded WireGuard MSI is deleted after use |

### 2.2 Other locations

| Path | Contents |
|---|---|
| `%LOCALAPPDATA%\NobadVPN\show_window.flag` | written by a non-elevated launch to ask the elevated copy (started by the launcher task) to show its window; deleted when read |
| `C:\ProgramData\NomadTunnel` | old product's data folder: **read** once (copied into `NobadVPN` if `NobadVPN\settings.json` does not exist yet), never deleted |
| `<app folder>\tunnel_settings.json`, `<app folder>\configs\` | very old locations, read once for migration; NOBAD logs a warning to delete the old configs (they may be synced to the cloud) |
| WebView2 user data | managed by pywebview / WebView2; the UI stores only the theme in `localStorage` (`nobad-theme`) |

---

## 3. Scheduled tasks

All three are registered through PowerShell `Register-ScheduledTask` and checked with `schtasks /Query /TN <name> /XML`.
The launcher and guard tasks are only created for an installed build (exe under `Program Files`), so an elevated or
SYSTEM task can never point at a file a normal user can replace. NOBAD re-registers a task when its action no longer
matches the current exe.

| Task name | Trigger | Runs | Account | Settings |
|---|---|---|---|---|
| `NobadVPN Launcher` | none (started on demand with `schtasks /Run`) | `NobadVPN.exe --background` | the installing user, interactive, highest privileges | battery allowed, start when available, parallel instances, no time limit, priority 4 |
| `NobadVPN` | at sign-in of that user, 15 s delay | `NobadVPN.exe --background` | the user, interactive, highest privileges | same as above |
| `NobadVPN Guard` | at system start-up, 20 s delay | `NobadVPN.exe --guard` | `SYSTEM` (service account), highest privileges | battery allowed, start when available, 3-minute time limit, priority 7 |

* `NobadVPN` exists only while *Start with Windows* is on (installer task, wizard or Settings). It is removed with
  `schtasks /Delete /TN NobadVPN /F` when turned off.
* `NobadVPN Launcher` is what makes a normal (non-elevated) launch open NOBAD without a UAC prompt.
* `NobadVPN Guard` restores internet after a reboot only if NOBAD died with its blocking rules left behind and nothing
  else will remove them (details in [ARCHITECTURE.md](ARCHITECTURE.md#25-boot-guard)).
* Legacy: the `NomadTunnel` task of the old product is deleted on start-up and again by the uninstaller.

---

## 4. Windows Firewall rules

NOBAD creates only outbound **block** rules, all with `profile=any`, through `netsh advfirewall firewall`:

| Rule | Purpose |
|---|---|
| `NobadKS4`, `NobadKS6` | kill switch (IPv4 / IPv6): block traffic not sourced from the tunnel address, except to LAN ranges and server endpoints |
| `NobadDNS4U`, `NobadDNS4T`, `NobadDNS6U`, `NobadDNS6T` | DNS leak block: block UDP/TCP ports 53 and 853 not sourced from the tunnel address |
| `NobadSelfTest` | created and immediately deleted by `--selftest` (local `192.0.2.0/24`, remote `192.0.2.1`) to prove rule creation works |

Rules exist only while the kill switch or DNS block is in effect (connected, connecting, or holding while
reconnecting / in strict mode). Every reset path removes them. Legacy rules `NomadKS4`, `NomadKS6`, `NomadDNS4U`,
`NomadDNS4T`, `NomadDNS6U`, `NomadDNS6T` are removed at start-up and by every reset. NOBAD also reads
`netsh advfirewall show allprofiles state` to detect a disabled firewall profile; it never turns the firewall on or off.

---

## 5. WireGuard tunnel services

* NOBAD needs **WireGuard for Windows** (`C:\Program Files\WireGuard\wireguard.exe`; `wg.exe` is used for handshake
  and traffic statistics if present).
* Connecting runs `wireguard.exe /installtunnelservice <config path>`, which creates the Windows service
  `WireGuardTunnel$<config name>` and a tunnel adapter with the same name. Disconnecting runs
  `wireguard.exe /uninstalltunnelservice <name>`.
* The config path is a runtime copy in `ProgramData\NobadVPN\runtime` (encrypted `.conf.dpapi` or a short-lived
  plaintext `.conf`) or, if no tuning is needed, the stored `.conf`.
* State is read with `sc query WireGuardTunnel$<name>` and `sc query type= service state= all`; failures are
  diagnosed with `wireguard.exe /dumplog`.
* Reset paths only remove services whose names match NOBAD's configs or runtime copies. Tunnels created in the
  WireGuard app are not touched.
* Quitting NOBAD normally leaves the tunnel service running ("Quit (VPN keeps running)"); NOBAD re-attaches to it at
  the next start.

---

## 6. Adapter DNS and other network settings

* **Normal VPN use does not change adapter settings.** DNS for the tunnel comes from the `DNS =` line in the config
  (or the fallback DNS that NOBAD adds to the runtime copy), applied by WireGuard to its own adapter.
* **Adapter DNS on your Wi-Fi/Ethernet adapter is changed only by the Network Intelligence fix agent**, either when you
  click *Fix DNS safely* (after a confirmation) or when you switched on *Smart fix agent* (off by default). The
  original setting is written to `netchanges.json` before `Set-DnsClientServerAddress` runs, and is restored by an
  automatic rollback, by *Undo this change*, by leaving that network, and by every reset (in-app Restore internet,
  Start-menu shortcuts, `--panic`, `--repair-network`, uninstall).
* **Repair actions** you start yourself run Windows' own commands: `ipconfig /flushdns`, `/registerdns`, `/renew`,
  `netsh interface ip delete arpcache` (quick); plus `netsh winsock reset`, `netsh int ipv4 reset`,
  `netsh int ipv6 reset`, `netsh winhttp reset proxy` (full, needs a restart; static IP settings must be re-entered).
* *Clear DNS cache* on the Network tab runs `ipconfig /flushdns`.

---

## 7. Commands NOBAD runs

All through `subprocess` with no console window and below-normal priority:
`netsh` (firewall, Wi-Fi interface info, repair), `sc`, `wireguard.exe`, `wg.exe`, `icacls`, `ping`, `route print`,
`ipconfig`, `schtasks`, `tasklist`, `taskkill`, `msiexec`, `winget` (WireGuard fallback), `explorer` (to show an
exported file), and `powershell -NoProfile -NonInteractive` for: Authenticode checks, task registration, Windows
toast notifications, default-gateway and Wi-Fi profile lookups, the Network Intelligence snapshot
(`Get-NetAdapter`, `Get-NetIPAddress`, `Get-NetRoute`, `Get-DnsClientServerAddress`, `Get-DnsClientDohServerAddress`,
`Get-DnsClientNrptPolicy`, registry reads), the DNS cache (`Get-DnsClientCache`) and the fix agent's DNS changes.

---

## 8. Network destinations

NOBAD has no NOBAD-operated server built in: the update URL and crash-report URL are empty by default. The table lists
every outbound destination found in the code.

### 8.1 Always involved when you use the VPN

| Destination | When | Notes |
|---|---|---|
| Your WireGuard server endpoints (from your configs) | connecting; Probe all / Fastest / Smart pick / failover (ICMP ping x3, then TCP 443 or 80 if ping fails); *Check endpoint* | endpoint hostnames are resolved through Windows DNS |
| `1.1.1.1` / `2606:4700:4700::1111` (ICMP) | handshake check and health check every 8 s while connected (through the tunnel); split tunnels ping a host inside the tunnel instead | a UDP socket "connect" to these addresses is also used to detect IPv4/IPv6 routes; that sends no packet |
| `http://www.msftconnecttest.com/connecttest.txt`, `http://connectivitycheck.gstatic.com/generate_204` | captive-portal check after a failed handshake (normal kill switch only), every 4 s for up to 10 min while waiting for a sign-in, fix-agent preflight, `--selftest` | plain HTTP, redirects not followed |

### 8.2 IP address and location lookups (setting *Look up my exit IP address*, **off by default since 1.2.0**; opt in from the setup checklist or Settings → Privacy)

| Destination | When |
|---|---|
| `https://ipinfo.io/<endpoint IP>/json` | once per server endpoint (result cached in `geo_cache.json`), at start-up and after importing or rescanning configs |
| `https://ipinfo.io/json` | your own location for the map (kept in memory only): at start-up when not connected, and after disconnecting if it is not known yet |
| `https://ipinfo.io/json`, then `https://ipapi.co/json/`, `https://api.ipify.org?format=json`, `https://www.cloudflare.com/cdn-cgi/trace` | exit-IP lookup after each connect, when NOBAD attaches to a running tunnel, at each UI launch, and on *Refresh* |

Turning the setting off stops all of these.

### 8.3 Checks you start (some also at launch)

| Destination | When |
|---|---|
| ping `1.1.1.1`, your router, DNS lookup of `example.com` | *Run network check*; also automatically once per UI launch |
| `https://speed.cloudflare.com/__down?bytes=8000000` | *Run speed test*; at launch only if *Run extra checks at startup* is on (off by default) |
| `https://www.cloudflare.com/cdn-cgi/trace`, `https://www.netflix.com/title/80018499`, `https://www.youtube.com/generate_204`, `https://www.disneyplus.com/`, `https://www.primevideo.com/`, `https://open.spotify.com/`, `https://www.twitch.tv/` | *Check* (service reachability); at launch only with *Run extra checks at startup*; the watched service (and the Cloudflare baseline) about 20 s after each connect and every 30 min when *Watch a streaming service* is set |
| VALORANT list in `tools.py`: ICMP/TCP to the community-reported Riot edge IPs listed for Mumbai and Singapore (for example `151.106.246.1`, `151.106.248.1`) and TCP 443 to `ec2.<region>.amazonaws.com` hosts | *Refresh all* on the Network tab; at launch only with *Run extra checks at startup* |
| a game server you type in | *Test custom* (ping x5) |
| an `https://` URL you type in | *Import from URL* (max 100,000 bytes) |

### 8.4 Network Intelligence (Intel tab)

Runs only when you open the Intel tab (the overview runs once automatically), press a button, or switch on the fix
agent.

| Destination | Purpose |
|---|---|
| DNS servers offered by your network (DHCP), the ones Windows uses, and the reference list (default `1.1.1.1`, `8.8.8.8`, `9.9.9.9`, `2606:4700:4700::1111`, `2001:4860:4860::8888`, editable) | plain DNS queries on port 53 (UDP, TCP fallback): the site you investigate, root `NS`, random non-existent names, `PTR` lookups |
| DoH templates Windows already has for the reference servers (at most two) | DNS-over-HTTPS POST queries |
| `192.0.2.53`, `198.51.100.53`, `2001:db8::53` | DNS interception test (documentation addresses; any answer means interception) |
| the investigated site's addresses | TCP 443 and 80 connects, TLS handshakes with the real name and with `nobad-sni-control.invalid`, one HTTPS GET |
| your router | ping, by the fix agent before and after a DNS change |
| names from the Windows DNS cache | resolved through Windows by the fix agent as "canaries" |

### 8.5 Streaming Region Intelligence (Streaming tab → Where to watch)

Nothing runs until you add a TMDB key and search. Requests carry the User-Agent `NOBAD-VPN/<version>`.

| Destination | Purpose |
|---|---|
| `https://api.tmdb.org/3/...`, falling back to `https://api.themoviedb.org/3/...` | search, title details (with alternative titles, external ids, age ratings and watch providers in one request), the covered-country list, country names and provider lists. Sends **your TMDB key**. |
| `https://image.tmdb.org/t/p/...` | posters and platform logos, fetched by NOBAD's local server and cached (the UI never loads remote images directly) |
| `https://en.wikipedia.org/w/api.php` | the banned-film lists (about a dozen pages, rebuilt at most weekly) and redirects for the selected title |
| `https://www.wikidata.org/w/api.php` | maps the title's Wikidata id to its Wikipedia article |
| your exit IP lookup and the existing service checks | only after you connect from a recommendation (*verify*), and the IP lookup only when that privacy setting is on |

Data is cached in `streamintel\cache.sqlite` and `streamintel\img\` (TMDB content at most six months). The TMDB key is
in `streamintel	mdb.credential`, encrypted with DPAPI.

### 8.6 Installation, updates and reports

| Destination | When | Opt-in? |
|---|---|---|
| `https://download.wireguard.com/windows-client/wireguard-<arch>-1.1.1.msi` | installing WireGuard when the bundled MSI is missing or fails its signature check | runs on *Install WireGuard*, and at start-up when WireGuard is missing and *Reinstall WireGuard automatically* is on (default on) |
| `winget` source (`WireGuard.WireGuard`) | last resort of the same chain | same |
| `https://www.wireguard.com/install/` | opened in your browser by *Open download page* | on click |
| `http://neverssl.com` | opened in your browser by *Open sign-in page* when the portal gave no address | on click |
| `windowsdefender://network/` | opens Windows Security's firewall page from the "Protection not enforced" banner | on click |
| *Update manifest URL* and the installer URL in it | *Check now*, or at launch with *Check for updates on launch* | yes: empty by default |
| *Crash report server* | *Send report*, or at start-up for pending reports when *Send crash reports* is on | yes: off and empty by default |
| `http://timestamp.digicert.com` / `http://timestamp.acs.microsoft.com`, `download.wireguard.com` | **build machine only** (`build.ps1`), not the user's PC | n/a |

### 8.7 Adapting to blocked services (Settings → Connectivity, on by default)

This applies only to NOBAD's own downloads: the IP lookups, the speed test, Where to watch, Wikipedia, and the
WireGuard and update downloads. It never applies to your VPN traffic, and the service checks and Network Intelligence
always measure the direct path.

| When | Destination |
|---|---|
| a hostname's TLS connection is reset | the service's official alternative name: `api.themoviedb.org` ↔ `api.tmdb.org`, `en.wikipedia.org` → `en.m.wikipedia.org`, `www.wikidata.org` → `m.wikidata.org` |
| the network's DNS fails or returns a blocked answer (0.0.0.0, loopback, private) | DNS-over-HTTPS lookups at `https://1.1.1.1/dns-query` (Cloudflare) or `https://8.8.8.8/resolve` (Google), then HTTPS to that address with the real hostname and certificate check |
| *Test connectivity* | one request to each service NOBAD uses |

### 8.8 Local only

The UI talks to a server on `127.0.0.1:<random port>` (token-protected; see
[ARCHITECTURE.md](ARCHITECTURE.md#71-server-security-serverpy)). A second launch talks to the same server to hand
over. The CLI repair path posts to it with proxies disabled.

---

## 9. Permissions

| Component | Rights | Why |
|---|---|---|
| Main app | administrator (elevated) | tunnel services, firewall rules, folder ACLs, scheduled tasks |
| Launch without UAC | `NobadVPN Launcher` task with highest privileges | starts the elevated app for a normal user launch |
| Watchdog | inherits the app's elevation | re-launches the app, may remove rules (fail-open) |
| Boot guard | `SYSTEM` | runs before anyone signs in |
| Installer / uninstaller | administrator | Program Files, WireGuard MSI, tasks |
| `--panic`, `--repair-network`, `--install-tasks`, `--guard` | administrator (exit code 1 or 2 without it) | |
| `--selftest`, `--version` | none | `--selftest` reports "not elevated" and skips the firewall test without admin |

Windows Firewall must be on for every profile, or the rules are reported as not enforced. Windows 11 24H2 and later
hide the Wi-Fi name from desktop apps without location permission; NOBAD then treats every Wi-Fi network as untrusted.

With trusted-network rules on, NOBAD reads the router's MAC address (`ping -n 1` to the gateway, then `arp -a`) and,
when Windows allows it, the Wi-Fi security type and access point (`netsh wlan show interfaces`) to recognise trusted
networks. These stay in `settings.json` and are left out of diagnostics exports.

---

## 10. Uninstall

The uninstaller:

1. runs `NobadVPN.exe --panic` (hidden): removes NOBAD firewall rules (and legacy `Nomad*` rules), uninstalls NOBAD
   tunnel services, deletes runtime copies, and restores adapter DNS changes from the journal. If a NOBAD instance is
   still running and answering, the request is forwarded to it;
2. deletes the tasks `NobadVPN`, `NobadVPN Launcher`, `NobadVPN Guard` and legacy `NomadTunnel`;
3. removes the program files and shortcuts installed by Setup.

Kept on purpose:

* **WireGuard for Windows** (other apps or the user may rely on it). Remove it in *Settings → Apps* if wanted.
* **`C:\ProgramData\NobadVPN`**, which holds your configs and private keys, settings, history and logs. Delete it by
  hand if wanted.
* `%LOCALAPPDATA%\NobadVPN` (at most a leftover `show_window.flag`) and `C:\ProgramData\NomadTunnel`, if present, are
  not removed either.
