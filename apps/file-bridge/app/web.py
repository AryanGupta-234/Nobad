"""Start NOBAD File Bridge with the new web UI (in development; the classic UI is ``python -m app.main``).

    python -m app.web             # app window (pywebview)
    python -m app.web --browser   # same UI in your default web browser
"""
from __future__ import annotations

import argparse
import sys
import threading
import webbrowser

from app_web import bus
from app_web.context import AppContext
from app_web.server import BridgeServer
from app_web.window import WindowController, WindowUnavailable
from core.diagnostics import install_diagnostics


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.web", description="NOBAD File Bridge (web UI)")
    parser.add_argument("--browser", action="store_true", help="open the UI in your web browser instead of a window")
    parser.add_argument("--db", help="use this database file instead of the normal one (for testing)")
    parser.add_argument("--debug", action="store_true", help="allow the web inspector in the window")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    install_diagnostics()
    ctx = AppContext.create(args.db)
    server = BridgeServer(ctx)
    server.start()
    bus.log(f"NOBAD File Bridge {ctx.version} started.", "ok")
    storage_warning = getattr(ctx.app_data, "storage_warning", None)
    if storage_warning:
        bus.log(storage_warning, "warn", "storage")
    try:
        if args.browser:
            webbrowser.open(server.launch_url())
            print(f"NOBAD File Bridge is running at {server.base_url}. Press Ctrl+C to stop.")
            threading.Event().wait()
        else:
            ctx.window = WindowController(
                frameless=bool(ctx.settings.get("web_ui.custom_titlebar")),
                load_geometry=ctx.load_window_geometry,
                save_geometry=ctx.save_window_geometry,
            )
            ctx.window.run(server.launch_url(), debug=args.debug)
    except WindowUnavailable as exc:
        print(exc, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        pass
    finally:
        ctx.terminals.close_all()
        ctx.editor.shutdown()
        server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
