# Contributing to NOBAD

NOBAD is an independent, free and open-source software studio. Contributions of every size are welcome: bug
reports, testing on your PC and network, documentation, translations and code.

## Ways to help

- **Test on your machine.** Windows 10, Windows 11, ARM64, laptops that sleep, hotel or café Wi-Fi with sign-in pages,
  and switching between Wi-Fi and Ethernet are the most useful. Open an issue with what you saw, even when it worked.
- **Report bugs** with the *Bug report* template. In NOBAD, *Settings → Help → Export diagnostics* creates a zip with
  private keys removed; attach it if you can.
- **Improve docs.** The user manual is `apps/vpn/docs/USER-MANUAL.md`.
- **Send code** as a pull request (see below).

## Building NOBAD VPN

Requirements: Windows 10/11 (x64), Python 3.11, and Inno Setup 6 for the installer.

```powershell
cd apps/vpn
python -m venv .venv-build; .\.venv-build\Scripts\Activate.ps1
python -m pip install --require-hashes -r requirements-lock.txt
python -m pytest -q tests                                        # all tests run against a simulated Windows
python nobad_vpn.py                                              # run from source (asks for admin rights)
powershell -ExecutionPolicy Bypass -File packaging\build.ps1     # full installer (tests, app, WireGuard, Inno)
```

The website lives in `site-pages/` as plain HTML and is built by `npm run build` at the repository root.

## Pull requests

1. Keep each PR focused on one change, and explain *why* in the description.
2. Add or update tests. The suite must pass (`python -m pytest -q tests`) and lint must be clean
   (`python -m pyflakes nobadvpn tests`).
3. Keep the existing style: plain, honest UI text that never claims more than the code measures; no tracking; no
   new outbound connections without a setting and an entry in `docs/SYSTEM-INTEGRATION.md`.
4. Anything that changes Windows network settings must be undoable by every reset path (see `netjournal.py` and
   `netrepair.py`).
5. By contributing, you agree that your contribution is licensed under the [MIT License](LICENSE).

## AI-assisted contributions

NOBAD itself is developed in collaboration with AI. AI-assisted contributions are welcome under the same rules:
a person submits the PR, understands it, and is responsible for it. Please say in the PR if AI helped.

## Code of conduct

Be kind and constructive. See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
