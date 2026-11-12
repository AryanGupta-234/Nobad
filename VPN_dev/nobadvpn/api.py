"""POST /api/<name> handlers. Each returns a JSON-able dict; long work is spawned, never run on the request thread."""
import os
import subprocess
import sys
import webbrowser

from . import autostart, configstore, crash, diagnostics, netinfo
from . import settings as settings_mod
from .const import EXPORT_DIR
from .ctx import ctx
from .engine import config_dir, ensure_dirs
from .lifecycle import request_quit
from .logbus import broadcast, log
from .syscmd import is_admin, run, run_once, spawn, try_self_elevate
from .tools import (fetch_ipinfo, gaming_probe, network_diagnose, speed_test, startup_checks, stream_check,
                    valorant_region_check)

ALLOWED_URLS = {"wireguard_install": "https://www.wireguard.com/install/", "neverssl": "http://neverssl.com",
                "firewall_settings": "windowsdefender://network/"}  # Windows Security → Firewall & network protection
_autostart_cache = {"v": None}


def _busy(msg):
    return {"ok": False, "error": msg}


def refresh_autostart_cache():
    _autostart_cache["v"] = autostart.task_exists()


def extra_state():
    nw = ctx.netwatch
    return {"tray": bool(ctx.tray and ctx.tray.available),
            "autostart": bool(_autostart_cache["v"]),
            "update": ctx.updater.snapshot() if ctx.updater else None,
            "crash_pending": len(crash.pending()),
            "network": {"name": nw.current if nw else None, "events": bool(nw and nw.events_ok)},
            "frozen": getattr(sys, "frozen", False)}


def apply_setting(key, val):
    s, t = ctx.settings, ctx.tunnel
    prev = s.get(key)
    if key == "kill_switch":
        s.set(key, val)
        spawn(t.set_kill_switch, val)
        return
    if key == "dns_leak_block":
        s.set(key, val)
        spawn(t.set_dns_block, val)
        return
    if key == "start_with_windows":
        def work():
            ok, msg = autostart.enable() if val else autostart.disable()
            refresh_autostart_cache()
            s.set(key, bool(_autostart_cache["v"]) if ok else prev)
            log(msg or ("start with Windows " + ("on" if val else "off")), "ok" if ok else "bad")
            broadcast("fix_result", {"ok": ok, "message": msg or ""})
            t.push()
        spawn(work)
        return
    if key == "encrypt_configs":
        s.set(key, val)

        def work2():
            r = configstore.set_encryption(val)
            if not r.get("ok"):
                s.set(key, prev)
            broadcast("fix_result", {"ok": r.get("ok", False), "message":
                                     (f"{r.get('converted', 0)} config(s) converted." if r.get("ok") else r.get("error", "Some configs could not be converted — see the log."))})
            t.push()
        spawn(work2)
        return
    s.set(key, val)
    if key == "ip_lookup":
        if not val:
            t.exit = {"disabled": True}
            t.home = None
        else:
            t.exit = None
            spawn(fetch_ipinfo)
            spawn(t.geo_refresh)
    elif key == "tray" and ctx.tray:
        spawn(ctx.tray.apply_setting)
    elif key in ("ssid_rules", "trusted_networks", "autoconnect_untrusted", "autodisconnect_trusted") and ctx.netwatch:
        ctx.netwatch.poke()
        if key == "ssid_rules" and val:
            spawn(ctx.netwatch.evaluate_rules, "rules enabled")
    t.push()


def h_settings(b):
    ok, val = settings_mod.coerce(b.get("key"), b.get("value"))
    if not ok:
        return {"ok": False, "error": val if isinstance(val, str) else "bad value"}
    apply_setting(b["key"], val)
    return {"ok": True}


def h_connect(b):
    name = str(b.get("name", ""))
    if not ctx.tunnel.has_region(name):
        return {"ok": False, "error": "unknown server"}
    spawn(ctx.tunnel.connect, name)
    return {"ok": True}


def h_disconnect(b):
    spawn(ctx.tunnel.disconnect)
    return {"ok": True}


def h_fastest(b):
    return {"ok": True} if run_once("fastest", ctx.tunnel.fastest) else _busy("Server comparison is already running.")


def h_smart(b):
    return {"ok": True} if run_once("fastest", ctx.tunnel.smart_connect, b.get("service") or None) else \
        _busy("Server comparison is already running.")


