"""Minimal DNS wire client (RFC 1035/6891/7766/8484) for resolver comparison. Results are real wire data only:
build_query()/parse_response() are pure; query()/query_doh() validate ID + question and never raise on network errors.
"""
import errno
import http.client
import ipaddress
import secrets
import socket
import ssl
import struct
import time
import urllib.error
import urllib.parse
import urllib.request

TYPES = {"A": 1, "NS": 2, "CNAME": 5, "SOA": 6, "PTR": 12, "MX": 15, "TXT": 16, "AAAA": 28}
TYPE_NAMES = {v: k for k, v in TYPES.items()}
RCODES = {0: "NOERROR", 1: "FORMERR", 2: "SERVFAIL", 3: "NXDOMAIN", 4: "NOTIMP", 5: "REFUSED", 6: "YXDOMAIN",
          7: "YXRRSET", 8: "NXRRSET", 9: "NOTAUTH", 10: "NOTZONE", 16: "BADVERS"}
OPT, CLASS_IN, EDNS_PAYLOAD, MAX_JUMPS = 41, 1, 1232, 32
_FLAG_BITS = {"aa": 0x0400, "tc": 0x0200, "rd": 0x0100, "ra": 0x0080, "ad": 0x0020, "cd": 0x0010}


class Malformed(Exception):
    """Internal: raised while parsing; parse_response() turns it into error="malformed"."""


def _type_code(rtype):
    if isinstance(rtype, int) and not isinstance(rtype, bool):
        if 0 < rtype < 65536:
            return rtype
    elif isinstance(rtype, str) and rtype.upper() in TYPES:
        return TYPES[rtype.upper()]
    raise ValueError(f"unsupported rtype: {rtype!r}")


def _type_name(code):
    return TYPE_NAMES.get(code, f"TYPE{code}")


def _norm_name(name):
    """Lowercase ASCII (IDNA for non-ASCII) name without trailing dot; ValueError if not a valid DNS name."""
    if not isinstance(name, str):
        raise ValueError("name must be a string")
    name = name.strip().rstrip(".")
    try:
        name = name.encode("ascii").decode()
    except UnicodeEncodeError:
        try:
            name = name.encode("idna").decode()
        except UnicodeError as e:
            raise ValueError(f"invalid name: {e}") from None
    if len(name) > 253:
        raise ValueError("name longer than 253 characters")
    for label in name.split(".") if name else []:
        if not label or len(label) > 63:
            raise ValueError("empty label or label longer than 63 characters")
    return name.lower()


def _encode_name(name):
    name = _norm_name(name)
    out = b"".join(bytes([len(lb)]) + lb.encode() for lb in name.split(".")) if name else b""
    return out + b"\x00"


def build_query(name, rtype="A", rd=True, edns=True, qid=None):
    """Return (wire bytes, id). qid=None picks a random 16-bit ID."""
    code = _type_code(rtype)
    qid = secrets.randbelow(65536) if qid is None else qid
    msg = struct.pack("!6H", qid, _FLAG_BITS["rd"] if rd else 0, 1, 0, 0, 1 if edns else 0)
    msg += _encode_name(name) + struct.pack("!HH", code, CLASS_IN)
    msg += (b"\x00" + struct.pack("!HHIH", OPT, EDNS_PAYLOAD, 0, 0)) if edns else b""
    return msg, qid


def _read_name(msg, off):
    labels, jumps, end, total = [], 0, None, 0
    while True:
        if off >= len(msg):
            raise Malformed("name out of bounds")
        ln = msg[off]
        if ln & 0xC0 == 0xC0:
            if off + 1 >= len(msg):
                raise Malformed("pointer out of bounds")
            jumps += 1
            if jumps > MAX_JUMPS:
                raise Malformed("compression loop")
            if end is None:
                end = off + 2
            off = ((ln & 0x3F) << 8) | msg[off + 1]
            continue
        if ln & 0xC0:
            raise Malformed("bad label type")
        off += 1
        if ln == 0:
            break
        if off + ln > len(msg):
            raise Malformed("label out of bounds")
        total += ln + 1
        if total > 255:
            raise Malformed("name too long")
        labels.append(msg[off:off + ln].decode("ascii", "replace").lower())
        off += ln
    return ".".join(labels), (off if end is None else end)


