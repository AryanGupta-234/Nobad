"""Adaptive reachability for NOBAD's own web requests (not for the user's traffic, which goes through the tunnel).

Some networks block services NOBAD relies on, in three different ways, and each needs a different answer:
  TLS name filtering   the connection is reset during the handshake for one hostname (seen for api.themoviedb.org)
                       -> try the service's other official hostnames (api.tmdb.org, en.m.wikipedia.org, ...)
  DNS blocking         the name doesn't resolve, or resolves to 0.0.0.0 / loopback / a private address
                       -> resolve it with encrypted DNS (DoH to 1.1.1.1 / 8.8.8.8 by IP, so the resolver itself
                          can't be DNS-blocked) and connect to that address with the real name (TLS still verified)
  IP blocking          nothing helps except the VPN; this is reported, not hidden.

With the 'net_adapt' setting on (default), `urlopen()` tries the routes in that order, remembers the route that
worked per hostname for a day, and `report()` explains every service's route. With it off, requests go direct."""
import http.client
import ipaddress
import json
import os
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .const import DATA_DIR

# Built-in alternatives: official mirrors of the same service (same data, same TLS owner), never third-party proxies.
ALTERNATE_HOSTS = {
    "api.themoviedb.org": ["api.tmdb.org"],
    "api.tmdb.org": ["api.themoviedb.org"],
    "en.wikipedia.org": ["en.m.wikipedia.org"],
    "www.wikidata.org": ["m.wikidata.org"],
    "ipinfo.io": [],
    "speed.cloudflare.com": [],
}
# What `report()` tests: id, label, URL (any HTTP answer, even 401/404, proves the route works).
SERVICES = [
    ("tmdb", "TMDB (Where to watch)", "https://api.tmdb.org/3/configuration"),
    ("tmdb_img", "TMDB images", "https://image.tmdb.org/t/p/w92/"),
    ("wikipedia", "Wikipedia (restrictions)", "https://en.wikipedia.org/w/api.php?action=query&format=json"),
    ("wikidata", "Wikidata (title identity)", "https://www.wikidata.org/w/api.php?action=query&format=json"),
    ("ipinfo", "IP location (ipinfo.io)", "https://ipinfo.io/json"),
    ("speed", "Speed test (Cloudflare)", "https://speed.cloudflare.com/__down?bytes=1000"),
    ("wireguard", "WireGuard download", "https://download.wireguard.com/windows-client/"),
]
DOH = [("1.1.1.1", "https://1.1.1.1/dns-query?name={name}&type={t}", {"Accept": "application/dns-json"}),
       ("8.8.8.8", "https://8.8.8.8/resolve?name={name}&type={t}", {})]
ROUTE_TTL = 86400
_lock = threading.Lock()
_routes = {}          # host -> {"route": "direct"|"alt"|"doh", "host": used host, "ip": ip or None, "ts": time}
_PATH = os.path.join(DATA_DIR, "reach.json")


class NoDowngradeRedirect(urllib.request.HTTPRedirectHandler):
    """Follow redirects, but never from https:// to anything else (http://, ftp://, file://). Otherwise anyone on the
    network path could answer an https link's redirect with a plain-http one and swap the content (a config, an update
    manifest, a geo answer)."""
    max_redirections = 5

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old = urllib.parse.urlsplit(req.full_url).scheme
        new = urllib.parse.urlsplit(urllib.parse.urljoin(req.full_url, newurl)).scheme
        if old == "https" and new != "https":
            raise urllib.error.HTTPError(req.full_url, code, f"refused redirect from https to {new or 'unknown'}",
                                         headers, fp)
        if new not in ("http", "https"):
            raise urllib.error.HTTPError(req.full_url, code, f"refused redirect to {new or 'unknown'}:", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def install_safe_redirects():
    """Make every urllib.request.urlopen in this process use NoDowngradeRedirect (called once at import)."""
    urllib.request.install_opener(urllib.request.build_opener(NoDowngradeRedirect))


install_safe_redirects()


def _enabled():
    try:
        from .ctx import ctx
        return bool(ctx.settings.get("net_adapt")) if ctx.settings else True
    except Exception:
        return True


def _load():
    global _routes
    try:
        with open(_PATH, encoding="utf-8") as f:
            d = json.load(f)
        _routes = {h: r for h, r in d.items() if time.time() - r.get("ts", 0) < ROUTE_TTL}
    except (OSError, ValueError):
        _routes = {}


def _save():
    try:
        tmp = _PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_routes, f)
        os.replace(tmp, _PATH)
    except OSError:
        pass


