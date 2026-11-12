"""Network discovery: adapters, addresses, gateways, routes, DNS configuration and DoH templates, from ONE
PowerShell call (~2 s, on demand only). Nothing is hardcoded about interface names or providers: the NOBAD tunnel
is recognised by the engine's own active tunnel name, everything else is classified from what Windows reports."""
import ipaddress
import json
import os

from ..syscmd import run

_PS = r"""
$ErrorActionPreference='SilentlyContinue'
$ads = Get-NetAdapter -IncludeHidden:$false | Where-Object { $_.Status -ne 'Not Present' }
$list = foreach ($a in $ads) {
  $i = $a.ifIndex
  $ip4 = Get-NetIPInterface -InterfaceIndex $i -AddressFamily IPv4
  $ip6 = Get-NetIPInterface -InterfaceIndex $i -AddressFamily IPv6
  $prof = Get-NetConnectionProfile -InterfaceIndex $i | Select-Object -First 1
  $reg = Get-ItemProperty -Path ('HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces\' + $a.InterfaceGuid)
  [pscustomobject]@{
    index=$i; name=$a.Name; desc=$a.InterfaceDescription; status=[string]$a.Status; media=[string]$a.MediaType
    phys=[string]$a.PhysicalMediaType; speed=[string]$a.LinkSpeed; virtual=[bool]$a.Virtual; hw=[bool]$a.HardwareInterface
    v4=@(Get-NetIPAddress -InterfaceIndex $i -AddressFamily IPv4 | ForEach-Object { @{ip=$_.IPAddress; prefix=$_.PrefixLength; origin=[string]$_.PrefixOrigin} })
    v6=@(Get-NetIPAddress -InterfaceIndex $i -AddressFamily IPv6 | ForEach-Object { @{ip=$_.IPAddress; prefix=$_.PrefixLength; origin=[string]$_.PrefixOrigin; suffix=[string]$_.SuffixOrigin} })
    gw4=@(Get-NetRoute -InterfaceIndex $i -DestinationPrefix '0.0.0.0/0' | ForEach-Object { @{nh=$_.NextHop; metric=[int]$_.RouteMetric} })
    gw6=@(Get-NetRoute -InterfaceIndex $i -DestinationPrefix '::/0' | ForEach-Object { @{nh=$_.NextHop; metric=[int]$_.RouteMetric} })
    dns4=@((Get-DnsClientServerAddress -InterfaceIndex $i -AddressFamily IPv4).ServerAddresses)
    dns6=@((Get-DnsClientServerAddress -InterfaceIndex $i -AddressFamily IPv6).ServerAddresses)
    suffix=[string](Get-DnsClient -InterfaceIndex $i).ConnectionSpecificSuffix
    dhcpdns=[string]$reg.DhcpNameServer; staticdns=[string]$reg.NameServer; dhcpdomain=[string]$reg.DhcpDomain
    metric4=[int]$ip4.InterfaceMetric; metric6=[int]$ip6.InterfaceMetric; dhcp4=[string]$ip4.Dhcp; mtu=[int]$ip4.NlMtu
    profile=$(if ($prof) { @{name=[string]$prof.Name; category=[string]$prof.NetworkCategory; c4=[string]$prof.IPv4Connectivity; c6=[string]$prof.IPv6Connectivity} } else { $null })
  }
}
$doh = @(Get-DnsClientDohServerAddress | ForEach-Object { @{server=$_.ServerAddress; template=$_.DohTemplate; auto=[bool]$_.AutoUpgrade} })
$cs = Get-CimInstance Win32_ComputerSystem
[pscustomobject]@{ adapters=@($list); doh=$doh; domain_joined=[bool]$cs.PartOfDomain; nrpt=@(Get-DnsClientNrptPolicy).Count } | ConvertTo-Json -Depth 6 -Compress
"""


def _as_list(x):
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def _split(s):
    return [x for x in str(s or "").replace(",", " ").split() if x]


def _addr_kind(ip):
    try:
        a = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return "invalid"
    if a.is_loopback:
        return "loopback"
    if a.is_link_local:
        return "link-local"
    if a.version == 4 and a in ipaddress.ip_network("100.64.0.0/10"):
        return "cgnat"
    if a.is_private:
        return "private"
    if a.is_global:
        return "public"
    return "special"


