"""Create the update manifest for a release:
    python packaging/make_manifest.py dist-installer/NobadVPN-Setup-<ver>.exe https://host/path/NobadVPN-Setup-<ver>.exe "notes" [--out latest.json]
Without --out the JSON is printed. With --out it is written as UTF-8 without a BOM (PowerShell's Out-File adds one)."""
import argparse
import hashlib
import json
import re

p = argparse.ArgumentParser()
p.add_argument("installer")
p.add_argument("url")
p.add_argument("notes", nargs="?", default="")
p.add_argument("--out")
a = p.parse_args()
if not a.url.lower().startswith("https://"):
    raise SystemExit("the installer URL must be https://")
m = re.search(r"Setup-(.+)\.exe$", a.installer.replace("\\", "/").split("/")[-1])
if not m:
    raise SystemExit("installer name must look like NobadVPN-Setup-<version>.exe")
h = hashlib.sha256()
with open(a.installer, "rb") as f:
    for chunk in iter(lambda: f.read(1 << 20), b""):
        h.update(chunk)
text = json.dumps({"version": m.group(1), "url": a.url, "sha256": h.hexdigest(), "notes": a.notes}, indent=1)
if a.out:
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(text + "\n")
else:
    print(text)
