# What still needs a real Windows PC

Automated: `python -m pytest tests` covers config parsing/validation, firewall rule maths, route/SSID parsing, usage,
smart ranking, netwatch with a fake clock, watchdog decisions, engine flows against a fake Windows and server security.
`tests/test_reliability.py` adds: endpoint pinning, stale-DNS fallback, keeping the kill switch armed while
reconnecting, give-up release, strict mode with captive portals, post-crash adoption, firewall-off detection, split-tunnel
health target, panic during connect, config-name traversal and hidden-SSID trust. There is also a headless-browser render
of the real UI. `tests/test_release.py` covers start-up hand-off, splash, WireGuard install order and signature checks, update trust, scheduled-task parsing, settings hardening and the packaging files (ASCII-only PowerShell, installer contents). None of that replaces the matrix below.

First run `NobadVPN.exe --selftest` (admin) on each machine and keep the output.

| # | Scenario | How | Expect |
|---|----------|-----|--------|
| 1 | Windows 10 and 11 | selftest + connect/disconnect | all PASS; kill switch + DNS rules appear in `wf.msc` as NobadKS4/6, NobadDNS4U/T/6U/T |
| 2 | DNS leak | connect, open dnsleaktest.com *extended* | only the VPN's resolver appears; `nslookup example.com 192.168.x.1` (your router) times out while connected |
| 3 | Config without DNS line | connect with *Add fallback DNS* on/off | on: lookups work; off: DNS block is skipped and the log says why |
| 4 | Sleep/resume | connect, sleep 2 min, wake | log "resumed after sleep… reconnecting"; no traffic leaked meanwhile (ping -t 8.8.8.8 shows timeouts, never replies from your ISP) |
| 5 | Wi-Fi → Ethernet | connect on Wi-Fi, plug cable, disable Wi-Fi | clean reconnect within ~10 s; kill switch stays armed |
| 6 | Network lost/returned | pull cable | "Network lost" banner/toast; reconnects when it returns |
| 7 | Captive portal | hotel/café Wi-Fi, or a router with a portal | handshake fails → "Wi-Fi sign-in required" banner, kill switch pauses, *Open sign-in page* works, auto-reconnects and re-arms |
| 8 | IPv6-only network | NAT64/IPv6-only hotspot | endpoint with AAAA connects; IPv4-only endpoint reports a handshake failure (expected without NAT64) |
| 9 | Crash watchdog | arm kill switch, `taskkill /F /IM python.exe` (or NobadVPN.exe) | watchdog relaunches within ~15 s; if not, toast says internet is blocked and `NobadVPN --panic` restores it |
| 10 | Panic reset | button, tray item, `--panic` | rules and tunnels gone, internet works |
| 11 | **DPAPI + WireGuard** | enable *Encrypt stored configs*, connect | connects with an encrypted runtime copy. If WireGuard refuses `.conf.dpapi` on your build, NOBAD logs it, flips `dpapi_runtime_ok` off and uses a short-lived plaintext copy in the locked runtime folder — verify which path you got |
| 12 | Start with Windows | enable, sign out/in; then launch manually while not elevated | no UAC prompt either time; window appears only on manual launch |
| 13 | Tray | close window, left-click tray, quit entries | window hides, mini window opens bottom-right, "Quit (VPN keeps running)" leaves the tunnel up |
| 14 | DPI scaling | 100/125/150/200/250/300 %, and move the window between monitors | text sharp, charts sharp, window restores on-screen (unplug a monitor, relaunch) |
| 15 | Keyboard/screen reader | Narrator and NVDA; Tab through everything | switches announce on/off, tabs announce selected, banners are read, modals trap focus and Esc closes. Code-level a11y work is done; a real screen-reader pass is still yours |
| 16 | Import | .conf ×3 at once, URL, QR screenshot, paste, drag-drop | each imported or a clear per-file error; configs with PostUp from URL/QR are refused |
| 17 | Updater | publish a **signed** installer + manifest for a higher version | banner → install → app restarts by itself (silent install relaunches it); wrong SHA-256, unsigned, or other-publisher installers are refused with a clear message |
| 18 | Installer | install, run, uninstall | uninstall runs `--panic` and deletes the startup task; ProgramData is kept |
| 19 | Upgrade from NOMAD Tunnel | install NOBAD VPN on a PC that had NOMAD Tunnel (configs, kill switch on, start-with-Windows on) | configs/settings/history appear; old `Nomad*` rules and `NomadTunnel` task are gone; re-enable *Start with Windows* works without UAC |
| 20 | Reconnect while DNS is blocked | hostname endpoint, kill switch + DNS block on, sleep > 10 min | reconnects (log: "using its last known address" if lookup is blocked); never leaks |
| 21 | Dead server failover | connect, then block the server's IP at the router | after 2 failed attempts NOBAD tries another server; after 8 the normal kill switch releases ("VPN is off") and strict keeps blocking |
| 22 | Windows Firewall off | turn a firewall profile off, connect with kill switch on | red "Protection not enforced" banner + toast; switch shows not armed |
| 23 | Hidden Wi-Fi name (Win 11 24H2+) | deny location access to desktop apps, trusted-network rules on | network shows as "Wi-Fi (name hidden)" or the profile name, never "Ethernet"; never auto-disconnects as trusted |
| 24 | Crash, then reboot | kill switch on, `taskkill /F` NOBAD and its watchdog, reboot | internet stays blocked until NOBAD starts and reconnects (no leak at boot) |
| 25 | Installer on a clean PC (no WireGuard) | run `NobadVPN-Setup-<ver>.exe` with defaults | WireGuard installs silently (no WireGuard window); NOBAD opens without a UAC prompt; `schtasks /Query /TN "NobadVPN Launcher"` exists |
| 26 | Installer when WireGuard is present | install over an existing WireGuard | WireGuard step is skipped; existing WireGuard tunnels untouched |
| 27 | ARM64 PC | install on Windows on ARM | the arm64 WireGuard MSI is used; tunnels connect |
| 28 | Start-up speed | cold start from the Start menu, then open again while running | splash with the NOBAD logo within ~1 s; window when ready; second open brings the window forward instantly |
| 29 | Lightweight idle | leave the window open on the map, not connected | Task Manager: NOBAD + WebView2 near 0-2 % CPU, GPU near 0 %; turning on *Visual effects* adds the glass/animations |
