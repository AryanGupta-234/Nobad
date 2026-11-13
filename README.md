# NOBAD

**NOBAD is an independent, free and open-source software studio**: privacy tools, utilities and practical software,
built in the open and developed in collaboration with AI. It's in its initial launch phase; **NOBAD VPN** is its
first major release.

**Website:** <https://nobad-platform.aassworld99.workers.dev/> · [Code signing policy](https://nobad-platform.aassworld99.workers.dev/code-signing-policy/) · [Privacy policy](https://nobad-platform.aassworld99.workers.dev/privacy/)

| Product | What it is | Where |
|---|---|---|
| **NOBAD VPN** | A WireGuard client for Windows with a kill switch, DNS leak block, Network Intelligence, "Fix my internet" and Where to watch | [`apps/vpn/`](apps/vpn/) · [Releases](https://github.com/AryanGupta-234/Nobad/releases) |
| Website | [nobad-platform.aassworld99.workers.dev](https://nobad-platform.aassworld99.workers.dev/), the product pages and the download desk | [`site-pages/`](site-pages/) |

## Repository layout

```
apps/vpn/            NOBAD VPN (Windows app)
  nobadvpn/          app source (engine, UI in nobadvpn/ui/)
  tests/             pytest suite
  packaging/         PyInstaller spec, Inno Setup installer, build.ps1
  docs/              user manual, architecture, features, system integration, code signing
  CHANGELOG.md       user-facing changes per version
site-pages/          website source (plain HTML), built into public/ by scripts/prepare-site.mjs
releases/vpn/        releases.json, the public release manifest the download desk reads
scripts/             site build and release-publishing helpers
assets/              NOBAD logo and icons (shared by the site and the app)
docs/                repo-wide docs: release process, release-notes template
.github/             CI, release, CodeQL, Scorecard workflows; issue and PR templates
```

Installers for every version are on [GitHub Releases](https://github.com/AryanGupta-234/Nobad/releases), not in
the repository. Local build output (`build/`, `dist/`, `dist-installer/`, `public/`) is git-ignored.

## Download NOBAD VPN

Get the installer from **[GitHub Releases](https://github.com/AryanGupta-234/Nobad/releases)**. Each release is built
by GitHub Actions from the tagged source on a clean Windows runner, and ships with its SHA-256, the update manifest
and a software bill of materials (CycloneDX).

> Builds are **not code-signed yet**, so Windows SmartScreen shows a warning: choose *More info → Run anyway* after
> checking the SHA-256 on the release page. Free code signing for open-source projects has been applied for.

NOBAD VPN is a *client*: it connects using WireGuard configs from your VPN provider or your own server. NOBAD doesn't
run VPN servers and doesn't collect telemetry.

## Contributing

Bug reports, testing on your PC and network, documentation and code are all welcome; see
[CONTRIBUTING.md](CONTRIBUTING.md). Report security problems privately: [SECURITY.md](SECURITY.md).

## Website: local development and deployment

Requirements: Node.js 20+ (and Python 3 for the local preview).

```bash
npm run build
python -m http.server 8000 --directory public
```

The site is deployed with **Cloudflare Workers Static Assets** (Workers Builds). The build command is
`npm run build` and the deploy command is `npx wrangler deploy`, from the repository root. Pushes to `main` deploy
automatically.

* `site-pages/`: the website as plain HTML (home, `products/vpn/`, policy pages, 404, `_headers`, sitemap). Edit
  these files directly.
* `scripts/prepare-site.mjs`: deterministic build that generates `public/`, filling the download desk from the
  release manifest. Don't edit `public/` by hand.
* `releases/vpn/releases.json`: the public release manifest. It only lists releases that really exist on GitHub
  Releases; add them with `scripts/publish_vpn_release.py` (see `docs/RELEASE-PROCESS.md`).

## Releasing NOBAD VPN

1. Bump `APP_VER` in `apps/vpn/nobadvpn/const.py` and add the version to `apps/vpn/CHANGELOG.md`.
2. Commit, then tag and push: `git tag vpn-v<version> && git push origin vpn-v<version>`.
3. The **NOBAD VPN release** workflow builds, tests and publishes the GitHub Release.
4. Add the release (URL, SHA-256, size) to `releases/vpn/releases.json` so the website's download desk shows it.

## License

Released under the [MIT License](LICENSE). Third-party components bundled with NOBAD VPN are listed in
[apps/vpn/THIRD-PARTY-NOTICES.md](apps/vpn/THIRD-PARTY-NOTICES.md). The MIT License covers the code, not the NOBAD name
or logo.
