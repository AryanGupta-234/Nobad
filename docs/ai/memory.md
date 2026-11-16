# Project memory (shared by every AI assistant and human contributor)

Decisions and open items that the code doesn't show. One line each, newest first within a section, with a date.
Add to it when the maintainer decides something; delete lines that stop being true. Nothing secret goes here
(this repository is public): no keys, configs, personal data or private review notes.

## Standing decisions
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
- PR #27 "NOBAD Files" (`apps/files/`, by @harshRaj1601, a collaborator with write access): reviewed, mergeable after
  fixes listed on the PR. The maintainer said not to merge yet. Decide: monorepo vs its own repository.
- Code signing isn't set up yet (SmartScreen warns; the in-app updater only accepts signed builds). SignPath for
  open source is the planned route (see `apps/vpn/docs/CODE-SIGNING.md`).

## Release history
- 1.5.1 Security: import folder outside the locked data folder, quarantine by ownership, .NET profiler variables stripped, links only on this session's desktop; site without inline scripts; strict attestation check documented.
- 1.5.0 Free servers in two clicks (Downloads folder pick-up).
- 1.4.1 Links open in the browser as the user; key-free Where to watch; lighter in the background.
- 1.4.0 Evil Twin network trust check.
- 1.3.4 Security hardening, Network Intelligence fixes, UI polish.