def h_probe(b):
    return {"ok": True} if run_once("probe", ctx.tunnel.probe_all) else _busy("Server scan is already running.")


def h_favorite(b):
    name = str(b.get("name", ""))
    if not ctx.tunnel.has_region(name):
        return {"ok": False, "error": "unknown server"}
    fav = list(ctx.settings.get("favorites") or [])
    fav.remove(name) if name in fav else fav.append(name)
    ctx.settings.set("favorites", fav)
    ctx.tunnel.push()
    return {"ok": True}


def h_theme(b):
    return h_settings({"key": "theme", "value": b.get("value")})


def h_network_diagnose(b):
    return {"ok": True} if run_once("network_diagnose", lambda: broadcast("network_diagnose", network_diagnose())) \
        else _busy("Network diagnostics are already running.")


def h_startup_checks(b):
    startup_checks()
    return {"ok": True}


def h_valorant(b):
    return {"ok": True} if run_once("valorant_manual", valorant_region_check) else _busy("VALORANT region checks are already running.")


def h_gaming(b):
    host = str(b.get("host", ""))
    return {"ok": True} if run_once("gaming", lambda: broadcast("gaming_probe", gaming_probe(host))) else \
        _busy("An endpoint test is already running.")


def h_flush_dns(b):
    if os.name != "nt":
        return {"ok": False, "error": "DNS cache clearing is supported on Windows only."}

    def work():
        r = run(["ipconfig", "/flushdns"], timeout=10)
        ok = r.returncode == 0
        log("DNS cache cleared" if ok else "DNS cache clear failed", "ok" if ok else "warn")
        broadcast("fix_result", {"ok": ok, "message": "Windows cleared its saved website lookups. Run the network check again."
                                 if ok else "Windows could not clear the DNS cache. Try running NOBAD as administrator."})
    return {"ok": True} if run_once("flush_dns", work) else _busy("DNS cache clearing is already running.")


def h_speedtest(b):
    return {"ok": True} if run_once("speed", speed_test) else _busy("A speed test is already running.")


def h_streamcheck(b):
    return {"ok": True} if run_once("stream", stream_check) else _busy("Service checks are already running.")


def h_ipinfo(b):
    if not ctx.settings.get("ip_lookup"):
        return {"ok": False, "error": "IP lookup is turned off in Settings → Privacy."}
    return {"ok": True} if run_once("ipinfo", fetch_ipinfo) else _busy("IP refresh is already running.")


def h_rescan(b):
    def work():
        ctx.tunnel.rescan()
        ctx.tunnel.push()
        spawn(ctx.tunnel.geo_refresh)
    return {"ok": True} if run_once("rescan", work) else _busy("A configuration scan is already running.")


def h_open_configs(b):
    ensure_dirs()
    if os.name == "nt":
        os.startfile(config_dir())
    return {"ok": True}


def h_import(b):
    return configstore.import_text(b.get("name"), b.get("content"), untrusted=bool(b.get("untrusted")))


def h_import_url(b):
    return configstore.import_url(b.get("url"), b.get("name"))


def h_config_get(b):
    return configstore.read(str(b.get("name", "")))


def h_config_validate(b):
    return configstore.validate(str(b.get("name", "")) or None, str(b.get("text", "")))


def h_config_save(b):
    return configstore.save(str(b.get("name", "")), b.get("text", ""), create=False)


def h_config_delete(b):
    return configstore.delete(str(b.get("name", "")))


def h_endpoint_check(b):
    name = str(b.get("name", ""))
    r = ctx.tunnel.region(name)
    if not r:
        return {"ok": False, "error": "unknown server"}

    def work():
        ips = ctx.tunnel._resolve(r["host"])
        rep = netinfo.endpoint_report(r["host"], r["port"], ips)
        rep["name"] = name
        broadcast("endpoint_report", rep)
    return {"ok": True} if run_once("endpoint_check", work) else _busy("An endpoint check is already running.")


def h_panic(b):
    spawn(ctx.tunnel.panic_reset)
    return {"ok": True}


def h_net_repair(b):
    """Network safety levels (netrepair): undo / quick / full. The UI confirms first; results stream back."""
    from . import netrepair
    level = b.get("level")
    if level not in netrepair.LEVELS:
        return {"ok": False, "error": "Unknown repair level."}

    def work():
        broadcast("net_repair_start", {"level": level})
        broadcast("net_repair_done", netrepair.repair(level, panic=ctx.tunnel.panic_reset))
    return {"ok": True} if run_once("net_repair", work) else _busy("A network repair is already running.")


