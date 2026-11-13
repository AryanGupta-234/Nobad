# Changelog

All notable changes to NOBAD VPN. Versions follow [semantic versioning](https://semver.org/).

## Unreleased

### Changed
- **Start with Windows is off by default.** The installer box is unticked on a new install; turn it on there or in
  Settings. An update no longer switches it off when the box is left unticked.

### Security
- **The kill switch no longer gives up (#14).** After 8 failed reconnects NOBAD used to remove the blocking rules
  unless the strict kill switch was on, so someone who blocked the VPN's traffic could get yours outside the
  tunnel. It now keeps blocking until you choose Restore internet or Disconnect.
- **Trusted networks check more than the name (#15).** A Wi-Fi network with your home network's name, or any network
  cable, used to switch the VPN off. NOBAD now also checks the router and, when Windows shows them, the Wi-Fi security
  type and access point. A mismatch keeps you protected and asks you to confirm in Settings; open Wi-Fi is never
  trusted. Networks trusted in an older version need one confirmation.
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
