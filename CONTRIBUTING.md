# Contributing to NOBAD

NOBAD is an independent, free and open-source software studio. *Software with a point of view.* Contributions of
every size are welcome: bug reports, testing on your PC and network, documentation, translations and code.

## Products and their tests

Each product has its own folder and its own test suite. Run the tests from that folder.

| Product | Folder | Tests |
|---|---|---|
| NOBAD VPN | [`apps/vpn/`](apps/vpn/) | `python -m pytest -q` |
| NOBAD Find | [`apps/find/`](apps/find/) | `python -m pytest -q tests` |

NOBAD File Bridge has its own repository: [nobad-studio/file-bridge](https://github.com/nobad-studio/file-bridge).

AI coding assistants: read [AGENTS.md](AGENTS.md) first.

## Ways to help

- **Test on your machine.** Windows 10, Windows 11, ARM64, laptops that sleep, hotel or café Wi-Fi with sign-in pages,
  and switching between Wi-Fi and Ethernet are the most useful. Open an issue with what you saw, even when it worked.
- **Report bugs** with the *Bug report* template. In NOBAD, *Settings → Help → Export diagnostics* creates a zip with
  private keys removed; attach it if you can.
- **Improve docs.** The user manual is `apps/vpn/docs/USER-MANUAL.md`.
- **Send code** as a pull request (see below). New here? Issues labelled
  [`good first issue`](https://github.com/nobad-studio/Nobad-VPN/labels/good%20first%20issue) are picked to be a
  friendly start, and [Discussions](https://github.com/nobad-studio/Nobad-VPN/discussions) is the place to ask first.

## Building NOBAD VPN

Requirements: Windows 10/11 (x64), Python 3.11, and Inno Setup 6 for the installer.

```powershell
cd apps/vpn
python -m venv .venv-build; .\.venv-build\Scripts\Activate.ps1
python -m pip install --require-hashes -r requirements-lock.txt
python -m pytest -q                                              # all tests run against a simulated Windows
python nobad_vpn.py                                              # run from source (asks for admin rights)
powershell -ExecutionPolicy Bypass -File packaging\build.ps1     # full installer (tests, app, WireGuard, Inno)
```

## Website

The website lives in `site-pages/` as plain HTML and is built by `npm run build` at the repository root.

## How changes reach `main`

`main` is protected. Only the maintainer can push to it; everyone else contributes through a pull request from a fork:

1. Fork the repository and create a branch for your change.
2. Open a pull request against `main`. GitHub Actions runs on it only after a maintainer approves the run (all
   outside contributors, not just first-timers), and with a read-only token.
3. Every pull request needs an approving review from the code owner (`.github/CODEOWNERS`), all review threads
   resolved, and the site build check passing. A new push after approval needs a fresh approval.
4. `main` can't be force-pushed or deleted, and release tags (`vpn-v*`) can only be created by the maintainer.
   Releases are built from a tag by `.github/workflows/vpn-release.yml` on a clean GitHub runner and carry a signed
   build-provenance attestation. Check it with
   `gh attestation verify NobadVPN-Setup-<version>.exe -R nobad-studio/Nobad-VPN --signer-workflow nobad-studio/Nobad-VPN/.github/workflows/vpn-release.yml --source-ref refs/tags/vpn-v<version> --deny-self-hosted-runners`
   (releases up to 1.6.1: see [docs/RELEASE-PROCESS.md](docs/RELEASE-PROCESS.md)).

## Pull requests

1. Keep each PR focused on one change, and explain *why* in the description.
2. Add or update tests. The product's suite must pass (see *Products and their tests*). For NOBAD VPN, lint must
   also be clean (`python -m pyflakes nobadvpn tests`, from `apps/vpn`).
3. Keep the existing style: plain, honest UI text that never claims more than the code measures; no tracking; no
   new outbound connections without a setting and an entry in `docs/SYSTEM-INTEGRATION.md`.
4. Anything that changes Windows network settings must be undoable by every reset path (see `netjournal.py` and
   `netrepair.py`).
5. **Sign the CLA once.** On your first pull request a bot asks you to agree to the
   [Contributor License Agreement](CLA.md) by posting one comment. You keep the copyright to your work; the CLA lets
   NOBAD ship it, today under the [MIT License](LICENSE) and in future NOBAD releases.

## Forks and the NOBAD name

Forking is welcome: that's how every contribution starts. If you publish your own build outside a pull request,
give it your own name and logo. Only the official release workflows publish "NOBAD" builds. See
[TRADEMARKS.md](TRADEMARKS.md).

## AI-assisted contributions

NOBAD itself is developed in collaboration with AI. AI-assisted contributions are welcome under the same rules:
a person submits the PR, understands it, and is responsible for it. Please say in the PR if AI helped.

## Code of conduct

Be kind and constructive. See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
