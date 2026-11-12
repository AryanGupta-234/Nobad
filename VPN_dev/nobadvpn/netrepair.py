"""Network reset / repair, usable with the app running, from the Start menu while NOBAD is closed, or offline.

Levels (each includes the ones before it; every step reports the real exit code of the real command):
  undo  - remove everything NOBAD itself changed: kill-switch/DNS-leak firewall rules, NOBAD tunnel services,
          runtime copies, and adapter DNS changes recorded in the change journal.
  quick - undo + flush the DNS cache, re-register DNS, clear the ARP cache, renew DHCP leases.
          Takes seconds; Wi-Fi/Ethernet may blink once while leases renew.
  full  - quick + reset Winsock, the IPv4/IPv6 TCP/IP stacks and the WinHTTP proxy (Windows' own "network reset"
          building blocks). Needs a restart; static IP settings on adapters must be re-entered afterwards.
Nothing here runs unless the user picked it (or the uninstaller runs `--panic`, which is `undo`)."""
from . import netjournal, recovery
from .logbus import log
from .syscmd import run

LEVELS = ("undo", "quick", "full")

QUICK_STEPS = [
    ("Flush DNS cache", ["ipconfig", "/flushdns"], 20),
    ("Re-register DNS names", ["ipconfig", "/registerdns"], 30),
    ("Clear ARP cache", ["netsh", "interface", "ip", "delete", "arpcache"], 20),
    ("Renew DHCP leases (IPv4)", ["ipconfig", "/renew"], 90),
]
FULL_STEPS = [
    ("Reset Winsock catalog", ["netsh", "winsock", "reset"], 60),
    ("Reset IPv4 TCP/IP stack", ["netsh", "int", "ipv4", "reset"], 60),
    ("Reset IPv6 TCP/IP stack", ["netsh", "int", "ipv6", "reset"], 60),
    ("Reset WinHTTP proxy", ["netsh", "winhttp", "reset", "proxy"], 20),
]


def _step(name, cmd, timeout):
    r = run(cmd, timeout=timeout)
    out = ((r.stdout or "") + " " + (r.stderr or "")).strip()
    ok = r.returncode == 0
    # /renew returns non-zero when some adapter has no DHCP (static IP / disconnected): not a failure of the repair
    if not ok and cmd[:2] == ["ipconfig", "/renew"] and "dhcp" in out.lower():
        ok = True
    return {"step": name, "command": " ".join(cmd), "ok": ok, "code": r.returncode,
            "detail": " ".join(out.split())[:240]}


def undo_nobad_changes(extra_names=(), panic=None):
    """`panic` lets the running engine pass its own (locked) panic_reset; the CLI/boot paths use recovery's."""
    steps = []
    s = panic() if panic else recovery.panic_reset_system(extra_names)
    s = s or {}
    left = s.get("rules_left") or []
    steps.append({"step": "Remove NOBAD firewall rules", "command": "netsh advfirewall firewall delete rule",
                  "ok": not left, "code": 0 if not left else 1,
                  "detail": f"{len(s.get('rules_removed') or [])} removed" + (f", left: {', '.join(left)}" if left else "")})
    steps.append({"step": "Stop NOBAD tunnel services", "command": "wireguard /uninstalltunnelservice",
                  "ok": True, "code": 0, "detail": f"{len(s.get('services_removed') or [])} stopped"})
    for x in netjournal.restore_all():
        steps.append({"step": "Restore adapter DNS", "command": "Set-DnsClientServerAddress", "ok": x["ok"],
                      "code": 0 if x["ok"] else 1, "detail": x["detail"]})
    return steps


def repair(level="quick", extra_names=(), panic=None):
    if level not in LEVELS:
        raise ValueError(f"unknown repair level {level!r}")
    steps = undo_nobad_changes(extra_names, panic)
    if level in ("quick", "full"):
        steps += [_step(*s) for s in QUICK_STEPS]
    if level == "full":
        steps += [_step(*s) for s in FULL_STEPS]
    ok = all(s["ok"] for s in steps)
    res = {"level": level, "ok": ok, "steps": steps, "restart_needed": level == "full"}
    log(f"network repair ({level}): {sum(s['ok'] for s in steps)}/{len(steps)} steps succeeded"
        + (" - restart Windows to finish" if level == "full" else ""), "ok" if ok else "warn")
    return res
