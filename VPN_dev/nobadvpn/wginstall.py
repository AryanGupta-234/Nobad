"""Install the official WireGuard for Windows, which NOBAD drives (tunnel service + wintun driver).

Order of preference:
  1. the MSI bundled with NOBAD's installer ({app}\\redist\\wireguard-<arch>.msi): works offline;
  2. the official MSI from download.wireguard.com, downloaded over HTTPS;
  3. winget, as a last resort.
Every MSI must carry a valid Authenticode signature from WireGuard LLC before msiexec runs it (elevated)."""
import os
import platform
import urllib.request

from .const import BASE_DIR, UA, UPDATE_DIR
from .logbus import log
from .syscmd import run, wg_tool

WG_VERSION = "1.1.1"                       # keep in sync with packaging/build.ps1 ($wgVersion)
WG_SIGNER = "CN=WireGuard LLC,"            # subject prefix of the official signing certificate
WG_BASE_URL = "https://download.wireguard.com/windows-client/"
MAX_MSI = 64 * 1024 * 1024


def arch():
    """'arm64' or 'amd64' — of the OS, not of this (possibly emulated x64) process."""
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes as wt
            k = ctypes.windll.kernel32
            proc, native = wt.USHORT(), wt.USHORT()
            if k.IsWow64Process2(k.GetCurrentProcess(), ctypes.byref(proc), ctypes.byref(native)):
                return "arm64" if native.value == 0xAA64 else "amd64"
        except Exception:
            pass
    m = (os.environ.get("PROCESSOR_ARCHITEW6432") or os.environ.get("PROCESSOR_ARCHITECTURE")
         or platform.machine()).lower()
    return "arm64" if "arm64" in m or "aarch64" in m else "amd64"


def msi_name(a=None):
    return f"wireguard-{a or arch()}.msi"


def bundled_msi():
    p = os.path.join(BASE_DIR, "redist", msi_name())
    return p if os.path.isfile(p) else None


def signature(path):
    """(status, subject) of an Authenticode signature."""
    lit = str(path).replace("'", "''")
    ps = (f"$s=Get-AuthenticodeSignature -LiteralPath '{lit}'; [string]$s.Status; "
          "[string]$s.SignerCertificate.Subject")
    lines = [x.strip() for x in (run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                                     timeout=60).stdout or "").splitlines()] + ["", ""]
    return lines[0], lines[1]


def signed_by_wireguard(path, sig=None):
    status, subject = (sig or signature)(path)
    return status == "Valid" and subject.startswith(WG_SIGNER)


def run_msi(path):
    """Silent per-machine install; DO_NOT_LAUNCH keeps WireGuard's own window from popping up."""
    r = run(["msiexec.exe", "/i", path, "/qn", "/norestart", "DO_NOT_LAUNCH=1"], timeout=600)
    return r.returncode in (0, 3010)  # 3010 = success, reboot suggested


def download_official(dest_dir=UPDATE_DIR):
    os.makedirs(dest_dir, exist_ok=True)
    name = f"wireguard-{arch()}-{WG_VERSION}.msi"
    dest = os.path.join(dest_dir, name)
    req = urllib.request.Request(WG_BASE_URL + name, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
        got = 0
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            got += len(chunk)
            if got > MAX_MSI:
                raise ValueError("download too large")
            f.write(chunk)
    return dest


def install(sig=None, msi_runner=None, downloader=None, winget=None, installed=None):
    """Returns (ok, message). The keyword hooks exist for tests."""
    sig = sig or signature
    msi_runner = msi_runner or run_msi
    downloader = downloader or download_official
    installed = installed or (lambda: wg_tool("wireguard.exe") is not None)
    if installed():
        return True, "WireGuard is already installed."
    tried = []
    src = bundled_msi()
    if src:
        if signed_by_wireguard(src, sig):
            log("installing the bundled WireGuard " + WG_VERSION, "info")
            if msi_runner(src) and installed():
                return True, "WireGuard is installed."
            tried.append("bundled installer failed")
        else:
            log("bundled WireGuard installer failed the signature check — not used", "bad")
            tried.append("bundled installer not trusted")
    try:
        path = downloader()
        try:
            if signed_by_wireguard(path, sig):
                log("installing WireGuard " + WG_VERSION + " from download.wireguard.com", "info")
                if msi_runner(path) and installed():
                    return True, "WireGuard is installed."
                tried.append("downloaded installer failed")
            else:
                tried.append("downloaded installer not trusted")
                log("downloaded WireGuard installer failed the signature check — not run", "bad")
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
    except Exception as e:
        tried.append(f"download failed ({type(e).__name__})")
    r = (winget or (lambda: run(["winget", "install", "--id", "WireGuard.WireGuard", "-e", "--silent",
                                 "--accept-source-agreements", "--accept-package-agreements"], timeout=600)))()
    if installed():
        return True, "WireGuard is installed."
    tried.append("winget failed" if r is not None else "winget unavailable")
    log("WireGuard install did not finish: " + "; ".join(tried), "bad")
    return False, "WireGuard could not be installed automatically (" + "; ".join(tried) + "). Use the download page."
