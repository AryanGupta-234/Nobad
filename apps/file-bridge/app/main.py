"""Start NOBAD File Bridge.

    nobad-file-bridge              # the app window
    nobad-file-bridge --browser    # the same app in your web browser
    nobad-file-bridge --classic    # the previous Qt window, while it still ships

``python -m app.main`` does the same."""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--classic" in args:
        args.remove("--classic")
        from app.classic import main as classic_main     # imports Qt only when asked for

        return classic_main(args)
    from app.web import main as web_main

    return web_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
