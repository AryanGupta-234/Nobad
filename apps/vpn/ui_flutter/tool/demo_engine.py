"""A demo engine for NOBAD VPN's Flutter window: screenshots and design work without the real app.

It runs the REAL pipe server (nobadvpn/rpc: the same DACL, caller check, parameter allowlist and events) on the
development pipe name `\\\\.\\pipe\\NOBADVPN-dev-<your SID>`, at normal rights, with made-up handlers behind it.
Nothing on the PC changes: no tunnel, no firewall rule, no elevation, no browser, no file outside a temp folder.

    python -I apps/vpn/ui_flutter/tool/demo_engine.py [off|connected|connecting|blocked|empty|error] [--light]
    set NOBAD_VPN_DEV_ENGINE=1 & apps\\vpn\\ui_flutter\\build\\windows\\x64\\runner\\Release\\nobad_vpn_ui.exe

Ctrl+C stops it; the window then shows "Not running".
"""
import math
import os
import random
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))            # apps/vpn
os.environ["NOBAD_DATA_DIR"] = tempfile.mkdtemp(prefix="nobad-demo-")  # never the real ProgramData folder

from nobadvpn import logbus  # noqa: E402
from nobadvpn.rpc import Rpc, methods, params, security  # noqa: E402

MODE = next((a for a in sys.argv[1:] if not a.startswith("--")), "off")
LIGHT = "--light" in sys.argv


def region(name, host, cc, city, rtt, enc=False, v6=False):
    return {"name": name, "host": host, "port": 51820, "ping": None if rtt is None else {"rtt": rtt, "loss": 0, "jitter": 2.1},
            "geo": {"country": cc, "city": city} if cc else None, "full": True, "v6": v6, "dns": True, "enc": enc}


REGIONS = [region("JP-FREE-3", "jp-free-3.protonvpn.net", "JP", "Tokyo", 61.0, enc=True),
           region("NL-FREE-12", "nl-free-12.protonvpn.net", "NL", "Amsterdam", 148.0, v6=True),
           region("US-FREE-34", "us-free-34.protonvpn.net", "US", "New York", 212.0),
           region("Home-Router", "home.example.net", "", "", None)]
SETTINGS = {"kill_switch": True, "dns_leak_block": True, "force_tunnel_dns": True, "fallback_dns": "1.1.1.1, 1.0.0.1",
            "ks_strict": False, "watchdog": True, "watchdog_failopen": False, "auto_repair": True, "stream_tuned": True,
            "reconnect_on_network_change": True, "smart_select": True, "tray": True, "close_to_tray": True,
            "notifications": True, "theme": "light" if LIGHT else "dark", "wizard_done": True, "last_region": "JP-FREE-3",
            "favorites": ["JP-FREE-3"], "trusted_networks": ["Home-WiFi"], "trusted_fingerprints": {"Home-WiFi": {}},
            "guard_service": "", "et_vpn_below": "C", "et_enabled": True, "ni_history": True,
            "ni_reference_dns": "1.1.1.1, 8.8.8.8, 9.9.9.9", "ip_lookup": True, "update_url": "", "crash_report_url": ""}
S = {"connected": False, "connecting": None, "note": None, "active": None, "since": None, "ks_active": False,
     "dns_active": False, "fw_off": False, "giveup": False, "settings": SETTINGS,
     "regions": [] if MODE == "empty" else REGIONS, "admin": True, "wireguard": True, "wg_installing": False,
     "wg_cli": True, "exit": None, "health": None, "home": {"country": "IN"}, "sessions": [], "error": None,
     "log": [{"ts": "09:12:04", "msg": "engine pipe ready for NOBAD's window", "level": "info"}], "tray": True,
     "autostart": False, "update": {"current": "2.0.0", "configured": False}, "crash_pending": 0,
     "network": {"name": "Home-WiFi", "events": True, "pending": None}, "frozen": False, "eviltwin": None}
LOCK = threading.Lock()


def push():
    logbus.broadcast("state", dict(S))


def up(name):
    with LOCK:
        S.update(connecting=None, connected=True, active=name, since=time.time() - (1680 if MODE == "connected" else 0),
                 ks_active=bool(SETTINGS.get("kill_switch")), dns_active=True,
                 exit={"ip": "203.0.113.7", "city": "Tokyo", "country": "JP"},
                 health={"rtt": 61.0, "loss": 0, "jitter": 2.4, "q": "great"})
        SETTINGS["last_region"] = name
    logbus.log(f"connected to {name} (handshake 0.4 s)", "ok")
    push()


