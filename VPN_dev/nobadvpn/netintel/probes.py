"""Transport-layer probes: TCP, TLS (with and without the real SNI), HTTP, OS resolution, DNS interception.
Every function measures something real and returns a JSON-able dict; nothing here changes system settings."""
import ipaddress
import os
import socket
import ssl
import tempfile
import time

from . import dnswire

# RFC 5737 / RFC 3849 documentation ranges: nothing may ever answer on them. A DNS reply from one of these
# addresses can only come from a middlebox that intercepts DNS traffic on the path.
NO_HOST_V4 = ("192.0.2.53", "198.51.100.53")
NO_HOST_V6 = ("2001:db8::53",)


def family_of(ip):
    return socket.AF_INET6 if ipaddress.ip_address(ip).version == 6 else socket.AF_INET


def _err_kind(e):
    if isinstance(e, socket.timeout) or "timed out" in str(e).lower():
        return "timeout"
    if isinstance(e, ConnectionResetError) or getattr(e, "winerror", None) == 10054:
        return "reset"
    if isinstance(e, ConnectionRefusedError) or getattr(e, "winerror", None) == 10061:
        return "refused"
    if getattr(e, "winerror", None) in (10051, 10065) or isinstance(e, OSError) and "unreachable" in str(e).lower():
        return "unreachable"
    if isinstance(e, ssl.SSLCertVerificationError):
        return "cert-" + ("mismatch" if "match" in str(e).lower() or "hostname" in str(e).lower() else "untrusted")
    if isinstance(e, ssl.SSLError):
        return "tls-error"
    return type(e).__name__


