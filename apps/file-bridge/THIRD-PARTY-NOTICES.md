# Third-party notices: NOBAD File Bridge

Bundled in this folder:

| Component | Where | License |
|---|---|---|
| xterm.js and `@xterm/addon-fit` | `app_web/ui/vendor/xterm/` | MIT |
| Monaco Editor 0.56.0 (`min/vs` only; translations and type definitions removed) | `resources/editor/vendor/monaco/` (its `LICENSE` and `ThirdPartyNotices.txt` are next to it) | MIT |
| Tailwind CSS (Play CDN build, design preview only, not shipped in the app) | `preview/tailwind.js` | MIT |

Nothing is loaded from a CDN at run time.

Python dependencies (installed from PyPI, listed in `pyproject.toml` and pinned in `uv.lock`): PySide6 (LGPL-3.0, Linux only: the Qt WebEngine window),
AsyncSSH (EPL-2.0 or GPL-2.0+), keyring (MIT), SQLAlchemy (MIT), chardet (LGPL-2.1+), aioftp (Apache-2.0),
Pillow (MIT-CMU), argon2-cffi (MIT), cryptography (Apache-2.0 or BSD-3-Clause), pywinpty (MIT, Windows only),
pywebview (BSD-3-Clause).
