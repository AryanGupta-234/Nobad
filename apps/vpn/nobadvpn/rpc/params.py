"""Every method the pipe serves, and the exact shape of its parameters (an allowlist).

The engine runs elevated and the UI doesn't, so nothing a pipe client sends is trusted:
- a method that isn't in SPEC doesn't exist on the pipe (METHOD_NOT_FOUND), even if api.HANDLERS has it;
- a parameter that isn't listed, has the wrong type, is too long, or doesn't match its pattern is refused
  (INVALID_PARAMS) before any handler runs;
- names are config names (const.NAME_RE), bare file names (never a path), or a choice from a fixed list. No
  parameter is ever a path, a command line or a shell string: the handlers look paths up themselves, and every
  check they already make for the WebView UI (settings.coerce, configstore._safe, ...) still runs after this one.

contract/methods.schema.json is generated from SPEC (`python -m nobadvpn.rpc.params > contract/methods.schema.json`)
and tests/test_rpc_contract.py fails when the two differ.
"""
import json
import re

from .protocol import INVALID_PARAMS, PROTOCOL, RpcError

_CTRL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u2028\u2029]")      # tab, LF and CR are allowed in text


class Param:
    json_type = "string"

    def __init__(self, required=True, doc=""):
        self.required, self.doc = required, doc

    def check(self, key, v):          # -> the value to pass on, or raise RpcError
        raise NotImplementedError

    def schema(self):
        return {"type": self.json_type}

    @staticmethod
    def bad(key, why):
        return RpcError(INVALID_PARAMS, f"'{key}' {why}")


class Str(Param):
    """Text of at most `max_len` characters; `pattern` must match the whole string; `multiline` allows LF/CR/tab,
    otherwise no control characters at all."""

    def __init__(self, max_len, pattern=None, multiline=False, **kw):
        super().__init__(**kw)
        self.max_len, self.multiline = max_len, multiline
        self.pattern = re.compile(pattern) if pattern else None

    def check(self, key, v):
        if not isinstance(v, str):
            raise self.bad(key, "must be a string")
        if len(v) > self.max_len:
            raise self.bad(key, f"is longer than {self.max_len} characters")
        if _CTRL.search(v) or (not self.multiline and re.search(r"[\t\r\n]", v)):
            raise self.bad(key, "contains control characters")
        if self.pattern is not None and not self.pattern.fullmatch(v):
            raise self.bad(key, "has an unexpected form")
        return v

    def schema(self):
        s = {"type": "string", "maxLength": self.max_len}
        if self.pattern is not None:
            s["pattern"] = "^(?:" + self.pattern.pattern + ")$"
        return s


class Bool(Param):
    json_type = "boolean"

    def check(self, key, v):
        if not isinstance(v, bool):
            raise self.bad(key, "must be true or false")
        return v


class Int(Param):
    json_type = "integer"

    def __init__(self, lo, hi, **kw):
        super().__init__(**kw)
        self.lo, self.hi = lo, hi

    def check(self, key, v):
        if not isinstance(v, int) or isinstance(v, bool) or not self.lo <= v <= self.hi:
            raise self.bad(key, f"must be a whole number from {self.lo} to {self.hi}")
        return v

    def schema(self):
        return {"type": "integer", "minimum": self.lo, "maximum": self.hi}


class Choice(Param):
    def __init__(self, values, **kw):
        super().__init__(**kw)
        self.values = tuple(values)

    def check(self, key, v):
        if not isinstance(v, str) or v not in self.values:
            raise self.bad(key, "must be one of " + ", ".join(repr(x) for x in self.values))
        return v

    def schema(self):
        return {"type": "string", "enum": list(self.values)}


class List(Param):
    json_type = "array"

    def __init__(self, item, max_items, **kw):
        super().__init__(**kw)
        self.item, self.max_items = item, max_items

    def check(self, key, v):
        if not isinstance(v, list):
            raise self.bad(key, "must be a list")
        if len(v) > self.max_items:
            raise self.bad(key, f"has more than {self.max_items} items")
        return [self.item.check(f"{key}[{i}]", x) for i, x in enumerate(v)]

    def schema(self):
        return {"type": "array", "maxItems": self.max_items, "items": self.item.schema()}