def h_connect(b):
    name = b["name"]
    if name not in {r["name"] for r in S["regions"]}:
        return {"ok": False, "error": "unknown server"}
    with LOCK:
        S.update(connecting=name, connected=False, error=None)
    push()
    threading.Timer(1.8, up, args=(name,)).start()
    return {"ok": True}


def h_disconnect(b):
    with LOCK:
        S.update(connected=False, connecting=None, active=None, since=None, ks_active=False, dns_active=False,
                 health=None, exit=None)
    logbus.log("disconnected", "info")
    push()
    return {"ok": True}


def h_settings(b):
    SETTINGS[b["key"]] = b["value"]
    push()
    return {"ok": True}


def h_favorite(b):
    fav = SETTINGS["favorites"]
    fav.remove(b["name"]) if b["name"] in fav else fav.append(b["name"])
    push()
    return {"ok": True}


def h_fastest(b):
    return h_connect({"name": "JP-FREE-3"})


FREE = [{"file": "wg-JP-FREE-7.conf", "name": "JP-FREE-7", "country": "Japan", "host": "146.70.205.2", "port": "51820",
         "provider": "Proton VPN", "already": False},
        {"file": "wg-NL-FREE-12.conf", "name": "NL-FREE-12", "country": "Netherlands", "host": "190.2.132.9",
         "port": "51820", "provider": "Proton VPN", "already": True}]


def ok(b=None):
    return {"ok": True}


HANDLERS = {n: ok for n in params.SPEC if n not in methods.PIPE_ONLY}
HANDLERS.update(connect=h_connect, disconnect=h_disconnect, settings=h_settings, favorite=h_favorite,
                fastest=h_fastest, smart=h_fastest,
                theme=lambda b: h_settings({"key": "theme", "value": b["value"]}),
                dismiss_error=lambda b: (S.update(error=None), push(), {"ok": True})[2],
                free_scan=lambda b: {"ok": True, "folder": "C:\\Users\\you\\Downloads", "files": FREE},
                net_changes=lambda b: {"ok": True, "changes": []},
                config_get=lambda b: {"ok": True, "name": b["name"], "encrypted": True, "text":
                                      "[Interface]\nPrivateKey = (hidden)\nAddress = 10.2.0.2/32\nDNS = 10.2.0.1\n\n"
                                      "[Peer]\nPublicKey = xTIBA5rboUvnH4htodjb6e697QjLERt1NAB4mZqp8Dg=\n"
                                      "AllowedIPs = 0.0.0.0/0, ::/0\nEndpoint = jp-free-3.protonvpn.net:51820\n"},
                config_validate=lambda b: {"ok": True, "valid": "[Interface]" in b["text"], "errors": [], "warnings": []})


def traffic():
    t = 0.0
    while True:
        time.sleep(.12 if MODE == "connected" and t < 60 else 2)   # "connected": a chart that already has a history
        if not S["connected"] or not logbus.has_subscribers() or (t >= 60 and not logbus.has_viewers()):
            continue
        t += 1
        wave = (math.sin(t / 3) + 1) / 2
        burst = 3.0 if random.random() < .12 else 1.0
        logbus.broadcast("traffic", {"rx_bps": 2.2e6 + 9e6 * wave * burst + random.random() * 8e5,
                                     "tx_bps": 2.4e5 + 6e5 * (1 - wave) + random.random() * 1e5,
                                     "rx_total": int(t * 3e6), "tx_total": int(t * 2e5)})


def main():
    sid = security.own_user_sid()
    rpc = Rpc(handlers=HANDLERS, state=lambda: dict(S), name=security.pipe_name(sid, dev=True), user_sid=sid,
              launch_ui=lambda w: False)
    if not rpc.start():
        print("the demo pipe is taken: is another demo engine running?")
        return 1
    if MODE == "connected":
        up("JP-FREE-3")
    elif MODE == "connecting":
        S.update(connecting="JP-FREE-3")
    elif MODE == "blocked":
        S.update(ks_active=True, note=None)
    elif MODE == "error":
        S.update(error={"code": "handshake", "title": "JP-FREE-3 never completed a handshake",
                        "detail": "Check the keys and the endpoint address/port.", "name": "JP-FREE-3",
                        "ts": int(time.time()), "actions": [{"id": "retry", "label": "Retry"},
                                                            {"id": "check_endpoint", "label": "Check endpoint"},
                                                            {"id": "show_log", "label": "Show log"}]})
    threading.Thread(target=traffic, daemon=True).start()
    print(f"demo engine ({MODE}) on {security.pipe_name(sid, dev=True)}; Ctrl+C stops it", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        rpc.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
