"""Network tools: exit-IP lookup, streaming reachability, speed test, plain-English diagnosis, game/VALORANT probes.
Most of this is carried over unchanged from the single-file version; the changes are called out in comments."""
import ipaddress
import json
import re
import socket
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from . import netinfo, reach
from .const import UA
from .ctx import ctx
from .logbus import broadcast, log
from .syscmd import ping_stats

SERVICES = [
    ("base", "Cloudflare (baseline)", "https://www.cloudflare.com/cdn-cgi/trace"),
    ("netflix", "Netflix", "https://www.netflix.com/title/80018499"),
    ("youtube", "YouTube", "https://www.youtube.com/generate_204"),
    ("disney", "Disney+", "https://www.disneyplus.com/"),
    ("prime", "Prime Video", "https://www.primevideo.com/"),
    ("spotify", "Spotify", "https://open.spotify.com/"),
    ("twitch", "Twitch", "https://www.twitch.tv/"),
]


IP_PROVIDERS = [
    ("https://ipinfo.io/json", "ipinfo"),
    ("https://ipapi.co/json/", "ipapi"),
    ("https://api.ipify.org?format=json", "ipify"),
    ("https://www.cloudflare.com/cdn-cgi/trace", "cf"),
]


def _lookup_ip():
    """Try several providers (with a retry each) so one blocked/rate-limited service doesn't break the card."""
    last = "no provider answered"
    for url, kind in IP_PROVIDERS:
        for attempt in range(2):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "curl/8.0", "Accept": "application/json"})
                with reach.urlopen(req, timeout=7) as r:
                    raw = r.read().decode("utf-8", "replace")
                if kind == "cf":
                    d = dict(x.split("=", 1) for x in raw.splitlines() if "=" in x)
                    if d.get("ip"):
                        return {"ip": d["ip"], "city": None, "region": None, "country": d.get("loc"), "org": None}
                    continue
                d = json.loads(raw)
                if not d.get("ip"):
                    continue
                country = d.get("country_code") or d.get("country") if kind == "ipapi" else d.get("country")
                return {"ip": d["ip"], "city": d.get("city"), "region": d.get("region"),
                        "country": country, "org": d.get("org")}
            except Exception as e:
                last = type(e).__name__
                time.sleep(0.7)
    raise OSError(last)


def fetch_ipinfo():
    tunnel = ctx.tunnel
    if not ctx.settings.get("ip_lookup"):  # privacy: no third-party lookup at all
        tunnel.exit = {"disabled": True}
        broadcast("ipinfo", tunnel.exit)
        return
    try:
        d = _lookup_ip()
        d["ts"] = time.time()
        tunnel.exit = d
    except Exception as e:
        tunnel.exit = {"error": str(e) or type(e).__name__}
        log(f"exit address lookup failed ({tunnel.exit['error']})", "warn")
    broadcast("ipinfo", tunnel.exit)


def check_service(sid, name, url):
    t0 = time.time()
    code, ms = None, None
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=9) as r:
            code = r.status
            ms = round((time.time() - t0) * 1000)
    except urllib.error.HTTPError as e:
        code = e.code
        ms = round((time.time() - t0) * 1000)
    except Exception as e:
        return {"id": sid, "name": name, "level": "bad", "ms": None, "note": f"unreachable ({type(e).__name__})"}
    if sid == "netflix":
        if code == 200:
            level, note = "ok", "Full catalogue reachable"
        elif code == 404:
            level, note = "warn", "Originals only (or VPN detected)"
        else:
            level, note = "warn", f"HTTP {code}"
    elif code in (403, 451):
        level, note = "bad", f"Blocked (HTTP {code})"
    elif code < 400:
        level, note = "ok", "Reachable"
    else:
        level, note = "warn", f"HTTP {code}"
    return {"id": sid, "name": name, "level": level, "ms": ms, "note": note}


def service_blocked(res):
    """A service counts as blocked for this exit when it is unreachable/forbidden, or (Netflix) VPN-detected."""
    if res["id"] == "netflix":
        return res["level"] != "ok"
    return res["level"] == "bad"


def stream_check():
    broadcast("stream_start", {})
    tunnel = ctx.tunnel
    server = tunnel.active if tunnel.connected else None

    def one(s):
        res = check_service(*s)
        broadcast("stream", res)
        if server and s[0] != "base":
            ctx.smart.record_service(server, s[0], not service_blocked(res))
        return res

    with ThreadPoolExecutor(max_workers=len(SERVICES)) as ex:
        results = list(ex.map(one, SERVICES))
    broadcast("stream_done", {})
    return results


def check_one_service(service_id):
    for s in SERVICES:
        if s[0] == service_id:
            return check_service(*s)
    return None


