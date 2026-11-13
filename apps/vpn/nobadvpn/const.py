"""Constants, paths and setting defaults. Import-time side effects: none (no files are touched)."""
import os
import re
import sys

APP_TITLE = "NOBAD VPN"
# Windows AppUserModelID: taskbar grouping, jump list and the sender name on notifications. The installer registers it
# on the Start-menu shortcut, which is what lets Windows show "NOBAD VPN" (not PowerShell/Python) on toasts.
APP_ID = "NOBAD.VPN"
APP_VER = "1.3.1"  # semantic version; bump on every release (build.ps1 reads it)
WINDOW_TITLE = f"{APP_TITLE}  ·  v{APP_VER}"

FROZEN = bool(getattr(sys, "frozen", False))
PKG_DIR = os.path.dirname(os.path.abspath(__file__))
if FROZEN:
    UI_DIR = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(PKG_DIR)), "nobadvpn", "ui")
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    UI_DIR = os.path.join(PKG_DIR, "ui")
    BASE_DIR = os.path.dirname(os.path.abspath(sys.argv[0])) if sys.argv and sys.argv[0] else os.getcwd()

_FOLDERID = {"ProgramData": "{62AB5D82-FDC1-4DC3-A9DD-070D1D495D97}",
             "ProgramFiles": "{905E63B6-C1BF-494E-B29C-65B732D3D21A}",
             "ProgramFilesX86": "{7C5A40EF-A0FB-4BFC-874A-C0F2E0B9FA8E}",
             "Windows": "{F38BF404-1D43-42F2-9305-67DE0B28FC23}",
             "Desktop": "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}",
             "Downloads": "{374DE290-123F-4565-9164-39C4925E467B}"}


