"""The tunnel controller: connect / verify / repair / fail over, clean reconnect after sleep or network changes,
captive-portal handling, streaming guard and usage accounting. The kill switch and DNS block live in protection.py,
panic reset and start-up takeover in failsafe.py; both are mixed into Tunnel."""
import ipaddress
import json
import os
import re
import shutil
import socket
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from . import confparse, dpapi, netinfo, reach, recovery
RECONNECT_TRIES = 8

from .const import (CONFIG_DIR, FAIL_THRESHOLD, GEO_PATH, HEALTH_SEC, LEGACY_CONFIG_DIR, MAX_REPAIR, PING_TARGET,
                    PING_TARGET_V6, RUNTIME_DIR, DATA_DIR, SERVICE_WAIT)
from .ctx import ctx
from .failsafe import FailsafeMixin
from .protection import ProtectionMixin
from .logbus import broadcast, log, recent_log, has_subscribers
from .notify import notify
from .syscmd import (is_admin, is_busy as syscmd_busy, lock_dir, ping_stats, probe_endpoint, quality_of, run,
                     service_running, spawn, wg_tool)


def _lock_dir(path, allow_user):
    """Restrict a folder to SYSTEM + Administrators (+ the current user for the configs folder)."""
    return lock_dir(path, allow_user)


_dirs = {"done": False, "config_dir": CONFIG_DIR}


def config_dir():
    return _dirs["config_dir"]


def ensure_dirs():
    """Create ProgramData folders once and lock them down; migrate configs from the legacy script folder."""
    if _dirs["done"]:
        os.makedirs(_dirs["config_dir"], exist_ok=True)
        return _dirs["config_dir"]
    _dirs["done"] = True
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        if not (_lock_dir(DATA_DIR, False) and _lock_dir(CONFIG_DIR, True)) and is_admin():
            log(f"{DATA_DIR} may be readable by other users — check its permissions", "bad")
    except OSError as e:
        _dirs["config_dir"] = LEGACY_CONFIG_DIR  # can't use ProgramData (not admin?) — fall back
        os.makedirs(LEGACY_CONFIG_DIR, exist_ok=True)
        log(f"couldn't create the private config folder ({e}) — using {LEGACY_CONFIG_DIR}", "warn")
        return LEGACY_CONFIG_DIR
    copied = []
    try:
        if os.path.isdir(LEGACY_CONFIG_DIR) and os.path.abspath(LEGACY_CONFIG_DIR) != os.path.abspath(CONFIG_DIR):
            for fn in os.listdir(LEGACY_CONFIG_DIR):
                src, dst = os.path.join(LEGACY_CONFIG_DIR, fn), os.path.join(CONFIG_DIR, fn)
                if fn.lower().endswith(".conf") and os.path.isfile(src) and not os.path.exists(dst):
                    shutil.copy2(src, dst)
                    copied.append(fn)
    except OSError as e:
        log(f"couldn't copy configs from {LEGACY_CONFIG_DIR}: {e}", "warn")
    if copied:
        log(f"copied {len(copied)} config(s) to {CONFIG_DIR} — delete the originals in {LEGACY_CONFIG_DIR}, "
            "they may be syncing to the cloud", "warn")
    return CONFIG_DIR


ACTION_LABELS = {
    "retry": "Retry", "check_endpoint": "Check endpoint", "install_wg": "Install WireGuard",
    "elevate": "Relaunch as administrator", "edit_config": "Edit config", "panic": "Restore internet",
    "open_portal": "Open sign-in page", "show_log": "Show log", "dismiss": "Dismiss",
}


