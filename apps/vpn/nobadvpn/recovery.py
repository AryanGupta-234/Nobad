"""Last-resort recovery that works without a running engine: used by the panic button, `--panic`
on the command line, the tray menu and the watchdog."""
import os

from . import firewall
import re

from .const import CONFIG_DIR, LEGACY_CONFIG_DIR, RUNTIME_DIR
from .confparse import stem_of
from .logbus import log
from .syscmd import run, wg_tool


def config_names():
    names = set()
    for d in (CONFIG_DIR, LEGACY_CONFIG_DIR):
        try:
            names.update(s for s in (stem_of(f) for f in os.listdir(d)) if s)
        except OSError:
            pass
    return sorted(names)


def runtime_names():
    """Tunnels started from our runtime folder (covers configs that were deleted or renamed since)."""
    try:
        return sorted({s for s in (stem_of(f) for f in os.listdir(RUNTIME_DIR)) if s})
    except OSError:
        return []


def tunnel_services():
    """Names of every installed WireGuardTunnel$<name> service."""
    r = run(["sc", "query", "type=", "service", "state=", "all"], timeout=20)
    return sorted(set(re.findall(r"SERVICE_NAME:\s*WireGuardTunnel\$(\S+)", r.stdout or "", re.I)))


def clean_runtime_dir():
    try:
        for fn in os.listdir(RUNTIME_DIR):
            if fn.lower().endswith((".conf", ".dpapi")):
                try:
                    os.remove(os.path.join(RUNTIME_DIR, fn))
                except OSError:
                    pass
    except OSError:
        pass


def panic_reset_system(extra_names=(), restore_dns=False):
    """Remove every NOBAD firewall rule and uninstall every tunnel service that belongs to one of our configs
    (current or legacy folder, runtime copies, or names the running engine knows). Other WireGuard tunnels
    (e.g. created in the WireGuard app) are left alone. Returns a summary dict."""
    wg = wg_tool("wireguard.exe")
    removed = []
    if wg:
        ours = set(config_names()) | set(runtime_names()) | set(extra_names or ())
        installed = set(tunnel_services())
        targets = sorted(ours & installed) if installed else sorted(ours)
        for name in targets:
            r = run([wg, "/uninstalltunnelservice", name], timeout=25)
            if r.returncode == 0:
                removed.append(name)
    found = firewall.installed_names()
    every = firewall.ALL_RULES + firewall.LEGACY_RULES
    present = [n for n in every if found is None or n in found]
    firewall.remove(every, known=found)     # None -> delete every name (listing failed: be thorough)
    after = firewall.installed_names()
    left = [n for n in every if after is not None and n in after]
    clean_runtime_dir()
    summary = {"services_removed": removed, "rules_removed": [n for n in present if n not in left],
               "rules_left": left, "wireguard_found": bool(wg)}
    if restore_dns:
        from . import netjournal   # adapter DNS the fix agent changed: put back what was there before
        summary["dns_restored"] = netjournal.restore_all()
    log(f"panic reset: removed {len(summary['rules_removed'])} firewall rule(s), "
        f"stopped {len(removed)} tunnel service(s)", "warn")
    return summary


def guard_decide(clean_exit, app_alive, tunnel_running, rules_present, autostart_on, failopen):
    """Boot guard policy (pure, unit-tested). Runs as SYSTEM when Windows starts, before anyone signs in.
    It only ever RESTORES internet, and only when NOBAD can't do it itself:
      * clean exit / NOBAD already running / tunnel up (you're protected) -> leave everything alone
      * kill-switch rules left behind, tunnel down:
          - NOBAD starts at sign-in and you chose 'stay blocked' -> leave it (that IS the kill switch; NOBAD
            re-arms or clears the rules itself a few seconds after sign-in)
          - otherwise nobody would ever remove them -> restore internet"""
    if clean_exit or app_alive or tunnel_running or not rules_present:
        return "leave"
    if autostart_on and not failopen:
        return "leave"
    return "restore"


def boot_guard():
    """`NobadVPN --guard` (the 'NobadVPN Guard' startup task). Returns the action taken."""
    import json
    from .autostart import task_exists
    from .const import CLEAN_EXIT_PATH, INSTANCE_PATH, SETTINGS_PATH
    from .syscmd import service_running
    from .watchdog import _pid_alive
    alive = False
    try:
        with open(INSTANCE_PATH) as f:
            alive = _pid_alive(int(json.load(f).get("pid") or 0))
    except (OSError, ValueError, TypeError):
        pass
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            failopen = bool(json.load(f).get("watchdog_failopen"))
    except (OSError, ValueError):
        failopen = False
    import time
    ours = set(config_names()) & set(tunnel_services())
    running = any(service_running(n) for n in ours)
    t0 = time.time()
    while ours and not running and time.time() - t0 < 30:   # an auto-start tunnel may still be coming up at boot
        time.sleep(3)
        running = any(service_running(n) for n in ours)
    action = guard_decide(os.path.exists(CLEAN_EXIT_PATH), alive, running, bool(firewall.present()),
                          task_exists(), failopen)
    if action == "restore":
        s = panic_reset_system(restore_dns=True)
        log(f"boot guard: NOBAD did not exit cleanly and left the kill switch on; internet restored "
            f"({len(s['rules_removed'])} rule(s) removed)", "warn")
    return action
