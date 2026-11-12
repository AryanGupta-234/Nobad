#!/usr/bin/env python3
"""Add a published NOBAD VPN GitHub Release to the website's download desk (releases/vpn/releases.json).

Run it AFTER the release workflow has published the GitHub Release:

    python scripts/publish_vpn_release.py 1.2.1 "Security and reliability update"

It reads the release from GitHub's public API, takes the installer's size and the SHA-256 that GitHub computed for the
uploaded asset, checks it against the published .sha256 file, and puts the entry first in releases.json. Nothing is
copied into the repository. Then review the diff, commit and push: the site rebuilds and shows the new version.

Rollback: `--latest <older version>` points the site back to an earlier release without deleting anything.
"""
from __future__ import annotations

import argparse
import json
import re
import urllib.request
from pathlib import Path

REPO = "AryanGupta-234/Nobad"
ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "releases" / "vpn" / "releases.json"
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def get(url: str, raw: bool = False):
    req = urllib.request.Request(url, headers={"User-Agent": "nobad-release-script", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    return data.decode("utf-8") if raw else json.loads(data)


def mb(n: int) -> str:
    return f"{n / 1_000_000:.1f} MB"


def entry_for(version: str, summary: str, channel: str) -> dict:
    rel = get(f"https://api.github.com/repos/{REPO}/releases/tags/vpn-v{version}")
    if rel.get("draft") or (rel.get("prerelease") and channel == "stable"):
        raise SystemExit("that release is a draft or pre-release; use --channel beta or publish it first")
    assets = {a["name"]: a for a in rel["assets"]}
    exe = f"NobadVPN-Setup-{version}.exe"
    if exe not in assets:
        raise SystemExit(f"{exe} is not attached to the release")
    a = assets[exe]
    digest = (a.get("digest") or "").removeprefix("sha256:")
    published = get(assets[exe + ".sha256"]["browser_download_url"], raw=True).split()[0].lower() if exe + ".sha256" in assets else ""
    if not re.fullmatch(r"[0-9a-f]{64}", digest or published):
        raise SystemExit("couldn't read the installer's SHA-256 from GitHub")
    if digest and published and digest != published:
        raise SystemExit(f"SHA-256 mismatch: GitHub says {digest}, the .sha256 file says {published}")
    return {
        "version": version,
        "releaseDate": rel["published_at"][:10],
        "channel": channel,
        "platform": "Windows 10 (1809+) / 11",
        "architecture": "x64 (ARM64 via emulation)",
        "summary": summary,
        "downloadUrl": a["browser_download_url"],
        "notesUrl": rel["html_url"],
        "sha256": digest or published,
        "size": mb(a["size"]),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("version", nargs="?", help="version that is already published on GitHub Releases, e.g. 1.2.1")
    ap.add_argument("summary", nargs="?", default="", help="one line for the download desk")
    ap.add_argument("--channel", default="stable")
    ap.add_argument("--latest", help="only change which listed version is current (rollback)")
    args = ap.parse_args()

    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    listed = [r["version"] for r in data["releases"]]
    if args.latest:
        if args.latest not in listed:
            raise SystemExit(f"{args.latest} isn't in releases.json ({', '.join(listed)})")
        data["latest"] = args.latest
    else:
        if not args.version or not SEMVER.match(args.version):
            raise SystemExit("give a version like 1.2.1")
        if not args.summary:
            raise SystemExit("give a one-line summary")
        if args.version in listed:
            raise SystemExit(f"{args.version} is already listed; published versions are never changed")
        data["releases"].insert(0, entry_for(args.version, args.summary, args.channel))
        data["latest"] = args.version
    MANIFEST.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"releases.json: latest = {data['latest']}. Review the diff, then commit and push.")


if __name__ == "__main__":
    main()
