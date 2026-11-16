# Project memory (shared by every AI assistant and human contributor)

Decisions and open items that the code doesn't show. One line each, newest first within a section, with a date.
Add to it when the maintainer decides something; delete lines that stop being true. Nothing secret goes here
(this repository is public): no keys, configs, personal data or private review notes.

## Standing decisions
- 2026-11-17 GitHub organization `nobad-studio` (`nobad` is taken), Aryan Gupta the only owner. Repos: `nobad`
  (NOBAD VPN + NOBAD Find, transferred from AryanGupta-234/Nobad), `website` (own repo, same Cloudflare Worker and
  URL), `file-bridge` (own repo, history kept), `.github` (org profile + shared community files). Harsh is an
  organization member: base permission Read, team `file-bridge` with Maintain on `file-bridge`; he must never have
  to redo work. Members can't create repositories; 2FA required.
- 2026-11-17 Open source for collaboration through forks and PRs: code stays MIT; contributors sign the CLA once
  (`CLA.md`, rights to Aryan Gupta and any future NOBAD company, bot in `cla.yml`); the brand is protected by
  `TRADEMARKS.md` (published forks use their own name; only official CI builds are "NOBAD …").
- 2026-11-17 One NOBAD orange on every product page (no per-product accent colours).
- 2026-11-16 Auto-approve for NOBAD File Bridge: PRs that change only `apps/file-bridge/` need no review (the folder has no CODEOWNERS owner; the ruleset requires 0 approvals but code-owner review) and merge once `file-bridge-tests` + `site-build` pass. Everything else needs @AryanGupta-234. No AI bot gets approval rights.
- 2026-11-16 Website style: premium, precise cybersecurity look; every product page uses the shared component system
  (`site-pages/assets/product.css`) in NOBAD orange. Always full product names ("NOBAD VPN", "NOBAD File
  Bridge"). Product pages say what users get and why to trust it: no author names, tech stack or build-process detail.
  Credits and collaboration live in one "Built in the open" section on the home page, driven by a list in `assets/home.js`.
- 2026-11-16 Brand: NOBAD is a studio with several products; motto "Software with a point of view." used verbatim everywhere (site titles/meta/footer, READMEs, repo description). The home page is the studio; each product has its own page under /products/ (vpn, file-bridge).
- 2026-11-16 The remote file manager app is named NOBAD File Bridge (`apps/file-bridge/`), a plain name non-technical users understand. On-disk/keyring ids stay `remote-file-manager` so existing data keeps working.
- 2026-11-16 No built-in servers. The free-server path is the default onboarding: highlight it in the app (empty Servers tab), README, user manual and the VPN page (#free-servers).
- 2026-11-16 Release "everywhere" every time: version, changelog, docs, site, `main`, CI release (playbook `release.md`).
- 2026-11-16 Releases come only from CI (tag → `vpn-release.yml`, attested, immutable). Never create one by hand.
- 2026-11-16 Never bundle WireGuard configs in the app or repo (shared private keys, one-connection free accounts,
  provider terms). Users get their own free servers through the Free servers guide.
- 2026-11-16 Where to watch must work without setup (Wikidata); a TMDB key is an optional upgrade. No shared key.
- 2026-11-16 Evil Twin ships inside the VPN first; it may become its own product later.
- 2026-11-16 New outbound connections need a setting and an entry in SYSTEM-INTEGRATION.md.

## Open items
- 2026-11-17 NOBAD Find (`apps/find/`, in development, no installer yet): private offline search over your own files.
  Maintainer chose: full build, pywebview + HTML UI, name "NOBAD Find". Out of scope: activity timeline/usage history
  and raw NTFS/MFT reading. Design: `docs/ai/ideas/nobad-find.md`. Not on the website until it ships.
- Releases before 1.5.0 aren't immutable (the setting only covers new releases); anyone with write access could
  replace their files. Users should verify with the strict `gh attestation verify ... --signer-workflow ...
  --source-ref ...` command (docs/RELEASE-PROCESS.md). Optional hardening: a protected `release` environment with
  the owner as required reviewer on the publish job.
- NOBAD File Bridge (`apps/file-bridge/`, formerly NOBAD Files in `apps/files/`, by @harshRaj1601, write access) was merged by the maintainer on 2026-11-16 (PR #27).
  Fixes still owed from its review: remote file names can write outside the download folder (sftp_ops/transfer_manager),
  Monaco editor loaded from a CDN without integrity pinning, world-readable app database on Linux, sudo password
  auto-typed on a server-controlled prompt, failing tests. Track them as issues; don't release NOBAD File Bridge before they're fixed.
- Code signing isn't set up yet (SmartScreen warns; the in-app updater only accepts signed builds). SignPath for
  open source is the planned route (see `apps/vpn/docs/CODE-SIGNING.md`).

## Release history
- 1.6.1 Window resizing fixed (SC_SIZE), hidden warning cards fixed, Investigate a site layout; site rebranded as the NOBAD studio with a File Bridge page.
- 1.6.0 Get free servers in 2 minutes (empty Servers tab + background Downloads pick-up); uninstall stops every NOBAD process; upgrades stop the old copy first.
- 1.5.1 Security: import folder outside the locked data folder, quarantine by ownership, .NET profiler variables stripped, links only on this session's desktop; site without inline scripts; strict attestation check documented.
- 1.5.0 Free servers in two clicks (Downloads folder pick-up).
- 1.4.1 Links open in the browser as the user; key-free Where to watch; lighter in the background.
- 1.4.0 Evil Twin network trust check.
- 1.3.4 Security hardening, Network Intelligence fixes, UI polish.
