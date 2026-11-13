"""One-click diagnostics bundle (zip). Private and preshared keys never enter it: configs are redacted, every text
is scrubbed, and the real key values found in the configs are removed from everything as a second line of defence."""
import io
import json
import os
import platform
import re
import sys
import time
import zipfile

from . import confparse, firewall, netinfo
from .const import APP_VER, EXPORT_DIR, LOG_DIR
from .ctx import ctx
from .logbus import scrub
from .syscmd import is_admin, list_wg_services, run, wg_tool

_MAC = re.compile(r"\b([0-9A-Fa-f]{2}[-:]){5}[0-9A-Fa-f]{2}\b")
_SENSITIVE_SETTINGS = ("trusted_networks", "crash_report_url", "update_url", "window")
# netsh / log lines that name a Wi-Fi network (SSIDs can identify your home or workplace)
_WLAN_LINE = re.compile(r"(?im)^(\s*(?:SSID|Profile|Network name)\s*:\s*)(.+?)\s*$")


def _config_dir():
    from .engine import config_dir  # the folder actually in use (ProgramData, or the legacy fallback)
    return config_dir()


def _network_names():
    names = set(ctx.settings.get("trusted_networks") or []) if ctx.settings else set()
    if ctx.netwatch and ctx.netwatch.current:
        names.add(ctx.netwatch.current)
    return {n for n in names if n and n not in ("Ethernet",)}


def scrub_text(text, secrets=(), names=()):
    text = scrub(text)
    text = _MAC.sub("xx-xx-xx-xx-xx-xx", text)
    text = _WLAN_LINE.sub(lambda m: m.group(1) + "(network name hidden)", text)
    for s in secrets:
        if s and len(s) >= 20:
            text = text.replace(s, "(hidden)")
    for n in names:
        text = text.replace(f'"{n}"', '"(network name hidden)"')
    return text


def _secret_values():
    out = set()
    d = _config_dir()
    try:
        for fn in os.listdir(d):
            if confparse.stem_of(fn):
                try:
                    t = confparse.read_conf_text(os.path.join(d, fn))
                except Exception:
                    continue
                for m in re.finditer(r"(?im)^\s*(?:PrivateKey|PresharedKey)\s*=\s*(\S+)", t):
                    out.add(m.group(1))
    except OSError:
        pass
    return out


def _dpi():
    try:
        import ctypes
        return round(ctypes.windll.user32.GetDpiForSystem() / 96 * 100)
    except Exception:
        return None


def _winver():
    try:
        v = sys.getwindowsversion()
        return f"{v.major}.{v.minor}.{v.build} (Windows {'11' if v.build >= 22000 else '10'})"
    except Exception:
        return platform.platform()


def collect(tunnel=None):
    """Returns {filename: text}. Pure data gathering; nothing is written here."""
    t = tunnel or ctx.tunnel
    files = {}
    st = {k: v for k, v in ctx.settings.snapshot().items() if k not in _SENSITIVE_SETTINGS}
    st["trusted_networks_count"] = len(ctx.settings.get("trusted_networks") or [])
    files["summary.json"] = json.dumps({
        "app_version": APP_VER, "python": sys.version, "os": _winver(), "admin": is_admin(), "dpi_percent": _dpi(),
        "net_caps": netinfo.net_caps(), "wireguard_exe": bool(wg_tool("wireguard.exe")),
        "settings": st, "connected": t.connected, "active": t.active, "kill_switch_armed": t.ks_active,
        "dns_block_armed": t.dns_active, "firewall_rules_present": firewall.present(),
        "network_events": [(int(a), b, c) for a, b, c in (ctx.netwatch.history[-30:] if ctx.netwatch else [])],
        "servers": [{"name": r["name"], "host": r["host"], "port": r["port"], "encrypted": r["enc"],
                     "full_tunnel": r["info"]["full"], "ipv6": r["info"]["v6"], "dns_line": r["info"]["dns"]}
                    for r in t._regions]}, indent=1)
    for r in t._regions:
        try:
            files[f"configs_redacted/{r['name']}.conf.txt"] = confparse.redact_conf(
                confparse.read_conf_text(os.path.join(_config_dir(), r["file"])))
        except Exception as e:
            files[f"configs_redacted/{r['name']}.error.txt"] = str(e)
    try:
        for fn in sorted(os.listdir(LOG_DIR)):
            if fn.startswith("nobad.log"):
                with open(os.path.join(LOG_DIR, fn), "r", encoding="utf-8", errors="replace") as f:
                    files[f"logs/{fn}"] = f.read()
    except OSError:
        pass
    cmds = {"system/ipconfig.txt": ["ipconfig", "/all"], "system/route4.txt": ["route", "print", "-4"],
            "system/route6.txt": ["route", "print", "-6"], "system/wlan.txt": ["netsh", "wlan", "show", "interfaces"],
            "system/firewall_nobad.txt": ["netsh", "advfirewall", "firewall", "show", "rule", "name=all", "dir=out"]}
    for fn, c in cmds.items():
        out = run(c, timeout=25).stdout or ""
        if fn.endswith("firewall_nobad.txt"):
            out = "\n\n".join(b for b in out.split("\n\n") if "Nobad" in b)
        files[fn] = out
    wg, cli = wg_tool("wireguard.exe"), wg_tool("wg.exe")
    if cli:
        files["system/wg_show.txt"] = run([cli, "show"], timeout=10).stdout or ""
    if wg:
        files["system/wireguard_log.txt"] = run([wg, "/dumplog"], timeout=15).stdout or ""
    files["system/wg_services.txt"] = "\n".join(
        f"{n}: {run(['sc', 'query', 'WireGuardTunnel$' + n]).stdout}" for n in list_wg_services())
    files["README.txt"] = ("NOBAD VPN diagnostics\n\nPrivate and preshared keys are removed. Server endpoints, public keys and "
                           "your network's IP addressing are included so problems can be reproduced; MAC addresses are masked. "
                           "Review the files before sharing them.\n")
    return files


def build_bundle(out_dir=None, tunnel=None, files=None):
    files = files if files is not None else collect(tunnel)
    secrets = _secret_values()
    names = _network_names()
    out_dir = out_dir or EXPORT_DIR
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, time.strftime("NobadDiagnostics-%Y%m%d-%H%M%S.zip"))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in files.items():
            z.writestr(name, scrub_text(text, secrets, names))
    with open(path, "wb") as f:
        f.write(buf.getvalue())
    return path


def user_destination():
    for sub in ("Desktop", "Downloads"):
        d = os.path.join(os.path.expanduser("~"), sub)
        if os.path.isdir(d):
            return d
    return EXPORT_DIR
