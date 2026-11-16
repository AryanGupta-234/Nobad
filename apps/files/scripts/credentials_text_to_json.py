#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from credentials.bulk_text_parser import credentials_text_to_json_text


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert loose credential notes into Remote File Manager credential JSON."
    )
    parser.add_argument("input", nargs="?", help="Input text file. Reads stdin when omitted.")
    parser.add_argument("-o", "--output", help="Output JSON file. Writes stdout when omitted.")
    parser.add_argument("-p", "--project", default="Imported Credentials", help="Project name in the output JSON.")
    args = parser.parse_args()

    if args.input:
        text = Path(args.input).read_text(encoding="utf-8")
    else:
        text = sys.stdin.read()

    output = credentials_text_to_json_text(text, project_name=args.project)
    if args.output:
        Path(args.output).write_text(output + "\n", encoding="utf-8")
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