def speed_test():
    broadcast("speed", {"phase": "start", "mbps": 0, "pct": 0})
    try:
        req = urllib.request.Request("https://speed.cloudflare.com/__down?bytes=8000000", headers={"User-Agent": UA})
        with reach.urlopen(req, timeout=10) as r:
            t0 = last_t = time.time()
            total = last_b = 0
            while True:
                chunk = r.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                now = time.time()
                if now - last_t >= 0.25:
                    inst = (total - last_b) * 8 / (now - last_t) / 1e6
                    last_t, last_b = now, total
                    broadcast("speed", {"phase": "run", "mbps": round(inst, 1), "pct": min(100, (now - t0) / 8 * 100)})
                if total >= 8_000_000 or now - t0 >= 5:
                    break
        el = max(time.time() - t0, 0.001)
        mbps = round(total * 8 / el / 1e6, 1)
        try:
            tunnel = ctx.tunnel
            ctx.usage.add_speed(mbps, tunnel.active if tunnel.connected else None)
        except Exception:
            pass
        broadcast("speed_done", {"mbps": mbps, "secs": round(el, 1)})
    except Exception as e:
        broadcast("speed_done", {"error": f"{type(e).__name__}: {e}"})



def probe_lan(ip):
    """Ping a LAN host; routers often drop ICMP, so fall back to a TCP handshake (a refusal still proves it's alive)."""
    p = ping_stats(ip, 3, 900)
    if p["rtt"] is not None:
        return {**p, "src": "icmp"}
    for port in (443, 80, 53, 8080, 22):
        t = time.perf_counter()
        try:
            c = socket.create_connection((ip, port), 1.0)
            c.close()
            alive = True
        except ConnectionRefusedError:
            alive = True
        except OSError:
            alive = False
        if alive:
            return {"rtt": max(1, round((time.perf_counter() - t) * 1000)), "loss": 0, "jitter": None, "src": "tcp"}
    return {"rtt": None, "loss": 100, "jitter": None, "src": "none"}


def network_diagnose():
    """One-shot, low-cost diagnostic. Does not alter network configuration."""
    started = time.time()
    gateway = netinfo.default_gateway(ctx.tunnel.tunnel_ips() if ctx.tunnel else ())
    gw = probe_lan(gateway) if gateway else {"rtt": None, "loss": 100, "jitter": None}
    internet = ping_stats("1.1.1.1", 3, 1100)
    dns_ms = None
    dns_ok = False
    try:
        t = time.perf_counter()
        socket.getaddrinfo("example.com", 443, type=socket.SOCK_STREAM)
        dns_ms = round((time.perf_counter() - t) * 1000)
        dns_ok = True
    except OSError:
        pass

    issues = []
    if not gateway:
        issues.append({"level": "warn", "title": "No default gateway found", "simple": "Windows could not find the router address for this connection.", "impact": "Your device may not have a working local network connection.", "suggestion": "Check that Wi-Fi or Ethernet is connected, then reconnect to your network."})
    elif gw["loss"] >= 50:
        issues.append({"level": "bad", "title": "Your device cannot reliably reach the router", "simple": "Your computer is having trouble talking to the box that connects you to the internet.", "impact": "This can cause disconnects, lag and slow loading.", "suggestion": "Move closer to the Wi-Fi router, check the cable, or restart the router if other devices are affected too."})
    if internet["loss"] >= 50:
        issues.append({"level": "bad", "title": "Internet reachability is poor", "simple": "The test could not reliably reach an internet address.", "impact": "Websites and online games may disconnect or fail to load.", "suggestion": "Check whether your internet provider has an outage. If the router test also failed, fix the local connection first."})
    elif internet["rtt"] is not None and internet["rtt"] > 150:
        issues.append({"level": "warn", "title": "Internet response is slow", "simple": "It takes a while for a test message to travel to the internet and come back.", "impact": "Online games may feel delayed, especially on distant servers.", "suggestion": "Pause large downloads and compare Ethernet with Wi-Fi. Test the actual game server for a more relevant result."})
    if not dns_ok:
        issues.append({"level": "bad", "title": "Name lookup failed", "simple": "Your computer could not translate a website name into its internet address.", "impact": "Some websites and game launchers may not connect.", "suggestion": "Try the safe 'Clear DNS cache' action, then run this check again."})
    elif dns_ms is not None and dns_ms > 700:
        issues.append({"level": "warn", "title": "Website name lookup is slow", "simple": "Your computer took longer than expected to find a website's address.", "impact": "The first connection to some websites or services may take longer.", "suggestion": "Try clearing the DNS cache. If this keeps happening, check the DNS server configured on your router."})

    if not issues:
        issues.append({"level": "good", "title": "Your basic connection looks healthy", "simple": "Your router, internet reachability and website name lookup passed these quick checks.", "impact": "This is a good baseline, but it does not guarantee a perfect route to every game server.", "suggestion": "If a game still lags, test its actual server address and compare Wi-Fi with Ethernet."})
    return {
        "ok": True, "gateway": gateway, "gateway_ping": gw,
        "internet_ping": internet, "dns_ms": dns_ms, "dns_ok": dns_ok,
        "issues": issues, "elapsed_ms": round((time.time()-started)*1000),
        "checked_at": int(time.time())
    }