class SettingValue(Param):
    """A setting's value before settings.coerce sees it: true/false, short text, or a short list of short texts
    (trusted network names). Nothing nested, nothing big."""
    _TEXT, _ITEM, _ITEMS = Str(2000), Str(64), 100

    def check(self, key, v):
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return self._TEXT.check(key, v)
        if isinstance(v, list):
            return List(self._ITEM, self._ITEMS).check(key, v)
        raise self.bad(key, "must be true/false, text, or a list of names")

    def schema(self):
        return {"anyOf": [{"type": "boolean"}, self._TEXT.schema(), List(self._ITEM, self._ITEMS).schema()]}


# ---------------------------------------------------------------- the shapes used more than once
CONFIG = r"[A-Za-z0-9_=+.\-]{1,32}"                     # const.NAME_RE: a config name, never a path
NAME = Str(32, CONFIG, doc="a server (config) name")
# a file name the user picked or dropped, as a label only: configstore.clean_name turns it into a config name
FILE_LABEL = r"[^\\/:*?\"<>|]{1,128}"
BARE_FILE = Str(128, FILE_LABEL, doc="a bare file name from free_scan's list, never a path")
HOST = Str(253, r"[A-Za-z0-9.:\-\[\]]{1,253}", doc="a host name or an IP address")
SITE = Str(253, r"[^\s\x00-\x1f]{1,253}", doc="a site the user typed (normalised and checked by netintel)")
WINDOWS = ("main", "mini")
URL_KEYS = ("wireguard_install", "neverssl", "firewall_settings", "proton_signup", "proton_downloads",
            "warp_app", "portal")
SERVICES = ("", "netflix", "youtube", "disney", "prime", "spotify", "twitch")   # settings.SERVICES_IDS
EVENT_NAME = Str(40, r"[a-z_]{1,40}")
DNS_TYPES = ("A", "AAAA", "CNAME", "MX", "TXT", "NS", "SOA")

