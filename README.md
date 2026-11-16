# NOBAD

*Software with a point of view.*

NOBAD is an independent, free and open-source software studio. It builds privacy tools, utilities and practical
software in the open, in collaboration with AI. Each product lives in its own folder under `apps/`.

[Website](https://nobad-platform.aassworld99.workers.dev/) ·
[Releases](https://github.com/AryanGupta-234/Nobad/releases) ·
[Discussions](https://github.com/AryanGupta-234/Nobad/discussions) ·
[Security policy](SECURITY.md) ·
[Code signing policy](https://nobad-platform.aassworld99.workers.dev/code-signing-policy/) ·
[Privacy policy](https://nobad-platform.aassworld99.workers.dev/privacy/)

## Products

| Product | What it is | Status | Where |
|---|---|---|---|
| **NOBAD VPN** | A WireGuard client for Windows with a kill switch, DNS leak block, Network Intelligence, an Evil Twin network check and Where to watch. | Available | [`apps/vpn/`](apps/vpn/) · [product page](https://nobad-platform.aassworld99.workers.dev/products/vpn/) |
| **NOBAD Files** | A remote file manager for SSH/SFTP and FTP/FTPS: transfers, sync, remote editing, terminals, an encrypted vault and deployments. Linux and Windows. By [@harshRaj1601](https://github.com/harshRaj1601). | In development: being hardened before its first release (see [issues labelled `nobad-files`](https://github.com/AryanGupta-234/Nobad/issues?q=is%3Aissue+label%3Anobad-files)) | [`apps/files/`](apps/files/) · [product page](https://nobad-platform.aassworld99.workers.dev/products/files/) |

The website source is in [`site-pages/`](site-pages/).

AI coding assistants: read [AGENTS.md](AGENTS.md) first.

## Repository layout

```
apps/files/          NOBAD Files (remote file manager, Python + PySide6)
  tests/             pytest suite
  packaging/         Linux .deb script; PyInstaller spec is build.spec
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

## Free servers in 2 minutes

NOBAD is the app, not a server company, but you don't need to pay for servers to start:

1. **Install NOBAD VPN** (below) and open the **Servers** tab.
2. **Create a free Proton VPN account:** <https://account.protonvpn.com/signup> (e-mail only, no payment).
3. **Download WireGuard configs:** <https://account.protonvpn.com/downloads> → WireGuard configuration → Windows →
   a free country → Create. Repeat for each country you want.
4. **Done.** NOBAD finds the files in your Downloads folder by itself and offers **Add now**.

Servers are never built into NOBAD: a shared config would give everyone the same private key and the same
one-connection free account. Each person gets their own.

## Download NOBAD VPN

Get the installer from **[GitHub Releases](https://github.com/AryanGupta-234/Nobad/releases)**. Each release is built
by GitHub Actions from the tagged source on a clean Windows runner, and ships with its SHA-256, the update manifest
and a software bill of materials (CycloneDX).

> Builds are **not code-signed yet**, so Windows SmartScreen shows a warning: choose *More info → Run anyway* after
> checking the SHA-256 on the release page. Free code signing for open-source projects has been applied for.

NOBAD VPN is a *client*: it connects using WireGuard configs from your VPN provider or your own server. NOBAD doesn't
run VPN servers and doesn't collect telemetry.

## Contributing

Bug reports, testing on your PC and network, documentation and code are all welcome, for either product; see
[CONTRIBUTING.md](CONTRIBUTING.md). Questions and ideas go to
[Discussions](https://github.com/AryanGupta-234/Nobad/discussions). Report security problems privately:
[SECURITY.md](SECURITY.md).

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

WireGuard is a registered trademark of Jason A. Donenfeld. Proton VPN, Cloudflare WARP, Netflix, Prime Video, Disney+, YouTube, Spotify, Twitch, Valorant, TMDB, JustWatch, Wikipedia, Windows and the other product names mentioned are trademarks of their owners. NOBAD is independent and is not affiliated with, endorsed by or sponsored by any of them; their names are used only to say what NOBAD works with.
