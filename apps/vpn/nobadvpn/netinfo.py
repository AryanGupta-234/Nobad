"""Network facts without touching configuration: physical route fingerprint, caps, SSID, captive portal."""
import http.client
import ipaddress
import os
import re
import socket

from .syscmd import run, ping_stats


def local_route_ip(dest, family):
    """Source address the OS would use to reach `dest` (UDP connect sends nothing)."""
    s = None
    try:
        s = socket.socket(family, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect((dest, 53))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        if s:
            s.close()


def net_caps():
    """{'v4': bool, 'v6': bool} — does the OS have a usable route for each family right now?"""
    return {"v4": local_route_ip("1.1.1.1", socket.AF_INET) is not None,
            "v6": local_route_ip("2606:4700:4700::1111", socket.AF_INET6) is not None}


def parse_route_v4(text, tun_ips=()):
    """Default routes from `route print -4 0.0.0.0`, minus on-link routes and the tunnel's own interface.
    Returns [(gateway, interface_ip, metric)]."""
    tun = {str(t) for t in tun_ips}
    out = []
    for line in (text or "").splitlines():
        p = line.split()
        if len(p) >= 5 and p[0] == "0.0.0.0" and p[1] == "0.0.0.0" and p[3] not in tun:
            try:
                gw = str(ipaddress.ip_address(p[2]))
                met = int(p[4])
            except ValueError:
                continue  # 'On-link' = the tunnel's own route
            if gw != "0.0.0.0":
                out.append((gw, p[3], met))
    return out


def parse_route_v6(text):
    """Default gateways from `route print -6` (rows: If Metric Destination Gateway)."""
    out = []
    for line in (text or "").splitlines():
        p = line.split()
        if len(p) >= 4 and p[2] == "::/0":
            try:
                ipaddress.ip_address(p[3].split("%")[0])
            except ValueError:
                continue  # On-link
            out.append((p[3], p[0]))
    return out


def physical_fingerprint(tun_ips=()):
    """Frozenset describing the physical uplink(s). Unchanged by the VPN connecting; changes on Wi-Fi<->Ethernet,
    roaming to another router, or losing the network (empty set)."""
    if os.name != "nt":
        v4 = local_route_ip("1.1.1.1", socket.AF_INET)
        return frozenset(filter(None, [("v4", v4)] if v4 else []))
    fp = set()
    for gw, ifip, _m in parse_route_v4(run(["route", "print", "-4", "0.0.0.0"], timeout=8).stdout, tun_ips):
        fp.add(("v4", gw, ifip))
    for gw, ifi in parse_route_v6(run(["route", "print", "-6"], timeout=8).stdout):
        fp.add(("v6", gw, ifi))
    return frozenset(fp)


def default_gateway(tun_ips=()):
    """Real LAN gateway (the router), skipping the VPN's own on-link default route."""
    if os.name != "nt":
        return None
    ps = ("Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | "
          "Where-Object { $_.NextHop -and $_.NextHop -ne '0.0.0.0' } | "
          "ForEach-Object { $a = Get-NetAdapter -InterfaceIndex $_.InterfaceIndex -ErrorAction SilentlyContinue; "
          "$m = (Get-NetIPInterface -AddressFamily IPv4 -InterfaceIndex $_.InterfaceIndex -ErrorAction SilentlyContinue).InterfaceMetric; "
          "[pscustomobject]@{NH=$_.NextHop; M=[int]$_.RouteMetric+[int]$m; D=[string]$a.InterfaceDescription} } | "
          "Where-Object { $_.D -notmatch 'WireGuard|Wintun|TAP|OpenVPN' } | "
          "Sort-Object M | Select-Object -First 1 -ExpandProperty NH")
    r = run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], timeout=10)
    for line in (r.stdout or "").splitlines():
        try:
            gw = str(ipaddress.ip_address(line.strip()))
            if gw != "0.0.0.0":
                return gw
        except ValueError:
            pass
    routes = parse_route_v4(run(["route", "print", "-4", "0.0.0.0"], timeout=8).stdout, tun_ips)
    return min(routes, key=lambda r: r[2])[0] if routes else None


