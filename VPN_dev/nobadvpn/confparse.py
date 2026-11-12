"""WireGuard config parsing, validation, redaction and the streaming-tuned runtime copy."""
import ipaddress
import os
import re

from . import dpapi
from .const import NAME_RE, STREAM_MTU

EXT_ENC = ".conf.dpapi"
EXT_PLAIN = ".conf"
KEY_MASK = "(hidden)"
_B64KEY = re.compile(r"^[A-Za-z0-9+/]{43}=$")
_HOST = re.compile(r"^(?=.{1,253}$)([A-Za-z0-9]([A-Za-z0-9\-]{0,61}[A-Za-z0-9])?)(\.[A-Za-z0-9]([A-Za-z0-9\-]{0,61}[A-Za-z0-9])?)*$")
_IFACE_KEYS = {"privatekey", "address", "listenport", "dns", "mtu", "table", "preup", "postup", "predown",
               "postdown", "saveconfig", "fwmark"}
_PEER_KEYS = {"publickey", "presharedkey", "allowedips", "endpoint", "persistentkeepalive"}
_SCRIPT_KEYS = {"preup", "postup", "predown", "postdown"}


def stem_of(filename):
    """'Name.conf' / 'Name.conf.dpapi' -> 'Name' (None if it isn't a config file or the name is unusable)."""
    low = filename.lower()
    if low.endswith(EXT_ENC):
        stem = filename[: -len(EXT_ENC)]
    elif low.endswith(EXT_PLAIN):
        stem = filename[: -len(EXT_PLAIN)]
    else:
        return None
    return stem if NAME_RE.match(stem) else None


def is_encrypted(path):
    return path.lower().endswith(".dpapi")


def read_conf_text(path):
    with open(path, "rb") as f:
        raw = f.read()
    if is_encrypted(path):
        name = stem_of(os.path.basename(path)) or ""
        raw = dpapi.unprotect(raw, name)
    return raw.decode("utf-8", "replace")


def write_conf_text(path, text, encrypted=None):
    """Write CRLF text; encrypt when the path ends in .dpapi."""
    text = text.replace("\r\n", "\n").replace("\n", "\r\n")
    if not text.endswith("\r\n"):
        text += "\r\n"
    enc = is_encrypted(path) if encrypted is None else encrypted
    data = text.encode("utf-8")
    if enc:
        name = stem_of(os.path.basename(path)) or ""
        data = dpapi.protect(data, name)
    dpapi.write_atomic(path, data)


def _new_info():
    return {"host": None, "port": None, "addrs": [], "mtu": False, "keepalive": False, "full": False,
            "v6": False, "dns": False, "dns_servers": [], "peers": 0, "allowed": []}


def _lines(text):
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            yield line


def _split_endpoint(v):
    if v.startswith("["):
        host, _, rest = v[1:].partition("]")
        port = rest.lstrip(":")
    else:
        host, _, port = v.rpartition(":")
    return host, port


def parse_conf_text(text):
    info = _new_info()
    section = None
    for line in _lines(text):
        if line.startswith("["):
            section = line.strip("[]").strip().lower()
            if section == "peer":
                info["peers"] += 1
            continue
        if "=" not in line:
            continue
        k, v = (x.strip() for x in line.split("=", 1))
        k = k.lower()
        if section == "interface":
            if k == "address":
                for a in v.split(","):
                    try:
                        ipaddress.ip_interface(a.strip())
                        info["addrs"].append(a.strip())
                    except ValueError:
                        pass
            elif k == "mtu":
                info["mtu"] = True
            elif k == "dns":
                info["dns"] = True
                info["dns_servers"] = [x.strip() for x in v.split(",") if x.strip()]
        elif section == "peer":
            if k == "endpoint":
                host, port = _split_endpoint(v)
                if info["host"] is None:  # first peer's endpoint drives probing/kill-switch
                    info["host"] = host or None
                    info["port"] = int(port) if port.isdigit() else None
            elif k == "persistentkeepalive":
                info["keepalive"] = True
            elif k == "allowedips":
                vs = [x.strip() for x in v.split(",") if x.strip()]
                info["allowed"].extend(vs)
                info["full"] = info["full"] or "0.0.0.0/0" in vs
                info["v6"] = info["v6"] or "::/0" in vs
    return info


