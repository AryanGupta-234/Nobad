"""Software bill of materials (CycloneDX 1.5 JSON) for a release: every component the installer bundles, with
version, licence and, for the bundled WireGuard installers, the SHA-256. Usage:
    python packaging/make_sbom.py <version> <out.json>"""
import datetime
import hashlib
import importlib.metadata as md
import json
import os
import platform
import sys
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Python packages that end up inside the app (test/build tools are not shipped).
BUNDLED = ["pywebview", "pythonnet", "clr_loader", "bottle", "proxy_tools", "pystray", "pillow", "cffi", "pycparser",
           "six", "typing_extensions"]


def _licence(meta):
    expr = meta.get("License-Expression")
    if expr:
        return {"expression": expr}
    lic = (meta.get("License") or "").strip()
    if lic and len(lic) < 60 and "\n" not in lic:
        return {"license": {"name": lic}}
    for c in meta.get_all("Classifier") or []:
        if c.startswith("License :: OSI Approved :: "):
            return {"license": {"name": c.split("::")[-1].strip()}}
    return None


def components():
    out = []
    for name in BUNDLED:
        try:
            meta = md.metadata(name)
        except md.PackageNotFoundError:
            continue
        c = {"type": "library", "name": meta["Name"], "version": meta["Version"],
             "purl": f"pkg:pypi/{meta['Name'].lower()}@{meta['Version']}"}
        lic = _licence(meta)
        if lic:
            c["licenses"] = [lic]
        out.append(c)
    out.append({"type": "framework", "name": "CPython", "version": platform.python_version(),
                "licenses": [{"license": {"id": "PSF-2.0"}}]})
    redist = os.path.join(ROOT, "packaging", "redist")
    for arch in ("amd64", "arm64"):
        p = os.path.join(redist, f"wireguard-{arch}.msi")
        if os.path.exists(p):
            ver = open(p + ".version").read().strip() if os.path.exists(p + ".version") else "unknown"
            with open(p, "rb") as f:
                sha = hashlib.sha256(f.read()).hexdigest()
            out.append({"type": "application", "name": f"WireGuard for Windows ({arch})", "version": ver,
                        "supplier": {"name": "WireGuard LLC"}, "hashes": [{"alg": "SHA-256", "content": sha}]})
    out.append({"type": "library", "name": "jsQR", "version": "vendored", "licenses": [{"license": {"id": "Apache-2.0"}}]})
    return out


def sbom(version):
    return {"bomFormat": "CycloneDX", "specVersion": "1.5", "serialNumber": f"urn:uuid:{uuid.uuid4()}", "version": 1,
            "metadata": {"timestamp": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                         "component": {"type": "application", "name": "NOBAD VPN", "version": version,
                                       "licenses": [{"license": {"id": "MIT"}}],
                                       "externalReferences": [{"type": "vcs", "url": "https://github.com/AryanGupta-234/Nobad"}]}},
            "components": components()}


if __name__ == "__main__":
    ver, out = sys.argv[1], sys.argv[2]
    with open(out, "w", encoding="utf-8") as f:
        json.dump(sbom(ver), f, indent=1)
    print(f"SBOM written: {out} ({len(sbom(ver)['components'])} components)")
