"""Start NOBAD File Bridge.

    nobad-file-bridge              # the app window
    nobad-file-bridge --browser    # the same app in your web browser

``python -m app.main`` does the same."""
from __future__ import annotations

import sys

CLASSIC_REMOVED = ("The classic Qt window was removed; File Bridge's window now has every screen it had. "
                   "Start it without --classic.")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--classic" in args:
        print(CLASSIC_REMOVED, file=sys.stderr)
        return 2
    from app.web import main as web_main

    return web_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