def h_net_changes(b):
    from . import netjournal
    return {"ok": True, "changes": netjournal.entries()}


def h_usage(b):
    days = b.get("days", 30)
    days = days if isinstance(days, int) and 0 <= days <= 400 else 30
    return {"ok": True, **ctx.usage.summary(days)}


def h_ui_state(b):
    tab = b.get("tab")
    ok, val = settings_mod.coerce("last_tab", tab)
    if ok:
        ctx.settings.set("last_tab", val)
    return {"ok": True}


def h_wizard_done(b):
    ctx.settings.set("wizard_done", True)
    ctx.tunnel.push()
    return {"ok": True}


def h_dismiss_error(b):
    ctx.tunnel.clear_error()
    ctx.tunnel.push()
    return {"ok": True}


def install_wireguard_work(auto=False, installer=None):
    """Shared by the Install button and the automatic start-up repair. Returns (ok, message)."""
    from . import wginstall
    ctx.tunnel.push()                       # state now carries wg_installing: the banner shows progress, not a button
    broadcast("fix_result", {"ok": True, "message": "WireGuard is missing. Installing it…" if auto else "Installing WireGuard…"})
    ok, msg = (installer or wginstall.install)()
    log(("automatic repair: " if auto else "") + msg, "ok" if ok else "bad")
    broadcast("fix_result", {"ok": ok, "message": msg})
    if ok and ctx.tunnel.last_error and ctx.tunnel.last_error.get("code") == "wg_missing":
        ctx.tunnel.clear_error()
    if auto and ctx.tray:
        ctx.tray.notify("WireGuard installed" if ok else "WireGuard couldn't be installed",
                        "NOBAD VPN is ready to connect." if ok else msg + " Use Install WireGuard in NOBAD to try again.")
    return ok, msg


def auto_install_wireguard(installed=None):
    """Start-up check: WireGuard missing + setting on + elevated -> install it once, in the background.
    Returns True when an install was started."""
    from .syscmd import is_admin
    from .syscmd import wg_tool
    if os.name != "nt" or not ctx.settings.get("auto_install_wg") or not is_admin():
        return False
    if (installed or (lambda: wg_tool("wireguard.exe") is not None))():
        return False
    log("WireGuard for Windows is missing: installing it automatically", "warn")
    return run_once("install_wg", install_wireguard_work, True)


def h_install_wireguard(b):
    if os.name != "nt":
        return {"ok": False, "error": "Windows only."}
    return {"ok": True} if run_once("install_wg", install_wireguard_work) else _busy("The install is already running.")


def h_elevate(b):
    if is_admin():
        return {"ok": False, "error": "Already running as administrator."}
    if try_self_elevate():
        request_quit(False)
        return {"ok": True}
    return {"ok": False, "error": "Windows did not grant administrator rights."}


def h_open_url(b):
    key = b.get("key")
    url = ALLOWED_URLS.get(key)
    if key == "portal":
        err = ctx.tunnel.last_error or {}
        p = err.get("portal")
        url = p if isinstance(p, str) and p.startswith(("http://", "https://")) else ALLOWED_URLS["neverssl"]
    if not url:
        return {"ok": False, "error": "unknown link"}
    webbrowser.open(url)
    return {"ok": True}


def h_diagnostics_export(b):
    def work():
        try:
            path = diagnostics.build_bundle(EXPORT_DIR)
            dest = diagnostics.user_destination()
            final = path
            if dest != EXPORT_DIR:
                import shutil
                final = os.path.join(dest, os.path.basename(path))
                shutil.copy2(path, final)
            log(f"diagnostics saved: {final}", "ok")
            broadcast("fix_result", {"ok": True, "message": f"Diagnostics saved to {final} (keys removed)."})
            if os.name == "nt":
                subprocess.Popen(["explorer", "/select,", final])
        except Exception as e:
            log(f"diagnostics export failed: {e}", "bad")
            broadcast("fix_result", {"ok": False, "message": f"Export failed: {e}"})
    return {"ok": True} if run_once("diag_export", work) else _busy("An export is already running.")