def gaming_probe(host):
    """Probe a user-supplied game endpoint; never invent a game's server address."""
    host = str(host or "").strip()
    if not host or len(host) > 253 or not re.fullmatch(r"[A-Za-z0-9.:-]+", host):
        return {"ok": False, "error": "Enter a valid game server IP address or hostname."}
    try:
        ipaddress.ip_address(host.strip("[]"))
        target = host.strip("[]")
    except ValueError:
        try:
            target = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)[0][4][0]
        except OSError:
            return {"ok": False, "error": "That server name could not be found. Check the address and try again."}
    result = ping_stats(target, 5, 1000)
    if result["rtt"] is None:
        verdict = "The server did not answer ping tests. It may block ping, so this alone does not prove the game server is offline."
    elif result["loss"] >= 20:
        verdict = "Many test messages were lost. This connection may feel unstable during online play."
    elif result["jitter"] is not None and result["jitter"] > 35:
        verdict = "Your response time is jumping around. This can feel like sudden lag or rubber-banding."
    elif result["rtt"] > 120:
        verdict = "The response time is high for fast-paced gaming. A nearer region or better route may help."
    else:
        verdict = "The test looks reasonably steady. Actual in-game latency can still differ."
    return {"ok": True, "host": host, "resolved_ip": target, **result, "verdict": verdict}



# =============================================================================
# VALORANT REGION CHECK — direct community-reported Riot edges where known;
# regional cloud TCP estimates elsewhere. Never label proxy latency as in-game ping.
# =============================================================================
VALORANT_REGIONS = [
    # APAC: Riot-reported locations; direct addresses below are community reported,
    # not an official permanent Riot IP catalogue.
    {"region":"APAC","name":"Mumbai","kind":"riot-edge","targets":["151.106.246.1","75.2.66.166","99.83.136.104","13.248.197.71","76.223.71.164"]},
    {"region":"APAC","name":"Singapore","kind":"riot-edge","targets":["151.106.248.1","13.248.193.101","75.2.69.178","99.83.157.116"]},
    {"region":"APAC","name":"Hong Kong","kind":"regional-estimate","host":"ec2.ap-east-1.amazonaws.com"},
    {"region":"APAC","name":"Tokyo","kind":"regional-estimate","host":"ec2.ap-northeast-1.amazonaws.com"},
    {"region":"APAC","name":"Sydney","kind":"regional-estimate","host":"ec2.ap-southeast-2.amazonaws.com"},
    {"region":"APAC","name":"Manila","kind":"regional-estimate","host":"ec2.ap-southeast-1.amazonaws.com"},
    {"region":"KR","name":"Seoul","kind":"regional-estimate","host":"ec2.ap-northeast-2.amazonaws.com"},
    {"region":"EU","name":"Frankfurt","kind":"regional-estimate","host":"ec2.eu-central-1.amazonaws.com"},
    {"region":"EU","name":"Paris","kind":"regional-estimate","host":"ec2.eu-west-3.amazonaws.com"},
    {"region":"EU","name":"Stockholm","kind":"regional-estimate","host":"ec2.eu-north-1.amazonaws.com"},
    {"region":"EU","name":"Istanbul","kind":"regional-estimate","host":"ec2.eu-central-1.amazonaws.com"},
    {"region":"EU","name":"London","kind":"regional-estimate","host":"ec2.eu-west-2.amazonaws.com"},
    {"region":"EU","name":"Warsaw","kind":"regional-estimate","host":"ec2.eu-central-2.amazonaws.com"},
    {"region":"EU","name":"Madrid","kind":"regional-estimate","host":"ec2.eu-south-2.amazonaws.com"},
    {"region":"EU","name":"Bahrain","kind":"regional-estimate","host":"ec2.me-south-1.amazonaws.com"},
    {"region":"BR","name":"São Paulo","kind":"regional-estimate","host":"ec2.sa-east-1.amazonaws.com"},
    {"region":"LATAM","name":"Santiago","kind":"regional-estimate","host":"ec2.sa-east-1.amazonaws.com"},
    {"region":"LATAM","name":"Mexico City","kind":"regional-estimate","host":"ec2.us-east-2.amazonaws.com"},
    {"region":"LATAM","name":"Miami","kind":"regional-estimate","host":"ec2.us-east-1.amazonaws.com"},
    {"region":"NA","name":"Oregon","kind":"regional-estimate","host":"ec2.us-west-2.amazonaws.com"},
    {"region":"NA","name":"N. California","kind":"regional-estimate","host":"ec2.us-west-1.amazonaws.com"},
    {"region":"NA","name":"N. Virginia","kind":"regional-estimate","host":"ec2.us-east-1.amazonaws.com"},
    {"region":"NA","name":"Texas","kind":"regional-estimate","host":"ec2.us-east-2.amazonaws.com"},
    {"region":"NA","name":"Illinois","kind":"regional-estimate","host":"ec2.us-east-2.amazonaws.com"},
    {"region":"NA","name":"Georgia","kind":"regional-estimate","host":"ec2.us-east-1.amazonaws.com"},
]