_SSID = re.compile(r"^\s*SSID\s*:\s*(.+?)\s*$", re.M)


def parse_ssid(netsh_output):
    m = _SSID.search(netsh_output or "")  # BSSID lines start with 'BSSID', so ^\s*SSID can't match them
    return m.group(1) if m else None


# Returned when Wi-Fi is in use but Windows hides its name (Windows 11 24H2+ without location permission).
# It is never treated as trusted, so a hidden name can only ever lead to *more* protection.
UNKNOWN_WIFI = "Wi-Fi (name hidden)"
_WLAN_STATE = re.compile(r"^\s*State\s*:\s*connected\s*$", re.M | re.I)


def _wifi_profile_name():
    """Fallback when netsh hides the SSID: the network-profile name of a connected wireless adapter
    (Windows names Wi-Fi profiles after the SSID). Returns (is_wifi, name|None)."""
    ps = ("$w = Get-NetAdapter -Physical -ErrorAction SilentlyContinue | Where-Object { $_.Status -eq 'Up' -and "
          "($_.PhysicalMediaType -match '802[.]11' -or $_.NdisPhysicalMedium -eq 9) }; "
          "if ($w) { $p = Get-NetConnectionProfile -InterfaceIndex $w[0].ifIndex -ErrorAction SilentlyContinue; "
          "'WIFI|' + [string]$p.Name } else { 'NOWIFI|' }")
    out = (run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], timeout=10).stdout or "").strip()
    kind, _, name = out.partition("|")
    if kind.strip().endswith("NOWIFI") or not kind.strip().endswith("WIFI"):
        return False, None
    return True, (name.strip() or None)  # exact match only: never loosen a trust decision


_BSSID = re.compile(r"^\s*(?:AP\s+)?BSSID\s*:\s*([0-9A-Fa-f]{2}(?:[:-][0-9A-Fa-f]{2}){5})\s*$", re.M)
_AUTH = re.compile(r"^\s*Authentication\s*:\s*(.+?)\s*$", re.M)
_ARP_MAC = re.compile(r"\b([0-9A-Fa-f]{2}(?:-[0-9A-Fa-f]{2}){5})\b")
# Authentication values (netsh) that mean anyone nearby can join and copy the network: never trustable.
OPEN_AUTH = ("open", "none", "")


def norm_mac(mac):
    return (mac or "").strip().lower().replace("-", ":")


def parse_wlan(netsh_output):
    """{'ssid', 'bssid', 'auth'} of the connected Wi-Fi from `netsh wlan show interfaces` (first interface)."""
    out = netsh_output or ""
    b, a = _BSSID.search(out), _AUTH.search(out)
    return {"ssid": parse_ssid(out), "bssid": norm_mac(b.group(1)) if b else None,
            "auth": a.group(1) if a else None}


def parse_arp_mac(arp_output, ip):
    for line in (arp_output or "").splitlines():
        if line.split()[:1] == [ip]:
            m = _ARP_MAC.search(line)
            if m and m.group(1).lower() not in ("ff-ff-ff-ff-ff-ff", "00-00-00-00-00-00"):
                return norm_mac(m.group(1))
    return None


def gateway_mac():
    """MAC address of the LAN router (from the ARP cache), or None. Identifies a wired network far better than
    the generic name 'Ethernet'."""
    if os.name != "nt":
        return None
    gw = default_gateway()
    if not gw:
        return None
    run(["ping", "-n", "1", "-w", "500", gw], timeout=4)      # make sure the ARP cache has the router
    return parse_arp_mac(run(["arp", "-a", gw], timeout=6).stdout, gw)