class Tunnel(ProtectionMixin, FailsafeMixin):
    def __init__(self):
        self.lock = threading.RLock()
        self.active = None
        self.connected = False
        self.connecting = None
        self.note = ""
        self.since = None
        self.ks_active = False
        self.dns_active = False
        self.pings = {}
        self.exit = None
        self.health = None
        self.want = False
        self.last_error = None
        self.gen = 0                      # bumps on every connect/teardown (lets watchers ignore self-inflicted changes)
        self._was_up = False
        self._up = threading.Event()
        self._stop = threading.Event()
        self._guard_kick = threading.Event()
        self._rx = None
        self._tx = None
        self._t_last = None
        self._ep_cache = {}
        self._regions = []
        self._tmp = None                  # runtime copy; must outlive the service start
        self._dns_injected = False
        self._captive_gen = 0
        self._retry_timer = None
        self._sess = {"peak": 0.0}
        self._caps = (0, None)
        self.geo = {}
        self.home = None
        self._tot = (0, 0)
        self._dns_warned = False
        self._captive_pending = False     # a captive-portal waiter owns reconnects until sign-in completes
        self._panic_gen = 0               # bumps on panic: an in-flight connect must abort, not re-arm
        self._fw_state = (0, None)        # (checked_at, Windows Firewall enabled on every profile?)
        self.fw_off = False
        self.giveup = False               # auto-reconnect gave up (netwatch or a manual connect start over)
        self._ep_path = os.path.join(DATA_DIR, "endpoints.json")
        self._ep_load()
        self._geo_load()
        self.rescan()

    # ------------------------------------------------------------------ regions
    def rescan(self):
        regs = []
        d = config_dir()
        found = {}
        if os.path.isdir(d):
            for fn in sorted(os.listdir(d)):
                stem = confparse.stem_of(fn)
                if not stem:
                    continue
                if stem not in found or fn.lower().endswith(confparse.EXT_ENC):  # prefer the encrypted copy
                    found[stem] = fn
        for stem in sorted(found):
            fn = found[stem]
            info = confparse.parse_conf(os.path.join(d, fn))
            regs.append({"name": stem, "file": fn, "host": info["host"], "port": info["port"],
                         "addrs": info["addrs"], "info": info, "enc": confparse.is_encrypted(fn)})
        self._regions = regs

    def region(self, name):
        return next((r for r in self._regions if r["name"] == name), None)

    def has_region(self, name):
        return self.region(name) is not None

    def region_names(self):
        return [r["name"] for r in self._regions]

    def tunnel_ips(self):
        reg = self.region(self.active) if self.active else None
        out = []
        for a in (reg["addrs"] if reg else []):
            try:
                out.append(str(ipaddress.ip_interface(a).ip))
            except ValueError:
                pass
        return out

    def state(self):
        regs = [{"name": r["name"], "host": r["host"], "port": r["port"], "ping": self.pings.get(r["name"]),
                 "geo": self.geo.get(r["host"]), "full": r["info"].get("full", False),
                 "v6": r["info"].get("v6", False), "dns": r["info"].get("dns", False), "enc": r["enc"]}
                for r in self._regions]
        d = {"connected": self.connected, "connecting": self.connecting, "note": self.note, "active": self.active,
             "since": self.since, "ks_active": self.ks_active, "dns_active": self.dns_active,
             "fw_off": self.fw_off, "giveup": self.giveup,
             "settings": ctx.settings.snapshot(), "regions": regs, "admin": is_admin(),
             "wireguard": bool(wg_tool("wireguard.exe")), "wg_installing": syscmd_busy("install_wg"), "wg_cli": bool(wg_tool("wg.exe")), "exit": self.exit,
             "health": self.health, "home": self.home,
             "sessions": ctx.usage.recent(8) if ctx.usage else [], "error": self.last_error,
             "log": recent_log()}
        for hook in ctx.state_hooks:
            try:
                d.update(hook())
            except Exception:
                pass
        return d

    def push(self):
        broadcast("state", self.state())
        tray = ctx.tray
        if tray is not None:
            try:
                tray.refresh()
            except Exception:
                pass

    # ------------------------------------------------------------------ errors with actions
    def _err(self, code, title, detail="", actions=("retry", "show_log"), name=None, extra=None):
        payload = {"code": code, "title": title, "detail": detail, "name": name, "ts": int(time.time()),
                   "actions": [{"id": a, "label": ACTION_LABELS.get(a, a)} for a in actions]}
        if extra:
            payload.update(extra)
        self.last_error = payload
        log(f"{title}" + (f" — {detail}" if detail else ""), "bad")
        broadcast("error_action", payload)
        return payload

    def clear_error(self):
        self.last_error = None

    # ------------------------------------------------------------------ DNS / endpoints
    def _caps_now(self):
        t, c = self._caps
        if time.time() - t > 30 or c is None:
            c = netinfo.net_caps()
            self._caps = (time.time(), c)
        return c

    def _ep_load(self):
        try:
            with open(self._ep_path, encoding="utf-8") as f:
                raw = json.load(f)
            self._ep_cache = {h: (float(v[0]), [str(x) for x in v[1]]) for h, v in raw.items()
                              if isinstance(v, list) and len(v) == 2 and isinstance(v[1], list)}
        except (OSError, ValueError, TypeError, AttributeError):
            self._ep_cache = {}

    def _ep_save(self):
        try:
            tmp = self._ep_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({h: [t, ips] for h, (t, ips) in self._ep_cache.items()}, f)
            os.replace(tmp, self._ep_path)
        except OSError:
            pass

    def _resolve(self, host):
        """Endpoint addresses, usable family first. While the DNS block / kill switch is armed a fresh lookup can
        fail (that is the point of the block), so the last known addresses are kept on disk and reused."""
        if not host:
            return []
        try:
            ipaddress.ip_address(host)
            return [host]
        except ValueError:
            pass
        c = self._ep_cache.get(host)
        if c and time.time() - c[0] < 300:
            return c[1]
        try:
            ips = sorted({ai[4][0].split("%")[0] for ai in socket.getaddrinfo(host, None)})
        except OSError:
            ips = []
        if not ips:
            if c:
                log(f"couldn't resolve {host} right now — using its last known address", "warn")
                return c[1]
            return []
        caps = self._caps_now()  # IPv6-only (or IPv4-only) uplink: try the usable family first
        ips.sort(key=lambda ip: (0 if ((":" in ip) == (not caps["v4"] and caps["v6"])) else 1))
        if not c or c[1] != ips:
            self._ep_cache[host] = (time.time(), ips)
            self._ep_save()
        else:
            self._ep_cache[host] = (time.time(), ips)
        return ips

    def _pick_endpoint_ip(self, region):
        """The address WireGuard should dial (only for hostname endpoints), honouring the uplink's IP family."""
        host = region.get("host")
        if not host:
            return None
        try:
            ipaddress.ip_address(host)
            return None
        except ValueError:
            pass
        ips = self._resolve(host)
        if not ips:
            return None
        caps = self._caps_now()
        usable = [ip for ip in ips if (caps["v6"] if ":" in ip else caps["v4"])]
        return (usable or ips)[0]

    def _all_endpoint_ips(self):
        s = set()
        for r in self._regions:
            s.update(self._resolve(r["host"]))
        return s

    def health_target(self, region=None):
        """Something that answers pings *through the tunnel*. Full tunnels ping 1.1.1.1 (or its IPv6 twin); split
        tunnels ping the config's DNS server or the first host of the first routed network instead, because a
        public target would go outside the tunnel and be dropped by the kill switch (false 'link down')."""
        region = region or (self.region(self.active) if self.active else None)
        if not region:
            return PING_TARGET
        has4 = any(":" not in a.split("/")[0] for a in region["addrs"]) if region["addrs"] else True
        public = PING_TARGET if has4 else PING_TARGET_V6
        nets = []
        for a in region["info"].get("allowed") or []:
            try:
                nets.append(ipaddress.ip_network(a, strict=False))
            except ValueError:
                pass
        if not nets:
            return public
        pub = ipaddress.ip_address(public)
        if any(pub.version == n.version and pub in n for n in nets):
            return public
        for d in region["info"].get("dns_servers") or []:
            try:
                ip = ipaddress.ip_address(d)
            except ValueError:
                continue
            if any(ip.version == n.version and ip in n for n in nets):
                return str(ip)
        n = nets[0]
        return str(n.network_address if n.num_addresses <= 2 else n.network_address + 1)

    # ------------------------------------------------------------------ runtime copies
    def _secure_runtime_dir(self):
        os.makedirs(RUNTIME_DIR, exist_ok=True)
        lock_dir(RUNTIME_DIR)

    def _write_runtime(self, region, body, encrypted):
        self._secure_runtime_dir()
        path = os.path.join(RUNTIME_DIR, region["name"] + (confparse.EXT_ENC if encrypted else confparse.EXT_PLAIN))
        confparse.write_conf_text(path, body, encrypted=encrypted)
        return path

    def _rm_tmp(self):
        """Delete the runtime copy (only after the service is gone)."""
        if self._tmp and os.path.exists(self._tmp):
            dpapi.wipe_and_remove(self._tmp)
        self._tmp = None

    def _clean_runtime_dir(self):
        recovery.clean_runtime_dir()

    def _runtime_has_dns(self, region):
        for ext in (confparse.EXT_ENC, confparse.EXT_PLAIN):
            p = os.path.join(RUNTIME_DIR, region["name"] + ext)
            if os.path.exists(p):
                return confparse.parse_conf(p)["dns"]
        return False

    # ------------------------------------------------------------------ install + diagnostics
    def _install_and_wait(self, wg, name, conf):
        r = run([wg, "/installtunnelservice", conf], timeout=30)
        t0 = time.time()
        while time.time() - t0 < SERVICE_WAIT:
            if service_running(name):
                return True, r
            time.sleep(0.4)
        return False, r

    def _diagnose(self, name, r):
        """Work out why the service didn't reach RUNNING and put the evidence in the log."""
        parts = []
        out = (getattr(r, "stderr", "") or getattr(r, "stdout", "") or "").strip()
        if out:
            parts.append(out[:120])
        q = run(["sc", "query", f"WireGuardTunnel${name}"]).stdout or ""
        st = re.search(r"STATE\s*:\s*\d+\s+(\w+)", q)
        ec = re.search(r"WIN32_EXIT_CODE\s*:\s*(\d+)", q)
        if st:
            parts.append(f"service state {st.group(1)}" + (f", exit code {ec.group(1)}" if ec and ec.group(1) != "0" else ""))
        else:
            parts.append("service was not installed")
        wg = wg_tool("wireguard.exe")
        if wg:
            lg = run([wg, "/dumplog"], timeout=10).stdout or ""
            lines = [x.strip() for x in lg.splitlines() if x.strip()]
            for x in lines[-8:]:
                log("wireguard: " + x[:200], "warn")
            if lines:
                parts.append("last log: " + lines[-1][:140])
        return " · ".join(parts) or "service did not start"

    # ------------------------------------------------------------------ geo + home
    def _geo_load(self):
        try:
            with open(GEO_PATH, "r", encoding="utf-8") as f:
                self.geo = json.load(f)
        except Exception:
            self.geo = {}

    @staticmethod
    def _ipinfo(path):
        req = urllib.request.Request(f"https://ipinfo.io/{path}json", headers={"User-Agent": "curl/8.0", "Accept": "application/json"})
        with reach.urlopen(req, timeout=6) as r:
            d = json.loads(r.read(65536).decode("utf-8", "replace"))
        lat, lon = (float(x) for x in d["loc"].split(","))
        return {"lat": lat, "lon": lon, "city": d.get("city"), "country": d.get("country"), "ip": d.get("ip")}

    def geo_refresh(self):
        """Look up where each server is (once; cached on disk). Only the public endpoint IP is sent — and only if
        the 'IP lookup' privacy setting is on."""
        if not ctx.settings.get("ip_lookup"):
            return
        changed = False
        for r in list(self._regions):
            h = r["host"]
            if not h or h in self.geo:
                continue
            ips = self._resolve(h)
            if not ips:
                continue
            try:
                self.geo[h] = self._ipinfo(ips[0] + "/")
                changed = True
            except Exception:
                continue
        if changed:
            try:
                with open(GEO_PATH, "w", encoding="utf-8") as f:
                    json.dump(self.geo, f)
            except OSError:
                pass
            self.push()

    def fetch_home(self):
        """Your own location (kept in memory only), used as the start of the map arc."""
        if self.connected or not ctx.settings.get("ip_lookup"):
            return
        try:
            self.home = self._ipinfo("")
        except Exception:
            return
        self.push()

    # ------------------------------------------------------------------ connect / disconnect
    def _handshake(self, name):
        cli = wg_tool("wg.exe")
        if not cli:
            return -1
        out = run([cli, "show", name, "latest-handshakes"], 6).stdout or ""
        best = 0
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[-1].isdigit():
                best = max(best, int(parts[-1]))
        return best

    def _verify(self, name, target):
        has_cli = wg_tool("wg.exe") is not None
        t0 = time.time()
        while time.time() - t0 < 14:
            p = ping_stats(target, 1, 1000)  # also triggers the handshake
            if has_cli:
                if self._handshake(name) > 0:
                    return True
            elif p["loss"] < 100:
                return True
            time.sleep(0.4)
        return False

    def _teardown_service(self):
        self._log_session()
        name = self.active
        wg = wg_tool("wireguard.exe")
        if name and wg:
            run([wg, "/uninstalltunnelservice", name], timeout=25)
        self._rm_tmp()
        self.connected = False
        self.active = None
        self.since = None
        self._rx = None
        self.gen += 1

    def connect(self, name):
        if not self.lock.acquire(blocking=False):
            log("another connection change is already in progress", "warn")
            return False
        try:
            return self._connect_locked(name)
        finally:
            self.lock.release()

    def _fail(self, name, code, title, detail="", actions=("retry", "show_log"), captive_check=False):
        wg = wg_tool("wireguard.exe")
        if wg:
            run([wg, "/uninstalltunnelservice", name], timeout=25)
        self._rm_tmp()
        s = ctx.settings
        strict = bool(s.get("kill_switch") and s.get("ks_strict"))
        # The tunnel was up and we are trying to get it back: keep blocking (that is what a kill switch is for).
        # A first, manual connect that fails releases the rules unless strict mode is on. Giving up on auto-reconnect
        # does not end the hold either: only Disconnect or Restore internet does (#14).
        hold = bool(s.get("kill_switch") and self.want and self._was_up)
        self.connecting = None
        self.connected = False
        self.active = None
        self.gen += 1
        if captive_check and strict:
            detail = (detail + " · " if detail else "") + ("on hotel/café Wi-Fi the strict kill switch also blocks "
                                                          "the sign-in page — use Restore internet to sign in")
            actions = tuple(actions) + ("panic",)
        elif captive_check:
            self._fw_remove()                       # the portal page is unreachable while we block it
            cs = netinfo.captive_check()
            if cs["status"] == "captive":
                self._err("captive", "Wi-Fi sign-in required",
                          "This network is intercepting traffic. Kill switch is paused so you can sign in; "
                          "NOBAD reconnects automatically afterwards.", ("open_portal", "retry"), name,
                          {"portal": cs["portal"]})
                notify("Wi-Fi sign-in required", "Kill switch paused until you sign in.", "captive", "warn")
                self._start_captive_wait(name)
                self.push()
                return False
        if strict or hold:
            region = self.region(name)
            if region:
                self._fw_apply(region)
                detail = (detail + " · " if detail else "") + "kill switch is still blocking traffic"
                if "panic" not in actions:
                    actions = tuple(actions) + ("panic",)
        else:
            self._fw_remove()
        self._err(code, title, detail, actions, name)
        if ctx.smart:
            ctx.smart.record_result(name, False)
        notify("Couldn't connect", f"{name}: {title}", "fail", "bad")
        self.push()
        return False

    def _start_captive_wait(self, name):
        self._captive_gen += 1
        gen = self._captive_gen

        def waiter():
            try:
                deadline = time.time() + 600
                while time.time() < deadline and gen == self._captive_gen and not self._stop.is_set():
                    time.sleep(4)
                    if netinfo.captive_check()["status"] == "open":
                        if gen != self._captive_gen or not self.want:
                            return
                        log("network sign-in detected — reconnecting", "ok")
                        self._captive_pending = False
                        self.connect(name)
                        return
                if gen == self._captive_gen:
                    log("gave up waiting for the Wi-Fi sign-in", "warn")
            finally:
                if gen == self._captive_gen:
                    self._captive_pending = False

        self._captive_pending = True
        spawn(waiter)

    def _connect_locked(self, name):
        s = ctx.settings
        wg = wg_tool("wireguard.exe")
        if not wg:
            self._err("wg_missing", "WireGuard for Windows isn't installed",
                      "NOBAD drives the official WireGuard service. Install it, then try again.",
                      ("install_wg", "dismiss"))
            return False
        if os.name == "nt" and not is_admin():
            self._err("not_admin", "NOBAD needs administrator rights",
                      "Creating tunnels and firewall rules requires elevation.", ("elevate", "dismiss"))
            return False
        region = self.region(name)
        if not region:
            log(f"no config named {name}", "bad")
            return False
        try:
            text = confparse.read_conf_text(os.path.join(config_dir(), region["file"]))
        except (OSError, dpapi.DpapiError) as e:
            self._err("bad_config", f"Can't read the config for {name}", str(e), ("edit_config", "dismiss"), name)
            return False
        check = confparse.validate_conf(text)
        for msg in check["errors"][:3]:
            log(f"config check ({name}): {msg}", "warn")

        self.want = True
        self._captive_gen += 1          # cancels any pending captive-portal waiter
        self._captive_pending = False
        self._up.set()
        self.connecting = name
        self.note = ""
        self.last_error = None
        self.gen += 1
        self.push()
        if ctx.netwatch:
            ctx.netwatch.poke()
        self._teardown_service()
        run([wg, "/uninstalltunnelservice", name], timeout=25)  # stale service of this name (crash, WireGuard app)
        log(f"connecting to {name}…")

        info = region["info"]
        tune = bool(s.get("stream_tuned"))
        dns_fb = None
        if s.get("dns_leak_block") and s.get("force_tunnel_dns") and not info["dns"]:
            dns_fb = s.get("fallback_dns")
        self._dns_injected = bool(dns_fb)
        self._dns_warned = False
        panic_gen = self._panic_gen
        ep_ip = self._pick_endpoint_ip(region)  # resolve BEFORE arming (or reuse the last known address)
        if region.get("host") and not ep_ip:
            try:
                ipaddress.ip_address(region["host"])
            except ValueError:
                return self._fail(name, "dns_endpoint", f"Can't find the server address for {name}",
                                  f"{region['host']} could not be resolved. Check your internet connection.",
                                  ("retry", "check_endpoint", "show_log"))
        self._fw_apply(region)

        # WireGuard (running as SYSTEM) only ever gets a copy NOBAD wrote into the admin-only runtime folder, made
        # from the text read and validated above. Never the stored file: the configs folder can be user-writable,
        # so it could be swapped between the check and the service install (#16).
        cands = []
        body = None
        if tune or dns_fb or region["enc"] or ep_ip:
            body = confparse.tuned_conf_text(text, info, stream=tune, dns_fallback=dns_fb, endpoint_ip=ep_ip)
            if region["enc"] and s.get("dpapi_runtime_ok") and dpapi.available():
                cands.append(("enc", body))
            cands.append(("plain", body))
        if not region["enc"] and body != text:
            cands.append(("orig", text))           # untuned fallback, still a locked runtime copy

        up, r, enc_failed = False, None, False
        for i, (kind, payload) in enumerate(cands):
            try:
                path = self._write_runtime(region, payload, kind == "enc")
            except (OSError, dpapi.DpapiError) as e:
                log(f"couldn't prepare a {kind} runtime copy: {e}", "warn")
                if kind == "enc":
                    enc_failed = True
                continue
            self._tmp = path
            up, r = self._install_and_wait(wg, name, path)
            if panic_gen != self._panic_gen:
                return self._abort_for_panic(wg, name)
            if up:
                if enc_failed:
                    s.set("dpapi_runtime_ok", False)
                    log("WireGuard did not accept an encrypted runtime copy; NOBAD will use a short-lived plaintext copy "
                        "in the locked runtime folder from now on", "warn")
                break
            run([wg, "/uninstalltunnelservice", name], timeout=25)
            self._rm_tmp()
            if kind == "enc":
                enc_failed = True
                log("encrypted runtime copy failed to start — retrying with a temporary plaintext copy", "warn")
            elif i + 1 < len(cands):
                log("tuned config failed to start — retrying with the untuned config", "warn")
        if not up:
            detail = self._diagnose(name, r)
            if check["errors"]:
                detail = check["errors"][0] + " · " + detail
            return self._fail(name, "start_failed", f"Couldn't start {name}", detail,
                              ("retry", "edit_config", "show_log"))

        self.active = name  # so _fail/teardown know what to remove
        verified = self._verify(name, self.health_target(region))
        if panic_gen != self._panic_gen:
            return self._abort_for_panic(wg, name)
        if not verified:
            self.active = name
            return self._fail(name, "handshake", f"{name} never completed a handshake",
                              "Check the keys and the endpoint address/port.", ("retry", "check_endpoint", "edit_config"),
                              captive_check=True)

        self.connected = True
        self.connecting = None
        self.giveup = False
        self.since = time.time()
        self._tot = (0, 0)
        self._sess = {"peak": 0.0}
        self.exit = None
        self.health = None
        self._was_up = True
        self._rx = None
        self.gen += 1
        s.set("last_region", name)
        if ctx.smart:
            ctx.smart.record_result(name, True)
        log(f"connected — {name}" + (" · kill switch on" if self.ks_active else "")
            + (" · DNS locked to tunnel" if self.dns_active else ""), "ok")
        notify("Connected", name + (" · kill switch on" if self.ks_active else ""), "connect", "ok")
        self.push()
        if s.get("ip_lookup"):
            from .tools import fetch_ipinfo
            spawn(fetch_ipinfo)
        else:
            self.exit = {"disabled": True}
            broadcast("ipinfo", self.exit)
        self._guard_kick.set()
        return True

    def disconnect(self, manual=True):
        with self.lock:
            self.want = False
            self._was_up = False
            self.giveup = False
            self._captive_gen += 1
            self._captive_pending = False
            self._teardown_service()
            self._fw_remove()
            self.connecting = None
            self.health = None
            self.exit = None
            self.note = ""
            self._up.clear()
            log("disconnected", "warn")
            if manual and ctx.netwatch:
                ctx.netwatch.note_manual_disconnect()
            self.push()
            if not self.home:
                spawn(self.fetch_home)

    # ------------------------------------------------------------------ clean reconnect (sleep / network change)
    def _wait_online(self, timeout=45):
        t0 = time.time()
        while time.time() - t0 < timeout and not self._stop.is_set():
            if netinfo.physical_fingerprint(self.tunnel_ips()):
                time.sleep(2.0)  # let DHCP / Wi-Fi settle
                return True
            time.sleep(1.5)
        return False

    def on_network_event(self, kind, new_fp, reason):
        """Called by NetWatch (from its own thread). kind: 'change' | 'resume'."""
        if not ctx.settings.get("reconnect_on_network_change"):
            return
        if not (self.want and (self.connected or self._was_up or self.connecting)):
            return
        if kind == "change" and not new_fp:
            self.note = "Network lost — waiting for it to return"
            log("network lost — tunnel stays blocked/idle until a network returns", "warn")
            notify("Network lost", "NOBAD will reconnect when a network is available.", "netlost", "warn")
            self.push()
            return
        self.reconnect_clean(reason)

    def reconnect_clean(self, reason):
        if not self.lock.acquire(blocking=False):
            if self._retry_timer is None:
                def again():
                    self._retry_timer = None
                    self.reconnect_clean(reason)
                self._retry_timer = threading.Timer(6.0, again)
                self._retry_timer.daemon = True
                self._retry_timer.start()
            return False
        try:
            target = self.active or ctx.settings.get("last_region")
            if not target or not self.want or not self.has_region(target):
                return False
            log(f"{reason} — reconnecting {target} cleanly", "warn")
            self.connecting = target
            self.note = reason
            self.push()
            self._teardown_service()      # firewall rules stay armed: no leak window
            self.connected = False
            if not self._wait_online(45):
                self.connecting = None
                self.note = "Waiting for a network"
                log("no network yet — will reconnect when one appears", "warn")
                self.push()
                return False
            ok = self._connect_locked(target)
            if ok:
                notify("Reconnected", f"{target} ({reason})", "reconnect", "ok")
            return ok
        finally:
            self.lock.release()

    # ------------------------------------------------------------------ probing / fastest / smart / failover
    def probe_all(self):
        regs = list(self._regions)
        via_tunnel = self.connected

        def one(r):
            res = probe_endpoint(self._resolve(r["host"]))
            if via_tunnel and r["name"] != self.active:
                res["est"] = True
            self.pings[r["name"]] = res
            if ctx.smart and not res.get("est"):
                ctx.smart.record_latency(r["name"], res.get("rtt"))
            broadcast("probe", {"name": r["name"], "ping": res})
            return r["name"], res

        if not regs:
            return {}
        with ThreadPoolExecutor(max_workers=min(8, len(regs))) as ex:
            results = dict(ex.map(one, regs))
        self.push()
        return results

    def _best(self, results, exclude=None):
        c = [(v["rtt"], n) for n, v in results.items() if n != exclude and v and v.get("rtt") is not None]
        return min(c)[1] if c else None

    def _drop_for_measuring(self):
        prev = self.active if self.connected else None
        if prev:
            log("dropping the tunnel briefly so servers can be measured accurately…")
            self._teardown_service()
            self.connected = False
            self.push()
        return prev

    def fastest(self):
        with self.lock:
            prev = self._drop_for_measuring()
            log("measuring all servers…")
            res = self.probe_all()
            best = self._best(res)
            if not best:
                log("no server answered ICMP or TCP — can't rank them", "warn")
                best = prev or ctx.settings.get("last_region") or (self._regions[0]["name"] if self._regions else None)
            else:
                log(f"fastest: {best} ({res[best]['rtt']} ms)", "ok")
            if best:
                self.connect(best)

    def smart_pick(self, res, exclude=(), service=None):
        live = {n: v["rtt"] for n, v in res.items() if v and v.get("rtt") is not None and not v.get("est")}
        names = [n for n in self.region_names() if n not in exclude]
        ranked = ctx.smart.rank(names, service=service or None, live=live) if ctx.smart else []
        return ranked

    def smart_connect(self, service=None):
        """Pick by live latency blended with what's been learned for this time of day, skipping servers known to be
        blocked for the chosen streaming service."""
        with self.lock:
            service = service or ctx.settings.get("guard_service") or None
            prev = self._drop_for_measuring()
            res = self.probe_all()
            ranked = self.smart_pick(res, service=service)
            if not ranked:
                log("smart pick: nothing usable — falling back to the fastest answer", "warn")
                best = self._best(res) or prev or ctx.settings.get("last_region")
            else:
                best = ranked[0][0]
                log(f"smart pick: {best}" + (f" (clear for {service})" if service else "")
                    + f" · score {ranked[0][1]:.0f}", "ok")
            if best:
                self.connect(best)

    def _failover(self, cur):
        with self.lock:
            self._teardown_service()
            self.connected = False
            self.push()
            res = self.probe_all()
            service = ctx.settings.get("guard_service") or None
            ranked = self.smart_pick(res, exclude=(cur,), service=service) if ctx.settings.get("smart_select") else []
            best = ranked[0][0] if ranked else self._best(res, exclude=cur)
            if not best:
                names = self.region_names()
                i = names.index(cur) if cur in names else -1
                best = names[(i + 1) % len(names)] if names else cur
            log(f"failing over to {best}", "warn")
            notify("Failing over", f"{cur} → {best}", "failover", "warn")
            return self.connect(best)

    # ------------------------------------------------------------------ streaming guard
    def guard_check(self, service=None):
        """Check the watched service through the current exit; if blocked, mark it and (optionally) switch."""
        from .tools import check_one_service, service_blocked
        service = service or ctx.settings.get("guard_service")
        if not (service and self.connected and self.active):
            return None
        res = check_one_service(service)
        if not res:
            return None
        cur = self.active
        if res.get("ms") is None:
            base = check_one_service("base")  # can we reach anything at all through this exit?
            if not base or base.get("ms") is None:
                log(f"streaming guard: the tunnel itself isn't reaching the internet — not blaming {service}", "warn")
                return res
        blocked = service_blocked(res)
        ctx.smart.record_service(cur, service, not blocked)
        broadcast("guard", {"service": service, "server": cur, "blocked": blocked, "note": res.get("note")})
        if blocked:
            log(f"{res['name']} looks blocked on {cur} ({res.get('note')})", "warn")
            if ctx.settings.get("guard_auto_switch"):
                self._guard_switch(service, cur)
        return res

    def _guard_switch(self, service, cur):
        from .tools import check_one_service, service_blocked
        with self.lock:
            tried = {cur}
            for _ in range(3):
                if not self.want:
                    return
                res = self.probe_all()
                ranked = self.smart_pick(res, exclude=tried, service=service)
                if not ranked:
                    log(f"no other server is known to work for {service}", "warn")
                    notify("Streaming blocked", f"No other server is clear for {service}.", "guard", "warn")
                    return
                nxt = ranked[0][0]
                tried.add(nxt)
                log(f"switching to {nxt} because {service} is blocked on {cur}", "warn")
                self._teardown_service()
                self.connected = False
                if not self._connect_locked(nxt):
                    continue
                r = check_one_service(service)
                if r and not service_blocked(r):
                    ctx.smart.record_service(nxt, service, True)
                    notify("Switched server", f"{service} works on {nxt}", "guard", "ok")
                    return
                ctx.smart.record_service(nxt, service, False)
                cur = nxt

    def _guard_loop(self):
        while not self._stop.is_set():
            self._up.wait()
            kicked = self._guard_kick.wait(1800)  # first check ~20 s after a connect, then every 30 min
            self._guard_kick.clear()
            if self._stop.is_set():
                return
            if kicked and self._stop.wait(20):
                return
            try:
                s = ctx.settings
                if self.connected and not self.connecting and s.get("guard_service"):
                    self.guard_check()
            except Exception as e:
                log(f"guard error: {e}", "warn")

    # ------------------------------------------------------------------ session log + background loops
    def _log_session(self):
        if not (self.connected and self.active and self.since):
            return
        secs = int(time.time() - self.since)
        tot = self._tot[0] + self._tot[1]
        rec = {"name": self.active, "start": int(self.since), "secs": secs, "rx": self._tot[0], "tx": self._tot[1],
               "avg_bps": int(tot * 8 / secs) if secs else 0, "peak_bps": int(self._sess.get("peak", 0))}
        if ctx.usage:
            ctx.usage.log_session(rec)

    def flush_usage(self):
        """Quit while the VPN keeps running: write the session so far, so nothing is lost or double counted."""
        self._log_session()
        if ctx.usage:
            ctx.usage.save(force=True)

    def start(self):
        """Called from the background start-up thread (the window is already up). Adopting runs under the
        connection lock so a click on Connect during start-up simply waits for it."""
        with self.lock:
            self._adopt()
        spawn(self.geo_refresh)
        if not self.connected:
            spawn(self.fetch_home)
        threading.Thread(target=self._health_loop, daemon=True).start()
        threading.Thread(target=self._traffic_loop, daemon=True).start()
        threading.Thread(target=self._guard_loop, daemon=True).start()

    def stop(self):
        self._stop.set()
        self._up.set()
        self._guard_kick.set()

    def _health_loop(self):
        bad = repairs = retries = 0
        next_try = 0.0
        while not self._stop.is_set():
            self._up.wait()
            if self._stop.wait(HEALTH_SEC):
                return
            try:
                if self.connecting or self._captive_pending:
                    continue
                if not self.connected:
                    s = ctx.settings
                    if not (self.want and self._was_up and s.get("auto_repair")) or self.giveup:
                        retries = 0
                        next_try = 0.0
                        continue
                    if time.time() < next_try:
                        continue
                    if retries >= RECONNECT_TRIES:
                        self._give_up()
                        retries = 0
                        continue
                    retries += 1
                    next_try = time.time() + min(120, HEALTH_SEC * (2 ** min(retries - 1, 4)))
                    target = s.get("last_region")
                    if retries == 1:
                        notify("Connection dropped", "NOBAD is reconnecting…", "drop", "warn")
                    if retries > 2 and len(self.region_names()) > 1:
                        log(f"link lost — {target} keeps failing, trying another server (attempt {retries})", "warn")
                        ok = bool(self._failover(target))
                    else:
                        log(f"link lost — reconnect attempt {retries}", "warn")
                        ok = bool(target and self.connect(target))
                    if ok:
                        retries = bad = repairs = 0
                        next_try = 0.0
                    continue
                retries = 0
                h = ping_stats(self.health_target(), 3)
                h["q"] = quality_of(h)
                self.health = h
                broadcast("health", h)
                if h["loss"] >= 50:
                    bad += 1
                    log(f"health check: {h['loss']}% loss ({bad}/{FAIL_THRESHOLD})", "warn")
                else:
                    if bad:
                        log("health check recovered", "ok")
                    bad = repairs = 0
                    continue
                if bad < FAIL_THRESHOLD:
                    continue
                bad = 0
                if not ctx.settings.get("auto_repair"):
                    log("connection degraded (auto-repair is off)", "warn")
                    continue
                cur = self.active
                notify("Connection dropped", f"{cur} stopped responding.", "drop", "warn")
                if repairs < MAX_REPAIR:
                    repairs += 1
                    log(f"auto-repair: reconnecting {cur} (attempt {repairs})", "info")
                    self.connect(cur)
                else:
                    repairs = 0
                    self._failover(cur)
            except Exception as e:
                log(f"monitor error: {e}", "warn")

    def _give_up(self):
        """Auto-reconnect ran out of attempts. With the kill switch on, traffic stays blocked until the user chooses
        Restore internet or Disconnect (#14): releasing it on its own would let anyone who can block the VPN's UDP
        traffic push this PC onto the open network within minutes. A later network change (NetWatch) or a manual
        connect starts over."""
        s = ctx.settings
        self.giveup = True
        if s.get("kill_switch"):
            self._err("reconnect_failed", "Couldn't reconnect",
                      f"Stopped retrying after {RECONNECT_TRIES} attempts. The kill switch keeps blocking traffic; "
                      "choose Restore internet to go online without the VPN.",
                      ("retry", "panic", "show_log"), s.get("last_region"))
            notify("Still offline", "Couldn't reconnect — the kill switch is blocking traffic. "
                   "Open NOBAD to retry or restore internet.", "fail", "bad")
        else:
            with self.lock:
                self._fw_remove()
            self._err("reconnect_failed", "Couldn't reconnect",
                      f"Gave up after {RECONNECT_TRIES} attempts. The kill switch is off, so you are online "
                      "WITHOUT the VPN.", ("retry", "show_log"), s.get("last_region"))
            notify("VPN is off", "Couldn't reconnect — you are online without the VPN.", "fail", "bad")
        self.push()

    def _traffic_loop(self):
        """2 s sampling while a window is open, 30 s otherwise (so usage history stays accurate with the UI closed)."""
        while not self._stop.is_set():
            self._up.wait()
            if self._stop.wait(2 if has_subscribers() else 30):
                return
            if not self.connected or not self.active:
                continue
            cli = wg_tool("wg.exe")
            if not cli:
                continue
            out = run([cli, "show", self.active, "dump"], 6).stdout or ""
            rx = tx = 0
            hs_age = endpoint = None
            now = time.time()
            for line in out.splitlines()[1:]:  # line 0 is the interface, the rest are peers
                p = line.split("\t")
                if len(p) >= 7 and p[5].isdigit() and p[6].isdigit():
                    rx += int(p[5])
                    tx += int(p[6])
                    endpoint = endpoint or (p[2] if p[2] != "(none)" else None)
                    if p[4].isdigit() and int(p[4]) > 0:
                        hs_age = max(0, int(now - int(p[4])))
            if self._rx is not None and self._t_last is not None and now > self._t_last:
                dt = now - self._t_last
                drx, dtx = max(0, rx - self._rx), max(0, tx - self._tx)
                rx_bps, tx_bps = drx * 8 / dt, dtx * 8 / dt
                self._sess["peak"] = max(self._sess.get("peak", 0.0), rx_bps + tx_bps)
                if ctx.usage:
                    ctx.usage.add_delta(self.active, drx, dtx, int(dt))
                if has_subscribers():
                    broadcast("traffic", {"rx_bps": rx_bps, "tx_bps": tx_bps, "rx_total": rx, "tx_total": tx,
                                          "hs_age": hs_age, "endpoint": endpoint})
            self._rx, self._tx, self._t_last = rx, tx, now
            self._tot = (rx, tx)
