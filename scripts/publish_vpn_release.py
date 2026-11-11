#!/usr/bin/env python3
"""Create an immutable NOBAD VPN release entry and copy its installer.

Example:
  python scripts/publish_vpn_release.py \
    --file dist/NOBAD-VPN-Setup.exe --version 1.0.0 \
    --date 2026-11-10 --platform Windows --architecture x64 \
    --channel stable --summary "First public release" \
    --notes docs/releases/vpn/1.0.0.md

Run from the nobad-platform directory. This script calculates SHA-256 and
updates releases/vpn/releases.json. It does not sign binaries or test them.
"""
from __future__ import annotations
import argparse, hashlib, json, re, shutil
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "releases" / "vpn" / "releases.json"
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$")

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def main() -> None:
    p = argparse.ArgumentParser(description="Publish a versioned NOBAD VPN release")
    p.add_argument("--file", required=True, type=Path, help="Tested installer or archive")
    p.add_argument("--version", required=True)
    p.add_argument("--date", required=True, help="Release date YYYY-MM-DD")
    p.add_argument("--platform", required=True)
    p.add_argument("--architecture", required=True)
    p.add_argument("--channel", choices=["stable", "beta", "preview"], default="stable")
    p.add_argument("--summary", required=True)
    p.add_argument("--notes", required=True, help="Release notes file, relative to project root")
    args = p.parse_args()

    if not SEMVER.fullmatch(args.version):
        p.error("--version must be semantic versioning, e.g. 1.0.0")
    try:
        date.fromisoformat(args.date)
    except ValueError:
        p.error("--date must be a valid YYYY-MM-DD date")
    source = args.file.resolve()
    notes = (ROOT / args.notes).resolve()
    if not source.is_file() or source.stat().st_size == 0:
        p.error("installer file does not exist or is empty")
    if not notes.is_file():
        p.error("release notes file does not exist inside the project")
    if ROOT not in notes.parents:
        p.error("release notes must be inside the project")

    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    releases = data.setdefault("releases", [])
    if any(r.get("version") == args.version for r in releases):
        p.error("this version already exists; publish a new version instead")

    artifact_dir = ROOT / "downloads" / "vpn" / args.version
    artifact_dir.mkdir(parents=True, exist_ok=False)
    artifact_name = f"nobad-vpn-{args.version}{source.suffix.lower()}"
    destination = artifact_dir / artifact_name
    shutil.copy2(source, destination)
    digest = sha256(destination)
    relative_download = destination.relative_to(ROOT).as_posix()
    relative_notes = notes.relative_to(ROOT).as_posix()

    entry = {
        "version": args.version,
        "releaseDate": args.date,
        "channel": args.channel,
        "platform": args.platform,
        "architecture": args.architecture,
        "summary": args.summary,
        "downloadUrl": "/" + relative_download,
        "notesUrl": "/" + relative_notes,
        "sha256": digest,
        "size": f"{destination.stat().st_size} bytes"
    }
    releases.insert(0, entry)
    data["latest"] = args.version
    MANIFEST.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"Published metadata for NOBAD VPN {args.version}")
    print(f"Artifact: {destination}")
    print(f"SHA-256: {digest}")
    print("Reminder: test the release and Authenticode-sign Windows binaries before public distribution.")

if __name__ == "__main__":
    main()