def h_update_check(b):
    return {"ok": True} if run_once("update_check", ctx.updater.check) else _busy("Already checking.")


def h_update_install(b):
    return {"ok": True} if run_once("update_install", ctx.updater.download_and_install) else _busy("Already installing.")


def h_crash_pending(b):
    items = []
    for p in crash.pending()[-3:]:
        try:
            r = crash.preview(p)
            items.append({"file": os.path.basename(p), "ts": r.get("ts"), "where": r.get("where"),
                          "traceback": r.get("traceback", "")[-1500:], "log_tail": r.get("log_tail", [])[-15:]})
        except Exception:
            continue
    return {"ok": True, "items": items, "configured": bool(ctx.settings.get("crash_report_url"))}


def _crash_path(name):
    from .const import CRASH_DIR
    name = os.path.basename(str(name))
    p = os.path.join(CRASH_DIR, name)
    return p if name.startswith("crash-") and name.endswith(".json") and os.path.exists(p) else None


def h_crash_send(b):
    p = _crash_path(b.get("file"))
    if not p:
        return {"ok": False, "error": "unknown report"}
    ok, msg = crash.send(p)
    ctx.tunnel.push()
    return {"ok": ok, "message": msg, **({} if ok else {"error": msg})}


def h_crash_dismiss(b):
    p = _crash_path(b.get("file"))
    if p:
        crash.dismiss(p)
    ctx.tunnel.push()
    return {"ok": True}


def h_guard_check(b):
    return {"ok": True} if run_once("guard", ctx.tunnel.guard_check) else _busy("Already checking.")


def h_current_network(b):
    return {"ok": True, "name": netinfo.current_network_name()}


def h_trusted_add(b):
    name = str(b.get("name") or "").strip() or netinfo.current_network_name()
    if not name:
        return {"ok": False, "error": "No network detected."}
    lst = list(ctx.settings.get("trusted_networks") or [])
    if name not in lst:
        lst.append(name)
    apply_setting("trusted_networks", lst)
    return {"ok": True, "name": name}


def h_window(b):
    w = ctx.windows
    act = b.get("do")
    if not w:
        return {"ok": False}
    if act == "show":
        w.show_main()
    elif act == "hide_mini":
        w.hide_mini()
    elif act == "mini":
        w.toggle_mini()
    # "noop": a background (tray-only) second launch just checks that this copy is alive
    return {"ok": True}


def h_quit(b):
    request_quit(bool(b.get("disconnect")))
    return {"ok": True}


HANDLERS = {
    "connect": h_connect, "disconnect": h_disconnect, "fastest": h_fastest, "smart": h_smart, "probe": h_probe,
    "settings": h_settings, "favorite": h_favorite, "theme": h_theme, "network_diagnose": h_network_diagnose,
    "startup_checks": h_startup_checks, "valorant_probe": h_valorant, "gaming_probe": h_gaming,
    "flush_dns": h_flush_dns, "speedtest": h_speedtest, "streamcheck": h_streamcheck, "ipinfo": h_ipinfo,
    "rescan": h_rescan, "open_configs": h_open_configs, "import": h_import, "import_url": h_import_url,
    "config_get": h_config_get, "config_validate": h_config_validate, "config_save": h_config_save,
    "config_delete": h_config_delete, "endpoint_check": h_endpoint_check, "panic_reset": h_panic,
    "net_repair": h_net_repair, "net_changes": h_net_changes,
    "usage": h_usage, "ui_state": h_ui_state, "wizard_done": h_wizard_done, "dismiss_error": h_dismiss_error,
    "install_wireguard": h_install_wireguard, "elevate": h_elevate, "open_url": h_open_url,
    "diagnostics_export": h_diagnostics_export, "update_check": h_update_check, "update_install": h_update_install,
    "crash_pending": h_crash_pending, "crash_send": h_crash_send, "crash_dismiss": h_crash_dismiss,
    "guard_check": h_guard_check, "current_network": h_current_network, "trusted_add": h_trusted_add,
    "window": h_window, "quit": h_quit,
}


from .netintel.api_handlers import HANDLERS as _NI_HANDLERS   # Network Intelligence (independent feature)
HANDLERS.update(_NI_HANDLERS)


def api_post(path, b):
    fn = HANDLERS.get(path)
    if not fn:
        return {"ok": False, "error": "not found"}
    return fn(b)
