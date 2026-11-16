"""Preview-only fake backend for the NOBAD VPN UI: no tunnel, no admin, nothing changes on the PC.
Usage (repo root): python -I docs/ai/tools/ui_preview_mock.py apps/vpn/nobadvpn/ui 8791 [connected]   then open http://127.0.0.1:8791/?tab=t5"""
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UI, PORT = os.path.abspath(sys.argv[1]), int(sys.argv[2])
CONNECTED = len(sys.argv) > 3 and sys.argv[3] == "connected"
sys.path.insert(0, os.path.dirname(os.path.dirname(UI)))
from nobadvpn.const import DEFAULTS  # noqa: E402

REG = [{"name": n, "host": f"{n}.example.net", "port": 51820, "ping": {"rtt": r, "loss": 0, "jitter": 2, "q": "good"},
        "geo": {"country": c}, "full": True, "v6": False, "dns": True, "enc": True}
       for n, r, c in [("japan", 61, "JP"), ("usa", 210, "US")]]
ET = {"ok": True, "network": "Home-WiFi", "kind": "wifi", "grade": "A", "score": 100, "vpn_connected": CONNECTED,
      "trusted": False, "ts": time.time() - 30, "took_s": 4.7, "summary": "Nothing suspicious found.",
      "checks": [{"id": "arp-spoof", "title": "Router identity (ARP)", "state": "pass", "points": 0, "cap": None,
                  "detail": "192.168.1.1 answers as 30:bd:13:2f:00:28, and only it does", "evidence": []}]}
STATE = {"connected": CONNECTED, "connecting": False, "active": "japan" if CONNECTED else None,
         "since": time.time() - 600 if CONNECTED else None, "ks_active": CONNECTED, "regions": REG,
         "settings": dict(DEFAULTS, wizard_done=True), "admin": True, "wireguard": True, "wg_cli": True,
         "sessions": [], "log": [], "eviltwin": ET, "home": {"country": "IN"},
         "exit": {"ip": "203.0.113.7", "city": "Tokyo", "country": "JP"} if CONNECTED else None,
         "health": {"rtt": 61, "loss": 0, "jitter": 3, "q": "good"} if CONNECTED else None}
CT = {"js": "text/javascript", "css": "text/css", "png": "image/png", "ico": "image/x-icon", "svg": "image/svg+xml"}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ct):
        b = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/":
            tab = self.path.split("tab=")[1].split("&")[0] if "tab=" in self.path else "t1"
            html = open(os.path.join(UI, "index.html"), encoding="utf-8").read()
            inj = ("<script>addEventListener('load',()=>setTimeout(()=>{const b=document.querySelector('#dock [data-tab=\"%s\"]');"
                   "if(b)b.click();const s=document.getElementById('splash');if(s)s.remove();},900))</script>" % tab)
            return self._send(200, html.replace("</body>", inj + "</body>"), "text/html; charset=utf-8")
        if p.startswith("/static/"):
            f = os.path.normpath(os.path.join(UI, p[len("/static/"):]))
            if f.startswith(UI) and os.path.isfile(f):
                return self._send(200, open(f, "rb").read(), CT.get(f.rsplit(".", 1)[-1], "application/octet-stream"))
            return self._send(404, "", "text/plain")
        if p == "/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            try:
                for i in range(16):
                    if CONNECTED:
                        for ev in ({"type": "health", "payload": {"rtt": 58 + i % 7, "loss": 0, "jitter": 2, "q": "good"}},
                                   {"type": "traffic", "payload": {"rx_bps": 4e6 + i * 2e5, "tx_bps": 6e5, "rx_total": 1e8,
                                                                   "tx_total": 1e7, "hs_age": 5, "endpoint": "1.2.3.4:51820"}}):
                            self.wfile.write(("data: " + json.dumps(ev) + "\n\n").encode())
                    self.wfile.flush()
                    time.sleep(0.25)
            except OSError:
                pass
            return
        return self._send(200, json.dumps(STATE), "application/json")

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if "si_status" in self.path:
            return self._send(200, json.dumps({"ok": True, "configured": False}), "application/json")
        body = STATE if "/api/state" in self.path else {"ok": True, "items": [], "enabled": True}
        return self._send(200, json.dumps(body), "application/json")


ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
