"""Command-line entry point."""

from __future__ import annotations

import argparse

from agentos import __version__


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="agentos",
        description="AgentOS supervised agent runtime",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("status", help="Show local runtime foundation status")
    args = parser.parse_args()

    if args.command == "status":
        print(f"AgentOS {__version__}: foundation initialized; no agents or tools enabled.")
    elif args.command is None:
        parser.print_help()


if __name__ == "__main__":
    main()
