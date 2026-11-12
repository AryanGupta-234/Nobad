"""`NobadVPN --selftest`: prints what this machine supports. Paste the output when reporting a Windows 10/11,
IPv6-only, captive-portal or DPI problem."""
import os
import time

from . import autostart, dpapi, firewall, netinfo
from .const import APP_VER, DATA_DIR
from .syscmd import is_admin, run, wg_tool


def _row(rows, name, ok, detail=""):
    rows.append((name, ok, detail))
    mark = {True: "PASS", False: "FAIL", None: "info"}[ok]
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))


def run_selftest():
    rows = []
    print(f"NOBAD VPN {APP_VER} self-test\n")
    from .diagnostics import _winver, _dpi
    _row(rows, "Windows version", None, _winver())
    _row(rows, "Display scaling", None, f"{_dpi()} %" if _dpi() else "unknown")
    _row(rows, "Administrator", is_admin() or os.name != "nt", "elevated" if is_admin() else "not elevated")
    wg = wg_tool("wireguard.exe")
    _row(rows, "WireGuard for Windows", bool(wg), wg or "not found")
    _row(rows, "wg.exe (traffic stats)", bool(wg_tool("wg.exe")), wg_tool("wg.exe") or "not found")
    caps = netinfo.net_caps()
    _row(rows, "IPv4 route", caps["v4"])
    _row(rows, "IPv6 route", None, "yes" if caps["v6"] else "no" + (" (IPv4-only network)" if caps["v4"] else ""))
    if not caps["v4"] and caps["v6"]:
        _row(rows, "IPv6-only network", None, "endpoints must have an AAAA record or be IPv6 literals")
    _row(rows, "Network name", None, str(netinfo.current_network_name()))
    cap = netinfo.captive_check()
    _row(rows, "Captive portal check", cap["status"] != "captive", cap["status"] + (f" → {cap['portal']}" if cap["portal"] else ""))
    try:
        blob = dpapi.protect(b"selftest", "selftest")
        _row(rows, "DPAPI round-trip", dpapi.unprotect(blob, "selftest") == b"selftest")
    except Exception as e:
        _row(rows, "DPAPI round-trip", False, str(e))
    if os.name == "nt" and is_admin():
        r = {"name": "NobadSelfTest", "protocol": "any", "remoteport": None,
             "localip": [firewall._N("192.0.2.0/24")], "remoteip": [firewall._N("192.0.2.1/32")]}
        ok = run(firewall._add_cmd(r), 20).returncode == 0
        gone = False
        if ok:
            run(["netsh", "advfirewall", "firewall", "delete", "rule", "name=NobadSelfTest"], 20)
            gone = not firewall.rule_exists("NobadSelfTest")
        _row(rows, "Firewall rule create/delete", ok and gone)
    else:
        _row(rows, "Firewall rule create/delete", None, "skipped (needs Windows + administrator)")
    _row(rows, "Scheduled tasks (start with Windows)", None, "task present" if autostart.task_exists() else "no task yet")
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        p = os.path.join(DATA_DIR, ".selftest")
        with open(p, "w") as f:
            f.write(str(time.time()))
        os.remove(p)
        _row(rows, "Data folder writable", True, DATA_DIR)
    except OSError as e:
        _row(rows, "Data folder writable", False, str(e))
    for mod in ("webview", "pystray", "PIL"):
        try:
            __import__(mod)
            _row(rows, f"Python module {mod}", True)
        except Exception:
            _row(rows, f"Python module {mod}", None, "missing (optional for tray)" if mod != "webview" else "missing (browser fallback)")
    failed = [n for n, ok, _ in rows if ok is False]
    print(f"\n{len(failed)} problem(s)." if failed else "\nAll checks passed.")
    return 1 if failed else 0