def tcp_connect(ip, port=443, timeout=3.0):
    t0 = time.perf_counter()
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return {"ip": ip, "port": port, "ok": True, "rtt_ms": round((time.perf_counter() - t0) * 1000, 1)}
    except OSError as e:
        return {"ip": ip, "port": port, "ok": False, "error": _err_kind(e),
                "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1)}


def _decode_der(der):
    """Subject / SAN / issuer of a certificate we could not verify (stdlib only; best effort)."""
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as f:
            f.write(ssl.DER_cert_to_PEM_cert(der))
            path = f.name
        try:
            return ssl._ssl._test_decode_cert(path)  # CPython helper, present since 3.x
        finally:
            os.unlink(path)
    except Exception:
        return None


def _names(cert):
    if not cert:
        return [], None
    names = [v for k, v in cert.get("subjectAltName", ()) if k == "DNS"]
    if not names:
        names = [v for rdn in cert.get("subject", ()) for k, v in rdn if k == "commonName"]
    issuer = next((v for rdn in cert.get("issuer", ()) for k, v in rdn if k in ("organizationName", "commonName")), None)
    return names[:12], issuer


def tls_probe(ip, sni, port=443, timeout=4.0):
    """Handshake to `ip` presenting `sni`. Reports TCP result, whether TLS completed, whether the certificate is
    valid for `sni`, the names it covers and its issuer. A failure is classified (reset/timeout/cert-mismatch/...)."""
    res = {"ip": ip, "sni": sni, "port": port, "tcp_ok": False, "tls_ok": False, "verify_ok": False}
    t0 = time.perf_counter()
    try:
        raw = socket.create_connection((ip, port), timeout=timeout)
    except OSError as e:
        res["error"] = _err_kind(e)
        return res
    res["tcp_ok"] = True
    res["tcp_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    ctx = ssl.create_default_context()
    try:
        with ctx.wrap_socket(raw, server_hostname=sni) as s:
            res.update(tls_ok=True, verify_ok=True, version=s.version())
            res["names"], res["issuer"] = _names(s.getpeercert())
            res["tls_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            return res
    except (ssl.SSLCertVerificationError, ssl.CertificateError) as e:
        res["error"] = _err_kind(e)
        res["tls_ok"] = True       # handshake got as far as a certificate: TLS itself works
    except OSError as e:
        res["error"] = _err_kind(e)
        return res
    # verification failed: fetch the certificate without verifying, only to report what was presented
    try:
        raw = socket.create_connection((ip, port), timeout=timeout)
        nv = ssl.create_default_context()
        nv.check_hostname = False
        nv.verify_mode = ssl.CERT_NONE
        with nv.wrap_socket(raw, server_hostname=sni) as s:
            res["names"], res["issuer"] = _names(_decode_der(s.getpeercert(binary_form=True)))
            res["version"] = s.version()
    except OSError:
        pass
    return res


def sni_filter_check(ip, sni, port=443, timeout=4.0):
    """Same IP, two handshakes: the real name and a neutral one. If only the real name is cut off (reset/timeout)
    while the neutral handshake reaches the server, something on the path filters by SNI (DNS fixes won't help)."""
    real = tls_probe(ip, sni, port, timeout)
    neutral_name = "nobad-sni-control.invalid"
    neutral = tls_probe(ip, neutral_name, port, timeout)
    # cut off = connection reset / silence after the ClientHello. A TLS *alert* (e.g. "unknown name") or any
    # certificate means a real TLS server answered, so the neutral handshake proves the path to the server works.
    cut = lambda r: r["tcp_ok"] and not r["tls_ok"] and r.get("error") in ("reset", "timeout")
    reached = lambda r: r["tcp_ok"] and (r["tls_ok"] or r.get("error") in ("tls-error", "cert-mismatch", "cert-untrusted"))
    return {"ip": ip, "real": real, "neutral": neutral, "sni_filtered": bool(cut(real) and reached(neutral))}


def http_probe(ip, host, tls=True, path="/", timeout=5.0):
    """One GET to `ip` with Host/SNI = host (certificate verification off: we want to SEE what is served, e.g. a
    block page). Reports status, redirect target, server header, <title> and size of the first 32 KB."""
    import http.client
    conn = None
    try:
        if tls:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            conn = http.client.HTTPSConnection(ip, 443, timeout=timeout, context=ctx)
            conn._tunnel_host = None
            sock = socket.create_connection((ip, 443), timeout=timeout)
            conn.sock = ctx.wrap_socket(sock, server_hostname=host)
        else:
            conn = http.client.HTTPConnection(ip, 80, timeout=timeout)
        conn.request("GET", path, headers={"Host": host, "User-Agent": "Mozilla/5.0 (NOBAD network check)",
                                           "Accept": "text/html,*/*"})
        r = conn.getresponse()
        body = r.read(32768).decode("utf-8", "replace")
        low = body.lower()
        title = None
        if "<title" in low:
            a = low.index("<title")
            a = low.index(">", a) + 1 if ">" in low[a:] else a
            b = low.find("</title>", a)
            title = " ".join(body[a:b if b > 0 else a + 120].split())[:120]
        return {"ip": ip, "host": host, "tls": tls, "ok": True, "status": r.status, "location": r.getheader("Location"),
                "server": r.getheader("Server"), "title": title, "bytes": len(body)}
    except (OSError, http.client.HTTPException) as e:
        return {"ip": ip, "host": host, "tls": tls, "ok": False, "error": _err_kind(e)}
    finally:
        if conn:
            conn.close()


def os_resolve(name, timeout=5.0):
    """What applications actually get: Windows' resolver (hosts file, cache, NRPT, DoH, adapter DNS)."""
    t0 = time.perf_counter()
    old = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout)
    try:
        infos = socket.getaddrinfo(name, 443, type=socket.SOCK_STREAM)
        ips = sorted({i[4][0].split("%")[0] for i in infos})
        return {"ok": True, "ips": ips, "ms": round((time.perf_counter() - t0) * 1000, 1)}
    except socket.gaierror as e:
        return {"ok": False, "error": "no such name" if e.errno in (socket.EAI_NONAME, 11001) else f"gai-{e.errno}",
                "ms": round((time.perf_counter() - t0) * 1000, 1)}
    except OSError as e:
        return {"ok": False, "error": _err_kind(e)}
    finally:
        socket.setdefaulttimeout(old)


def interception_test(v6=False, name="example.com", timeout=1.5):
    """Send real DNS queries to addresses where no DNS server can exist. Any answer = DNS interception on path."""
    from concurrent.futures import ThreadPoolExecutor
    targets = list(NO_HOST_V4) + (list(NO_HOST_V6) if v6 else [])
    with ThreadPoolExecutor(max_workers=len(targets)) as ex:
        replies = list(ex.map(lambda ip: dnswire.query(name, "A", server=ip, timeout=timeout), targets))
    out = []
    for ip, r in zip(targets, replies):
        out.append({"target": ip, "answered": r["rcode"] is not None, "rcode": r.get("rcode_name"),
                    "answers": [a["data"] for a in r["answers"] if a["type"] == "A"], "error": r["error"]})
    return {"intercepted": any(x["answered"] for x in out), "probes": out}
