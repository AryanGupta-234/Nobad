# Changelog

All notable changes to NOBAD VPN. Versions follow [semantic versioning](https://semver.org/).

## 1.3.3 · 2026-11-13

### Added
- **Report a problem** (Settings, the Ctrl+K palette, and a *Report it* button on the "NOBAD closed unexpectedly"
  notice): saves a diagnostics zip with private keys removed, shows it in File Explorer, and opens a pre-filled bug
  report on GitHub in your browser. You attach the zip and submit; NOBAD itself sends nothing. The pre-filled report
  only carries the app version, Windows version, how many crash reports were saved and the zip's name.
- **Crash reports are part of the diagnostics zip**, so a bug report includes the error and where it happened.

### Security
- **Diagnostics hide your home folder and Windows user name**, as crash reports already did (for example in the
  log line that records where a zip was saved).

### Changed
- **Minimize, close and restore animate.** The window fades and shrinks slightly before it minimizes or closes,
  and settles back in when it comes back (opacity and transform only; off when Windows asks for reduced motion).
  The custom title bar has no native caption, so Windows itself doesn't animate it.
- **Light theme gets depth too.** Side-panel cards are translucent white over a softly tinted panel, and the
  floating panels over the map and the top bar are translucent, like the dark theme. No blur, so it stays light.

## 1.3.2 · 2026-11-13

### Added
- **Free servers guide** in the Servers tab: how to get free WireGuard servers from Proton VPN Free (several
  countries, from your own free account) with buttons that open Proton's pages in your browser and import the
  downloaded files in one go, and why Cloudflare WARP needs Cloudflare's own app. NOBAD never ships configs: a
  shared config would give every user the same private key.

## 1.3.1 · 2026-11-13

### Changed
- **Where to watch is readable again.** With Visual effects off (the default) the window was see-through, so the
  map and side panel showed through the results. It is now a mostly solid sheet over a darker backdrop; with
  effects on, the frosted blur stays, a little more opaque.
- **Night on the map is visible.** The night side is shaded in cool indigo over land and sea, with a soft amber
  dusk/dawn band, and the day side is slightly warm, matching the "night · live" legend.
- **Map pins show their ping colour.** NOBAD pings your own servers shortly after start and every 5 minutes, so the
  green / amber / red colours from the legend appear without opening the Servers tab. The connected server keeps
  its green ring around its ping colour, and the legend explains grey ("not tested").
- **A clearer light theme.** Cool grey page and side panel, white cards with a visible edge and soft shadow, tinted
  inner tiles, darker text, and ping labels that are readable on white.
- **Quick view server list follows the theme.** The dropdown had a see-through background, so Windows drew its
  list in the wrong colours. It now uses solid theme colours and a crisp arrow, in dark and light.
- **Sharper on high-DPI screens.** NOBAD declares per-monitor DPI awareness (v2) as the very first step, before
  any window, also when it starts in the background, so Windows never scales it as a blurry bitmap.
- **Taskbar click minimizes NOBAD,** like other apps: clicking its taskbar button while it is in front now
  minimizes it, and clicking again brings it back. Win+Down and the minimize animation work too. (The custom title
  bar's window lacked the style bits Windows looks for.)
- **Lighter, smoother side panel.** Frosted-looking cards from static gradients (no blur cost), hover that only
  moves the card, and pointer effects updated at most once per frame instead of on every mouse event.

## 1.3.0 · 2026-11-13

### Changed
- **Start with Windows is off by default.** The installer box is unticked on a new install; turn it on there or in
  Settings. An update no longer switches it off when the box is left unticked.
- **Code: engine.py is split (#8).** The kill switch and DNS block moved to `protection.py`, and the panic reset and
  start-up takeover to `failsafe.py`. Nothing changes in how NOBAD behaves.

### Security
- **The kill switch no longer gives up (#14).** After 8 failed reconnects NOBAD used to remove the blocking rules
  unless the strict kill switch was on, so someone who blocked the VPN's traffic could get yours outside the
  tunnel. It now keeps blocking until you choose Restore internet or Disconnect.
- **Trusted networks check more than the name (#15).** A Wi-Fi network with your home network's name, or any network
  cable, used to switch the VPN off. NOBAD now also checks the router and, when Windows shows them, the Wi-Fi security
  type and access point. A mismatch keeps you protected and asks you to confirm in Settings; open Wi-Fi is never
  trusted. Networks trusted in an older version need one confirmation.
- **The app window runs no inline scripts (#7).** The page scripts moved into their own files and the window's
  security policy no longer allows inline scripts, so injected script code can't run even if a bug let it in.
- **No admin file operations in your user folders that a link could redirect (#20).** The normal launcher now asks
  the admin copy to show its window through a Windows event instead of a file in `%LOCALAPPDATA%` that the admin
  copy deleted. Diagnostics exports find your Desktop or Downloads through Windows (not environment variables), skip
  a folder that is a link, and never replace an existing file.
- **Leftover runtime configs are wiped (#21).** Copies left behind by a crash or power cut are overwritten before
  they are deleted, the same as on a normal disconnect.
- **Windows tools are started by full path (#19).** NOBAD runs with admin rights and used to find netsh, PowerShell,
  schtasks and the rest by name, which searches folders a normal user can change. They now always come from
  System32, WireGuard only from Program Files, and the installed app refuses to run any other program by name. The
  last-resort winget install of WireGuard is skipped in the installed app for the same reason; the bundled and
  downloaded installers (both signature-checked) still work.
- **Crash reports and logs hide raw keys (#18).** A WireGuard key that appeared without a "PrivateKey =" label, for
  example inside an error message, could end up in a crash report. Any text shaped like a key is now hidden (a
  labelled public key is kept), and crash reports also remove the real key values found in your configs.
- **Stricter checks on every setting (#17).** On/off settings must be true or false (the text "false" used to
  count as on), text settings must be text with a length limit, update and crash-report URLs need a real host and no
  user name or password, and the window position, last server, favourites and streaming preferences can only be set
  by NOBAD itself and are checked when settings are loaded.
- **WireGuard only gets NOBAD's locked copy of a config (#16).** The tunnel service (running as SYSTEM) used to be
  handed the stored file from the configs folder when nothing was tuned, so it could be swapped after NOBAD checked
  it. Every connect now uses a copy written to the admin-only runtime folder from the checked text.
- **The installed app ignores redirecting environment variables.** Its data folder and Program Files are taken
  from Windows (known folders), not from `%ProgramData%`, `%ProgramFiles%` or `NOBAD_DATA_DIR`, which a normal user
  can set for the processes NOBAD starts. Folder locking refuses junctions and symbolic links and removes any
  planted inside before it runs.
- **Start with Windows only for the installed app.** The no-UAC startup task is created only when NOBAD runs from
  Program Files, never for a copy in a folder other users could change.
- **Links open in your normal browser, not as administrator** (captive-portal sign-in pages, streaming links).
- **Imports from a link** refuse addresses on this PC or the local network and re-check where a redirect leads; no
  download anywhere in the app follows a redirect from `https://` to `http://`.
- **A stale instance file can't make NOBAD close another program** whose process ID was reused.
- **Restore internet** only passes adapter numbers and IP addresses from its change journal to PowerShell, and one bad
  entry no longer stops the rest of the reset.
- Smaller: update downloads are capped at 300 MB, IP-lookup answers at 64 KB, streaming provider IDs are numbers
  only, and the poster image proxy only serves NOBAD's own windows.

## 1.2.1 · 2026-11-12

Security and reliability update. **Recommended for everyone.** 1.2.0 can't update itself (it only accepts signed
installers, and releases aren't code-signed yet), so download 1.2.1 from GitHub Releases and install it over 1.2.0.

### Security
- **Only NOBAD's own window can control NOBAD.** The local control page no longer contains its access token. NOBAD
  opens its windows with a one-time launch code that becomes an HttpOnly, SameSite=Strict session cookie; any other
  program on the PC gets a locked page. Secrets are no longer passed in URLs.
- **Imported configs never carry script hooks.** PreUp/PostUp/PreDown/PostDown are refused for every import (file,
  paste, link, QR). They can still be added on purpose in the config editor.
- **Private folders are really private.** `C:\ProgramData\NobadVPN` and its runtime folder are now owned by
  Administrators and reset recursively, so a folder or file created there earlier by another user can't keep access.
  Failures are reported instead of ignored.
- **Installers run from a fresh admin-only folder.** App updates and the WireGuard installer are downloaded, checked
  and run from a new private folder each time, so nothing can be swapped in between the check and the install.
- **Poster and logo images can't run script.** SVG images fetched from TMDB are served with a sandboxing
  Content-Security-Policy.

### Fixed
- **Tabs that seemed to do nothing.** Settings, Servers and the other tabs appear below the status cards in the side
  column, often below the visible area, so a click looked like it did nothing. Selecting a tab now brings it into
  view, with a short fade.
- **Window opening at the edge of the screen.** A remembered position with only a sliver of the window on screen was
  accepted. The window now always opens fully on screen (moved back inside, or centred), and a position recorded
  while minimized is never saved.
- **Server list:** names no longer break over several lines and the address under them is readable; *Edit* is now a
  compact icon.
- **Network Intelligence:** its six sections sit in an even 3 × 2 grid.
- **Tray quick view:** while connected it shows the server you are actually connected to (not the last one picked
  there), and a click before the first status update no longer throws an error.
- **Kill switch:** when a firewall rule has to be recreated, a bridge copy keeps blocking until the new rule is in
  place, and failed rule changes are retried. Before, a failed re-add could leave the kill switch off mid-session.

### Faster
- **The window appears about twice as fast.** UI files are served from memory with fixed content types (Python's
  `mimetypes` read the registry on first use and every file of the first page load waited for it: ~340 ms each, now
  ~10 ms). Page ready 1.1 s → 0.55 s in testing.
- Opening Settings no longer stalls a frame (long groups are laid out only when scrolled near: 33 ms → 6 ms).

## 1.2.0 · 2026-11-12

First public, open-source release.

### New
- **Where to watch (Streaming Region Intelligence).** Find which countries list a movie, series or anime and on
  which platforms, see documented restrictions, and get a recommendation of which of your servers matches. It needs
  your own free TMDB key.
- **Network Intelligence (Intel tab).** Explains why a site or the network fails, with evidence: DNS filtering, TLS
  name blocking, IPv4/IPv6 and VPN integrity.
- **Fix my internet.** Restore / Quick repair / Full reset from the Intel tab, the tray or the Start menu, plus a boot
  guard and a change journal, so Windows' network settings always come back.
- **Connectivity adaptation.** NOBAD's own downloads route around networks that block a hostname or its DNS
  (official alternative names, encrypted DNS). *Test connectivity* shows the route for each service.
- **Own title bar** with native drag, snap, resize and window buttons (optional).
- **Search everything (Ctrl+K):** actions, servers, tabs and every setting, with fuzzy matching.
- **Live day/night map:** the night side of the world is shaded from the real sun position.
- Automatic WireGuard reinstall at start-up if it goes missing.

### Changed
- Refreshed design: frosted floating surfaces, rounder cards, smooth transitions. Still lightweight: blur only where
  it is visible.
- **Privacy:** *Look up my exit IP address* (ipinfo.io) is now **off by default** and offered in the setup checklist.
- Notifications and the taskbar show **NOBAD VPN** (not PowerShell or Python).

### Fixed
- The speed-test button could stay stuck after start-up checks.
- The tray quick view was placed off-screen at 125 % display scaling, and its content was clipped.
- A failed connection could break the layout until *Retry* was pressed.
- The smart fix agent couldn't apply DNS fixes.
- Many smaller UI fixes; see the commit history.

### Known limits
- **Builds are not code-signed yet,** so Windows SmartScreen will warn, and auto-update only accepts signed builds.
  Free signing for open-source projects is being applied for.
- Some behaviour still needs verification on more PCs and networks (sleep/resume, captive portals, ARM64).

## 1.0.0 · 2026-11-11

Internal milestone (not published): first NOBAD VPN build after the rebrand from NOMAD Tunnel.
