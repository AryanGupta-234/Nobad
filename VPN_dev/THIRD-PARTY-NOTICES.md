# Third-party notices

NOBAD VPN's own source code is released under the MIT License (see `LICENSE` in the repository root).
The Windows installer and the built app also contain the third-party components below, each under its own license.
They are used unmodified.

| Component | Used for | License |
|---|---|---|
| [WireGuard for Windows](https://www.wireguard.com/) (official MSIs, `redist\`) | the tunnel service NOBAD drives | Published and signed by WireGuard LLC. Bundled unmodified; its license terms are shown and accepted when it installs. WireGuard is a registered trademark of Jason A. Donenfeld. |
| [Python](https://www.python.org/) 3.11 runtime | runs the app | PSF License Agreement (PSF-2.0) |
| [PyInstaller](https://pyinstaller.org/) bootloader | starts the bundled app | GPL-2.0 with the PyInstaller bootloader exception, which allows distribution with programs under any license |
| [pywebview](https://github.com/r0x0r/pywebview) | native window (Microsoft Edge WebView2) | BSD-3-Clause |
| [pythonnet](https://github.com/pythonnet/pythonnet), [clr-loader](https://github.com/pythonnet/clr-loader) | .NET bridge used by pywebview on Windows | MIT |
| [bottle](https://bottlepy.org/), [proxy_tools](https://github.com/jtushman/proxy_tools) | pywebview dependencies | MIT |
| [pystray](https://github.com/moses-palmer/pystray) | tray icon | LGPL-3.0 (see note below) |
| [Pillow](https://python-pillow.org/) | tray and splash images | MIT-CMU (HPND) |
| [cffi](https://cffi.readthedocs.io/), [pycparser](https://github.com/eliben/pycparser) | native-call helpers | MIT-0, BSD-3-Clause |
| [six](https://github.com/benjaminp/six), [typing_extensions](https://github.com/python/typing_extensions) | compatibility helpers | MIT, PSF-2.0 |
| [OpenSSL](https://www.openssl.org/) (`libssl-3.dll`, `libcrypto-3.dll`) | TLS in the Python runtime | Apache-2.0 |
| [libffi](https://sourceware.org/libffi/) | Python `ctypes` | MIT |
| Microsoft Visual C++ runtime (`VCRUNTIME140.dll`) | required by Python | Microsoft Visual C++ Redistributable license |
| [jsQR](https://github.com/cozmo/jsQR) (`nobadvpn/ui/vendor/jsqr.js`) | reading WireGuard QR codes | Apache-2.0 (`nobadvpn/ui/vendor/jsqr.LICENSE.txt`) |

## pystray (LGPL-3.0)

pystray is used without modification. The complete source of NOBAD VPN and its build script
(`packaging/build.ps1`, `packaging/nobad.spec`) are public under the MIT License, so you can rebuild the app with
your own modified copy of pystray. pystray's source is available at https://github.com/moses-palmer/pystray.

## Data sources used at runtime (not bundled)

| Source | Used for | Terms |
|---|---|---|
| [TMDB](https://www.themoviedb.org/) API | titles, metadata, posters, age ratings | TMDB API Terms of Use. Each user supplies their own key. Required notice: "This product uses the TMDB API but is not endorsed or certified by TMDB." TMDB content is cached for at most six months. |
| [JustWatch](https://www.justwatch.com/) (through TMDB's watch-provider data) | streaming availability per country | Attribution to JustWatch required (shown in the app) |
| [Wikipedia](https://en.wikipedia.org/) / [Wikidata](https://www.wikidata.org/) | documented film restrictions, identity links | Wikipedia text CC BY-SA 4.0 (records link to their source section); Wikidata CC0 |

## Names and logos

The MIT License covers the code. It doesn't grant rights to the NOBAD name or logo (`nobadvpn/ui/brand/`,
`assets/`). Forks are welcome, but please give them a different name and logo so users can tell them apart.
