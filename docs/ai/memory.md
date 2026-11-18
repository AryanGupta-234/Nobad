# Project memory (shared by every AI assistant and human contributor)

Decisions and open items that the code doesn't show. One line each, newest first within a section, with a date.
Add to it when the maintainer decides something; delete lines that stop being true. Nothing secret goes here
(this repository is public): no keys, configs, personal data or private review notes.

## Standing decisions
- 2026-11-18 Product icons: every NOBAD app uses the company mark (black tile, "n"); only the "n" colour changes:
  NOBAD VPN orange, NOBAD File Bridge blue, NOBAD Find yellow (maintainer's choice).
- 2026-11-18 NOBAD File Bridge lives only in nobad-studio/file-bridge; its copy in this repo was removed (its open review
  fixes are tracked there). `file-bridge-ci.yml` is a stub that keeps the ruleset's required check green until it's dropped.
- 2026-11-17 GitHub organization `nobad-studio` (`nobad` is taken), Aryan Gupta the only owner. Repos: `Nobad-VPN`
  (NOBAD VPN + NOBAD Find, transferred from AryanGupta-234/Nobad, renamed from `nobad`), `website` (own repo, same Cloudflare Worker and
  URL), `file-bridge` (own repo, history kept), `.github` (org profile + shared community files). Harsh is an
  organization member: base permission Read, team `file-bridge` with Maintain on `file-bridge`; he must never have
  to redo work. Members can't create repositories; 2FA required.
- 2026-11-17 Open source for collaboration through forks and PRs: code stays MIT; contributors sign the CLA once
  (`CLA.md`, rights to Aryan Gupta and any future NOBAD company, bot in `cla.yml`); the brand is protected by
  `TRADEMARKS.md` (published forks use their own name; only official CI builds are "NOBAD …").
- 2026-11-17 One NOBAD orange on every product page (no per-product accent colours).
- 2026-11-16 Website style: premium, precise cybersecurity look; every product page uses the shared component system
  (`site-pages/assets/product.css`) in NOBAD orange. Always full product names ("NOBAD VPN", "NOBAD File
  Bridge"). Product pages say what users get and why to trust it: no author names, tech stack or build-process detail.
  Credits and collaboration live in one "Built in the open" section on the home page, driven by a list in `assets/home.js`.
- 2026-11-16 Brand: NOBAD is a studio with several products; motto "Software with a point of view." used verbatim everywhere (site titles/meta/footer, READMEs, repo description). The home page is the studio; each product has its own page under /products/ (vpn, file-bridge).
- 2026-11-16 The remote file manager app is named NOBAD File Bridge (now nobad-studio/file-bridge), a plain name non-technical users understand. On-disk/keyring ids stay `remote-file-manager` so existing data keeps working.
- 2026-11-16 No built-in servers. The free-server path is the default onboarding: highlight it in the app (empty Servers tab), README, user manual and the VPN page (#free-servers).
- 2026-11-16 Release "everywhere" every time: version, changelog, docs, site, `main`, CI release (playbook `release.md`).
- 2026-11-16 Releases come only from CI (tag → `vpn-release.yml`, attested, immutable). Never create one by hand.
- 2026-11-16 Never bundle WireGuard configs in the app or repo (shared private keys, one-connection free accounts,
  provider terms). Users get their own free servers through the Free servers guide.
- 2026-11-16 Where to watch must work without setup (Wikidata); a TMDB key is an optional upgrade. No shared key.
- 2026-11-16 Evil Twin ships inside the VPN first; it may become its own product later.
- 2026-11-16 New outbound connections need a setting and an entry in SYSTEM-INTEGRATION.md.

## Open items
- 2026-11-17 NOBAD Find photo meaning: maintainer approved an optional image model download. Chosen: SigLIP base
  (Apache-2.0, ~211 MB) instead of OpenAI CLIP (its model card rules out deployed use).
- 2026-11-17 NOBAD Find admin indexing: maintainer asked for an optional elevated "turbo" index (NTFS change
  journal/MFT) with reminders to enable it, reversing the 2026-11-17 "normal user only" decision. Not built yet;
  the app still never runs elevated. Kernel drivers are out (signing, crash risk, no accuracy gain).
- 2026-11-17 NOBAD Find has its own packaging in `apps/find/packaging/` (maintainer: never reuse the VPN's).
  Per-user Inno Setup installer, no admin; CI job `find-build` checks every PR; releases via `find-release.yml`.
- 2026-11-18 NOBAD VPN 1.6.2: quick view {"ok": false} after the install was removed under a running app (UI now cached
  at start-up), drops can't navigate windows (WebView2 NavigationStarting guard), HTML fallback for page navigations.
- 2026-11-18 NOBAD Find roadmap (`apps/find/ROADMAP.md`): maintainer's aim is RAM/CPU/GPU first, then features.
  Measured 0.7.0: WebView2 425 MB in 7 processes; engine 549 MB working / 3.98 GB committed. Plan: measure →
  engine diet → named-pipe engine service → Flutter UI (Qt fallback) → 0.8.0 models. Status table in the roadmap.
- 2026-11-18 NOBAD Find 0.7.0: resource governor (levels + per-app memory), job objects + watchdog, close stops
  indexing (keep_background setting), Indexing transparency page, quick find bar (Ctrl+Alt+Space), splash, Settings pages.
  Model tiers (multilingual) are 0.8.0, same spec.
- 2026-11-18 NOBAD Find 0.6.2: query linking words ("having/containing X") and Enter keeps the window. 0.7.0 (governor,
  transparency, find bar, UI) is designed in `docs/superpowers/specs/2026-11-18-find-governor-transparency-models-design.md`.
- 2026-11-17 NOBAD Find (`apps/find/`): private offline search over your own files, first release 0.6.0.
  Releases only from CI: tag `find-vX.Y.Z` -> `find-release.yml` (attested; never marked the repo's "latest" so
  NOBAD VPN keeps that). On the website at /products/find/; the home slider card is red (maintainer's choice,
  the one exception to "one NOBAD orange"). Out of scope: activity timeline/usage history. Design:
  `docs/ai/ideas/nobad-find.md`.
- 2026-11-17 Move to `nobad-studio` done: repo transferred and renamed to `nobad-studio/Nobad-VPN` (old URLs redirect,
  but attestation `--signer-workflow` must name the exact repo); website in `nobad-studio/website` (Cloudflare deploys
  `nobad-platform` from its `main`, address `https://nobad-platform.nobad-studio.workers.dev/`); File Bridge in
  `nobad-studio/file-bridge`. Still pending: remove `site-pages/`, `releases/` and the site build from this repo
  (site edits go to `nobad-studio/website` only).
- 2026-11-17 Releases up to 1.6.1 keep their attestations under the old owner: verify with `--owner AryanGupta-234
  --signer-workflow AryanGupta-234/Nobad/.github/workflows/vpn-release.yml` (tested). New releases: `-R nobad-studio/Nobad-VPN`.
- Releases before 1.5.0 aren't immutable (the setting only covers new releases); anyone with write access could
  replace their files. Users should verify with the strict `gh attestation verify ... --signer-workflow ...
  --source-ref ...` command (docs/RELEASE-PROCESS.md). Optional hardening: a protected `release` environment with
  the owner as required reviewer on the publish job.
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
