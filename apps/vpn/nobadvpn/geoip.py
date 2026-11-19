"""Offline endpoint geolocation: which country a server's address is in, from a file shipped with the app.

Nothing is sent anywhere. The data is DB-IP's "IP to Country Lite" (CC BY 4.0, https://db-ip.com, see
THIRD-PARTY-NOTICES.md), reduced at build time by `compact()` (packaging/make_geoip.py) to
`nobadvpn/data/geoip-country.bin`: sorted, merged ranges as packed arrays (IPv4 as 32-bit numbers, IPv6 by its
first 64 bits, which is finer than any range DB-IP lists), about 5 MB, loaded in a fraction of a second and
searched by bisection.

Used by engine.Tunnel.geo_refresh for the endpoint addresses the engine already has (from an import or a connect: no
new DNS lookups). The online lookup (ipinfo.io, behind the "IP lookup" setting, off by default) still adds a city
when it's on. Without the file (a source run that didn't build it) every lookup answers None, and the window shows
"location unknown" rather than a guess.
"""
import array
import bisect
import gzip
import ipaddress
import os
import re
import struct
import threading

MAGIC = b"NBGEO1\n"
_CC = re.compile(r"^[A-Z]{2}$")
_NOT_COUNTRIES = {"ZZ", "XX", "EU", "AP", "A1", "A2", "O1"}


def default_path():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "data", "geoip-country.bin")


def _key(ip):
    """(4 or 6, integer) for an address, or None. IPv4-mapped IPv6 stays IPv6 (as DB-IP lists it)."""
    try:
        a = ipaddress.ip_address(str(ip).strip())
    except ValueError:
        return None
    return (a.version, int(a))


def _fold(fam, n):
    """The number a family's table is sorted by: IPv4 as is, IPv6 by its first 64 bits."""
    return n if fam == 4 else n >> 64


class Db:
    """Packed, sorted ranges per family, loaded on first use, then bisected."""

    def __init__(self, path=None):
        self.path = path or default_path()
        self._lock = threading.Lock()
        self._loaded = False
        self._t = {4: (array.array("I"), array.array("I"), b""), 6: (array.array("Q"), array.array("Q"), b"")}

    @property
    def available(self):
        self._load()
        return bool(len(self._t[4][0]) or len(self._t[6][0]))

    def _load(self):
        with self._lock:
            if self._loaded:
                return
            self._loaded = True
            try:
                with open(self.path, "rb") as f:
                    raw = f.read(64 * 1024 * 1024)
                if not raw.startswith(MAGIC):
                    return
                pos = len(MAGIC)
                for fam, code in ((4, "I"), (6, "Q")):
                    (n,) = struct.unpack_from("<I", raw, pos)
                    pos += 4
                    size = array.array(code).itemsize
                    starts, ends = array.array(code), array.array(code)
                    starts.frombytes(raw[pos:pos + n * size])
                    pos += n * size
                    ends.frombytes(raw[pos:pos + n * size])
                    pos += n * size
                    cc = raw[pos:pos + n * 2]
                    pos += n * 2
                    if len(starts) != n or len(ends) != n or len(cc) != 2 * n:
                        raise ValueError("truncated")
                    self._t[fam] = (starts, ends, cc)
            except (OSError, ValueError, struct.error):
                self._t = {4: (array.array("I"), array.array("I"), b""), 6: (array.array("Q"), array.array("Q"), b"")}

    def country(self, ip):
        """ISO 3166 code for a public address, or None (unknown, private, reserved, not an address)."""
        k = _key(ip)
        if k is None:
            return None
        try:
            if not ipaddress.ip_address(str(ip).strip()).is_global:
                return None
        except ValueError:
            return None
        self._load()
        fam, n = k
        starts, ends, cc = self._t[fam]
        v = _fold(fam, n)
        i = bisect.bisect_right(starts, v) - 1
        if i < 0 or v > ends[i]:
            return None
        return cc[2 * i:2 * i + 2].decode("ascii")


_db = None


def lookup(ip):
    """The bundled database's country for `ip`, or None."""
    global _db
    if _db is None:
        _db = Db()
    return _db.country(ip)


def compact(src, dest):
    """DB-IP's CSV (`first,last,CC`, maybe more columns; .csv or .csv.gz) -> the packed file the app reads. Returns
    the number of ranges kept after merging neighbours of the same country. Lines that aren't a valid range with a
    real country code are dropped."""
    rows = {4: [], 6: []}
    opener = gzip.open if str(src).endswith(".gz") else open
    with opener(src, "rt", encoding="utf-8", errors="replace") as f:
        for line in f:
            parts = [p.strip().strip('"') for p in line.strip().split(",")]
            if len(parts) < 3:
                continue
            a, b, cc = _key(parts[0]), _key(parts[1]), parts[2].upper()
            if not a or not b or a[0] != b[0] or a[1] > b[1] or not _CC.match(cc) or cc in _NOT_COUNTRIES:
                continue
            rows[a[0]].append((_fold(a[0], a[1]), _fold(a[0], b[1]), cc))
    out = bytearray(MAGIC)
    kept = 0
    for fam, code in ((4, "I"), (6, "Q")):
        merged = []
        for s, e, cc in sorted(rows[fam]):
            if merged and merged[-1][2] == cc and s <= merged[-1][1] + 1:
                merged[-1][1] = max(merged[-1][1], e)
            elif merged and s <= merged[-1][1]:
                continue                                    # overlaps a different country: keep the first
            else:
                merged.append([s, e, cc])
        out += struct.pack("<I", len(merged))
        out += array.array(code, [m[0] for m in merged]).tobytes()
        out += array.array(code, [m[1] for m in merged]).tobytes()
        out += "".join(m[2] for m in merged).encode("ascii")
        kept += len(merged)
    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    tmp = dest + ".tmp"
    with open(tmp, "wb") as f:
        f.write(bytes(out))
    os.replace(tmp, dest)
    return kept
