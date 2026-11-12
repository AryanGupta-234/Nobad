"""Windows DPAPI helpers for encrypting stored configs.

Threat model (be honest about it): we use MACHINE scope, because the WireGuard tunnel service runs as
LocalSystem and has to be able to read the file (WireGuard itself stores its configs this way, as
`<name>.conf.dpapi` with the tunnel name as the DPAPI description). That protects the keys from being
read out of a copied/backed-up/cloud-synced file or a stolen disk image. It does NOT protect them from
another local administrator or from code running on this machine.
"""
import ctypes
import ctypes.wintypes as wt
import os

CRYPTPROTECT_UI_FORBIDDEN = 0x1
CRYPTPROTECT_LOCAL_MACHINE = 0x4

_backend = None  # tests inject (protect_fn, unprotect_fn)


class DpapiError(OSError):
    pass


class _BLOB(ctypes.Structure):
    _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


_api_cache = {}


def _api():
    """crypt32/kernel32 with declared signatures and reliable GetLastError (use_last_error)."""
    if not _api_cache:
        c = ctypes.WinDLL("crypt32", use_last_error=True)
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        P = ctypes.POINTER(_BLOB)
        c.CryptProtectData.argtypes = [P, wt.LPCWSTR, P, ctypes.c_void_p, ctypes.c_void_p, wt.DWORD, P]
        c.CryptProtectData.restype = wt.BOOL
        c.CryptUnprotectData.argtypes = [P, ctypes.POINTER(wt.LPWSTR), P, ctypes.c_void_p, ctypes.c_void_p,
                                         wt.DWORD, P]
        c.CryptUnprotectData.restype = wt.BOOL
        k.LocalFree.argtypes = [ctypes.c_void_p]
        k.LocalFree.restype = ctypes.c_void_p
        _api_cache.update(crypt32=c, kernel32=k)
    return _api_cache["crypt32"], _api_cache["kernel32"]


def _to_blob(data):
    buf = ctypes.create_string_buffer(data, len(data))
    return _BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def _from_blob(blob):
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        _api()[1].LocalFree(ctypes.cast(blob.pbData, ctypes.c_void_p))


def available():
    return _backend is not None or os.name == "nt"


def protect(data, description):
    if _backend:
        return _backend[0](data, description)
    if os.name != "nt":
        raise DpapiError("DPAPI is only available on Windows")
    inp, keep = _to_blob(data)
    out = _BLOB()
    crypt32, _k = _api()
    ok = crypt32.CryptProtectData(ctypes.byref(inp), description, None, None, None,
                                  CRYPTPROTECT_UI_FORBIDDEN | CRYPTPROTECT_LOCAL_MACHINE, ctypes.byref(out))
    err = ctypes.get_last_error()
    del keep
    if not ok:
        raise DpapiError(f"CryptProtectData failed ({err})")
    return _from_blob(out)


def unprotect(blob, expected_description=None):
    if _backend:
        return _backend[1](blob, expected_description)
    if os.name != "nt":
        raise DpapiError("DPAPI is only available on Windows")
    inp, keep = _to_blob(blob)
    out = _BLOB()
    descr = wt.LPWSTR()
    crypt32, kernel32 = _api()
    ok = crypt32.CryptUnprotectData(ctypes.byref(inp), ctypes.byref(descr), None, None, None,
                                    CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out))
    err = ctypes.get_last_error()
    del keep
    if not ok:
        raise DpapiError(f"CryptUnprotectData failed ({err})")
    got = descr.value
    if descr:
        kernel32.LocalFree(ctypes.cast(descr, ctypes.c_void_p))
    data = _from_blob(out)
    if expected_description is not None and got != expected_description:
        raise DpapiError("encrypted config belongs to a different tunnel name")
    return data


def write_atomic(path, data):
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def wipe_and_remove(path):
    """Best-effort secure delete: overwrite then unlink (no guarantee on SSDs / journaling filesystems)."""
    try:
        size = os.path.getsize(path)
        with open(path, "r+b") as f:
            f.write(b"\0" * size)
            f.flush()
            os.fsync(f.fileno())
    except OSError:
        pass
    try:
        os.remove(path)
    except OSError:
        pass