def _rdata(msg, t, off, rdlen):
    end, raw = off + rdlen, msg[off:off + rdlen]
    if t in (1, 28):
        if rdlen != (4 if t == 1 else 16):
            raise Malformed("bad address length")
        return str(ipaddress.ip_address(raw))
    if t in (2, 5, 12, 15):
        if t == 15 and rdlen < 3:
            raise Malformed("short MX")
        target, o = _read_name(msg, off + 2 if t == 15 else off)
        if o != end:
            raise Malformed("rdata length mismatch")
        return {"preference": struct.unpack_from("!H", msg, off)[0], "exchange": target} if t == 15 else target
    if t == 16:
        out, i = [], 0
        while i < rdlen:
            if i + 1 + raw[i] > rdlen:
                raise Malformed("TXT out of bounds")
            out.append(raw[i + 1:i + 1 + raw[i]].decode("utf-8", errors="replace"))
            i += 1 + raw[i]
        return out
    if t == 6:
        mname, o = _read_name(msg, off)
        rname, o = _read_name(msg, o)
        if o + 20 != end:
            raise Malformed("rdata length mismatch")
        vals = struct.unpack_from("!5I", msg, o)
        return dict(mname=mname, rname=rname, **dict(zip(("serial", "refresh", "retry", "expire", "minimum"), vals)))
    return {"type_code": t, "hex": raw.hex()}


def _read_rr(msg, off):
    name, off = _read_name(msg, off)
    if off + 10 > len(msg):
        raise Malformed("RR header out of bounds")
    t, _cls, ttl, rdlen = struct.unpack_from("!HHIH", msg, off)
    off += 10
    if off + rdlen > len(msg):
        raise Malformed("rdata out of bounds")
    if t == OPT:
        return {"opt": True, "ttl": ttl}, off + rdlen
    return {"name": name, "type": _type_name(t), "ttl": ttl, "data": _rdata(msg, t, off, rdlen)}, off + rdlen


def parse_response(data):
    """Parse a DNS message. Never raises; returns {"error": "malformed", ...} for bad packets."""
    out = {"id": None, "qr": False, "rcode": None, "rcode_name": None, "flags": {k: False for k in _FLAG_BITS},
           "questions": [], "answers": [], "authority": [], "additional": [], "error": None}
    try:
        if len(data) < 12:
            raise Malformed("short header")
        qid, flags, qd, an, ns, ar = struct.unpack_from("!6H", data, 0)
        off, questions, sections, ext = 12, [], {"answers": [], "authority": [], "additional": []}, 0
        for _ in range(qd):
            qname, off = _read_name(data, off)
            if off + 4 > len(data):
                raise Malformed("question out of bounds")
            qt, qc = struct.unpack_from("!HH", data, off)
            off += 4
            questions.append({"name": qname, "type": _type_name(qt), "class": qc})
        for key, count in (("answers", an), ("authority", ns), ("additional", ar)):
            for _ in range(count):
                rr, off = _read_rr(data, off)
                if rr.get("opt"):
                    ext = rr["ttl"] >> 24
                else:
                    sections[key].append(rr)
    except (Malformed, struct.error, ValueError, IndexError):
        out["error"] = "malformed"
        return out
    rcode = (ext << 4) | (flags & 0x000F)
    out.update(id=qid, qr=bool(flags & 0x8000), rcode=rcode, rcode_name=RCODES.get(rcode, f"RCODE{rcode}"),
               flags={k: bool(flags & bit) for k, bit in _FLAG_BITS.items()}, questions=questions, **sections)
    return out


def _matches(parsed, qid, qname, code):
    q = parsed["questions"]
    return (parsed["error"] is None and parsed["qr"] and parsed["id"] == qid and len(q) == 1
            and q[0]["name"] == qname and q[0]["type"] == _type_name(code) and q[0]["class"] == CLASS_IN)


def _result(server, transport, name, code, parsed=None, rtt=0.0, error=None):
    r = {"server": server, "transport": transport, "name": name, "type": _type_name(code), "rcode": None,
         "rcode_name": None, "flags": {k: False for k in _FLAG_BITS}, "answers": [], "authority": [],
         "additional": [], "rtt_ms": round(rtt * 1000.0, 3), "error": error}
    if parsed is not None and error is None:
        r.update({k: parsed[k] for k in ("rcode", "rcode_name", "flags", "answers", "authority", "additional")})
    return r


