# Changelog

All notable changes to NOBAD VPN. Versions follow [semantic versioning](https://semver.org/).

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

### Fixed
- **Kill switch:** when a firewall rule has to be recreated, a bridge copy keeps blocking until the new rule is in
  place, and failed rule changes are retried. Before, a failed re-add could leave the kill switch off mid-session.

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