# ---------------------------------------------------------------- every method on the pipe
# Group: which api handler it reaches. "pipe" methods are the pipe's own (rpc/methods.py).
SPEC = {
    # the pipe itself
    "hello": {},
    "subscribe": {"events": List(EVENT_NAME, 64)},
    "unsubscribe": {"events": List(EVENT_NAME, 64)},
    "state": {},
    "ui_shown": {"window": Choice(WINDOWS)},
    "ui_hidden": {"window": Choice(WINDOWS)},
    "ui_show": {"window": Choice(WINDOWS)},
    # connection
    "connect": {"name": NAME},
    "disconnect": {},
    "fastest": {},
    "smart": {"service": Choice(SERVICES, required=False)},
    "probe": {},
    "favorite": {"name": NAME},
    "endpoint_check": {"name": NAME},
    "dismiss_error": {},
    "panic_reset": {},
    "net_repair": {"level": Choice(("undo", "quick", "full"))},
    "net_changes": {},
    # settings
    "settings": {"key": Str(40, r"[a-z0-9_]{1,40}"), "value": SettingValue()},
    "theme": {"value": Choice(("dark", "light"))},
    "wizard_done": {},
    "trusted_add": {"name": Str(64, required=False)},
    "current_network": {},
    # servers and configs (config text is the only free text; it's validated by confparse, never executed)
    "rescan": {},
    "open_configs": {},
    "import": {"name": Str(128, FILE_LABEL), "content": Str(400_000, multiline=True)},
    "import_url": {"url": Str(2048, r"https://[^\s]{1,2040}"), "name": Str(64, required=False)},
    "free_scan": {},
    "free_import": {"files": List(BARE_FILE, 40)},
    "config_get": {"name": NAME},
    "config_validate": {"name": Str(32, r"(?:" + CONFIG + r")?"), "text": Str(400_000, multiline=True)},
    "config_save": {"name": NAME, "text": Str(400_000, multiline=True)},
    "config_delete": {"name": NAME},
    # checks and tools
    "network_diagnose": {},
    "startup_checks": {},
    "valorant_probe": {},
    "gaming_probe": {"host": HOST},
    "flush_dns": {},
    "speedtest": {},
    "streamcheck": {},
    "ipinfo": {},
    "guard_check": {},
    "usage": {"days": Int(0, 400, required=False)},
    "reach_test": {},
    "reach_forget": {},
    "et_run": {},
    # setup, links, updates, reports
    "install_wireguard": {},
    "elevate": {},
    "open_url": {"key": Choice(URL_KEYS)},
    "diagnostics_export": {},
    "report_problem": {"crash": Bool(required=False)},
    "update_check": {},
    "update_install": {},
    "crash_pending": {},
    "crash_send": {"file": Str(80, r"crash-[A-Za-z0-9_.\-]{1,70}\.json")},
    "crash_dismiss": {"file": Str(80, r"crash-[A-Za-z0-9_.\-]{1,70}\.json")},
    "quit": {"disconnect": Bool(required=False)},
    # Network Intelligence
    "ni_overview": {},
    "ni_investigate": {"target": SITE},
    "ni_lookup": {"name": SITE, "types": List(Choice(DNS_TYPES), 7, required=False)},
    "ni_vpn": {},
    "ni_history": {},
    "ni_history_clear": {},
    "ni_fix": {"id": Str(12, r"[0-9]{1,12}")},
    "ni_rollback": {"entry": Str(32, r"[0-9a-f]{1,32}")},
    # Streaming Region Intelligence
    "si_status": {},
    "si_key": {"key": Str(512, r"[A-Za-z0-9._\-]{1,512}")},
    "si_key_clear": {},
    "si_search": {"q": Str(200)},
    "si_title": {"key": Str(40, r"(?:movie|tv):[0-9]{1,9}|wd:Q[0-9]{1,12}"), "force": Bool(required=False)},
    "si_providers": {"region": Str(2, r"(?:[A-Za-z]{2})?", required=False)},
    "si_prefs": {"my_services": List(Int(1, 10**7 - 1), 200)},
    "si_verify": {"country": Str(2, r"[A-Za-z]{2}"), "services": List(Str(20, r"[a-z]{2,20}"), 4, required=False)},
    "si_open": {"url": Str(2000, r"https?://[^\s]{1,1990}"), "confirm": Bool(required=False)},
    "si_cache_clear": {},
}

# Methods that lower protection or change Windows networking: logged with the calling program (methods.py).
SENSITIVE = {"disconnect", "panic_reset", "net_repair", "quit", "config_delete", "ni_fix", "ni_rollback",
             "flush_dns", "install_wireguard", "update_install", "elevate"}
# settings keys whose "off" lowers protection (logged like SENSITIVE)
PROTECTION_KEYS = {"kill_switch", "dns_leak_block", "ks_strict", "watchdog", "force_tunnel_dns", "auto_repair",
                   "reconnect_on_network_change", "et_enabled"}


def validate(method, params):
    """The checked parameters of `method` (only the ones given), or RpcError. Unknown names are refused."""
    spec = SPEC.get(method)
    if spec is None:
        raise RpcError(-32601, "Method not found")
    extra = sorted(set(params) - set(spec))
    if extra:
        raise RpcError(INVALID_PARAMS, f"unknown parameter '{str(extra[0])[:40]}'")
    out = {}
    for key, p in spec.items():
        if key in params:
            out[key] = p.check(key, params[key])
        elif p.required:
            raise RpcError(INVALID_PARAMS, f"'{key}' is required")
    return out


def json_schema():
    """contract/methods.schema.json: every method and its parameters (JSON Schema 2020-12)."""
    methods = {}
    for name, spec in SPEC.items():
        props = {k: dict(p.schema(), **({"description": p.doc} if p.doc else {})) for k, p in spec.items()}
        methods[name] = {"type": "object", "additionalProperties": False, "properties": props,
                         "required": [k for k, p in spec.items() if p.required]}
    return {"$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "NOBAD VPN engine pipe: method parameters", "protocol": PROTOCOL,
            "description": "Generated from nobadvpn/rpc/params.py SPEC; do not edit by hand.",
            "methods": methods}


if __name__ == "__main__":
    print(json.dumps(json_schema(), indent=2, ensure_ascii=True))