def current_network_identity():
    """What a trust decision is based on (#15): {'name', 'kind': 'wifi'|'wired', 'auth', 'bssid', 'gw_mac'}, or
    None when offline. A field NOBAD couldn't read is None, and a network missing any field it needs is never
    treated as trusted."""
    name = current_network_name()
    if name is None:
        return None
    if name == "Ethernet":
        return {"name": name, "kind": "wired", "auth": None, "bssid": None, "gw_mac": gateway_mac()}
    w = parse_wlan(run(["netsh", "wlan", "show", "interfaces"], timeout=8).stdout) if os.name == "nt" else {}
    same = w.get("ssid") == name
    # Without Location permission Windows hides the access point and security type; the router still identifies it.
    return {"name": name, "kind": "wifi", "auth": w.get("auth") if same else None,
            "bssid": w.get("bssid") if same else None, "gw_mac": gateway_mac()}


def current_network_name():
    """Wi-Fi SSID, 'Ethernet' for a wired uplink, UNKNOWN_WIFI when Wi-Fi is up but its name is hidden,
    or None when offline."""
    if os.name == "nt":
        out = run(["netsh", "wlan", "show", "interfaces"], timeout=8).stdout or ""
        ssid = parse_ssid(out)
        if ssid:
            return ssid
        if not physical_fingerprint():
            return None
        wifi, name = _wifi_profile_name()
        if wifi:
            return name or UNKNOWN_WIFI
        if _WLAN_STATE.search(out) or "location" in out.lower():
            return UNKNOWN_WIFI   # Wi-Fi may be in use but we can't see it: never call that "Ethernet"
        return "Ethernet"
    return "Ethernet" if physical_fingerprint() else None


CAPTIVE_PROBES = [("www.msftconnecttest.com", "/connecttest.txt", 200, "Microsoft Connect Test"),
                  ("connectivitycheck.gstatic.com", "/generate_204", 204, "")]


def captive_check(timeout=4):
    """Same idea as the OS check: plain-HTTP fetch that must come back untouched.
    Returns {'status': 'open'|'captive'|'offline', 'portal': url|None}. Never follows redirects."""
    for host, path, want_code, want_body in CAPTIVE_PROBES:
        conn = None
        try:
            conn = http.client.HTTPConnection(host, 80, timeout=timeout)
            conn.request("GET", path, headers={"User-Agent": "NCSI", "Cache-Control": "no-cache"})
            r = conn.getresponse()
            body = r.read(512).decode("utf-8", "replace").strip()
            if r.status == want_code and (not want_body or body == want_body):
                return {"status": "open", "portal": None}
            loc = r.getheader("Location")
            return {"status": "captive", "portal": loc if loc and loc.startswith("http") else None}
        except (OSError, http.client.HTTPException):
            continue
        finally:
            if conn:
                conn.close()
    return {"status": "offline", "portal": None}


def endpoint_report(host, port, ips):
    """Used by the 'Check endpoint' action: DNS, ICMP, TCP reachability — nothing is changed."""
    rep = {"host": host, "port": port, "resolved": ips, "dns_ok": bool(ips), "icmp": None, "tcp": None, "notes": []}
    if not ips:
        rep["notes"].append("The server name did not resolve. Check the Endpoint line and your DNS/network.")
        return rep
    p = ping_stats(ips[0], 3, 1200)
    rep["icmp"] = p
    if p["rtt"] is None:
        rep["notes"].append("No ping reply (many VPN servers block ICMP, so this is not conclusive).")
    for prt in (443, 80):
        try:
            s = socket.create_connection((ips[0], prt), 2.0)
            s.close()
            rep["tcp"] = prt
            break
        except OSError:
            continue
    if p["rtt"] is None and rep["tcp"] is None:
        rep["notes"].append("The host did not answer ping or TCP. WireGuard uses UDP, which cannot be tested without "
                            "a handshake — a firewall, captive portal or wrong endpoint is the usual cause.")
    return rep
