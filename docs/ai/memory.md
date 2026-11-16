# Project memory (shared by every AI assistant and human contributor)

Decisions and open items that the code doesn't show. One line each, newest first within a section, with a date.
Add to it when the maintainer decides something; delete lines that stop being true. Nothing secret goes here
(this repository is public): no keys, configs, personal data or private review notes.

## Standing decisions
- 2026-11-16 No built-in servers. The free-server path is the default onboarding: highlight it in the app (empty Servers tab), README, user manual and the VPN page (#free-servers).
- 2026-11-16 Release "everywhere" every time: version, changelog, docs, site, `main`, CI release (playbook `release.md`).
- 2026-11-16 Releases come only from CI (tag → `vpn-release.yml`, attested, immutable). Never create one by hand.
- 2026-11-16 Never bundle WireGuard configs in the app or repo (shared private keys, one-connection free accounts,
  provider terms). Users get their own free servers through the Free servers guide.
- 2026-11-16 Where to watch must work without setup (Wikidata); a TMDB key is an optional upgrade. No shared key.
- 2026-11-16 Evil Twin ships inside the VPN first; it may become its own product later.
- 2026-11-16 New outbound connections need a setting and an entry in SYSTEM-INTEGRATION.md.

## Open items
- Releases before 1.5.0 aren't immutable (the setting only covers new releases); anyone with write access could
  replace their files. Users should verify with the strict `gh attestation verify ... --signer-workflow ...
  --source-ref ...` command (docs/RELEASE-PROCESS.md). Optional hardening: a protected `release` environment with
  the owner as required reviewer on the publish job.
- NOBAD Files (`apps/files/`, by @harshRaj1601, write access) was merged by the maintainer on 2026-11-16 (PR #27).
  Fixes still owed from its review: remote file names can write outside the download folder (sftp_ops/transfer_manager),
  Monaco editor loaded from a CDN without integrity pinning, world-readable app database on Linux, sudo password
  auto-typed on a server-controlled prompt, failing tests. Track them as issues; don't release NOBAD Files before they're fixed.
- Code signing isn't set up yet (SmartScreen warns; the in-app updater only accepts signed builds). SignPath for
  open source is the planned route (see `apps/vpn/docs/CODE-SIGNING.md`).

## Release history
- 1.6.0 Get free servers in 2 minutes (empty Servers tab + background Downloads pick-up); uninstall stops every NOBAD process; upgrades stop the old copy first.
- 1.5.1 Security: import folder outside the locked data folder, quarantine by ownership, .NET profiler variables stripped, links only on this session's desktop; site without inline scripts; strict attestation check documented.
- 1.5.0 Free servers in two clicks (Downloads folder pick-up).
- 1.4.1 Links open in the browser as the user; key-free Where to watch; lighter in the background.
- 1.4.0 Evil Twin network trust check.
- 1.3.4 Security hardening, Network Intelligence fixes, UI polish.