def parse_conf(path):
    try:
        return parse_conf_text(read_conf_text(path))
    except (OSError, dpapi.DpapiError):
        return _new_info()


def tuned_conf_text(text, info, stream=True, dns_fallback=None, endpoint_ip=None):
    """Runtime copy: MTU + keepalive for streaming, (optionally) a DNS line when the config has none, and
    (optionally) the first peer's Endpoint pinned to an already-resolved IP. Pinning matters because the DNS
    block / kill switch may already be armed when WireGuard starts, so WireGuard itself could not resolve a
    hostname. The stored config is never edited."""
    out = []
    pinned = False
    for line in text.splitlines():
        body = line.split("#", 1)[0]
        if endpoint_ip and not pinned and "=" in body and body.split("=", 1)[0].strip().lower() == "endpoint":
            host, port = _split_endpoint(body.split("=", 1)[1].strip())
            if host and port and host == info.get("host"):
                ip = f"[{endpoint_ip}]" if ":" in endpoint_ip else endpoint_ip
                line = f"Endpoint = {ip}:{port}"
            pinned = True
        out.append(line)
        low = line.strip().lower()
        if low == "[interface]":
            if stream and not info["mtu"]:
                out.append(f"MTU = {STREAM_MTU}")
            if dns_fallback and not info["dns"]:
                out.append(f"DNS = {dns_fallback}")
        elif low == "[peer]" and stream and not info["keepalive"]:
            out.append("PersistentKeepalive = 25")
    return "\r\n".join(out) + "\r\n"


def redact_conf(text):
    return re.sub(r"(?im)^(\s*(?:PrivateKey|PresharedKey)\s*=\s*).*$", lambda m: m.group(1) + KEY_MASK, text)


def restore_masked(new_text, old_text):
    """The editor shows keys as (hidden). On save, put the original values back (matched by order)."""
    olds = {"privatekey": [], "presharedkey": []}
    for line in old_text.splitlines():
        m = re.match(r"^\s*(PrivateKey|PresharedKey)\s*=\s*(.*)$", line, re.I)
        if m:
            olds[m.group(1).lower()].append(m.group(2).strip())
    seen = {"privatekey": 0, "presharedkey": 0}

    def sub(m):
        key = m.group(1).lower()
        val = m.group(2).strip()
        if val != KEY_MASK:
            return m.group(0)
        i = seen[key]
        seen[key] += 1
        if i < len(olds[key]):
            return f"{m.group(1)} = {olds[key][i]}"
        return m.group(0)  # nothing to restore -> validation will flag the mask as an invalid key

    return re.sub(r"(?im)^\s*(PrivateKey|PresharedKey)\s*=\s*(.*)$", sub, new_text)


def _valid_host(h):
    if not h:
        return False
    try:
        ipaddress.ip_address(h.strip("[]"))
        return True
    except ValueError:
        return bool(_HOST.match(h))