def _net_error(e):
    if isinstance(e, (socket.timeout, TimeoutError)):
        return "timeout"
    if isinstance(e, (ConnectionRefusedError, ConnectionResetError)):
        return "refused-connection"
    codes = {getattr(e, "errno", None), getattr(e, "winerror", None)}
    if codes & {errno.ENETUNREACH, errno.EHOSTUNREACH, 10051, 10065}:
        return "network-unreachable"
    return "network-error"


def _recv_exact(sock, n, deadline):
    buf = b""
    while len(buf) < n:
        sock.settimeout(max(deadline - time.perf_counter(), 0.001))
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionResetError("closed")
        buf += chunk
    return buf


def _udp(msg, qid, qname, code, fam, addr, deadline):
    """Return parsed response or an error string. Non-matching datagrams are ignored until the deadline."""
    seen_malformed = False
    with socket.socket(fam, socket.SOCK_DGRAM) as s:
        s.connect(addr)
        s.send(msg)
        while True:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                return "malformed" if seen_malformed else "timeout"
            s.settimeout(remaining)
            try:
                parsed = parse_response(data := s.recv(65535))
            except (socket.timeout, TimeoutError):
                continue
            if _matches(parsed, qid, qname, code):
                return parsed
            seen_malformed |= parsed["error"] is not None and data[:2] == msg[:2]


def _tcp(msg, qid, qname, code, fam, addr, deadline):
    with socket.socket(fam, socket.SOCK_STREAM) as s:
        s.settimeout(max(deadline - time.perf_counter(), 0.001))
        s.connect(addr)
        s.sendall(struct.pack("!H", len(msg)) + msg)
        n = struct.unpack("!H", _recv_exact(s, 2, deadline))[0]
        parsed = parse_response(_recv_exact(s, n, deadline))
    return parsed if _matches(parsed, qid, qname, code) else "malformed"


def query(name, rtype="A", server="1.1.1.1", port=53, timeout=2.0, tcp=False, rd=True, edns=True):
    """Ask one resolver over UDP (TCP fallback on TC, or tcp=True). Never raises for network errors."""
    code, qname = _type_code(rtype), _norm_name(name)
    ip = ipaddress.ip_address(server)  # ValueError for a non-IP server
    fam, addr = (socket.AF_INET6 if ip.version == 6 else socket.AF_INET), (str(ip), int(port))
    msg, qid = build_query(qname, code, rd=rd, edns=edns)
    transport, start = ("tcp" if tcp else "udp"), time.perf_counter()
    try:
        res = (_tcp if tcp else _udp)(msg, qid, qname, code, fam, addr, start + timeout)
        if not tcp and isinstance(res, dict) and res["flags"]["tc"]:
            transport = "tcp"
            res = _tcp(msg, qid, qname, code, fam, addr, time.perf_counter() + timeout)
    except OSError as e:
        res = _net_error(e)
    err, parsed = (res, None) if isinstance(res, str) else (None, res)
    return _result(str(ip), transport, qname, code, parsed, time.perf_counter() - start, err)


def query_doh(name, rtype="A", url="https://cloudflare-dns.com/dns-query", timeout=4.0):
    """RFC 8484 POST query (ID 0). TLS verification uses the default context. Never raises for network errors."""
    code, qname = _type_code(rtype), _norm_name(name)
    if urllib.parse.urlsplit(url).scheme != "https":
        raise ValueError("DoH url must be https")
    msg, qid = build_query(qname, code, rd=True, edns=True, qid=0)
    req = urllib.request.Request(url, data=msg, method="POST", headers={
        "Content-Type": "application/dns-message", "Accept": "application/dns-message"})
    start, err, parsed = time.perf_counter(), None, None
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            parsed = parse_response(r.read(65536))
        if not _matches(parsed, qid, qname, code):
            err = "malformed"
    except urllib.error.HTTPError as e:
        err = f"http-{e.code}"
    except urllib.error.URLError as e:
        err = ("tls-error" if isinstance(e.reason, ssl.SSLError)
               else _net_error(e.reason) if isinstance(e.reason, OSError) else "network-error")
    except ssl.SSLError:
        err = "tls-error"
    except http.client.HTTPException:
        err = "network-error"
    except OSError as e:
        err = _net_error(e)
    return _result(url, "doh", qname, code, parsed, time.perf_counter() - start, err)


def ptr_name(ip):
    """'1.2.3.4' -> '4.3.2.1.in-addr.arpa'; IPv6 -> nibble ip6.arpa name."""
    return ipaddress.ip_address(ip).reverse_pointer
