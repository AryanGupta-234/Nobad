# Third-party notices: NOBAD File Bridge

Bundled in this folder:

| Component | Where | License |
|---|---|---|
| xterm.js and `@xterm/addon-fit` | `resources/terminal/vendor/` | MIT |
| Tailwind CSS (Play CDN build, design preview only, not shipped in the app) | `preview/tailwind.js` | MIT |

Loaded at runtime, not bundled:

| Component | Source | License |
|---|---|---|
| Monaco Editor | `cdnjs.cloudflare.com` / `unpkg.com` (see `resources/editor/`) | MIT |

Python dependencies (installed from PyPI, listed in `pyproject.toml` and pinned in `uv.lock`): PySide6 (LGPL-3.0),
AsyncSSH (EPL-2.0 or GPL-2.0+), keyring (MIT), SQLAlchemy (MIT), chardet (LGPL-2.1+), aioftp (Apache-2.0),
Pillow (MIT-CMU), argon2-cffi (MIT), cryptography (Apache-2.0 or BSD-3-Clause), pywinpty (MIT, Windows only).