def forget():
    """Network changed (or the user asked): routes are re-learned."""
    with _lock:
        _routes.clear()
        _save()


def bogus(ip):
    """An answer a public service never has: a sign of DNS blocking/sinkholing."""
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return a.is_unspecified or a.is_loopback or a.is_private or a.is_link_local or a.is_multicast or a.is_reserved


def system_resolve(host):
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError:
        return []
    return list(dict.fromkeys(i[4][0] for i in infos))


def doh_resolve(host, opener=None, timeout=6):
    """A/AAAA for host via DNS-over-HTTPS at a fixed IP (works when the network's DNS lies or is blocked)."""
    open_ = opener or urllib.request.urlopen
    for _name, url, hdr in DOH:
        ips = []
        for t in ("A", "AAAA"):
            req = urllib.request.Request(url.format(name=urllib.parse.quote(host), t=t), headers=dict(hdr, **{"User-Agent": "NOBAD-VPN"}))
            try:
                with open_(req, timeout=timeout) as r:
                    d = json.loads(r.read(200000).decode("utf-8", "replace"))
                ips += [a["data"] for a in d.get("Answer", []) if a.get("type") in (1, 28) and not bogus(a.get("data", ""))]
            except Exception:
                continue
        if ips:
            return list(dict.fromkeys(ips))
    return []