def known_folder(name):
    """A Windows known folder from the shell, never from environment variables: NOBAD runs elevated, and a normal
    user can set HKCU\\Environment (ProgramData=..., NOBAD_DATA_DIR=...) for the processes it starts. None off
    Windows or on failure."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        import uuid
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("d1", wintypes.DWORD), ("d2", wintypes.WORD), ("d3", wintypes.WORD), ("d4", ctypes.c_ubyte * 8)]
        u = uuid.UUID(_FOLDERID[name])
        g = GUID(u.time_low, u.time_mid, u.time_hi_version, (ctypes.c_ubyte * 8)(*u.bytes[8:]))
        out = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(out)) != 0:
            return None
        try:
            return out.value
        finally:
            ctypes.windll.ole32.CoTaskMemFree(out)
    except Exception:
        return None


# NOBAD_DATA_DIR redirects everything for tests and source runs. The INSTALLED app ignores it (see known_folder).
_ENV_DATA_DIR = None if FROZEN else os.environ.get("NOBAD_DATA_DIR")
PROGRAMDATA = known_folder("ProgramData") or (r"C:\ProgramData" if FROZEN else os.environ.get("ProgramData", r"C:\ProgramData"))
DATA_DIR = _ENV_DATA_DIR or os.path.join(PROGRAMDATA, "NobadVPN")
# Previous product name (NOMAD Tunnel): its data folder is copied over once and its rules/task are cleaned up.
LEGACY_DATA_DIR = None if _ENV_DATA_DIR else os.path.join(PROGRAMDATA, "NomadTunnel")
CONFIG_DIR = os.path.join(DATA_DIR, "configs")         # holds private keys: local only, never synced
LEGACY_CONFIG_DIR = os.path.join(BASE_DIR, "configs")  # very old location (may be inside OneDrive)
RUNTIME_DIR = os.path.join(DATA_DIR, "runtime")        # temp tuned copies (admin/SYSTEM only)
LOG_DIR = os.path.join(DATA_DIR, "logs")
EXPORT_DIR = os.path.join(DATA_DIR, "exports")
CRASH_DIR = os.path.join(DATA_DIR, "crash")
UPDATE_DIR = os.path.join(DATA_DIR, "updates")
GEO_PATH = os.path.join(DATA_DIR, "geo_cache.json")
SESS_PATH = os.path.join(DATA_DIR, "sessions.json")     # legacy (migrated into usage.json)
USAGE_PATH = os.path.join(DATA_DIR, "usage.json")
SMART_PATH = os.path.join(DATA_DIR, "smart.json")
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")
LEGACY_SETTINGS_PATH = os.path.join(BASE_DIR, "tunnel_settings.json")
INSTANCE_PATH = os.path.join(DATA_DIR, "instance.json")
CLEAN_EXIT_PATH = os.path.join(DATA_DIR, "clean_exit.flag")

WG_DIRS = [r"C:\Program Files\WireGuard", r"C:\Program Files (x86)\WireGuard"]
# Who may sign updates. Default (both empty): the SAME publisher name as the signed NobadVPN.exe that is running.
# Prefer pinning the full certificate SUBJECT (stable across renewals; Microsoft Artifact Signing certificates are
# re-issued every few days, so their thumbprints change constantly). Thumbprints pin one exact certificate.
UPDATE_SIGNER_SUBJECTS = ()      # e.g. ("CN=NOBAD Technologies Pvt Ltd, O=NOBAD Technologies Pvt Ltd, L=..., C=IN",)
UPDATE_SIGNER_THUMBPRINTS = ()   # SHA-1, upper-case hex
TASK_NAME = "NobadVPN"
LEGACY_TASK_NAME = "NomadTunnel"
PING_TARGET = "1.1.1.1"
PING_TARGET_V6 = "2606:4700:4700::1111"
HEALTH_SEC = 8
FAIL_THRESHOLD = 2
MAX_REPAIR = 2
STREAM_MTU = 1380
SERVICE_WAIT = 15  # seconds to wait for the tunnel service to reach RUNNING
NAME_RE = re.compile(r"^[A-Za-z0-9_=+.\-]{1,32}$")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

SETTINGS_VERSION = 2
DEFAULTS = {
    "settings_version": SETTINGS_VERSION,
    # protection
    "kill_switch": False,
    "ks_strict": False,            # keep blocking even if a connect attempt fails
    "dns_leak_block": True,
    "force_tunnel_dns": True,      # inject fallback DNS into the runtime copy when the config has none
    "fallback_dns": "1.1.1.1, 1.0.0.1",
    # connection
    "auto_repair": True,
    "stream_tuned": True,
    "reconnect_on_network_change": True,
    "auto_connect": False,
    "last_region": None,
    "favorites": [],
    "smart_select": True,
    "guard_service": "",           # watch one streaming service and switch server if it gets blocked
    "guard_auto_switch": False,
    # background behaviour
    "guardian": True,
    "watchdog": True,
    "watchdog_failopen": False,
    "tray": True,
    "close_to_tray": True,
    "start_with_windows": False,
    "notifications": True,
    # trusted networks
    "ssid_rules": False,
    "trusted_networks": [],
    "trusted_fingerprints": {},    # name -> Wi-Fi security + confirmed access points, or router MAC (#15); not UI-settable
    "autoconnect_untrusted": True,
    "autodisconnect_trusted": True,
    # privacy / security
    "ip_lookup": False,            # privacy first: opt-in (setup checklist or Settings > Privacy); sends your IP to ipinfo.io
    "startup_checks": False,       # speed test + service checks at launch: opt-in (slow, contacts 3rd parties)
    "visual_effects": False,       # frosted glass + ambient animations: off by default (GPU/CPU heavy)
    # Network Intelligence (on demand; nothing runs in the background unless the fix agent is switched on)
    "ni_reference_dns": "1.1.1.1, 8.8.8.8, 9.9.9.9, 2606:4700:4700::1111, 2001:4860:4860::8888",  # editable
    "ni_history": True,            # keep local diagnostic history + per-network baselines (never uploaded)
    "ni_autofix": False,           # smart fix agent: OFF until the user switches it on (that is the authorisation)
    # Streaming Region Intelligence (TMDB key is stored encrypted elsewhere, never in settings)
    "si_my_services": [],          # TMDB provider ids the user subscribes to (optional filter)
    "si_language": "en-US",
    "custom_titlebar": True,
    "net_adapt": True,             # NOBAD's own downloads adapt to blocked hostnames/DNS (alternate names, encrypted DNS)       # NOBAD's own top bar with window buttons (off = classic Windows title bar)
    "encrypt_configs": False,
    "dpapi_runtime_ok": True,      # flipped off automatically if WireGuard refuses .dpapi files
    "crash_reporting": False,
    "crash_report_url": "",
    # updates
    "update_url": "",
    "auto_update_check": False,
    "auto_install_wg": True,       # reinstall a missing WireGuard at start-up (bundled, signature-checked copy first)
    # appearance / UI memory
    "theme": "dark",
    "wizard_done": False,
    "window": None,
    "last_tab": "t1",
}