def _probe_riot_edge(ip):
    result = ping_stats(ip, 3, 900)
    if result["rtt"] is not None:
        return {"host": ip, **result, "method": "ICMP", "reachable": True}
    # Many game edges intentionally ignore ICMP; TCP handshake is only a reachability estimate.
    for port in (443, 80):
        try:
            started = time.perf_counter()
            with socket.create_connection((ip, port), timeout=1.6):
                pass
            return {"host": ip, "rtt": round((time.perf_counter()-started)*1000), "loss": None,
                    "jitter": None, "method": f"TCP/{port}", "reachable": True,
                    "note": "TCP handshake estimate; not in-game UDP ping"}
        except OSError:
            continue
    return {"host": ip, "rtt": None, "loss": 100, "jitter": None, "method": "No reply",
            "reachable": False, "note": "This address may block probes or may have changed"}


def _probe_valorant_region(item):
    if item["kind"] == "riot-edge":
        with ThreadPoolExecutor(max_workers=min(5, len(item["targets"]))) as edge_pool:
            results = list(edge_pool.map(_probe_riot_edge, item["targets"]))
        good = [x for x in results if x.get("rtt") is not None]
        best = min(good, key=lambda x: x["rtt"]) if good else results[0]
        return {"region": item["region"], "name": item["name"], "kind": item["kind"],
                "rtt": best.get("rtt"), "loss": best.get("loss"), "jitter": best.get("jitter"),
                "method": best.get("method"), "target": best.get("host"), "reachable": bool(good),
                "tested": len(results), "note": best.get("note") or ("Best response among community-reported Riot edge IPs; actual match ping may differ." if good else "No probe reply. Riot edges may block ICMP/TCP probes; this does not prove the game server is down.")}
    host = item["host"]
    try:
        started = time.perf_counter()
        with socket.create_connection((host, 443), timeout=2.4):
            ms = round((time.perf_counter()-started)*1000)
        return {"region": item["region"], "name": item["name"], "kind": item["kind"],
                "rtt": ms, "loss": None, "jitter": None, "method": "TCP/443 regional estimate",
                "target": host, "reachable": True, "tested": 1,
                "note": "Cloud-region network estimate only — not a Riot game server or actual in-game ping."}
    except OSError as e:
        return {"region": item["region"], "name": item["name"], "kind": item["kind"],
                "rtt": None, "loss": None, "jitter": None, "method": "No reply", "target": host,
                "reachable": False, "tested": 1, "note": f"Regional estimate unavailable ({type(e).__name__}); not a game-server outage diagnosis."}


def valorant_region_check():
    broadcast("valorant_start", {"total": len(VALORANT_REGIONS)})
    results = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(_probe_valorant_region, item) for item in VALORANT_REGIONS]
        for future in futures:
            try:
                row = future.result()
            except Exception as e:
                row = {"region":"?", "name":"Probe error", "rtt":None, "reachable":False, "note":str(e)}
            results.append(row)
            broadcast("valorant_result", row)
    ranked = sorted((x for x in results if x.get("rtt") is not None), key=lambda x:x["rtt"])
    broadcast("valorant_done", {"count":len(results), "reachable":sum(bool(x.get("reachable")) for x in results),
                                "best": ranked[0] if ranked else None,
                                "note":"Mumbai/Singapore use community-reported Riot edge IPs. Other locations use regional cloud TCP estimates, not Riot game servers."})



def startup_checks():
    """One bounded startup sweep per app launch; each task is independently guarded."""
    from .syscmd import run_once
    # Same lock keys as the buttons: a check started at launch can't run twice in parallel with a click, and its
    # task_done re-enables the matching button (separate 'startup_*' keys left buttons disabled for good).
    run_once("network_diagnose", lambda: broadcast("network_diagnose", network_diagnose()))
    if not ctx.settings.get("startup_checks"):
        run_once("ipinfo", fetch_ipinfo)
        return
    run_once("speed", speed_test)
    run_once("stream", stream_check)
    run_once("ipinfo", fetch_ipinfo)
    run_once("valorant_manual", valorant_region_check)