def validate_conf(text, untrusted_source=False):
    """Returns {ok, errors[], warnings[], info}. `untrusted_source` (any import: file, paste, URL, QR) rejects script hooks."""
    errors, warnings = [], []
    section = None
    n_iface = n_peer = 0
    cur = {}
    peers = []
    iface = {}
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("["):
            section = line.strip("[]").strip().lower()
            if section == "interface":
                n_iface += 1
                cur = iface
            elif section == "peer":
                n_peer += 1
                cur = {}
                peers.append(cur)
            else:
                errors.append(f"line {lineno}: unknown section [{section}]")
                cur = {}
            continue
        if "=" not in line:
            errors.append(f"line {lineno}: expected 'Key = Value'")
            continue
        if section not in ("interface", "peer"):
            errors.append(f"line {lineno}: setting outside an [Interface] or [Peer] section")
            continue
        k, v = (x.strip() for x in line.split("=", 1))
        kl = k.lower()
        known = _IFACE_KEYS if section == "interface" else _PEER_KEYS
        if kl not in known:
            warnings.append(f"line {lineno}: unknown {section} key '{k}' (WireGuard may reject it)")
        if kl in _SCRIPT_KEYS:
            if untrusted_source:
                errors.append(f"line {lineno}: '{k}' runs commands — refused for imported configs (add it in the config editor if you really need it)")
            else:
                warnings.append(f"line {lineno}: '{k}' runs commands; WireGuard ignores it unless script execution is enabled")
        cur.setdefault(kl, []).append((v, lineno))

    if n_iface != 1:
        errors.append("a config needs exactly one [Interface] section")
    if n_peer < 1:
        errors.append("a config needs at least one [Peer] section")

    def key_ok(v):
        return bool(_B64KEY.match(v))

    for v, ln in iface.get("privatekey", []):
        if not key_ok(v):
            errors.append(f"line {ln}: PrivateKey is not a valid 44-character base64 key")
    if n_iface and "privatekey" not in iface:
        errors.append("[Interface] is missing PrivateKey")
    addrs = iface.get("address", [])
    if n_iface and not addrs:
        errors.append("[Interface] is missing Address")
    for v, ln in addrs:
        for a in v.split(","):
            try:
                ipaddress.ip_interface(a.strip())
            except ValueError:
                errors.append(f"line {ln}: '{a.strip()}' is not a valid Address (use e.g. 10.0.0.2/32)")
    for v, ln in iface.get("dns", []):
        for d in (x.strip() for x in v.split(",")):
            if not d:
                continue
            try:
                ipaddress.ip_address(d)
            except ValueError:
                if not _HOST.match(d):
                    errors.append(f"line {ln}: '{d}' is not a valid DNS server or search domain")
    for v, ln in iface.get("mtu", []):
        if not v.isdigit() or not (576 <= int(v) <= 1500):
            errors.append(f"line {ln}: MTU must be a number between 576 and 1500")
        elif int(v) < 1280:
            warnings.append(f"line {ln}: MTU below 1280 breaks IPv6 inside the tunnel")
    for v, ln in iface.get("listenport", []):
        if not v.isdigit() or not (1 <= int(v) <= 65535):
            errors.append(f"line {ln}: ListenPort must be 1-65535")

    for i, p in enumerate(peers, 1):
        tag = f"peer {i}"
        if "publickey" not in p:
            errors.append(f"{tag}: missing PublicKey")
        for v, ln in p.get("publickey", []):
            if not key_ok(v):
                errors.append(f"line {ln}: PublicKey is not a valid 44-character base64 key")
        for v, ln in p.get("presharedkey", []):
            if not key_ok(v):
                errors.append(f"line {ln}: PresharedKey is not a valid 44-character base64 key")
        if "allowedips" not in p:
            errors.append(f"{tag}: missing AllowedIPs")
        for v, ln in p.get("allowedips", []):
            for a in v.split(","):
                try:
                    ipaddress.ip_network(a.strip(), strict=False)
                except ValueError:
                    errors.append(f"line {ln}: '{a.strip()}' is not a valid AllowedIPs entry")
        for v, ln in p.get("endpoint", []):
            host, port = _split_endpoint(v)
            if not _valid_host(host) or not port.isdigit() or not (1 <= int(port) <= 65535):
                errors.append(f"line {ln}: Endpoint must look like host:port or [ipv6]:port")
        for v, ln in p.get("persistentkeepalive", []):
            if not (v.isdigit() and 0 <= int(v) <= 65535) and v.lower() != "off":
                errors.append(f"line {ln}: PersistentKeepalive must be 0-65535 or 'off'")
        if "endpoint" not in p:
            warnings.append(f"{tag}: no Endpoint — NOBAD cannot probe or kill-switch this server")

    info = parse_conf_text(text)
    if info["full"] and not info["dns"]:
        warnings.append("full-tunnel config without a DNS line — NOBAD will add a fallback DNS if that setting is on")
    return {"ok": not errors, "errors": errors, "warnings": warnings, "info": info}
