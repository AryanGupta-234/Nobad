"""Build-time only: fetch DB-IP's "IP to Country Lite" (CC BY 4.0) and reduce it to the file NOBAD VPN reads offline
(nobadvpn/data/geoip-country.bin, see nobadvpn/geoip.py). The app itself never downloads it and never sends an
address anywhere for it.

    python packaging/make_geoip.py 2026-11            # the month's file from download.db-ip.com
    python packaging/make_geoip.py --file <csv(.gz)>  # a file you downloaded yourself

Attribution (required by the licence) is in THIRD-PARTY-NOTICES.md; the packed file has no room for it.
"""
import argparse
import hashlib
import os
import sys
import tempfile
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from nobadvpn import geoip  # noqa: E402

URL = "https://download.db-ip.com/free/dbip-country-lite-{month}.csv.gz"
MAX = 64 * 1024 * 1024


def fetch(month, dest):
    url = URL.format(month=month)
    req = urllib.request.Request(url, headers={"User-Agent": "NobadVPN-build"})
    h, n = hashlib.sha256(), 0
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            n += len(chunk)
            if n > MAX:
                raise SystemExit("download is larger than expected; refusing")
            h.update(chunk)
            f.write(chunk)
    print(f"downloaded {url} ({n} bytes, sha256 {h.hexdigest()})")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("month", nargs="?", help="YYYY-MM")
    p.add_argument("--file")
    a = p.parse_args()
    out = os.path.join(os.path.dirname(HERE), "nobadvpn", "data", "geoip-country.bin")
    src = a.file
    if not src:
        if not a.month:
            p.error("give a month (YYYY-MM) or --file")
        src = os.path.join(tempfile.mkdtemp(prefix="nobad-geoip-"), "dbip.csv.gz")
        fetch(a.month, src)
    n = geoip.compact(src, out)
    print(f"{n} ranges -> {out} ({os.path.getsize(out)} bytes)")


if __name__ == "__main__":
    main()