def snapshot(tunnel_name=None, runner=None):
    """Structured view of the machine's networking right now, or {'error': ...}."""
    if os.name != "nt":
        return {"error": "network discovery is implemented for Windows"}
    r = (runner or run)(["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS], timeout=40)
    try:
        raw = json.loads((r.stdout or "").strip() or "{}")
    except ValueError:
        return {"error": "could not read the network configuration", "detail": (r.stderr or "")[:200]}
    return parse_snapshot(raw, tunnel_name)


def parse_snapshot(raw, tunnel_name=None):
    adapters = []
    for a in _as_list(raw.get("adapters")):
        v4 = [x for x in _as_list(a.get("v4")) if x and x.get("ip")]
        v6 = [x for x in _as_list(a.get("v6")) if x and x.get("ip")]
        gw4 = [g for g in _as_list(a.get("gw4")) if g and g.get("nh") not in (None, "", "0.0.0.0")]
        gw6 = [g for g in _as_list(a.get("gw6")) if g and g.get("nh") not in (None, "", "::")]
        on_link6 = [g for g in _as_list(a.get("gw6")) if g and g.get("nh") in ("::",)]
        on_link4 = [g for g in _as_list(a.get("gw4")) if g and g.get("nh") == "0.0.0.0"]
        is_tunnel = bool(tunnel_name and a.get("name") == tunnel_name)
        role = "nobad-tunnel" if is_tunnel else ("virtual" if a.get("virtual") or not a.get("hw") else "physical")
        global6 = [x["ip"] for x in v6 if _addr_kind(x["ip"]) == "public" and x.get("origin") != "WellKnown"]
        adapters.append({
            "index": a.get("index"), "name": a.get("name"), "description": a.get("desc"), "status": a.get("status"),
            "media": a.get("phys") or a.get("media"), "speed": a.get("speed"), "role": role,
            "ipv4": [{"ip": x["ip"], "prefix": x.get("prefix"), "origin": x.get("origin"), "kind": _addr_kind(x["ip"])} for x in v4],
            "ipv6": [{"ip": x["ip"], "prefix": x.get("prefix"), "origin": x.get("origin"), "kind": _addr_kind(x["ip"])} for x in v6],
            "gateways4": [g["nh"] for g in sorted(gw4, key=lambda g: g.get("metric", 0))],
            "gateways6": [g["nh"] for g in sorted(gw6, key=lambda g: g.get("metric", 0))],
            "default4": bool(gw4 or on_link4), "default6": bool(gw6 or on_link6),
            "route_metric4": min([g.get("metric", 0) for g in gw4 + on_link4] or [None]) if (gw4 or on_link4) else None,
            "dns4": [d for d in _as_list(a.get("dns4")) if d], "dns6": [d for d in _as_list(a.get("dns6")) if d],
            "suffix": a.get("suffix") or "", "metric4": a.get("metric4"), "metric6": a.get("metric6"),
            "dhcp4": (a.get("dhcp4") or "").lower() == "enabled", "mtu": a.get("mtu"),
            "global_v6": global6, "profile": a.get("profile"),
            # what the network OFFERS (DHCP) vs what was set by hand: lets us test the ISP/router resolver even when
            # the user has already switched Windows to another DNS
            "dhcp_dns": _split(a.get("dhcpdns")), "static_dns": _split(a.get("staticdns")),
            "dhcp_domain": a.get("dhcpdomain") or "",
        })
    up = [a for a in adapters if (a["status"] or "").lower() == "up"]
    uplinks = sorted([a for a in up if a["default4"] and a["role"] != "nobad-tunnel"],
                     key=lambda a: (a["route_metric4"] or 0) + (a["metric4"] or 0))
    primary = uplinks[0] if uplinks else None
    tunnel = next((a for a in up if a["role"] == "nobad-tunnel"), None)
    doh = [{"server": d.get("server"), "template": d.get("template"), "auto": bool(d.get("auto"))}
           for d in _as_list(raw.get("doh")) if d and d.get("server")]
    return {
        "adapters": adapters, "primary": primary["index"] if primary else None, "tunnel": tunnel["index"] if tunnel else None,
        "v4_available": any(a["default4"] for a in up), "v6_available": any(a["default6"] and a["global_v6"] for a in up),
        "doh_templates": doh, "domain_joined": bool(raw.get("domain_joined")), "nrpt_rules": int(raw.get("nrpt") or 0),
    }


def adapter(snap, index):
    return next((a for a in snap.get("adapters", []) if a["index"] == index), None)


def system_resolvers(snap):
    """DNS servers Windows is configured to use on the active uplink (and the tunnel, when up), in order."""
    out = []
    for idx, via in ((snap.get("tunnel"), "tunnel"), (snap.get("primary"), "uplink")):
        a = adapter(snap, idx) if idx is not None else None
        if not a:
            continue
        for d in a["dns4"] + a["dns6"]:
            if d not in [x["ip"] for x in out] and _addr_kind(d) not in ("link-local", "invalid"):
                out.append({"ip": d, "via": via, "adapter": a["name"], "kind": _addr_kind(d)})
    return out


def network_resolvers(snap):
    """Resolvers the network itself hands out (DHCP) on the uplink: the ISP's / router's default. They are tested
    even when Windows is set to something else, so filtering by the network's own DNS is still visible."""
    a = adapter(snap, snap.get("primary")) or {}
    return [{"ip": d, "via": "dhcp", "adapter": a.get("name"), "kind": _addr_kind(d)}
            for d in a.get("dhcp_dns", []) if _addr_kind(d) not in ("link-local", "invalid")]


def signature(snap):
    """Compact, privacy-light fingerprint for change detection and per-network baselines (no MACs, no SSIDs)."""
    p = adapter(snap, snap.get("primary")) or {}
    return {"gateways4": p.get("gateways4", []), "dns": p.get("dns4", []) + p.get("dns6", []),
            "media": p.get("media"), "v6": bool(snap.get("v6_available")), "suffix": p.get("suffix", ""),
            "tunnel": snap.get("tunnel") is not None}