class _PinnedHTTPS(http.client.HTTPSConnection):
    """HTTPS to a fixed IP while sending (and verifying the certificate for) the real hostname."""

    def __init__(self, host, ip, timeout, context):
        super().__init__(host, timeout=timeout, context=context)
        self._ip = ip

    def connect(self):
        sock = socket.create_connection((self._ip, self.port or 443), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _Resp:
    """urllib-like wrapper for an http.client response (status, headers, read, context manager)."""

    def __init__(self, conn, resp, url):
        self._c, self._r, self.url = conn, resp, url
        self.status, self.headers = resp.status, resp.msg

    def read(self, *a):
        return self._r.read(*a)

    def getcode(self):
        return self.status

    def close(self):
        try:
            self._r.close()
        finally:
            self._c.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
        return False


def _pinned_open(req, host, ip, timeout):
    u = urllib.parse.urlsplit(req.full_url)
    conn = _PinnedHTTPS(host, ip, timeout, ssl.create_default_context())
    path = (u.path or "/") + ("?" + u.query if u.query else "")
    headers = dict(req.header_items())
    headers["Host"] = host
    conn.request(req.get_method(), path, body=req.data, headers=headers)
    resp = conn.getresponse()
    if resp.status >= 400:
        body = resp.read(65536)
        conn.close()
        raise urllib.error.HTTPError(req.full_url, resp.status, resp.reason, resp.msg, None) if not body else \
            urllib.error.HTTPError(req.full_url, resp.status, resp.reason, resp.msg, __import__("io").BytesIO(body))
    return _Resp(conn, resp, req.full_url)


def _swap_host(req, host):
    u = urllib.parse.urlsplit(req.full_url)
    netloc = host + (f":{u.port}" if u.port else "")
    r = urllib.request.Request(urllib.parse.urlunsplit((u.scheme, netloc, u.path, u.query, u.fragment)),
                               data=req.data, headers=dict(req.header_items()), method=req.get_method())
    return r


def _network_error(e):
    """Errors that a different route may get past (not HTTP answers: those prove the route works)."""
    return isinstance(e, (urllib.error.URLError, OSError, ssl.SSLError, http.client.HTTPException)) and \
        not isinstance(e, urllib.error.HTTPError)


def urlopen(req, timeout=12, _direct=None, _doh=None):
    """Drop-in for urllib.request.urlopen(Request) with automatic route adaptation (see module docstring)."""
    _direct = _direct or urllib.request.urlopen          # looked up per call, so tests can patch urllib
    if isinstance(req, str):
        req = urllib.request.Request(req)
    host = urllib.parse.urlsplit(req.full_url).hostname or ""
    if not _enabled() or not host or urllib.parse.urlsplit(req.full_url).scheme != "https":
        return _direct(req, timeout=timeout)
    if not _routes and os.path.exists(_PATH):
        with _lock:
            _load()
    known = _routes.get(host)
    attempts = []
    if known and time.time() - known.get("ts", 0) < ROUTE_TTL:
        attempts.append(known["route"])
    attempts += [r for r in ("direct", "alt", "doh") if r not in attempts]
    last = None
    for route in attempts:
        try:
            if route == "direct":
                ips = system_resolve(host)
                if ips and all(bogus(i) for i in ips):
                    raise urllib.error.URLError(f"DNS answer for {host} looks blocked ({ips[0]})")
                resp, used, ip = _direct(req, timeout=timeout), host, None
            elif route == "alt":
                resp = None
                for alt in ALTERNATE_HOSTS.get(host, []):
                    try:
                        resp, used, ip = _direct(_swap_host(req, alt), timeout=timeout), alt, None
                        break
                    except Exception as e:
                        if not _network_error(e):
                            raise
                        last = e
                if resp is None:
                    continue
            else:
                resp = None
                for ip_ in (_doh or doh_resolve)(host)[:3]:
                    try:
                        resp, used, ip = _pinned_open(req, host, ip_, timeout), host, ip_
                        break
                    except Exception as e:
                        if not _network_error(e):
                            raise
                        last = e
                if resp is None:
                    continue
        except Exception as e:
            if not _network_error(e):
                raise
            last = e
            continue
        if not known or known.get("route") != route:
            with _lock:
                _routes[host] = {"route": route, "host": used, "ip": ip, "ts": time.time()}
                _save()
        return resp
    raise last or urllib.error.URLError(f"{host}: no route worked")


def report(opener=None, timeout=8):
    """Test every service NOBAD uses; for each: status, route and a plain explanation."""
    out = []
    for sid, label, url in SERVICES:
        host = urllib.parse.urlsplit(url).hostname
        sys_ips = system_resolve(host)
        dns = "ok" if sys_ips and not all(bogus(i) for i in sys_ips) else ("blocked" if sys_ips else "failed")
        t0 = time.time()
        status, route, detail = "unreachable", None, ""
        try:
            with (opener or urlopen)(urllib.request.Request(url, headers={"User-Agent": "NOBAD-VPN"}), timeout=timeout) as r:
                status = "ok"
                r.read(256)
        except urllib.error.HTTPError as e:
            status, detail = "ok", f"HTTP {e.code}"        # an HTTP answer means the route works
        except Exception as e:
            detail = f"{type(e).__name__}: {getattr(e, 'reason', e)}"[:160]
        r_ = _routes.get(host) or {}
        route = r_.get("route") if status == "ok" else None
        out.append({"id": sid, "label": label, "host": host, "status": status, "dns": dns,
                    "route": route or ("direct" if status == "ok" else None), "via": r_.get("host") if route == "alt" else None,
                    "ms": round((time.time() - t0) * 1000), "detail": detail,
                    "explain": _explain(status, route, dns, r_)})
    return {"adapt": _enabled(), "services": out, "ts": time.time()}


def _explain(status, route, dns, r):
    if status != "ok":
        return "Not reachable on this network by any route. Connecting the VPN usually helps."
    if route == "alt":
        return f"The usual name is blocked here; NOBAD uses the official alternative {r.get('host')}."
    if route == "doh":
        return "This network's DNS blocks the name; NOBAD looks it up with encrypted DNS instead."
    if dns != "ok":
        return "Reachable, although this network's DNS answer looks wrong."
    return "Works normally."
