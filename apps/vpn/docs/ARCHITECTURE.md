# NOBAD VPN for Windows: architecture

This document describes how the client works inside. It was written from the source in `nobadvpn/`, `packaging/` and
`tests/`. Constants quoted here (timeouts, counts, names) are the values in the code at the time of writing.

> **Verification status.** The automated tests run against a simulated Windows (see [Testing strategy](#13-testing-strategy)).
> Some live-tunnel behaviour on real PCs (sleep/resume, captive portals, DPAPI with WireGuard, installer upgrades,
> the updater and more) still needs verification on more machines.

Related documents: [SYSTEM-INTEGRATION.md](SYSTEM-INTEGRATION.md) (what NOBAD touches on Windows and the network),
[FEATURES.md](FEATURES.md), [USER-MANUAL.md](USER-MANUAL.md), [CODE-SIGNING.md](CODE-SIGNING.md).

---

## 1. Overview

NOBAD VPN is a Python application with an HTML/JavaScript UI shown in a pywebview (WebView2) window. It does not
implement WireGuard itself: it drives the official **WireGuard for Windows** (`wireguard.exe /installtunnelservice`,
`wg.exe show`) and adds its own protection with **Windows Firewall rules** created through `netsh`.

```
 nobad_vpn.py / NobadVPN.exe
   boot.early_splash()          native Win32 splash (before heavy imports)
   app.main()                   CLI dispatch, elevation, single instance
     server.py  ThreadingHTTPServer on 127.0.0.1:<random port>   <-- pywebview window(s) load http://127.0.0.1:<port>/
       api.py + netintel/api_handlers.py   POST /api/<name>
       logbus.py                            GET /events (Server-Sent Events)
     engine.Tunnel             connect / verify / health / repair / failover / kill switch / DNS block
     netwatch.NetWatch         sleep and network-change detection, trusted-network rules
     netintel.agent.FixAgent   optional DNS fix agent (off by default)
     tray.Tray                 pystray icon (optional)
     window.WindowManager      main window + mini window (pywebview)
   watchdog (separate process: --watchdog <pid>)
   boot guard (scheduled task as SYSTEM: --guard)
```

Process-wide singletons live in `ctx.py` (`ctx.settings`, `ctx.tunnel`, `ctx.usage`, `ctx.smart`, `ctx.tray`,
`ctx.netwatch`, `ctx.niagent`, `ctx.windows`, `ctx.updater`). `app.init()` creates them; modules read them at call
time so the import graph stays acyclic and tests can substitute fakes.

---

## 2. Process model

### 2.1 Elevation

Creating tunnel services and firewall rules needs administrator rights. `app.main()` handles a non-elevated start in
this order:

1. If the command is not `--panic` / `--repair-network`, `autostart.launch_via_task()` tries to start an elevated
   scheduled task: first `NobadVPN Launcher`, then `NobadVPN` (start with Windows). A task is used only if its action
   matches this install (`action_matches`), so a stale task from another install location is skipped. If a window
   is wanted, the launcher creates the signalled session event `Local\NobadVPN.ShowWindow` and holds it until the
   elevated copy (started with `--background`) has reset it and shown its window (at most 15 s). No file is involved,
   so the elevated copy never deletes anything in the user's folders. This is the "no-UAC launcher".
2. Otherwise `syscmd.try_self_elevate()` re-runs the same command line with `ShellExecuteW(..., "runas", ...)`, which
   shows a UAC prompt.

The PyInstaller build is deliberately **not** built with a `requireAdministrator` manifest (`packaging/nobad.spec`),
because that would force a UAC prompt before the scheduled-task route could be used.

The launcher and boot-guard tasks are only registered for an **installed** build: a frozen exe under
`Program Files` (`autostart.installed_location()`), a folder only administrators can change. Source runs never get
these tasks.

### 2.2 Single instance and hand-off

`lifecycle.py` keeps `ProgramData\NobadVPN\instance.json` with `{port, pid, ts, token}`. The folder is restricted to
SYSTEM and Administrators, so only another elevated NOBAD can read the token.

On start, `_run_main_process()` calls `lifecycle.handoff_to_running()`:

* If the advertised PID is alive, it POSTs `/api/window` with `{"do": "show"}` (or `"noop"` for a background launch)
  to the running copy, timeout 2.5 s. If that answers `ok`, the new process exits.
* If the running copy does not answer, it is killed with `taskkill /PID <pid> /T /F` (which also ends its watchdog)
  and the new process continues.

Then `lifecycle.kill_other_instances()` (frozen builds only) uses `tasklist` to find other `NobadVPN.exe` (and legacy
`NomadTunnel.exe`) processes and kills them. Source runs skip this scan.

`lifecycle.mark_started()` records whether the previous run left `clean_exit.flag` and deletes it;
`mark_clean_exit()` writes it again on a normal shutdown. The engine, the watchdog and the boot guard all use this
marker to tell a crash from a normal exit.

### 2.3 Tray, windows and closing

* `tray.Tray` needs `pystray` and `Pillow`; without them `available` is False and NOBAD runs without a tray.
* `window.WindowManager` creates the main window hidden and reveals it on the page's `loaded` event (15 s safety
  timer). The mini window (`/mini`, 340 x 270, always on top, bottom-right of the work area) is created on first use
  and only when the tray is available.
* Closing the main window hides it instead of quitting when `close_to_tray` is on and the tray icon exists.
* When the window loop ends and `guardian` is on while a tunnel is connected or wanted, the process keeps running
  ("guarding in the background") until a quit is requested.
* If pywebview is not installed, NOBAD opens the UI in the default browser instead.
* `lifecycle.request_quit(disconnect)` sets the quit event and destroys the windows. By default the tunnel is left
  running (the WireGuard service is independent of NOBAD); with `disconnect=True` it is torn down first.

### 2.4 Watchdog

If the `watchdog` setting is on (default), `_background_start()` spawns a detached copy of itself with
`--watchdog <pid>`. `watchdog.run_watchdog()` waits for that PID to exit, then decides (`watchdog.decide`, pure and
unit-tested):

| Situation after the app exited | Action |
|---|---|
| `clean_exit.flag` present | exit |
| one of our tunnel services still running | relaunch the app (`--background`), up to 3 attempts |
| NOBAD firewall rules present, tunnel gone | relaunch up to 3 attempts; then `failopen` if `watchdog_failopen` is on, otherwise stay blocked |
| nothing left behind | exit |

A relaunch counts as successful when a new `instance.json` with a different PID appears within 45 s. "Fail open"
runs `recovery.panic_reset_system(restore_dns=True)` and shows a toast; "stay blocked" shows a toast saying internet
is blocked and that the Start-menu shortcut "Restore internet (NOBAD)" restores it.

### 2.5 Boot guard

`NobadVPN Guard` is a scheduled task that runs `NobadVPN.exe --guard` as SYSTEM about 20 s after Windows starts
(see [SYSTEM-INTEGRATION.md](SYSTEM-INTEGRATION.md#3-scheduled-tasks)). `recovery.boot_guard()` waits up to 30 s for
one of our tunnel services to come up, then applies `recovery.guard_decide()`:

* clean exit, NOBAD already running, a tunnel up, or no rules left: leave everything alone;
* rules left behind and tunnel down: if the start-with-Windows task exists and `watchdog_failopen` is off, leave the
  rules (NOBAD will re-arm or clear them after sign-in); otherwise restore internet with
  `recovery.panic_reset_system(restore_dns=True)`, which also puts back adapter DNS recorded in the change journal.

The boot guard only ever removes NOBAD's own blocking; it never adds rules.

---

## 3. Start-up sequence

`nobad_vpn.py` (and `python -m nobadvpn`) call `boot.early_splash()` before importing pywebview or the engine. The
splash (`splash.py`) is a Win32 layered window drawn from `ui/brand/splash.png`, shown only in the process that will
open a window: elevated, not a CLI flag (`--panic`, `--repair-network`, `--guard`, `--selftest`, `--version`,
`--watchdog`, `-h`, `--help`), and not `--background` unless the show flag exists. It closes when the main window is
shown, and never stays longer than 25 s.

`app.main()` dispatch order:

1. `--version` prints the version; `--watchdog` runs the watchdog; `--selftest` runs the self-test;
   `--install-tasks` registers tasks; `--guard` runs the boot guard (needs admin, otherwise exit code 2).
2. Elevation (section 2.1).
3. `--panic` / `--repair-network`: `_cli_repair()` (section 9.3), no window.
4. Otherwise `_run_main_process()`:
   1. hand-off / replace a running copy (2.2), `kill_other_instances()`, `mark_started()`;
   2. install crash hooks (`crash.install_hooks()`);
   3. `init()`: copy legacy NOMAD Tunnel data if needed, start file logging, load settings, `engine.ensure_dirs()`
      (create and lock the ProgramData folders, copy legacy configs), create `Usage`, `Smart`, `Updater`, `Tray`,
      `Tunnel`, `NetWatch`, `FixAgent`;
   4. start the loopback HTTP server on `127.0.0.1` with port 0 (random), write `instance.json`;
   5. start `NetWatch`, the tray (if the `tray` setting is on), set per-monitor DPI awareness, create the main window;
   6. spawn `_background_start()`, then run the window loop.

`_background_start()` deliberately runs everything that calls `netsh`, `schtasks` or PowerShell **after** the window
has painted (it waits for the window's reveal event, up to 12 s, then 1.5 s more):

1. `_legacy_cleanup()`: remove `Nomad*` firewall rules and the `NomadTunnel` task;
2. `tunnel.start()`: adopt a running tunnel or decide what to do with leftover rules (4.6), then start the health,
   traffic and streaming-guard threads, and spawn the server geo lookup and home-location lookup;
3. `api.auto_install_wireguard()` if WireGuard is missing (section 10);
4. connect to `last_region` if `auto_connect` is on;
5. refresh the start-with-Windows state; repair the `NobadVPN` task if it points at an old install;
6. `autostart.ensure_launcher_task()` and `autostart.ensure_guard_task()` (installed builds only);
7. `ctx.niagent.start()` (a thread that wakes every 30 min; a scan does nothing unless the agent is switched on);
8. spawn the watchdog 3 s later if `watchdog` is on;
9. send pending crash reports if the user opted in and set a URL;
10. check for updates if `auto_update_check` is on and `update_url` is set.

When the UI connects its event stream it requests `/api/state`, and about 2.5 s later calls `/api/startup_checks`
once per page load (see 7.3).

Shutdown runs, each step guarded so one failure cannot skip the rest: save window geometry, stop NetWatch, flush the
usage of the running session, stop the engine threads, stop the tray, remove `instance.json`; then
`mark_clean_exit()` if the exit was normal.

---

## 4. Module map

| Module | Responsibility |
|---|---|
| `app.py` | CLI parsing, start-up order, `init()`, background start-up, `--install-tasks`, `--panic` / `--repair-network` CLI path, legacy data migration |
| `boot.py`, `splash.py` | earliest splash decision and the native layered-window splash |
| `lifecycle.py` | `instance.json`, clean-exit marker, hand-off to a running copy, replacing stray copies, quit |
| `ctx.py` | process-wide singletons |
| `const.py` | version, paths, task names, constants and setting defaults (no side effects at import) |
| `settings.py` | versioned settings (`settings_version` 2), migration from v1, validation of every value (`coerce`), re-validation of values read from disk |
| `engine.py` | `Tunnel`: config discovery, connect/verify, runtime copies, firewall application, health loop, reconnect, failover, captive portal, panic, streaming guard, traffic and session accounting, server geo lookup |
| `firewall.py` | kill-switch and DNS-block rule maths (pure) and `netsh advfirewall` calls |
| `netinfo.py` | physical-uplink fingerprint (`route print`), IPv4/IPv6 capability, default gateway, Wi-Fi name, captive-portal check, endpoint report |
| `netwatch.py` | sleep/resume and network-change detection; trusted-network rules |
| `watchdog.py` | crash watchdog process |
| `recovery.py` | engine-independent cleanup (`panic_reset_system`), boot guard policy |
| `netjournal.py` | change journal for adapter DNS changed by the fix agent |
| `netrepair.py` | repair levels `undo`, `quick`, `full` |
| `wginstall.py` | WireGuard install chain with Authenticode checks |
| `autostart.py` | scheduled tasks: start with Windows, no-UAC launcher, boot guard; legacy task removal |
| `updater.py` | update manifest, download, SHA-256 and Authenticode checks, silent install |
| `server.py` | loopback HTTP server, token, Host/Origin checks, static whitelist, CSP, SSE |
| `api.py` | POST handlers (`/api/<name>`), setting side effects, WireGuard install work, diagnostics export, crash report endpoints |
| `logbus.py` | SSE fan-out, in-memory log ring (200 entries), rotating log file, key scrubbing |
| `notify.py` | in-app and Windows notifications (tray balloon, else a PowerShell toast); 5 s rate limit per kind |
| `tray.py` | tray icon, status dot, menu |
| `window.py` | pywebview windows, geometry memory and on-screen clamping, DPI awareness, dark title bar |
| `syscmd.py` | `run()` wrapper (no console window, below-normal priority), admin check, self-elevation, `wg_tool`, `ping_stats`, `probe_endpoint`, `run_once` busy keys |
| `confparse.py` | WireGuard config parsing, validation, redaction, tuned runtime copy |
| `configstore.py` | config files: list, view, save, delete, import (file, URL, QR text), DPAPI conversion |
| `dpapi.py` | Windows DPAPI (machine scope) encrypt/decrypt, atomic write, best-effort wipe |
| `smart.py` | learned server ranking (latency by time of day, per-service blocking, failure penalty) |
| `usage.py` | usage history (daily, per server, sessions, speed tests) |
| `tools.py` | exit-IP lookup, service reachability, speed test, network check, game and VALORANT probes |
| `crash.py` | local crash/error reports, optional sending |
| `diagnostics.py` | diagnostics zip with keys removed |
| `selftest.py` | `--selftest` report |
| `netintel/` | Network Intelligence engine (section 8) |
| `ui/` | `index.html`, `app_ext.js`, `netintel.js`, `mini.html`, CSS, `brand/`, `vendor/jsqr.js` |

---

## 5. Engine (`engine.Tunnel`)

### 5.1 Configs

`rescan()` lists `ProgramData\NobadVPN\configs` for `<name>.conf` and `<name>.conf.dpapi` (the encrypted copy wins if
both exist). Names must match `^[A-Za-z0-9_=+.\-]{1,32}$`. Each config is parsed for the first peer's endpoint, the
interface addresses, whether it routes `0.0.0.0/0` / `::/0`, and whether it has a DNS line.

### 5.2 Connect

`connect(name)` takes the connection lock without waiting (a second request while one runs is refused and logged).
`_connect_locked()`:

1. Checks that `wireguard.exe` exists (error `wg_missing`) and that the process is elevated (error `not_admin`).
2. Reads the config (DPAPI-decrypted if needed) and runs `validate_conf`; validation errors are logged.
3. Sets `want = True`, cancels any captive-portal waiter, tears down a previous NOBAD tunnel and uninstalls a stale
   service of the same name.
4. Decides the runtime options: streaming tune (`stream_tuned`: add `MTU = 1380` and `PersistentKeepalive = 25` if
   absent), fallback DNS (when `dns_leak_block` and `force_tunnel_dns` are on and the config has no DNS line), and the
   endpoint IP.
5. **Resolves the endpoint before arming any rule.** A hostname endpoint is resolved and pinned as an IP in the runtime
   copy, because once the DNS block or kill switch is armed WireGuard might not be able to resolve it. Results are
   cached for 300 s in memory and kept in `endpoints.json`; if a fresh lookup fails, the last known address is reused.
   The address family the uplink can actually use is tried first.
6. Applies the firewall rules (`_fw_apply`, section 6).
7. Tries candidates in order until the service reaches `RUNNING` (polled for up to 15 s, `SERVICE_WAIT`):
   encrypted runtime copy (`.conf.dpapi`, only for an encrypted config while `dpapi_runtime_ok` is on), then a
   plaintext runtime copy, then an untuned copy of the config text (only for a non-encrypted config). WireGuard is never
   handed the stored file: every candidate is written from the text read and validated in step 1. Runtime copies go to
   `ProgramData\NobadVPN\runtime`, whose ACL is SYSTEM + Administrators only. If WireGuard refuses the encrypted copy
   but a later candidate works, `dpapi_runtime_ok` is switched off for future connects.
8. If no candidate starts, `_diagnose()` collects evidence (`sc query WireGuardTunnel$<name>` state and exit code, the
   last lines of `wireguard.exe /dumplog`) and the attempt fails with `start_failed`.
9. **Handshake check** (`_verify`, up to 14 s): pings the health target once per loop (which also triggers the
   handshake) and reads `wg.exe show <name> latest-handshakes`; success is a non-zero handshake time. Without
   `wg.exe` it falls back to "the ping got any reply". Failure: error `handshake`, with the captive-portal check.
10. On success: `connected = True`, `last_region` saved, the result recorded for smart ranking, a notification sent,
    and an exit-IP lookup started if `ip_lookup` is on.

Failures go through `_fail()`, which uninstalls the service, removes the runtime copy, and decides about the
firewall rules: a **first, manual** connect that fails releases the rules unless the strict kill switch is on; a
reconnect after the tunnel had been up (`want and _was_up and not giveup`) keeps them. Errors are pushed to the UI as
`error_action` events carrying action buttons (Retry, Check endpoint, Install WireGuard, Relaunch as administrator,
Edit config, Restore internet, Open sign-in page, Show log, Dismiss).

A panic reset during a connect bumps `_panic_gen`; the in-flight connect notices and aborts instead of re-arming.

### 5.3 Health checks, auto-repair and failover

`_health_loop()` runs every 8 s (`HEALTH_SEC`) while a tunnel is wanted.

**While connected** it pings the health target 3 times. The health target is `1.1.1.1` (or `2606:4700:4700::1111`
for an IPv6-only config) for full tunnels. For split tunnels, where a public address would leave outside the tunnel
and be dropped by the kill switch, it uses the config's DNS server if it is inside the routed networks, else the first
host of the first routed network. Loss of 50 % or more counts as a bad check; after 2 bad checks in a row
(`FAIL_THRESHOLD`), if `auto_repair` is on, NOBAD reconnects the same server, up to 2 times (`MAX_REPAIR`), and then
fails over.

**While the tunnel is down but wanted** (it was up before, `auto_repair` on, not given up), it retries with backoff
`min(120, 8 * 2^min(n-1, 4))` seconds. Attempts 1 and 2 reconnect the same server; from attempt 3 on, if there is more
than one server, it fails over. After 8 attempts (`RECONNECT_TRIES`) it gives up: with the kill switch on (strict or
not) the rules stay and an error explains that traffic is still blocked until the user chooses Restore internet or
Disconnect; with the kill switch off, the DNS block is removed and the user is told they are online **without** the VPN. A later network change or a manual connect starts over.

**Failover** (`_failover`) tears down the tunnel, probes every server, and picks the best smart-ranked server other
than the current one (if `smart_select` is on), else the lowest measured latency, else the next server in the list.

Probing (`probe_all`, up to 8 in parallel) pings each endpoint 3 times; if ICMP gets no answer it times a TCP connect
to port 443, then 80, and marks the result as an estimate. While connected, results for servers other than the active
one are marked as estimates and are not used for learning. **Fastest** and **Smart pick** drop the tunnel briefly
(firewall rules stay) so all servers are measured from the same uplink.

### 5.4 Smart ranking (`smart.py`)

* Latency: exponential moving average (alpha 0.3) per server and per 4-hour block of the day.
* Services: a failed service check marks the server blocked for that service for 24 h.
* Failures: 60 ms penalty per recorded failure, fading linearly over 24 h; a success clears it.
* Score (lower is better): `0.6 * live + 0.4 * learned` when both exist, otherwise whichever exists, otherwise 500
  (never measured servers are tried after known-good ones).

### 5.5 Reconnect on network change and sleep

`NetWatch` registers `NotifyUnicastIpAddressChange` and `NotifyRouteChange2` (iphlpapi) so it sleeps until Windows
reports a change; if registration fails it polls. While a tunnel is wanted it also ticks every 5 s, only to notice a
wall-clock jump of more than 25 s (the machine slept). After an event it waits 3 s for DHCP/Wi-Fi to settle.

The "network" is a fingerprint of the physical default routes (`route print -4 0.0.0.0` and `route print -6`, gateway
and interface, excluding the tunnel's own addresses), plus the Wi-Fi name when trusted-network rules are on. On a
change or resume, if `reconnect_on_network_change` is on and a tunnel is wanted:

* no network: the tunnel stays idle/blocked with the note "Network lost";
* otherwise `reconnect_clean()`: uninstall the tunnel service **without removing the firewall rules**, wait up to 45 s
  for a network, then connect again.

Registered listeners (the fix agent's `on_network_change`) are called on every change as well.

### 5.6 Start-up adoption

`_adopt()` runs under the connection lock when the engine starts:

* If a tunnel service for one of the configs is running, NOBAD attaches to it and re-applies the firewall rules.
* Otherwise leftover runtime copies are deleted. If NOBAD rules are still present, they are **kept** and the last
  server is reconnected when the kill switch is on, `last_region` exists, and either strict mode is on or the
  previous run crashed and `watchdog_failopen` is off. In every other case the stale rules are removed.

### 5.7 Captive portals

When the handshake fails, `_fail(..., captive_check=True)`:

* **Normal kill switch:** removes the rules (a portal page cannot load through them) and runs `netinfo.captive_check()`:
  a plain-HTTP GET to `http://www.msftconnecttest.com/connecttest.txt` (expects 200 and `Microsoft Connect Test`);
  only if that host cannot be reached at all, `http://connectivitycheck.gstatic.com/generate_204` (expects 204).
  Redirects are not followed. If the answer is not the expected one, the UI shows "Wi-Fi sign-in required" with **Open sign-in page** (the portal's `Location`
  header if it is http(s), otherwise `http://neverssl.com`). A waiter checks every 4 s for up to 10 minutes and
  reconnects once the check passes.
* **Strict kill switch:** never pauses; the error explains that the sign-in page is blocked too and offers Restore
  internet.

### 5.8 Streaming guard

If `guard_service` names a service (Netflix, YouTube, Disney+, Prime Video, Spotify, Twitch), `_guard_loop` checks it
through the tunnel about 20 s after each connect and then every 30 min. If the service fails, a Cloudflare baseline
request decides whether the tunnel itself is the problem. A blocked result is recorded in `smart.json`; with
`guard_auto_switch` on, NOBAD tries up to 3 other servers ranked as clear for that service.

### 5.9 Traffic and usage

`_traffic_loop` reads `wg.exe show <name> dump` every 2 s while a UI is subscribed, otherwise every 30 s, and feeds
bytes into `usage.json` as they arrive (so totals survive a crash). Sessions are logged on teardown. History limits:
400 days, 500 sessions, 200 speed tests.

### 5.10 States as the UI sees them

| `state()` field | Meaning |
|---|---|
| `connecting` | name being connected, or null |
| `connected`, `active`, `since` | tunnel up and verified |
| `ks_active`, `dns_active` | kill-switch / DNS-block rules confirmed armed |
| `fw_off` | rules exist but Windows Firewall is off on at least one profile |
| `giveup` | auto-reconnect gave up |
| `note` | e.g. "Network lost — waiting for it to return" |
| `error` | last error with actions |

The tray icon reduces this to four states: connecting (amber), connected (green), not connected but kill switch
blocking (red), off (grey).

---

## 6. Kill switch and DNS leak block

Both are outbound **block** rules in Windows Firewall (`netsh advfirewall firewall add rule ... dir=out
action=block enable=yes profile=any`). The rule maths in `firewall.build_rules()` is pure and unit-tested.

| Rule name | Protocol | Local IP (source) | Remote IP / port |
|---|---|---|---|
| `NobadKS4` | any | every IPv4 address except the tunnel's own addresses and `127.0.0.0/8` | every IPv4 address except LAN ranges and the endpoint IPs |
| `NobadKS6` | any | every IPv6 address except the tunnel's own addresses and `::1` | every IPv6 address except LAN ranges and the endpoint IPs |
| `NobadDNS4U` / `NobadDNS4T` | UDP / TCP | every IPv4 address except the tunnel's | port `53,853`, any address |
| `NobadDNS6U` / `NobadDNS6T` | UDP / TCP | every IPv6 address except the tunnel's | port `53,853`, any address |

LAN ranges excluded from the kill switch: `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `169.254.0.0/16`,
`224.0.0.0/4`, `127.0.0.0/8`, `255.255.255.255/32`, `fe80::/10`, `fc00::/7`, `ff00::/8`, `::1/128`. "Every address
except X" is computed exactly as a list of CIDR blocks (`firewall.complement`). The endpoint IPs of **all** configured
servers are excepted, so probing and reconnecting to another server keeps working while blocked. The DNS rules have no
remote-address exception: DNS to a LAN resolver (e.g. the router) outside the tunnel is blocked too.

Behaviour:

* Rules are applied **before** the tunnel service starts, and updated in place with `netsh ... set rule` when they
  already exist (no unprotected gap). Stale NOBAD rules not in the new set are deleted.
* Which rules exist is read from **one** `netsh advfirewall firewall show rule name=all dir=out` listing; if that
  fails, NOBAD falls back to one query per rule.
* The DNS block is skipped (and the log says why) when the config has no DNS line and no fallback DNS was injected,
  because it would break name lookups.
* A config without an `Address` line cannot be protected; the kill switch is reported as not armed.
* At most once a minute NOBAD reads `netsh advfirewall show allprofiles state`. If any profile is off, the rules are
  reported as **not enforced** (`fw_off`), with a red banner and a notification. Unreadable (localized) output is
  treated as unknown, not as off.
* DNS-over-HTTPS on port 443 is not covered by the DNS rules; only the kill switch blocks it.

When the tunnel is down, the rules stay only while the kill switch is "holding": strict mode, or a reconnect after
the tunnel had been up (not given up). Otherwise turning either setting off, a manual disconnect, or a failed first
connect removes them.

---

## 7. Loopback HTTP API and UI event flow

### 7.1 Server security (`server.py`)

* Bound to `127.0.0.1` on a random port (port 0).
* **No secret in any page.** Two random values are made on every launch (`secrets.token_urlsafe(24)`):
  * `TOKEN`, for NOBAD's own processes only. It is written to the admin-only `instance.json` and sent in the
    `X-Token` header (single-instance hand-off, `lifecycle.py`).
  * `SESSION`, the UI windows' cookie. NOBAD opens each window with a **one-time launch code**
    (`server.launch_url`, valid 10 minutes, usable once). `GET /?k=<code>` answers `303` with
    `Set-Cookie: nobad_s=<SESSION>; HttpOnly; SameSite=Strict` and redirects to the clean URL. The page's `fetch`
    and `EventSource` calls send the cookie automatically, so JavaScript never sees a secret.
  * Both are compared with `hmac.compare_digest`. Secrets in query strings (`?t=`) are no longer accepted.
* **Host and Origin checks** (DNS-rebinding and cross-site protection): every request must have
  `Host: 127.0.0.1:<port>` or `localhost:<port>`; an `Origin` header, if present, must be
  `http://127.0.0.1:<port>` or `http://localhost:<port>`.
* **Unauthenticated routes:** `/favicon.ico`, `/static/...`, `/si/img/...`, `/api/ping`. `/` and `/mini` without a
  valid launch code or session cookie return a locked page (`403`) with nothing secret in it. Everything else
  (`/api/state`, `/events`, every POST) requires the cookie or the `X-Token` header.
* **Static whitelist:** `/static/<path>` must match `^[A-Za-z0-9_\-]+(/[A-Za-z0-9_\-]+)*\.(js|css|json|svg|png|ico)$`
  and resolve inside `nobadvpn/ui`. HTML files cannot be fetched through `/static/`.
* Responses carry `Cache-Control: no-store` and `X-Content-Type-Options: nosniff`; HTML pages also get a
  Content-Security-Policy (`default-src 'self'`, `connect-src 'self'`, `frame-ancestors 'none'`, `form-action 'none'`
  and others; inline scripts and styles are allowed).
* POST bodies are capped at 400,000 bytes; rejected POSTs still read the body so the client receives the status code.

### 7.2 Handlers

`api.HANDLERS` (plus `netintel.api_handlers.HANDLERS`) map `/api/<name>` to a function. Anything slow is started with
`syscmd.run_once(key, ...)`, which refuses a second run with the same key ("already running") and broadcasts
`task_done` when it finishes. Setting changes go through `settings.coerce()`, which rejects unknown keys and
`settings_version` / `dpapi_runtime_ok`, and validates types, IP lists and `https://` URLs.

### 7.3 Events

`logbus.broadcast(type, payload)` puts a JSON message on every subscriber queue (300 messages each; overflow is
dropped). `/events` streams them as Server-Sent Events with a keep-alive comment every 15 s.

* `Tunnel.push()` broadcasts a full `state` snapshot (connection fields, settings, servers with ping and geo, admin,
  WireGuard presence, recent sessions, recent log, and extra keys from `api.extra_state()`: tray, autostart, update
  state, pending crash reports, network name) and refreshes the tray.
* Other events: `log`, `health`, `traffic`, `probe`, `ipinfo`, `speed`/`speed_done`, `stream_start`/`stream`/
  `stream_done`, `network_diagnose`, `valorant_start`/`valorant_result`/`valorant_done`, `gaming_probe`,
  `endpoint_report`, `error_action`, `notify`, `fix_result`, `update`, `guard`, `task_done`, `net_repair_start`/
  `net_repair_done`, and the Network Intelligence events `ni_overview`, `ni_progress`, `ni_investigation`,
  `ni_lookup`, `ni_vpn`, `ni_fix`.

The UI (`index.html`, then `app_ext.js` and `netintel.js` which chain their `handle()` functions) applies `state` to
the DOM and appends results as events arrive. On (re)connecting the event stream it fetches `/api/state`. Once per page
load it calls `/api/startup_checks`, which always runs the quick network check and the exit-IP lookup (the lookup
respects `ip_lookup`); the speed test, service checks and VALORANT checks are added only when `startup_checks` is on.

---

## 8. Network Intelligence engine (`nobadvpn/netintel/`)

### 8.1 Design rules

* **On demand.** Nothing polls in the background. Work starts from a button, from opening the Intel tab (the overview
  runs once automatically), or from the fix agent when it is switched on.
* **Evidence, not assumptions.** No ISP, resolver or domain is hardcoded as "the censor". Resolvers are discovered at
  run time; independent reference resolvers come from the editable `ni_reference_dns` setting (default
  `1.1.1.1, 8.8.8.8, 9.9.9.9, 2606:4700:4700::1111, 2001:4860:4860::8888`, at least two, at most eight).
* **Every finding** carries `kind`, `layer` (dns, tcp, tls, http, ipv6, routing, vpn, local, network), `severity`,
  `confidence` (0-1, with label high >= 0.8, medium >= 0.55, otherwise low), the evidence lines, contradicting
  evidence and recommendations.
* **Confidence** for DNS filtering is `1 - prod(1 - w)` over the weighted signals found, minus 0.25 per piece of
  contradicting evidence, clamped to 0.05-0.99. Signals include: NXDOMAIN while independent resolvers answer (0.45),
  a CNAME to a different registrable domain (0.35), policy words in that target (0.35 for an `rpz` label, else 0.22),
  non-public answer addresses (0.40), no overlap with independent addresses (0.15, or 0.07 if the independents
  disagree among themselves), an address already seen as a sinkhole on this network (0.25), and addresses that do not
  present a valid certificate for the name while the independent ones do (0.45). At 0.3 or more the finding is
  "dns-filtering", below that "dns-divergence".
* **Operator attribution** only with evidence: the filtering is linked to the user's provider only when a token from
  the provider's name (exit-IP lookup `org` field or the reverse DNS of the public IP, only while not connected)
  matches a token from the redirect target or the sinkhole's reverse DNS. Generic words are ignored.

### 8.2 Components

| File | Role |
|---|---|
| `dnswire.py` | minimal DNS wire client (UDP with TCP fallback on truncation, TCP, DoH POST per RFC 8484). Validates ID and question; never raises on network errors. Unit-tested against crafted packets and local sockets. |
| `system.py` | one PowerShell call (on demand) that lists adapters, addresses, gateways, routes, DNS servers (configured, DHCP-offered, static from the registry), DoH templates, domain membership and NRPT rule count. The NOBAD tunnel adapter is recognised by the active tunnel's name. |
| `probes.py` | TCP connect, TLS handshake with the real SNI (and an unverified second handshake only to report what certificate was presented), SNI-filter comparison against the neutral name `nobad-sni-control.invalid`, one HTTP GET, Windows resolution (`getaddrinfo`), and the DNS interception test. |
| `dnsintel.py` | resolve the same name across resolver groups in parallel, build the independent consensus, produce DNS findings. |
| `investigate.py` | orchestration: `overview()`, `investigate_site()`, `vpn_integrity()`, verdicts and recommendations. |
| `history.py` | local history and per-network baselines (section 8.4). |
| `agent.py` | the smart fix agent (section 8.5). |
| `api_handlers.py` | `/api/ni_*` handlers; keeps the last 10 investigations in memory so a fix acts on a measured investigation, never on raw input. |

Resolver groups: **network** (offered by DHCP on the uplink), **configured** (what Windows uses on the uplink and the
tunnel), **reference** (the independent list, minus any already in use), **encrypted** (DoH templates that Windows
itself has registered for the reference servers, at most two).

The **interception test** sends real DNS queries for `example.com` to `192.0.2.53` and `198.51.100.53` (and
`2001:db8::53` when IPv6 is available), documentation addresses where no server can exist. Any answer means something
on the path intercepts DNS.

### 8.3 Entry points

* **Overview:** resolver health (root `NS` query, plus two random non-existent names to detect NXDOMAIN rewriting),
  interception test, multiple default routes, IPv6 inconsistency, and changes against the network's baseline.
* **Investigate a site:** normalise the input to a hostname (IP addresses are refused), compare resolvers, run the
  interception test and Windows resolution alongside, probe TLS for suspect and consensus addresses, then TCP 443 (and
  80) reachability, SNI filtering, HTTP 451, broken IPv6, and whether apps on this PC actually receive the filtered
  answer (`affected`). The verdict is the most serious finding kind in a fixed priority order.
* **DNS lookup:** any of A, AAAA, CNAME, MX, TXT, NS, SOA against every resolver, raw records shown.
* **VPN integrity** (only while connected): tunnel adapter present, which local address IPv4 and IPv6 leave from
  (a UDP socket connect to a reference resolver), IPv6 leak risk, direct DNS to the network's own resolvers (a reply
  means a DNS path outside the tunnel), tunnel without DNS, and recent NetWatch transitions.

### 8.4 History and baselines

Stored in `ProgramData\NobadVPN\netintel\` only while `ni_history` is on (default on): `history.jsonl` (last 400
entries), `baselines.json` (per network: gateways, DNS, suffix, IPv6, DNS latency as a moving average with alpha
0.25), `sinkholes.json` (addresses that answered for filtered names, per network). A network key is the first 16 hex
characters of a SHA-256 over the uplink's gateways, DHCP-offered DNS and media type; no SSID or MAC is stored. The
History pane's **Clear** deletes the three files.

### 8.5 Smart fix agent

Authorisation: nothing is changed unless the user clicks **Fix DNS safely** on an investigation (with a
confirmation), or switched `ni_autofix` on (off by default). A fix:

1. **Preflight** refuses when DNS filtering (confidence >= 0.55 manual, >= 0.8 automatic) or a failing resolver was
   not found; when Windows already gets the real address; when the site is also SNI-filtered or IP-unreachable; when
   DNS is intercepted; when NOBAD is connected; on a domain-joined PC; with NRPT rules; when the network provides a
   DNS suffix; with an active captive portal; or with no active adapter.
2. **Plan:** reference resolvers that returned the consensus address, fastest first, up to two IPv4 (required) and
   two IPv6 (only if the adapter has global IPv6).
3. **Canaries:** up to 10 names from the Windows DNS cache that resolve right now.
4. **Apply:** the adapter's current DNS (static lists from the registry; empty means automatic) is written to the
   change journal **first**, then `Set-DnsClientServerAddress` and `Clear-DnsClientCache`.
5. **Verify:** the site resolves to a consensus address, every canary still resolves, and the router still answers
   ping if it did before. Any failure rolls back from the journal.

A successful fix is remembered per network (`fix_profiles.json`). On a network change the agent restores the original
DNS for fixes made on another network, and, if the agent is on, re-applies a remembered fix on its own network (same
checks). In autonomous mode it also scans the Windows DNS cache every 30 minutes for CNAMEs with policy words or
known sinkhole addresses and investigates them.

---

## 8b. Streaming Region Intelligence (`nobadvpn/streamintel/`)

A separate package that only reads engine state (`tunnel._regions`, `geo`, `pings`, `home`, `smart` service
history) and connects through the existing `/api/connect`. Handlers live in `streamintel/api_handlers.py`
(`si_*`). Results come back as the events `si_title`, then `si_restrictions` and `si_verify`. Posters are served by
`GET /si/img/<size>/<file>`, a validating, caching proxy, so the UI's CSP stays `img-src 'self'`. Sources, honesty
rules, scoring, caching and configuration are documented in [STREAMING-INTELLIGENCE.md](STREAMING-INTELLIGENCE.md).
Tests: `tests/test_streamintel.py` (all HTTP faked per URL).

## 9. Fail-safe design

### 9.1 Change journal (`netjournal.py`)

`ProgramData\NobadVPN\netchanges.json` holds every Windows network change NOBAD makes outside its own tunnel services
and firewall rules. Today that is only adapter DNS (and any DoH registration recorded as `doh_added`) changed by the
fix agent. The original value is recorded **before** the change; writes are atomic (temp file + replace). Restoring
puts the static DNS list back (or resets to automatic), removes only DoH registrations NOBAD added, and clears the DNS
cache. A restore whose adapter no longer exists counts as done; real failures stay in the journal for the next reset.
The current code never sets `doh_added`, so in practice only DNS server lists are journaled.

### 9.2 Repair levels (`netrepair.py`)

| Level | Steps (each reports the real exit code) |
|---|---|
| `undo` | remove every NOBAD firewall rule (and legacy `Nomad*` rules), uninstall NOBAD tunnel services, delete runtime copies, restore every journaled DNS change |
| `quick` | `undo` + `ipconfig /flushdns`, `ipconfig /registerdns`, `netsh interface ip delete arpcache`, `ipconfig /renew` (a non-zero `/renew` mentioning DHCP is not counted as a failure) |
| `full` | `quick` + `netsh winsock reset`, `netsh int ipv4 reset`, `netsh int ipv6 reset`, `netsh winhttp reset proxy`; a restart is needed |

`recovery.panic_reset_system()` only uninstalls tunnel services whose names belong to NOBAD (current or legacy config
folders, runtime copies, or names the running engine knows); tunnels created in the WireGuard app are left alone.

### 9.3 Entry points

| Entry point | Level |
|---|---|
| In-app panic button, tray "Restore internet (panic reset)", banners | engine `panic_reset()` (= `undo`) |
| Intel tab "Fix my internet" card, Settings → Network safety | `undo`, `quick` or `full` (confirmed first) |
| Tray "Repair network (quick)" | `quick` |
| Start menu "Restore internet (NOBAD)" | `--panic --show-result` (`undo`) |
| Start menu "Repair network (NOBAD)" | `--repair-network quick --show-result` |
| Uninstaller | `--panic` |
| Watchdog fail-open, boot guard | `recovery.panic_reset_system(restore_dns=True)` (`undo` without the engine, journal included) |

The CLI path needs admin rights. If a NOBAD instance is alive, it forwards the request to the running engine
(`/api/net_repair`) so auto-repair cannot fight the reset; otherwise it does the work itself without starting the
engine, prints one line per step, and with `--show-result` shows a message box.

### 9.4 Other guards

* Key material never reaches logs, toasts, crash reports or diagnostics (`logbus.scrub` replaces `PrivateKey` /
  `PresharedKey` values; diagnostics also remove the real key values found in the configs).
* Configs imported from a URL or QR code may not contain `PreUp`, `PostUp`, `PreDown` or `PostDown`.
* Config names are restricted so they cannot become paths (`..`, separators and drive letters are rejected).
* Settings read from disk are validated like values from the UI; invalid values fall back to defaults.

---

## 10. WireGuard install chain

`wginstall.install()` (WireGuard version pinned as `WG_VERSION = "1.1.1"`, kept in sync with `build.ps1`):

1. If `wireguard.exe` already exists in `C:\Program Files\WireGuard` (or `Program Files (x86)`, or on PATH): done.
2. The bundled MSI `{app}\redist\wireguard-<arch>.msi` (arch from `IsWow64Process2`: `amd64` or `arm64`).
3. The official MSI downloaded over HTTPS from
   `https://download.wireguard.com/windows-client/wireguard-<arch>-1.1.1.msi` into `ProgramData\NobadVPN\updates`
   (64 MB cap; the file is deleted afterwards).
4. `winget install --id WireGuard.WireGuard -e --silent ...` as a last resort.

Before `msiexec /i <msi> /qn /norestart DO_NOT_LAUNCH=1` runs, each MSI must have an Authenticode status of `Valid`
and a signer subject starting with `CN=WireGuard LLC,` (read with `Get-AuthenticodeSignature`). Exit codes 0 and 3010
count as success. Triggers: the installer (its own copy of step 2), the **Install WireGuard** button, and the
start-up check when `auto_install_wg` is on (default) and NOBAD is elevated.

`build.ps1` downloads the same two MSIs and refuses to bundle them unless they pass the same signature check.

---

## 11. Updater signature verification (`updater.py`)

Inert until `update_url` is set (empty by default). Steps:

1. Fetch the manifest over HTTPS (64 KB cap, a UTF-8 BOM is tolerated). It must contain a numeric `version`, an
   `https://` `url` and a 64-hex `sha256`; `notes` is optional (2000 characters max).
2. Offer it only if the version is higher than `APP_VER` (numeric tuple comparison).
3. Download to `ProgramData\NobadVPN\updates\NobadVPN-Setup-<version>.exe`, hashing as it downloads. A SHA-256
   mismatch deletes the file.
4. Read the Authenticode status, subject and thumbprint. Accept only if the status is `Valid` **and** either the
   subject is in `UPDATE_SIGNER_SUBJECTS` / the thumbprint is in `UPDATE_SIGNER_THUMBPRINTS` (both empty by default
   in `const.py`), or, with no pins, the subject equals that of the running, validly signed `NobadVPN.exe`. An
   unsigned running build therefore refuses every update.
5. Run the installer with `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS` and
   quit the app (the tunnel keeps running). The installer's silent-mode `[Run]` entry starts `NobadVPN.exe
   --background` again.

---

## 12. Data files

See [SYSTEM-INTEGRATION.md](SYSTEM-INTEGRATION.md#2-files-and-folders) for the full list with contents. In short,
everything lives in `C:\ProgramData\NobadVPN` (or `NOBAD_DATA_DIR`): settings, configs, runtime copies, logs, usage,
smart data, endpoint and geo caches, instance file, clean-exit marker, change journal, Network Intelligence history,
crash reports, exports and update downloads. JSON stores are written atomically (temp file + `os.replace`).

---

## 13. Testing strategy

`python -m pytest tests` (also run by `build.ps1` together with `pyflakes`).

* **Fake Windows.** `tests/conftest.py` sets `NOBAD_DATA_DIR` to a temp folder and provides `FakeWin`, a stand-in for
  `syscmd.run` that understands `wireguard.exe /installtunnelservice` and `/uninstalltunnelservice`, `sc query`,
  `wg.exe ... latest-handshakes`, and `netsh advfirewall firewall add/set/delete/show`. It records every command,
  keeps installed services and rule names in memory, and can be told to reject DPAPI runtime copies or fail
  handshakes. The `win` fixture patches it into `syscmd`, `engine`, `firewall`, `netinfo` and `recovery`, fakes admin
  rights, ping and endpoint resolution, and disables real ACL changes and IP lookups.
* **Pure logic** is tested directly: firewall rule maths, config parsing and validation, route and SSID parsing,
  settings migration and validation, smart ranking, usage history, watchdog and boot-guard decisions, NetWatch with a
  fake clock and fake fingerprints, DNS wire format (crafted packets, compression loops, truncation, spoofed
  datagrams, TCP fallback on local sockets).
* **Engine flows** against `FakeWin` (`test_engine.py`, `test_reliability.py`): arming and cleanup, DNS fallback,
  strict mode, captive portal, DPAPI fallback, clean reconnect, give-up, crash adoption, firewall-off detection,
  split-tunnel health target, panic during connect.
* **Server security** (`test_server.py`): launch codes, session cookie, locked page, import hooks refused, token, CSP, DNS-rebinding Host check, cross-origin POST, static whitelist and
  traversal, config-name escape.
* **Release and packaging** (`test_release.py`, `test_netsafety.py`): hand-off, splash decision, scheduled-task XML
  parsing and matching, WireGuard install order and signer checks, update signature policy, manifest BOM handling,
  ASCII-only packaging files, installer contents (shortcuts, tasks, uninstall), UI JavaScript syntax (with Node, if
  installed) and static checks of the UI frame budget.

Not covered by unit tests: the Network Intelligence analysis modules (`dnsintel.py`, `investigate.py`, `agent.py`,
`system.py`) have no dedicated tests in `tests/`; only `dnswire.py` does. Nothing in the suite runs a real tunnel,
real firewall rules or a real WebView2 window; those are verified manually on real PCs.
